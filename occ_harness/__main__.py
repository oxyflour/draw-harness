from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .engine import Harness, HarnessError


def main() -> int:
    parser = argparse.ArgumentParser(description="OCCT 7.7 DRAW agent harness (JSON output)")
    parser.add_argument("--state-dir", help="Persistent workspace state directory")
    parser.add_argument("--timeout", type=float, help="RPC deadline; stops DRAW on expiry")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("mcp", help="MCP stdio server; no API key required")
    for command in ("start", "stop", "context", "exec", "inspect", "topology", "topology_graph", "select", "export", "import", "checkpoint", "restore", "memory", "help", "surface_info", "patch_context", "expand_selection", "edit_candidate", "validate_edit"):
        p = sub.add_parser(command)
        p.add_argument("session")
        if command in ("surface_info", "patch_context", "expand_selection", "edit_candidate", "validate_edit"):
            p.add_argument("shape" if command != "validate_edit" else "source")
            p.add_argument("--faces", nargs="+", type=int, required=command != "surface_info")
            p.add_argument("--expected-revision", required=command in ("patch_context", "expand_selection", "edit_candidate"))
            if command == "surface_info":
                p.add_argument("--offset", type=int)
                p.add_argument("--limit", type=int)
            if command == "patch_context":
                p.add_argument("--depth", type=int, default=1)
                p.add_argument("--max-faces", type=int, default=100)
            if command in ("edit_candidate", "validate_edit"):
                p.add_argument("--vector", nargs=3, type=float, required=True)
                p.add_argument("--policy", type=Path, required=True, help="JSON file declaring target_mode, allow_breakthrough and allow_new_supports")
            if command == "validate_edit":
                p.add_argument("candidate")
                p.add_argument("--source-revision", required=True)
                p.add_argument("--candidate-revision", required=True)
        elif command == "start":
            p.add_argument("--model", default="gpt-6-luna", help="Session metadata; select the actual model in your agent client")
        elif command == "exec":
            source = p.add_mutually_exclusive_group(required=True)
            source.add_argument("--script")
            source.add_argument("--file", type=Path)
            source.add_argument("--stdin", action="store_true")
            p.add_argument("--check", nargs="+", help="Require these outputs to exist and pass BRepCheck")
        elif command in ("inspect", "topology", "topology_graph", "select", "export", "import"):
            p.add_argument("shape")
            if command == "topology_graph":
                p.add_argument("--output", type=Path, help="Write complete graph JSON and return a small summary")
                p.add_argument("--overwrite", action="store_true")
            if command in ("topology", "select"):
                p.add_argument("type", choices=["edge", "face", "vertex", "wire", "shell", "solid", "compound", "compsolid"])
            if command == "topology":
                p.add_argument("--offset", type=int, default=0)
                p.add_argument("--limit", type=int, default=100)
            if command == "select":
                p.add_argument("index", type=int)
                p.add_argument("name")
            if command in ("export", "import"):
                p.add_argument("path", type=Path)
                p.add_argument("--format", choices=["brep", "step", "stl"] if command == "export" else ["brep", "step"])
            if command == "export":
                p.add_argument("--overwrite", action="store_true")
                p.add_argument("--deflection", type=float, default=0.1)
        elif command == "checkpoint":
            p.add_argument("name")
            p.add_argument("shapes", nargs="+")
        elif command == "restore":
            p.add_argument("name")
        elif command == "memory":
            p.add_argument("--key")
            value = p.add_mutually_exclusive_group()
            value.add_argument("--value")
            value.add_argument("--json", dest="json_value", help="JSON value to remember")
        elif command == "help":
            p.add_argument("draw_command")
    args = parser.parse_args()
    try:
        harness = Harness(args.state_dir, args.timeout)
        cmd = args.command
        if cmd == "mcp":
            from .mcp import serve
            serve(harness)
            return 0
        if cmd == "doctor":
            result = harness.doctor()
        elif cmd == "start":
            result = harness.start(args.session, args.model)
        elif cmd in ("stop", "context"):
            result = getattr(harness, cmd)(args.session)
        elif cmd == "exec":
            script = args.script if args.script is not None else args.file.read_text(encoding="utf-8-sig") if args.file else sys.stdin.read()
            result = harness.execute(args.session, script, args.check)
        elif cmd == "inspect":
            result = harness.call(args.session, "inspect", shape=args.shape)
        elif cmd in ("surface_info", "patch_context", "expand_selection", "edit_candidate", "validate_edit"):
            from .mcp import invoke, validate, BY_NAME
            p = {key: value for key, value in vars(args).items() if key not in ("command", "state_dir", "timeout") and value is not None}
            if cmd in ("edit_candidate", "validate_edit"):
                p["policy"] = json.loads(args.policy.read_text(encoding="utf-8-sig"))
            tool_name = "occ_" + cmd
            validate(p, BY_NAME[tool_name]["inputSchema"])
            result = invoke(harness, tool_name, p)
        elif cmd == "topology":
            result = harness.call(args.session, "subshapes", shape=args.shape, type=args.type, offset=args.offset, limit=args.limit)
        elif cmd == "topology_graph":
            extra = {"path": args.output.resolve().as_posix()} if args.output else {}
            result = harness.call(args.session, "topology_graph", shape=args.shape, overwrite=args.overwrite, **extra)
        elif cmd == "select":
            result = harness.call(args.session, "select", shape=args.shape, type=args.type, index=args.index, name=args.name)
        elif cmd in ("export", "import"):
            ext = args.path.suffix.lower().lstrip(".")
            fmt = args.format or {"stp": "step", "brp": "brep"}.get(ext, ext)
            extra = {"overwrite": args.overwrite, "deflection": args.deflection} if cmd == "export" else {}
            result = harness.call(args.session, cmd, shape=args.shape, path=args.path.resolve().as_posix(), format=fmt, **extra)
        elif cmd == "checkpoint":
            result = harness.checkpoint(args.session, args.name, args.shapes)
        elif cmd == "restore":
            result = harness.restore(args.session, args.name)
        elif cmd == "memory":
            value = json.loads(args.json_value) if args.json_value is not None else args.value
            result = harness.memory(args.session, args.key, value, write=args.value is not None or args.json_value is not None)
        elif cmd == "help":
            result = harness.help(args.session, args.draw_command)
        else:
            raise HarnessError("Unknown command")
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
