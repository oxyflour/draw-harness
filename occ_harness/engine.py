from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAX_MESSAGE = 4 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}\Z")
_CHILDREN: dict[int, subprocess.Popen] = {}


class HarnessError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def valid_name(value: str) -> str:
    if not NAME.fullmatch(value):
        raise HarnessError("Use 1-64 ASCII letters/digits/underscores/hyphens for session/checkpoint names")
    # Windows device names are invalid even with an extension.
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *[f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)]}:
        raise HarnessError("Windows reserved name")
    return value


def _process(pid: int, terminate: bool = False, expected: dict | None = None) -> dict | None:
    """Validate creation time AND executable path before terminating a stored PID."""
    if os.name != "nt":
        raise HarnessError("This SDK integration requires Windows")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle = k.OpenProcess(0x1000 | (0x100001 if terminate else 0), False, pid)
    if not handle:
        return None
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        if exited.dwLowDateTime or exited.dwHighDateTime:
            return None
        buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        identity = {"created": (created.dwHighDateTime << 32) | created.dwLowDateTime,
                    "exe": os.path.normcase(buf.value)}
        if terminate:
            if identity != expected:
                raise HarnessError("Process identity changed; refusing to terminate this PID")
            if not k.TerminateProcess(handle, 1):
                raise HarnessError("Could not terminate timed out DRAW process")
            if k.WaitForSingleObject(handle, 5000) != 0:
                raise HarnessError("DRAW did not exit after termination")
            child = _CHILDREN.pop(pid, None)
            if child is not None:
                child.wait(timeout=5)
        return identity
    finally:
        k.CloseHandle(handle)


