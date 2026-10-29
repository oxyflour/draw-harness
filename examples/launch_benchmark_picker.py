"""Launch the installed draw.bat with a local benchmark picking panel and RPC."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from occ_harness.engine import Harness, ROOT, _process, now, write_json


def tcl(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace('\n', '\\n').replace('\r', '\\r') + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "artifacts/benchmarks/toStudent_EM_top10/manifest.json")
    parser.add_argument("--initial", type=int, default=1)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not 1 <= args.initial <= len(manifest["exports"]):
        parser.error("initial case is outside the manifest")
    stamp = str(time.time_ns())
    session = "benchmark_gui_" + stamp
    output = ROOT / "artifacts/benchmarks/toStudent_EM_selections" / stamp
    output.mkdir(parents=True)
    (output / "snapshots").mkdir()
    h = Harness(ROOT / ".occ-harness", timeout=300)
    directory = h.directory(session)
    directory.mkdir(parents=True)
    env = h._environment()
    token = secrets.token_hex(32)
    ready, info = directory / "ready.port", directory / "gui-info.json"
    env.update(OCC_HARNESS_GUI="1", OCC_HARNESS_TOKEN=token, OCC_HARNESS_READY=str(ready), OCC_GUI_INFO=str(info))
    config = ["namespace eval ::bench {}", f"set ::bench::output {tcl(output.as_posix())}",
              f"set ::bench::session {tcl(session)}",
              f"set ::bench::latestPointer {tcl((ROOT / '.occ-harness/latest_benchmark_picker.json').as_posix())}",
              f"set ::bench::initial {args.initial}", "set ::bench::cases [dict create]"]
    for entry in manifest["exports"]:
        path = args.manifest.parent / entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("STEP changed since export: " + str(path))
        config.append(f"dict set ::bench::cases {entry['rank']} [dict create path {tcl(path.resolve().as_posix())} sha256 {tcl(entry['sha256'])} faces {entry['faces']} source_index {entry['source_solid_index']}]")
    config += [f"source -encoding utf-8 {tcl((ROOT / 'runtime/server.tcl').as_posix())}",
               f"source -encoding utf-8 {tcl((ROOT / 'runtime/benchmark_picker.tcl').as_posix())}"]
    init = directory / "DrawAppliInit.tcl"
    body = "\n".join(config)
    init.write_text("if {[catch {\n" + body + "\n} error options]} {\nset f [open " + tcl((directory / "startup_error.log").as_posix()) + " w]\nputs $f $error\nputs $f [dict get $options -errorinfo]\nclose $f\n}\n", encoding="utf-8")
    env["CSF_DrawAppliInit"] = str(init)
    # User explicitly requested a visible interactive DRAW; invoke the real vendor draw.bat.
    process = subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(h.occt / "draw.bat")],
                               env=env, cwd=directory, creationflags=subprocess.CREATE_NEW_CONSOLE)
    deadline = time.monotonic() + 40
    while not (ready.is_file() and info.is_file()):
        error = directory / "startup_error.log"
        if error.exists():
            raise RuntimeError(error.read_text(errors="replace"))
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("DRAW did not report a ready GUI; inspect its windows and " + str(directory))
        time.sleep(0.1)
    gui = json.loads(info.read_text(encoding="utf-8"))
    meta = {"session": session, "pid": gui["pid"], "process": _process(gui["pid"]), "token": token,
            "port": int(ready.read_text().strip()), "status": "running", "started_at": now(), "gui": True,
            "model": h.config["default_model"], "units": h.config["units"], "occt_root": str(h.occt),
            "selection_directory": str(output), "launcher_pid": process.pid}
    if not meta["process"]:
        raise RuntimeError("Cannot identify interactive DRAW")
    write_json(directory / "session.json", meta)
    write_json(output / "session.json", {k: v for k, v in meta.items() if k not in ("token", "port", "process")})
    write_json(output / "source_manifest.json", manifest)
    write_json(ROOT / ".occ-harness/latest_benchmark_picker.json", {"session": session, "output": str(output)})
    print(json.dumps({"ok": True, "session": session, "pid": gui["pid"], "selection_directory": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
