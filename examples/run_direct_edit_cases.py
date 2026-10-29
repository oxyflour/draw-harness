"""Run raw-source direct-edit tasks; no prepared plugs/tools or reference answers."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from occ_harness.engine import Harness, ROOT, write_json
from occ_harness.editing import normalize_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".occ-harness")
    args = parser.parse_args()
    task = json.loads(args.case.read_text(encoding="utf-8-sig"))
    policy = normalize_policy(task["policy"])
    source = (args.case.resolve().parent / task["input"]).resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new or empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    h = Harness(args.state_dir, timeout=180)
    session = "raw_edit_" + str(time.time_ns())
    results = []
    h.start(session)
    try:
        loaded = h.call(session, "import", shape="source", format=task.get("format", "brep"), path=source.as_posix())
        if not loaded["ok"]:
            raise RuntimeError(loaded)
        for i, vector in enumerate(task["vectors"]):
            started = time.monotonic()
            response = h.edit_candidate(session, shape="source", faces=task["faces"], vector=vector,
                                        expected_revision=loaded["data"]["revision"], policy=policy)
            report = response.get("data", {})
            case_id = f"case_{i+1:02d}"
            folder = output / case_id
            folder.mkdir()
            for fmt, file in report.get("artifacts", {}).items():
                shutil.copyfile(file, folder / ("candidate.brep" if fmt == "brep" else "candidate.stp"))
            write_json(folder / "report.json", response)
            result = {"case": case_id, "vector": vector, "operation_ok": response["ok"],
                      "accepted": report.get("accepted", False), "status": report.get("status"),
                      "seconds": round(time.monotonic()-started, 3), "manifest": response.get("manifest")}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if report.get("session_invalidated"):
                break
    finally:
        h.stop(session)
        write_json(output / "summary.json", {"schema_version": 1, "input": str(source),
                   "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "seed_faces": task["faces"],
                   "policy": policy, "input_scope": "Original BRep plus selection/vector/policy only; tools and expansion computed at runtime",
                   "results": results})


if __name__ == "__main__":
    main()
