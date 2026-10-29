"""Build +/- X face-move benchmark inputs and measured DRAW Boolean baselines.

The translated trimmed faces are targets, not assumed ground truth solids.
In particular a valid solid is insufficient when Boolean trimming loses a target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from occ_harness.engine import Harness, ROOT, write_json


def require(response):
    if not response.get("ok"):
        raise RuntimeError(json.dumps(response, ensure_ascii=False))
    return response.get("data", response)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_counts(response):
    text = require(response)["result"]
    return {label.strip(): int(count) for label, count in
            re.findall(r"^\s*([^\n]+?)\s*\.{2,}\s*(\d+)\s*$", text, re.M)}


def replay_text(indices, dx, nurbs):
    lines = ["# Run in DRAW: source /absolute/path/to/replay.tcl",
             "pload MODELING", "set here [file dirname [file normalize [info script]]]",
             "restore [file join $here .. input part_03.brep] base",
             "explode base F", "boptions -default", "bnondestructive 1"]
    for i in indices:
        # OCCT 7.7 tcopy's multi-pair loop is broken; use one pair per call.
        lines += [f"tcopy base_{i} target_{i}",
                  f"ttranslate target_{i} {dx} 0 0",
                  f"prism swept_{i} base_{i} {dx} 0 0"]
    lines += [f"bfuse tool swept_{indices[0]} swept_{indices[1]}"]
    if nurbs:
        lines += ["# Analytic tool fails PCurve construction for the negative case.",
                  "nurbsconvert tool_nurbs tool", "bcut result base tool_nurbs"]
    else:
        lines += ["bfuse result base tool"]
    lines += ["checkshape result", "save result [file join $here replayed.brep]"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(s) for s in args.selections.read_text(encoding="utf-8").splitlines() if s.strip()]
    if len(rows) != 2 or {r["case"] for r in rows} != {3}:
        parser.error("This benchmark requires the two recorded faces of case 03")
    indices = sorted({r["face_index"] for r in rows})
    if indices != [6, 727] or len({r["part_snapshot"] for r in rows}) != 1:
        parser.error("This fixture uses faces 6 and 727 from the same frozen BREP")
    source = Path(rows[0]["part_snapshot"]).resolve(strict=True)
    out = args.output.resolve()
    (out / "input").mkdir(parents=True, exist_ok=True)
    (out / "diagnostics").mkdir(exist_ok=True)
    frozen = out / "input/part_03.brep"
    if frozen.exists() and sha256(frozen) != sha256(source):
        parser.error("Output belongs to a different input snapshot")
    shutil.copyfile(source, frozen)
    if args.selections.resolve() != (out / "input/selections.jsonl"):
        shutil.copyfile(args.selections, out / "input/selections.jsonl")
    h = Harness(ROOT / ".occ-harness", timeout=180)
    reports = []
    for dx, case_id in [(3, "plus_x3"), (-3, "minus_x3")]:
        folder = out / case_id
        folder.mkdir(exist_ok=True)
        session = "move_case_" + str(time.time_ns())
        require(h.start(session))
        attempts = []

        def execute(script, check=()):
            started = time.monotonic()
            response = h.execute(session, script, list(check))
            attempts.append({"script": script, "seconds": time.monotonic() - started,
                             "response": response})
            write_json(folder / "attempts.json", attempts)
            return response

        try:
            original = require(h.call(session, "import", shape="base", path=frozen.as_posix(), format="brep"))
            input_exact = execute("checkshape base input_errors -exact")
            require(execute("boptions -default; bnondestructive 1"))
            if dx == 3:
                require(h.call(session, "topology_graph", shape="base",
                               path=(out / "diagnostics/input_topology.json").as_posix(), overwrite=True))
            task = {"schema_version": 1, "id": case_id, "units": "mm",
                    "input": "../input/part_03.brep", "input_sha256": sha256(frozen),
                    "source_step_sha256": rows[0]["source_sha256"],
                    "selection": {"type": "face", "indices": indices,
                                  "index_basis": "1-based TopExp::MapShapes of frozen input BREP"},
                    "operation": {"type": "translate_faces", "vector": [dx, 0, 0], "simultaneous": True},
                    "target_contract": "Rigidly translated trimmed patches; rebuild connections to one closed solid",
                    "baseline_policy": "Sweep patches and fuse/cut; ruled transition faces are allowed. This does not preserve all neighboring support surfaces.",
                    "checks": ["ordinary BRepCheck", "single manifold solid", "full target patch coverage",
                               "old patches absent", "STEP roundtrip", "exact check compared with input"]}
            write_json(folder / "case.json", task)
            for i in indices:
                require(h.call(session, "select", shape="base", type="face", index=i, name=f"f{i}"))
                require(execute(f"tcopy f{i} target{i}; ttranslate target{i} {dx} 0 0", [f"target{i}"]))
                require(h.call(session, "export", shape=f"target{i}", format="brep", overwrite=True,
                               path=(folder / f"target_face_{i}.brep").as_posix()))
            require(execute("compound " + " ".join(f"target{i}" for i in indices) + " targets", ["targets"]))
            require(h.call(session, "export", shape="targets", format="step", overwrite=True,
                           path=(folder / "target_faces.step").as_posix()))
            require(execute("reshape naive base " + " ".join(f"-replace f{i} target{i}" for i in indices)))
            naive = require(h.call(session, "inspect", shape="naive"))
            for i in indices:
                require(execute(f"prism sweep{i} f{i} {dx} 0 0", [f"sweep{i}"]))
            require(execute(f"bfuse tool sweep{indices[0]} sweep{indices[1]}", ["tool"]))
            operation = "bfuse" if dx > 0 else "bcut"
            direct = execute(f"{operation} result base tool", ["result"])
            nurbs_fallback = not direct["ok"]
            if nurbs_fallback:
                require(execute("nurbsconvert tool_nurbs tool", ["tool_nurbs"]))
                require(execute(f"{operation} result base tool_nurbs", ["result"]))
            result = require(h.call(session, "inspect", shape="result"))
            result_exact = execute("checkshape result output_errors -exact")
            graph_path = folder / "topology.json"
            require(h.call(session, "topology_graph", shape="result", path=graph_path.as_posix(), overwrite=True))
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            bad_incidence = [edge for edge, faces in graph["edge_faces"].items() if len(faces) != 2]
            require(execute("eval compound [explode result F] boundary"))
            coverage = []
            for i in indices:
                target = require(h.call(session, "inspect", shape=f"target{i}"))
                require(execute(f"bcommon overlap{i} boundary target{i}"))
                overlap = require(h.call(session, "inspect", shape=f"overlap{i}"))
                require(execute(f"bcommon old_overlap{i} boundary f{i}"))
                old_overlap = require(h.call(session, "inspect", shape=f"old_overlap{i}"))
                coverage.append({"input_face_index": i, "target_area_mm2": target["area"],
                                 "retained_target_area_mm2": overlap["area"],
                                 "retained_fraction": overlap["area"] / target["area"],
                                 "full_patch_retained": abs(overlap["area"] - target["area"]) <= 1e-6 * target["area"],
                                 "original_patch_remaining_area_mm2": old_overlap["area"],
                                 "target": target, "overlap": overlap})
            for fmt, ext in [("brep", "brep"), ("step", "stp")]:
                require(h.call(session, "export", shape="result", format=fmt, overwrite=True,
                               path=(folder / f"candidate.{ext}").as_posix()))
            step = require(h.call(session, "import", shape="roundtrip", format="step",
                                  path=(folder / "candidate.stp").as_posix()))
            volume_error = abs(step["volume"] - result["volume"]) / result["volume"]
            all_targets = all(c["full_patch_retained"] for c in coverage)
            original_removed = all(c["original_patch_remaining_area_mm2"] < 1e-6 for c in coverage)
            ordinary_solid = result["valid"] and result["topology"]["solid"] == 1 and not bad_incidence
            roundtrip_ok = step["valid"] and step["topology"]["solid"] == 1 and volume_error < 1e-5
            report = {"case": task, "input_inspection": original, "naive_replacement_valid": naive["valid"],
                      "candidate_inspection": result, "nurbs_tool_fallback": nurbs_fallback,
                      "two_face_incidence_for_all_edges": not bad_incidence,
                      "target_coverage": coverage, "full_target_patches_retained": all_targets,
                      "original_patches_removed": original_removed,
                      "ordinary_single_manifold_solid": ordinary_solid,
                      "full_patch_move_baseline_pass": ordinary_solid and all_targets and original_removed and roundtrip_ok,
                      "exact_checks": {"input": input_exact, "candidate": result_exact,
                                       "input_issue_counts": exact_counts(input_exact),
                                       "candidate_issue_counts": exact_counts(result_exact),
                                       "note": "Both source and results fail exact checking; ordinary validity does not certify exact curve-on-surface consistency."},
                      "step_roundtrip": {"inspection": step, "relative_volume_error": volume_error, "pass": roundtrip_ok},
                      "artifacts": {f"candidate.{ext}": sha256(folder / f"candidate.{ext}") for ext in ("stp", "brep")}}
            write_json(folder / "report.json", report)
            (folder / "replay.tcl").write_text(replay_text(indices, dx, nurbs_fallback), encoding="utf-8")
            reports.append(report)
            print(json.dumps({"case": case_id, "valid_solid": ordinary_solid,
                              "target_coverage": [c["retained_fraction"] for c in coverage],
                              "full_patch_move_baseline_pass": report["full_patch_move_baseline_pass"],
                              "STEP_roundtrip_pass": roundtrip_ok}), flush=True)
        finally:
            h.stop(session)
    write_json(out / "manifest.json", {"units": "mm", "canonical_input_sha256": sha256(frozen),
                                      "faces": indices, "cases": [r["case"]["id"] for r in reports],
                                      "reports": [r["case"]["id"] + "/report.json" for r in reports]})
    shutil.copyfile(ROOT / "examples/templates/move_face_review.tcl", out / "review.tcl")
    lines = ["# Case 03：面 6、727 同时沿 X 平移 ±3 mm", "",
             "输入编号以 input/part_03.brep 的冻结快照为准。两个 case 都从原件开始，互不累计。",
             "target_faces.step 是两个独立目标面的参考，不能当作完整实体。candidate.stp / candidate.brep 是扫掠加料/去料基线。",
             "这套基线允许新增直纹过渡面；没有强制保留所有邻接支撑曲面，因此不能替代仅延伸/重裁邻面的直接编辑算法。", "",
             "| Case | 位移 mm | 常规有效单实体 | 面 6 保留率 | 面 727 保留率 | 完整目标面平移基线 |", "|---|---|---|---|---|---|"]
    for r in reports:
        c = r["target_coverage"]
        lines.append(f"| [{r['case']['id']}]({r['case']['id']}/candidate.stp) | {r['case']['operation']['vector'][0]:+d} | {r['ordinary_single_manifold_solid']} | {c[0]['retained_fraction']:.6%} | {c[1]['retained_fraction']:.6%} | {r['full_patch_move_baseline_pass']} |")
    lines += ["", "−3 mm 的去料会打通局部外壁，面 727 消失，面 6 只保留极小一片。有效实体不能被误判为完整保面平移成功。",
              "−3 mm 的解析扫掠工具触发 OCCT 7.7 参数曲线构造失败；转换工具为 NURBS 后得到去料结果。没有放大布尔容差。", "",
              "严格检查另行报告：原件 370 个 Invalid Curve on Surface、224 个 Unorientable Shape；+3 mm 数量相同，−3 mm 为 364 / 222。",
              "这只是数量比较，不证明所有缺陷身份相同；两个基线均未通过严格检查。普通 BRepCheck、双面边关联及 STEP 往返结果见各 case 的 report.json。", "",
              "在交互 DRAW 中 `source -encoding utf-8 /absolute/path/to/review.tcl` 可切换原件与两个结果，青色线框表示目标面。",
              "在 DRAW 中 source 各 case 的 replay.tcl 可重建 BREP。Python 重新生成几何与验证报告：", "", "```powershell",
              "python examples/move_face_benchmark.py --selections <selections.jsonl> --output <output-directory>", "```", "",
              "case.json 记录输入散列、面索引、位移和验收约束；attempts.json 保存真实命令及响应；没有将失败的解析布尔操作当作成功。"]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