class Harness:
    def __init__(self, state_dir: str | Path | None = None, timeout: float | None = None):
        self.config = read_json(ROOT / "harness.json")
        self.occt = Path(os.environ.get("OCC_HARNESS_OCCT_ROOT", self.config["occt_root"])).resolve()
        self.state = Path(state_dir or os.environ.get("OCC_HARNESS_STATE_DIR", Path.cwd() / ".occ-harness")).resolve()
        self.timeout = float(timeout if timeout is not None else self.config["timeout_seconds"])
        if not 0 < self.timeout <= 3600:
            raise HarnessError("timeout must be in (0, 3600] seconds")

    def directory(self, session: str) -> Path:
        return self.state / "sessions" / valid_name(session)

    @contextlib.contextmanager
    def lock(self, session: str):
        import msvcrt
        directory = self.directory(session)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "client.lock").open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + self.timeout + 5
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise HarnessError("Session is busy; lock wait timed out")
                    time.sleep(0.05)
            try:
                yield directory
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def doctor(self) -> dict:
        paths = {"draw_bat": self.occt / "draw.bat", "environment": self.occt / "env.bat",
                 "draw_exe": self.occt / "win64/vc14/bin/DRAWEXE.exe", "native_module": ROOT / "bin/occ_agent.dll",
                 "tcl": self.occt.parent / "tcltk-86-64/bin/tcl86.dll"}
        checks = {key: {"path": str(path), "exists": path.is_file()} for key, path in paths.items()}
        return {"ok": os.name == "nt" and all(x["exists"] for x in checks.values()),
                "model": self.config["default_model"], "state_dir": str(self.state), "checks": checks}

    def _environment(self) -> dict:
        env = dict(os.environ, OCC_ENV_BAT=str(self.occt / "env.bat"))
        # Static wrapper avoids interpolating a user-supplied SDK path into shell code.
        result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ROOT / "runtime/env.cmd")],
                                env=env, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise HarnessError("OCCT env.bat failed: " + result.stderr.decode(errors="replace")[-2000:])
        # cmd.exe uses the Windows OEM codepage for redirected environment output.
        codepage = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        for line in result.stdout.decode(codepage, errors="replace").splitlines():
            if "=" in line and not line.startswith("="):
                key, value = line.split("=", 1)
                for old in list(env):
                    if old.casefold() == key.casefold():
                        del env[old]
                env[key] = value
        path_key = next((k for k in env if k.casefold() == "path"), "PATH")
        env[path_key] = str(ROOT / "bin") + os.pathsep + env.get(path_key, "")
        env["CSF_AgentPluginDefaults"] = str(ROOT / "runtime")
        return env

    def _metadata(self, session: str) -> dict:
        meta = read_json(self.directory(session) / "session.json")
        if not meta:
            raise HarnessError("Session does not exist; run start first")
        return meta

    def _history(self, directory: Path, request: dict, response: dict, elapsed: float) -> None:
        entry = {"at": now(), "request": request, "response": response, "elapsed_seconds": round(elapsed, 4)}
        with (directory / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rpc(self, session: str, request: dict, *, record: bool = True, timeout: float | None = None) -> dict:
        directory, meta = self.directory(session), self._metadata(session)
        if meta.get("status") != "running" or _process(meta["pid"]) != meta["process"]:
            raise HarnessError("Session is stopped or stale. Start it explicitly; use a checkpoint to recover geometry")
        message = json.dumps(dict(request, token=meta["token"]), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(message) > 1024 * 1024:
            raise HarnessError("Request exceeds 1 MiB")
        started = time.monotonic()
        try:
            deadline = started + (timeout or self.timeout)
            with socket.create_connection(("127.0.0.1", meta["port"]), timeout=timeout or self.timeout) as sock:
                sock.sendall(message)
                raw = bytearray()
                while b"\n" not in raw:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("RPC deadline exceeded")
                    sock.settimeout(remaining)
                    block = sock.recv(65536)
                    if not block:
                        raise ConnectionError("DRAW closed the connection before returning a result")
                    raw.extend(block)
                    if len(raw) > MAX_MESSAGE:
                        raise HarnessError("Response exceeds 4 MiB")
                response = json.loads(raw.split(b"\n", 1)[0])
        except (OSError, ValueError, HarnessError) as exc:
            # A timeout or broken transport has unknown mutation status. Never retry it.
            _process(meta["pid"], terminate=True, expected=meta["process"])
            meta["status"] = "invalid"
            meta["stopped_at"] = now()
            write_json(directory / "session.json", meta)
            response = {"ok": False, "error": str(exc), "session_invalidated": True,
                        "state_may_have_changed": True, "recovery": "Start explicitly and restore a saved checkpoint; no automatic replay"}
        if record:
            self._history(directory, request, response, time.monotonic() - started)
        return response

    def start(self, session: str, model: str | None = None) -> dict:
        if not self.doctor()["ok"]:
            raise HarnessError("Dependencies missing; run doctor and scripts/build.ps1")
        with self.lock(session) as directory:
            previous = read_json(directory / "session.json")
            if previous and previous.get("status") == "running" and _process(previous["pid"]) == previous["process"]:
                response = self._rpc(session, {"op": "ping"}, record=False)
                return {"ok": response["ok"], "session": session, "reused": True, "engine": response}
            ready = directory / "ready.port"
            ready.unlink(missing_ok=True)
            env = self._environment()
            token = secrets.token_hex(32)
            env.update(OCC_HARNESS_TOKEN=token, OCC_HARNESS_READY=str(ready))
            with (directory / "draw.log").open("ab", buffering=0) as log:
                process = subprocess.Popen([str(self.occt / "win64/vc14/bin/DRAWEXE.exe"), "-b", "-f", str(ROOT / "runtime/server.tcl")],
                                           env=env, cwd=directory, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                deadline = time.monotonic() + 25
                while not ready.is_file():
                    if process.poll() is not None:
                        raise HarnessError("DRAW startup failed: " + (directory / "draw.log").read_text(errors="replace")[-4000:])
                    if time.monotonic() > deadline:
                        raise HarnessError("DRAW startup timed out; see " + str(directory / "draw.log"))
                    time.sleep(0.05)
                meta = {"session": session, "pid": process.pid, "process": _process(process.pid), "token": token,
                        "port": int(ready.read_text().strip()), "status": "running", "started_at": now(),
                        "model": model or self.config["default_model"], "units": self.config["units"],
                        "occt_root": str(self.occt)}
                if not meta["process"]:
                    raise HarnessError("Cannot identify DRAW process")
                write_json(directory / "session.json", meta)
                # Keep a process handle while this client lives; sessions intentionally outlive CLI calls.
                _CHILDREN[process.pid] = process
                response = self._rpc(session, {"op": "ping"}, record=False)
                if not response["ok"]:
                    raise HarnessError("DRAW handshake failed: " + str(response))
                return {"ok": True, "session": session, "reused": False, "pid": process.pid,
                        "model": meta["model"], "units": meta["units"], "engine": response["data"],
                        "memory": read_json(directory / "memory.json", {}),
                        "checkpoint_names": self._checkpoint_names(directory)}
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                raise

    def call(self, session: str, op: str, **arguments) -> dict:
        with self.lock(session):
            return self._rpc(session, dict(op=op, **arguments))

    def execute(self, session: str, script: str, check: list[str] | None = None) -> dict:
        with self.lock(session):
            response = self._rpc(session, {"op": "eval", "script": script})
            if response["ok"] and check:
                checks = {name: self._rpc(session, {"op": "inspect", "shape": name}) for name in check}
                response["checks"] = checks
                response["ok"] = all(r["ok"] and r["data"]["valid"] for r in checks.values())
                if not response["ok"]:
                    response["error"] = "A requested output shape is absent or invalid; prior state may have changed"
            return response

    def stop(self, session: str) -> dict:
        with self.lock(session) as directory:
            meta = self._metadata(session)
            response = {"ok": True, "already_stopped": True}
            if meta.get("status") == "running" and _process(meta["pid"]) == meta["process"]:
                response = self._rpc(session, {"op": "shutdown"}, timeout=3)
                deadline = time.monotonic() + 3
                while _process(meta["pid"]) == meta["process"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                if _process(meta["pid"]) == meta["process"]:
                    _process(meta["pid"], terminate=True, expected=meta["process"])
            meta["status"], meta["stopped_at"] = "stopped", now()
            child = _CHILDREN.pop(meta["pid"], None)
            if child is not None:
                child.wait(timeout=5)
            write_json(directory / "session.json", meta)
            return response

    def memory(self, session: str, key: str | None = None, value: Any = None, *, write: bool = False) -> dict:
        with self.lock(session) as directory:
            memory = read_json(directory / "memory.json", {})
            if write:
                if not key or len(key) > 128:
                    raise HarnessError("Memory key must have 1-128 characters")
                if len(json.dumps(value, ensure_ascii=False)) > 32768:
                    raise HarnessError("Memory value exceeds 32 KiB")
                memory[key] = {"value": value, "updated_at": now()}
                write_json(directory / "memory.json", memory)
            return {"ok": True, "memory": memory if key is None else {key: memory.get(key)}}

    @staticmethod
    def _checkpoint_names(directory: Path) -> list[str]:
        base = directory / "checkpoints"
        return sorted(p.parent.name for p in base.glob("*/manifest.json"))

    def checkpoint(self, session: str, name: str, shapes: list[str]) -> dict:
        valid_name(name)
        if not shapes or len(shapes) != len(set(shapes)):
            raise HarnessError("Supply a nonempty list of unique shapes")
        with self.lock(session) as directory:
            folder = directory / "checkpoints" / name
            if folder.exists():
                raise HarnessError("Checkpoint already exists; choose a new name")
            # Inspect every shape before writing anything.
            inspections = {}
            for shape in shapes:
                result = self._rpc(session, {"op": "inspect", "shape": shape})
                if not result["ok"] or not result["data"]["valid"]:
                    return {"ok": False, "error": "Checkpoint requires existing valid shapes", "shape": shape, "details": result}
                inspections[shape] = result["data"]
            folder.mkdir(parents=True)
            entries = []
            for i, shape in enumerate(shapes):
                path = folder / f"{i:03d}.brep"
                result = self._rpc(session, {"op": "export", "shape": shape, "format": "brep", "path": path.as_posix()})
                if not result["ok"]:
                    return {"ok": False, "error": "Checkpoint incomplete; choose a new name", "details": result}
                entries.append({"shape": shape, "file": path.name, "inspection": inspections[shape]})
            manifest = {"schema": 1, "name": name, "created_at": now(), "shapes": entries,
                        "memory": read_json(directory / "memory.json", {}),
                        "scope": "Named BRep geometry only. Tcl variables/procedures and other shapes are not restored."}
            write_json(folder / "manifest.json", manifest)
            return {"ok": True, "manifest": str(folder / "manifest.json"), "shapes": shapes}

    def restore(self, session: str, name: str) -> dict:
        valid_name(name)
        with self.lock(session) as directory:
            folder = directory / "checkpoints" / name
            manifest = read_json(folder / "manifest.json")
            if not manifest:
                raise HarnessError("Checkpoint not found or incomplete")
            # Preflight all files; restoration overwrites only the names listed in the manifest.
            for entry in manifest["shapes"]:
                path = (folder / entry["file"]).resolve()
                if path.parent != folder.resolve() or not path.is_file():
                    raise HarnessError("Checkpoint contains an invalid or missing shape file")
            results = {}
            for entry in manifest["shapes"]:
                results[entry["shape"]] = self._rpc(session, {"op": "import", "shape": entry["shape"], "format": "brep",
                                                              "path": (folder / entry["file"]).as_posix()})
                if not results[entry["shape"]]["ok"]:
                    return {"ok": False, "error": "Partial restore; inspect state before continuing", "shapes": results}
            return {"ok": True, "shapes": results, "memory_at_checkpoint": manifest["memory"], "scope": manifest["scope"]}

    def context(self, session: str) -> dict:
        with self.lock(session) as directory:
            meta = read_json(directory / "session.json", {})
            public = {k: v for k, v in meta.items() if k not in ("token", "port", "process")}
            public["alive"] = bool(meta.get("pid") and _process(meta["pid"]) == meta.get("process"))
            recent = []
            history = directory / "history.jsonl"
            if history.exists():
                from collections import deque
                with history.open(encoding="utf-8") as handle:
                    for line in deque(handle, maxlen=6):
                        item = json.loads(line)
                        req = item["request"]
                        recent.append({"at": item["at"], "op": req["op"], "ok": item["response"]["ok"],
                                       "script": req.get("script", "")[:1200], "shape": req.get("shape")})
            return {"ok": True, "session": public, "memory": read_json(directory / "memory.json", {}),
                    "checkpoints": self._checkpoint_names(directory), "recent": recent,
                    "history_file": str(history), "draw_log": str(directory / "draw.log")}

    def help(self, session: str, command: str) -> dict:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:]*", command):
            raise HarnessError("Supply an exact DRAW command name")
        # Return actual installed-version help, not a guessed syntax table.
        return self.execute(session, "help " + command)
