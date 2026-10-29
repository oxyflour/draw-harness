"""Create, directly edit, inspect, checkpoint and export a real sample part."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from occ_harness.engine import Harness, ROOT, write_json


def require(result):
    if not result["ok"]:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result.get("data", result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/demo")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    h = Harness(ROOT / ".occ-harness")
    session = "mounting_plate_demo"
    require(h.start(session))
    try:
        require(h.execute(session, (ROOT / "examples/mounting_plate.tcl").read_text(encoding="utf-8"), ["plate_v4"]))
        edges = require(h.call(session, "subshapes", shape="plate_v4", type="edge", limit=100))["items"]
        corner = next(e for e in edges if e["bbox"]["min"] == [0, 0, 0] and e["bbox"]["max"] == [0, 0, 10])
        require(h.call(session, "select", shape="plate_v4", type="edge", index=corner["index"], name="outer_corner"))
        require(h.execute(session, "blend final_part plate_v4 3 outer_corner", ["final_part"]))
        measured = require(h.call(session, "inspect", shape="final_part"))
        require(h.memory(session, "part", {"goal": "带凸台和五个通孔的安装板，外角 R3", "units": "mm", "shape": "final_part",
                                           "dimensions": [100, 70, 22], "verified_volume": measured["volume"]}, write=True))
        # Unique names keep earlier recovery points intact on repeated demo runs.
        import time
        checkpoint = f"finished_{time.time_ns()}"
        require(h.checkpoint(session, checkpoint, ["final_part"]))
        files = {}
        for fmt in ("brep", "step", "stl"):
            path = output / f"mounting_plate.{fmt}"
            files[fmt] = require(h.call(session, "export", shape="final_part", path=path.as_posix(), format=fmt, overwrite=True))
        files["topology_graph"] = require(h.call(session, "topology_graph", shape="final_part", path=(output / "topology_graph.json").as_posix(), overwrite=True))
        report = {"ok": True, "session": session, "checkpoint": checkpoint, "inspection": measured, "files": files}
        write_json(output / "report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        h.stop(session)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
