"""Audited direct-edit branches. Geometry facts and acceptance come from OCCT.

The built-in recipe recognizes an analytic coaxial bore from raw source faces;
it does not consume prepared benchmark plugs, tools, parameters or answers.
"""
from __future__ import annotations

import math
from pathlib import Path
import secrets

from .engine import HarnessError, now, read_json, write_json


DEFAULT_POLICY = {
    "target_mode": "support_geometry", "allow_breakthrough": False,
    "allow_new_supports": False, "require_exact": False,
    "linear_tolerance": 1e-6, "area_relative_tolerance": 1e-5,
    "max_tolerance_growth": 1e-5, "relative_volume_tolerance": 1e-5,
}


def normalize_policy(policy):
    if not isinstance(policy, dict):
        raise HarnessError("An explicit edit policy object is required")
    required = {"target_mode", "allow_breakthrough", "allow_new_supports"}
    if not required <= policy.keys() or policy.keys() - DEFAULT_POLICY.keys():
        raise HarnessError("Policy requires target_mode, allow_breakthrough, allow_new_supports; unknown fields are rejected")
    result = {**DEFAULT_POLICY, **policy}
    if result["target_mode"] not in ("support_geometry", "trimmed_patch"):
        raise HarnessError("target_mode must be support_geometry or trimmed_patch")
    for key in ("allow_breakthrough", "allow_new_supports", "require_exact"):
        if not isinstance(result[key], bool):
            raise HarnessError(f"{key} must be boolean")
    for key, maximum in (("linear_tolerance", .01), ("area_relative_tolerance", .1),
                         ("max_tolerance_growth", .01), ("relative_volume_tolerance", .1)):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value > maximum or value < 0 or value == 0 and key != "max_tolerance_growth":
            raise HarnessError(f"Invalid policy tolerance: {key}")
    return result


def translate_vector(vector):
    if not isinstance(vector, list) or len(vector) != 3 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e9 for v in vector
    ):
        raise HarnessError("vector requires three finite numbers with absolute value <= 1e9 model units")
    return [float(v) for v in vector]


def primitive_script(name, segment):
    axis, origin = segment["axis"], segment["origin"]
    radius0, radius1, height = segment["radius_start"], segment["radius_end"], segment["length"]
    if min(radius0, radius1, height) <= 0 or not all(math.isfinite(v) for v in [*axis, *origin, radius0, radius1, height]):
        raise HarnessError("Unsupported nonpositive or nonfinite tool segment")
    if abs(radius0 - radius1) < 1e-10:
        script = f"pcylinder {name} {radius0:.17g} {height:.17g}"
    else:
        script = f"pcone {name} {radius0:.17g} {radius1:.17g} {height:.17g}"
    # DRAW primitives start on +Z. Rotate to the measured world-space bore axis.
    cross = [-axis[1], axis[0], 0.0]
    if math.hypot(*cross[:2]) > 1e-12:
        angle = math.degrees(math.acos(max(-1.0, min(1.0, axis[2]))))
        script += f"; trotate {name} 0 0 0 {' '.join(format(v, '.17g') for v in cross)} {angle:.17g}"
    elif axis[2] < 0:
        script += f"; trotate {name} 0 0 0 1 0 0 180"
    return script + f"; ttranslate {name} " + " ".join(format(v, ".17g") for v in origin)


class RecipeFailure(HarnessError):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


