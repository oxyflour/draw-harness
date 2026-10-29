"""Measure independent X/Z hole-relocation cases using verified prepared BREP inputs.

feature.json and prepare.tcl document how the selected walls were expanded and
the original hole filled. All cases cut a translated stepped tool from that same
filled solid; neighboring exterior surfaces are retrimmed by the Boolean kernel.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from occ_harness.engine import Harness, ROOT, write_json
from move_face_benchmark import require, sha256, exact_counts


def numbers(text, key):
    match = re.search(r"^\s*" + re.escape(key) + r"\s*:\s*([^\n]+)", text, re.M)
    return [float(x) for x in match[1].split(",")] if match else None


def support_type(text, geometry, p, dx, dz):
    origin, axis = numbers(text, "Origin"), numbers(text, "Axis")
    if not origin or not axis or abs(abs(axis[1]) - 1) > 1e-8:
        return None
    if geometry == "plane":
        return "ledge" if abs(origin[1] - p["shoulder_y"]) < 1e-6 else None
    if abs(origin[0] - p["center_x"] - dx) > 1e-6 or abs(origin[2] - p["center_z"] - dz) > 1e-6:
        return None
    radius = numbers(text, "Radius")
    if not radius:
        return None
    if geometry == "cylinder":
        for label in ("outer", "inner"):
            if abs(radius[0] - p[label + "_radius"]) < 1e-7:
                return label
    if geometry == "cone":
        angle = numbers(text, "Angle")
        if angle:
            at_shoulder = radius[0] + (p["shoulder_y"] - origin[1]) * math.tan(angle[0]) / axis[1]
            if abs(at_shoulder - p["cone_start_radius"]) < 1e-6:
                return "taper"
    return None


def measure_sections(execute, inspect, p, dx, dz, sections, prefix):
    rings = []
    for label, y, radius in sections:
        curve, edge, common = f"probe_{prefix}_{label}", f"ring_{prefix}_{label}", f"ring_overlap_{prefix}_{label}"
        require(execute(f"circle {curve} {p['center_x']+dx:.17g} {y:.17g} {p['center_z']+dz:.17g} 0 1 0 {radius:.17g}; mkedge {edge} {curve}; bcommon {common} boundary {edge}", [edge, common]))
        overlap = inspect(common)
        fraction = overlap["length"] / (2 * math.pi * radius)
        rings.append({"step": label, "axial_y": y, "radius": radius, "retained_fraction": fraction,
                      "complete_circle": abs(fraction - 1) < 1e-5})
    return rings


def core_sections(p):
    # Probe both sides of the internal transitions, independently of the exit
    # trimming. Original wall midpoints can lie outside a correctly retrimmed bore.
    return [("outer", p["shoulder_y"] - .001, p["outer_radius"]),
            ("taper", (p["shoulder_y"] + p["cone_end_y"]) / 2,
             (p["cone_start_radius"] + p["inner_radius"]) / 2),
            ("inner", p["cone_end_y"] + .001, p["inner_radius"])]


def write_summary(out, p, reports):
    manifest = {"part_rank": 5, "selection_case": 2, "units": "mm", "user_faces": p["original_faces"],
                "expanded_faces": p["expanded_faces"], "cases": [r["case"]["id"] for r in reports],
                "input_sha256": {path.name: sha256(path) for path in (out / "input").iterdir() if path.is_file()}}
    write_json(out / "manifest.json", manifest)
    lines = ["# 选面 case 0002：05 号件的阶梯孔沿 X/Z 平移 ±3 mm", "",
             "用户原选面：8、317。沿同一孔的邻接关系扩展为 6、7、8、317、318、319、320，共 7 面。",
             "扩展包括外径圆柱壁、环形台阶、锥面及内径圆柱壁；邻接外表面 30、83、84 保持原支撑曲面，由布尔运算重新裁剪。",
             "四个 case 均从同一原件独立开始。先补旧孔，再平移完整阶梯孔工具重切；原位置重建的双向布尔差为空（OCCT 容差内）。",
             "candidate.stp / candidate.brep 是候选实体；expanded_targets.step 是刚性平移后的 7 个参考面，后者不是实体答案。", "",
             "| Case | 常规有效单实体 | 台阶连接完整 | 7 个裁剪面完整保留 | STEP 往返 |", "|---|---|---|---|---|"]
    for r in reports:
        n = r["case"]["id"]
        if r["result_available"]:
            lines.append(f"| [{n}]({n}/candidate.stp) | {r['ordinary_single_solid']} | {r['stepped_hole_core_pass']} | {r['full_trimmed_patch_move_pass']} | {r['step_roundtrip']['pass']} |")
        else:
            lines.append(f"| {n} | 无可用结果 | False | False | 未执行 |")
    lines += ["", "“台阶连接完整”要求有效单实体、外孔→台阶→锥面→内孔邻接链，以及台阶两侧和锥面中部的整圆截面均保留。它只检查孔的核心连接，不证明出口范围或全局质量。",
              "原孔壁中部的平移截面另存 representative_circular_sections，仅用于比较裁剪变化，不作为核心连接的通过条件。",
              "X−3 mm 的台阶仍连接完整，内孔出口被外形重新裁短；X+3 mm 的原始代表截面均保留。Z±3 mm 均与外壁相交，局部孔壁变为开口。",
              "“7 个裁剪面完整保留”要求原有有限面片平移后仍完整存在；邻接面重新裁剪会改变面片范围。X 方向外圆柱面面积覆盖接近 100%，仍按固定的严格阈值报告。",
              "Z−3 mm 的 STEP 导回后仍是常规有效单实体，但体积相对差约 85 ppm，超过 10 ppm 阈值；双向布尔差均为空（OCCT 容差内）。体积门槛保留为未通过，详见 report.json 和 roundtrip_boolean_*.json。",
              "源件和每个结果的 checkshape -exact 均有缺陷，单列于 report.json；普通有效性通过不能替代严格检查。", "",
              "复现：在 DRAW 中 source -encoding utf-8 各 case 的 replay.tcl。input/prepare.tcl 记录从原件生成共用填孔体和工具的流程。",
              "准备流程和四个 case 已在独立无界面会话重放；验证见 diagnostics/preparation_replay.json 和各 case 的 replay_verification.json。",
              "查看：在已启用图形界面的 DRAW 中 source -encoding utf-8 本目录 review.tcl；金色为结果，青色线框为平移参考面。", "",
              "重新生成候选：python examples/relocate_hole_benchmark.py --package <本目录>。",
              "只复核现有候选的台阶连接截面：加 --audit-existing；不会重写几何。"]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    def q(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace('\n', '\\n') + '"'
    config = [f"set ::holebench::center {{{p['center_x']} -84.8 {p['center_z']}}}", "set ::holebench::cases [dict create]",
              'dict set ::holebench::cases original [dict create file "input/part_05.brep" target "input/expanded_patch.brep" label "原件 · 05 号零件" status "用户选择 8、317；扩展到同一个阶梯孔的 7 个面。"]']
    for r in reports:
        if not r["result_available"]:
            continue
        n = r["case"]["id"]
        vector = r["case"]["operation"]["vector"]
        axis, delta = ("X", vector[0]) if vector[0] else ("Z", vector[2])
        status = "台阶连接完整。" if r["stepped_hole_core_pass"] else "孔壁与外形相交，台阶整圆检查未通过。"
        if n == "x_minus3":
            status += "内孔出口被外形重新裁短。"
        status += " 核心外孔/锥面/内孔截面：" + ", ".join(f"{v['retained_fraction']:.1%}" for v in r["core_transition_sections"]) + "。"
        if not r["step_roundtrip"]["pass"]:
            status += " STEP 导回有效，但体积差约 85 ppm，未通过 10 ppm 门槛。"
        config.append(f"dict set ::holebench::cases {n} [dict create file {q(n+'/candidate.brep')} target {q(n+'/expanded_targets.brep')} label {q(axis+' '+format(delta, '+d')+' mm')} status {q(status)}]")
    (out / "review_config.tcl").write_text("\n".join(config) + "\n", encoding="utf-8")


def audit_existing(out, p):
    h = Harness(ROOT / ".occ-harness", timeout=180)
    session = "hole_core_audit_" + str(time.time_ns())
    require(h.start(session))
    reports = []
    try:
        for folder in sorted(out.iterdir()):
            report_path = folder / "report.json"
            if not report_path.is_file():
                continue
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not report["result_available"]:
                reports.append(report)
                continue
            for file, expected in report["artifacts"].items():
                if sha256(folder / file) != expected:
                    raise RuntimeError(f"Artifact hash changed: {folder / file}")
            require(h.call(session, "import", shape="candidate", path=(folder / "candidate.brep").as_posix(), format="brep"))
            require(h.execute(session, "eval compound [explode candidate F] boundary", ["boundary"]))
            attempts = []
            def execute(script, check):
                response = h.execute(session, script, list(check))
                attempts.append({"script": script, "response": response})
                return response
            def inspect(name):
                return require(h.call(session, "inspect", shape=name))
            dx, _, dz = report["case"]["operation"]["vector"]
            rings = measure_sections(execute, inspect, p, dx, dz, core_sections(p), folder.name + "_core")
            report.pop("complete_stepped_hole_baseline_pass", None)
            report["core_transition_sections"] = rings
            report["stepped_hole_core_pass"] = report["ordinary_single_solid"] and report["support_chain_retained"] and all(r["complete_circle"] for r in rings)
            report["representative_sections_policy"] = "Translated original wall midpoints measure retrimming only; core-transition sections and adjacency test the internal step connection. Neither is a global proof."
            report["step_roundtrip"]["relative_volume_tolerance"] = 1e-5
            write_json(folder / "core_section_audit.json", attempts)
            write_json(report_path, report)
            reports.append(report)
            print(json.dumps({"case": folder.name, "core_circle_retention": [r["retained_fraction"] for r in rings], "core_pass": report["stepped_hole_core_pass"]}), flush=True)
    finally:
        h.stop(session)
    write_summary(out, p, reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--audit-existing", action="store_true")
    args = parser.parse_args()
    out = args.package.resolve(strict=True)
    p = json.loads((out / "input/feature.json").read_text(encoding="utf-8"))
    if args.audit_existing:
        audit_existing(out, p)
        return
    indices = p["expanded_faces"]
    source = out / "input/part_05.brep"
    h = Harness(ROOT / ".occ-harness", timeout=180)
    session = "hole_cases_" + str(time.time_ns())
    require(h.start(session))
    reports = []
    common_attempts = []
    attempts = common_attempts

    def execute(script, check=()):
        started = time.monotonic()
        response = h.execute(session, script, list(check))
        attempts.append({"script": script, "seconds": time.monotonic() - started, "response": response})
        return response

    def inspect(name):
        return require(h.call(session, "inspect", shape=name))

    def export(name, path, fmt="brep"):
        require(h.call(session, "export", shape=name, path=path.as_posix(), format=fmt, overwrite=True))

    try:
        original = require(h.call(session, "import", shape="base", path=source.as_posix(), format="brep"))
        require(h.call(session, "import", shape="filled", path=(out / "input/filled_part.brep").as_posix(), format="brep"))
        require(h.call(session, "import", shape="original_tool", path=(out / "input/hole_tool.brep").as_posix(), format="brep"))
        require(execute("boptions -default; bnondestructive 1"))
        input_exact = execute("checkshape base source_errors -exact")
        for i in indices:
            require(h.call(session, "select", shape="base", type="face", index=i, name=f"f{i}"))
        require(execute("compound " + " ".join(f"f{i}" for i in indices) + " original_patch", ["original_patch"]))
        export("original_patch", out / "input/expanded_patch.brep")
        # Repeat the zero-displacement calibration from the serialized inputs.
        require(execute("bcut calibration filled original_tool", ["calibration"]))
        require(execute("bcut calibration_extra calibration base; bcut calibration_missing base calibration"))
        calibration = {n: inspect("calibration_" + n) for n in ("extra", "missing")}
        if any(v["topology"]["solid"] or v["topology"]["face"] for v in calibration.values()):
            raise RuntimeError("Prepared tool does not reconstruct the original hole within Boolean tolerance")
        write_json(out / "diagnostics/calibration_verified.json", {"differences": calibration, "attempts": common_attempts})
        for axis, delta in [("x", -3), ("x", 3), ("z", -3), ("z", 3)]:
            name = f"{axis}_{'minus' if delta < 0 else 'plus'}3"
            folder = out / name
            folder.mkdir(exist_ok=True)
            attempts = []
            vector = [delta if axis == "x" else 0, 0, delta if axis == "z" else 0]
            dx, _, dz = vector
            vector_text = " ".join(str(v) for v in vector)
            task = {"schema_version": 1, "id": name, "units": "mm", "selection_case": 2, "part_rank": 5,
                    "input": "../input/part_05.brep", "input_sha256": sha256(source),
                    "original_user_faces": p["original_faces"], "expanded_faces": indices,
                    "fixed_exterior_faces_before_edit": p["fixed_boundary_faces"],
                    "operation": {"type": "translate_expanded_stepped_hole", "vector": vector, "simultaneous": True},
                    "method": "Fill the old complete hole; cut a translated outer bore, annular ledge, taper and inner bore. Retrim exterior faces by Boolean intersection.",
                    "boundary_policy": "Support geometry moves rigidly; trimming may change. Full trimmed-patch coverage is measured separately."}
            write_json(folder / "case.json", task)
            require(execute(f"tcopy original_tool moved_tool; ttranslate moved_tool {vector_text}", ["moved_tool"]))
            for i in indices:
                require(execute(f"tcopy f{i} target{i}; ttranslate target{i} {vector_text}", [f"target{i}"]))
            require(execute("compound " + " ".join(f"target{i}" for i in indices) + " targets", ["targets"]))
            export("targets", folder / "expanded_targets.brep")
            export("targets", folder / "expanded_targets.step", "step")
            direct = execute(f"bcut result_{name} filled moved_tool", [f"result_{name}"])
            fallback = not direct["ok"]
            if fallback:
                require(execute("nurbsconvert moved_tool_nurbs moved_tool", ["moved_tool_nurbs"]))
                direct = execute(f"bcut result_{name} filled moved_tool_nurbs", [f"result_{name}"])
            if not direct["ok"]:
                write_json(folder / "report.json", {"case": task, "result_available": False, "failure": direct, "attempts": attempts})
                reports.append({"case": task, "result_available": False})
                continue
            result_name = "result_" + name
            result = inspect(result_name)
            exact = execute(f"checkshape {result_name} errors_{name} -exact")
            require(execute(f"eval compound [explode {result_name} F] boundary"))
            coverage = []
            for i in indices:
                target = inspect(f"target{i}")
                overlap_name, old_name = f"overlap_{name}_{i}", f"old_overlap_{name}_{i}"
                require(execute(f"bcommon {overlap_name} boundary target{i}", [overlap_name]))
                overlap = inspect(overlap_name)
                require(execute(f"bcommon {old_name} boundary f{i}", [old_name]))
                old = inspect(old_name)
                coverage.append({"face_index_before_edit": i, "user_selected": i in p["original_faces"],
                                 "target_area_mm2": target["area"], "retained_area_mm2": overlap["area"],
                                 "retained_fraction": overlap["area"] / target["area"],
                                 "full_patch_retained": abs(overlap["area"] - target["area"]) < 1e-5 * target["area"],
                                 "old_area_remaining_mm2": old["area"]})
            # Original wall midpoints measure retrimming, not feature completeness.
            outer_y = (min(inspect(f"f{i}")["bbox"]["min"][1] for i in p["original_faces"]) + p["shoulder_y"]) / 2
            sections = [("outer", outer_y, p["outer_radius"]),
                        ("taper", (p["shoulder_y"] + p["cone_end_y"]) / 2, (p["cone_start_radius"] + p["inner_radius"]) / 2),
                        ("inner", (p["cone_end_y"] + p["back_face_y"]) / 2, p["inner_radius"])]
            rings = measure_sections(execute, inspect, p, dx, dz, sections, name)
            core_rings = measure_sections(execute, inspect, p, dx, dz, core_sections(p), name + "_core")
            all_faces = require(h.call(session, "subshapes", shape=result_name, type="face", offset=0, limit=500))["items"]
            groups = {label: [] for label in ("outer", "ledge", "taper", "inner")}
            for face in all_faces:
                b = face["bbox"]
                if face["geometry"] not in ("cylinder", "cone", "plane"):
                    continue
                if b["min"][0] < p["center_x"] + dx - p["outer_radius"] - 1e-4 or b["max"][0] > p["center_x"] + dx + p["outer_radius"] + 1e-4:
                    continue
                if b["min"][2] < p["center_z"] + dz - p["outer_radius"] - 1e-4 or b["max"][2] > p["center_z"] + dz + p["outer_radius"] + 1e-4:
                    continue
                require(h.call(session, "select", shape=result_name, type="face", index=face["index"], name="support_face"))
                dump = require(execute("mksurface support_surface support_face; dump support_surface"))["result"]
                label = support_type(dump, face["geometry"], p, dx, dz)
                if label:
                    groups[label].append(face["index"])
            graph_path = folder / "topology.json"
            require(h.call(session, "topology_graph", shape=result_name, path=graph_path.as_posix(), overwrite=True))
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            nodes = {n["id"]: n for n in graph["nodes"]}
            connected = {}
            for a, b in [("outer", "ledge"), ("ledge", "taper"), ("taper", "inner")]:
                connected[a + "_" + b] = any(any(nodes[f]["type_index"] in groups[a] for f in fs) and any(nodes[f]["type_index"] in groups[b] for f in fs) for fs in graph["edge_faces"].values())
            ordinary = result["valid"] and result["topology"]["solid"] == 1
            support_chain = all(groups.values()) and all(connected.values())
            for fmt, ext in [("brep", "brep"), ("step", "stp")]:
                export(result_name, folder / ("candidate." + ext), fmt)
            step = require(h.call(session, "import", shape="roundtrip", path=(folder / "candidate.stp").as_posix(), format="step"))
            error = abs(step["volume"] - result["volume"]) / max(abs(result["volume"]), 1e-12)
            report = {"case": task, "result_available": True, "candidate_inspection": result,
                      "ordinary_single_solid": ordinary, "target_coverage": coverage, "representative_circular_sections": rings,
                      "mapped_support_faces_after_edit": groups, "support_chain_connections": connected,
                      "support_chain_retained": bool(support_chain),
                      "full_trimmed_patch_move_pass": ordinary and all(c["full_patch_retained"] for c in coverage),
                      "core_transition_sections": core_rings,
                      "stepped_hole_core_pass": ordinary and bool(support_chain) and all(r["complete_circle"] for r in core_rings),
                      "exact_checks": {"input": input_exact, "candidate": exact, "input_issues": exact_counts(input_exact), "candidate_issues": exact_counts(exact)},
                      "nurbs_tool_fallback": fallback,
                      "step_roundtrip": {"inspection": step, "relative_volume_error": error,
                                         "relative_volume_tolerance": 1e-5,
                                         "pass": step["valid"] and step["topology"]["solid"] == 1 and error < 1e-5},
                      "artifacts": {name: sha256(folder / name) for name in ("candidate.brep", "candidate.stp")}}
            write_json(folder / "report.json", report)
            write_json(folder / "attempts.json", attempts)
            replay = ["pload MODELING", "set here [file dirname [file normalize [info script]]]",
                      "restore [file join $here .. input filled_part.brep] filled",
                      "restore [file join $here .. input hole_tool.brep] tool",
                      "boptions -default", "bnondestructive 1", f"ttranslate tool {vector_text}"]
            if fallback:
                replay += ["nurbsconvert tool_nurbs tool", "bcut result filled tool_nurbs"]
            else:
                replay += ["bcut result filled tool"]
            replay += ["checkshape result", "save result [file join $here replayed.brep]"]
            (folder / "replay.tcl").write_text("\n".join(replay) + "\n", encoding="utf-8")
            reports.append(report)
            print(json.dumps({"case": name, "valid_single_solid": ordinary,
                              "user_face_retention": [c["retained_fraction"] for c in coverage if c["user_selected"]],
                              "circle_retention": [r["retained_fraction"] for r in rings],
                              "feature_chain": groups, "core_pass": report["stepped_hole_core_pass"],
                              "STEP_pass": report["step_roundtrip"]["pass"]}), flush=True)
    finally:
        h.stop(session)
    write_summary(out, p, reports)


if __name__ == "__main__":
    main()