def edit_candidate(h, session, shape, faces, vector, policy, expected_revision):
    """Hold the session lock for the WHOLE branch, including validation/export.

    Only generated Tcl is run here. Raw occ_exec remains trusted full DRAW access,
    not a sandbox. Failures keep branch evidence; source geometry is never replaced.
    """
    policy, vector = normalize_policy(policy), translate_vector(vector)
    with h.lock(session) as directory:
        initial = h._rpc(session, {"op": "inspect", "shape": shape})
        if not initial.get("ok"):
            return initial
        if "revision" not in initial["data"]:
            raise HarnessError("Session has an older native module; start a new named session and import the saved source or checkpoint")
        if initial["data"]["revision"] != expected_revision:
            raise HarnessError("Stale source revision; inspect and select again")
        if not initial["data"]["valid"] or initial["data"]["topology"]["solid"] != 1:
            raise HarnessError("Built-in hole recipe requires a valid single-solid source")
        # Native preflight validates all indices before allocating or writing a branch.
        expansion = h._rpc(session, {"op": "expand_selection", "shape": shape, "faces": faces,
                                     "expected_revision": expected_revision, "linear_tolerance": policy["linear_tolerance"]})
        if not expansion.get("ok"):
            return expansion
        identifier = "edit_" + secrets.token_hex(6)
        folder = directory / "edits" / identifier
        folder.mkdir(parents=True)
        manifest = {"schema_version": 1, "id": identifier, "created_at": now(), "source": shape,
                    "source_revision": expected_revision, "seed_faces": faces, "vector": vector, "policy": policy,
                    "strategy": "coaxial_hole", "status": "preflight", "expansion": expansion["data"],
                    "stages": [], "source_replaced": False,
                    "scope": "BRep branch only; session Tcl options/names remain. Timeout invalidates session and is never retried."}
        journal = []

        def persist():
            write_json(folder / "manifest.json", manifest)
            write_json(folder / "operations.json", journal)

        def stage(name):
            manifest["status"] = name
            manifest["stages"].append({"stage": name, "at": now()})
            persist()

        def call(op, **arguments):
            response = h._rpc(session, {"op": op, **arguments})
            journal.append({"op": op, "arguments": arguments, "response": response})
            if not response.get("ok"):
                raise RecipeFailure(f"{op} failed during {manifest['status']}", response)
            return response["data"]

        def execute(script, *outputs):
            result = call("eval", script=script)
            if not result.get("ok"):
                raise RecipeFailure("Tcl operation failed", result)
            for output in outputs:
                measured = call("inspect", shape=output)
                if not measured["valid"]:
                    raise RecipeFailure(f"Invalid output: {output}", measured)

        def solid(name):
            measured = call("inspect", shape=name)
            if not measured["valid"] or measured["topology"]["solid"] != 1:
                raise RecipeFailure(f"Expected a valid single solid: {name}", measured)
            return measured

        def name(suffix):
            return identifier + "_" + suffix

        persist()
        try:
            feature = expansion["data"]
            if not feature["supported"]:
                manifest["status"] = "unsupported_feature"
                manifest["accepted"] = False
                return {"ok": True, "data": manifest, "manifest": str(folder / "manifest.json")}
            stage("checkpoint")
            call("export", shape=shape, path=(folder / "input.brep").as_posix(), format="brep")
            base = name("base")
            call("import", shape=base, path=(folder / "input.brep").as_posix(), format="brep")
            selected = []
            for i in feature["expanded_faces"]:
                item = name(f"face{i}")
                call("select", shape=base, type="face", index=i, name=item)
                selected.append(item)
            stage("fill_original_feature")
            healed, plug, filled = name("healed"), name("plug"), name("filled")
            execute("boptions -default; bnondestructive 1")
            execute(f"removefeatures {healed} {base} " + " ".join(selected), healed)
            solid(healed)
            execute(f"bcut {plug} {healed} {base}", plug)
            solid(plug)
            execute(f"bfuse {filled} {base} {plug}", filled)
            solid(filled)
            stage("build_measured_tool")
            segments = [dict(v) for v in feature["tool_segments"]]
            axial_shift = sum(v*d for v,d in zip(vector, feature["axis_direction"]))
            # Terminal cylinders represent the unbounded bore support. Keep
            # them covering the stock at both zero and requested displacement.
            if axial_shift > 0:
                first = segments[0]
                first["origin"] = [v-d*axial_shift for v,d in zip(first["origin"], first["axis"])]
                first["length"] += axial_shift
            elif axial_shift < 0:
                segments[-1]["length"] -= axial_shift
            manifest["tool_segments_for_vector"] = segments
            primitives = []
            for i, segment in enumerate(segments):
                item = name(f"tool{i}")
                execute(primitive_script(item, segment), item)
                primitives.append(item)
            tool = primitives[0]
            for i, item in enumerate(primitives[1:]):
                joined = name(f"tool_join{i}")
                execute(f"bfuse {joined} {tool} {item}", joined)
                tool = joined
            solid(tool)
            stage("zero_displacement_calibration")
            calibration = name("calibration")
            execute(f"bcut {calibration} {filled} {tool}", calibration)
            solid(calibration)
            diffs = {}
            for label, left, right in [("extra", calibration, base), ("missing", base, calibration)]:
                output = name(label)
                execute(f"bcut {output} {left} {right}", output)
                diffs[label] = call("inspect", shape=output)
            manifest["calibration"] = diffs
            if any(v["topology"][kind] for v in diffs.values() for kind in ("face", "edge", "solid")):
                raise RecipeFailure("Zero-displacement reconstruction differs from source; recipe is not applicable", diffs)
            stage("translate_and_cut")
            moved, candidate = name("moved_tool"), name("candidate")
            execute(f"tcopy {tool} {moved}; ttranslate {moved} " + " ".join(format(v, ".17g") for v in vector), moved)
            # One exact analytic attempt. Return kernel evidence on failure; no
            # tolerance escalation, automatic replay or hidden NURBS conversion.
            execute(f"bcut {candidate} {filled} {moved}", candidate)
            measured = solid(candidate)
            manifest["candidate"] = candidate
            manifest["candidate_revision"] = measured["revision"]
            stage("independent_validation")
            validation = call("validate_edit", source=base, candidate=candidate, faces=feature["expanded_faces"],
                              vector=vector, source_revision=call("inspect", shape=base)["revision"],
                              candidate_revision=measured["revision"], policy=policy)
            manifest["validation"] = validation
            stage("exchange_validation")
            for fmt, filename in [("brep", "candidate.brep"), ("step", "candidate.stp")]:
                call("export", shape=candidate, format=fmt, path=(folder / filename).as_posix())
            exchange = call("import", shape=name("step_roundtrip"), format="step", path=(folder / "candidate.stp").as_posix())
            error = abs(exchange["volume"] - measured["volume"]) / max(abs(measured["volume"]), 1e-12) if exchange["volume"] is not None else None
            step_pass = exchange["valid"] and exchange["topology"]["solid"] == 1 and error is not None and error <= policy["relative_volume_tolerance"]
            manifest["step_roundtrip"] = {"inspection": exchange, "relative_volume_error": error,
                                          "relative_volume_tolerance": policy["relative_volume_tolerance"], "pass": step_pass}
            manifest["accepted"] = validation["accepted"] and step_pass
            manifest["status"] = "accepted" if manifest["accepted"] else "candidate_rejected"
            manifest["artifacts"] = {"brep": str(folder / "candidate.brep"), "step": str(folder / "candidate.stp")}
            return {"ok": True, "data": manifest, "manifest": str(folder / "manifest.json")}
        except (HarnessError, OSError, ValueError) as exc:
            manifest["status"] = "execution_failed"
            manifest["accepted"] = False
            manifest["error"] = str(exc)
            manifest["failure"] = getattr(exc, "response", None)
            return {"ok": False, "data": manifest, "manifest": str(folder / "manifest.json"), "error": str(exc)}
        finally:
            # Never restart or issue more kernel work after a transport timeout.
            meta = read_json(directory / "session.json", {})
            if meta.get("status") == "running":
                check = h._rpc(session, {"op": "inspect", "shape": shape})
                manifest["source_revision_after"] = check.get("data", {}).get("revision")
                manifest["source_unchanged"] = check.get("ok", False) and manifest["source_revision_after"] == expected_revision
                if not manifest["source_unchanged"]:
                    manifest["accepted"] = False
                    manifest["status"] = "source_changed"
            else:
                manifest["session_invalidated"] = True
                manifest["accepted"] = False
            persist()
            memory = read_json(directory / "memory.json", {})
            memory[identifier] = {"updated_at": now(), "value": {key: manifest.get(key) for key in
                ("source", "source_revision", "candidate", "candidate_revision", "status", "accepted", "seed_faces", "vector", "policy")}}
            memory[identifier]["value"]["manifest"] = str(folder / "manifest.json")
            write_json(directory / "memory.json", memory)
