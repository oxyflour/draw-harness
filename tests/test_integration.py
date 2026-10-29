"""Behavioral checks against the actual installed OCCT kernel; no mocked modeling."""
from __future__ import annotations
import concurrent.futures
import json
import math
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from occ_harness.engine import Harness, HarnessError, ROOT, read_json


class DrawIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="occ-harness-test-")
        cls.state = Path(cls.temp.name) / "工作空间 with spaces"
        cls.h = Harness(cls.state, timeout=15)
        cls.h.start("geometry")

    @classmethod
    def tearDownClass(cls):
        for name in ("geometry", "timeout", "isolated"):
            if (cls.h.directory(name) / "session.json").exists():
                cls.h.stop(name)
        cls.temp.cleanup()

    def data(self, response):
        self.assertTrue(response["ok"], response)
        return response.get("data", response)

    def box(self, name="block"):
        return self.data(self.h.execute("geometry", f"box {name} 80 50 12", [name]))

    def test_01_tcl_persistence_and_unicode_capture(self):
        self.box()
        result = self.data(self.h.execute("geometry", 'set 中文变量 17; puts "建模完成"; puts -nonewline stderr "警告"; set 中文变量', []))
        self.assertEqual(result["result"], "17")
        self.assertEqual(result["stdout"], "建模完成\n警告")
        # A second Python client and a separate CLI process must see the same session.
        second = Harness(self.state)
        inspected = self.data(second.call("geometry", "inspect", shape="block"))
        self.assertAlmostEqual(inspected["volume"], 48000)
        completed = subprocess.run([sys.executable, "-m", "occ_harness", "--state-dir", str(self.state), "inspect", "geometry", "block"],
                                   cwd=ROOT, capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["data"]["topology"]["solid"], 1)

    def test_02_boolean_volume_and_topology(self):
        script = "box stock 80 50 12; pcylinder drill 6 20; ttranslate drill 40 25 -4; bcut plate stock drill"
        self.data(self.h.execute("geometry", script, ["plate"]))
        p = self.data(self.h.call("geometry", "inspect", shape="plate"))
        self.assertTrue(p["valid"])
        self.assertEqual(p["topology"]["solid"], 1)
        self.assertEqual(p["bbox"]["size"], [80, 50, 12])
        self.assertAlmostEqual(p["volume"], 48000 - math.pi * 36 * 12, places=6)
        faces = self.data(self.h.call("geometry", "subshapes", shape="plate", type="face"))
        self.assertEqual(sum(f["geometry"] == "cylinder" for f in faces["items"]), 1)

    def test_03_select_edge_and_fillet(self):
        self.box("fillet_source")
        edges = self.data(self.h.call("geometry", "subshapes", shape="fillet_source", type="edge", limit=20))
        edge = next(e for e in edges["items"] if e["bbox"]["min"] == [0, 0, 0] and e["bbox"]["max"] == [0, 0, 12])
        selected = self.data(self.h.call("geometry", "select", shape="fillet_source", type="edge", index=edge["index"], name="corner_edge"))
        self.assertEqual(selected["type"], "edge")
        self.assertIsNone(selected["volume"])
        self.data(self.h.execute("geometry", "blend rounded fillet_source 2 corner_edge", ["rounded"]))
        rounded = self.data(self.h.call("geometry", "inspect", shape="rounded"))
        self.assertEqual(rounded["topology"]["solid"], 1)
        self.assertAlmostEqual(rounded["volume"], 48000 - (4 - math.pi) * 12, places=5)

    def test_04_exchange_roundtrip_and_no_overwrite(self):
        self.box("exchange_source")
        output = self.state / "导出文件 with spaces"
        output.mkdir(exist_ok=True)
        for fmt in ("brep", "step", "stl"):
            path = (output / f"模型.{fmt}").as_posix()
            result = self.data(self.h.call("geometry", "export", shape="exchange_source", path=path, format=fmt))
            self.assertGreater(result["bytes"], 100)
            self.assertFalse(self.h.call("geometry", "export", shape="exchange_source", path=path, format=fmt)["ok"])
            if fmt != "stl":
                restored = self.data(self.h.call("geometry", "import", shape=f"from_{fmt}", path=path, format=fmt))
                self.assertTrue(restored["valid"])
                self.assertAlmostEqual(restored["volume"], 48000, places=5)
            else:
                content = Path(path).read_bytes()
                triangles = struct.unpack_from("<I", content, 80)[0]
                self.assertGreater(triangles, 0)
                self.assertEqual(len(content), 84 + triangles * 50)

    def test_05_checkpoint_memory_and_restart(self):
        self.h.start("isolated")
        self.data(self.h.execute("isolated", "box original 10 20 30; set transient 7", ["original"]))
        self.h.memory("isolated", "goal", {"尺寸": [10, 20, 30], "units": "mm"}, write=True)
        self.data(self.h.checkpoint("isolated", "before_edit", ["original"]))
        self.data(self.h.execute("isolated", "ttranslate original 100 0 0", ["original"]))
        self.data(self.h.restore("isolated", "before_edit"))
        self.assertEqual(self.data(self.h.call("isolated", "inspect", shape="original"))["bbox"]["min"], [0, 0, 0])
        self.h.stop("isolated")
        self.h.start("isolated")
        self.assertFalse(self.h.call("isolated", "inspect", shape="original")["ok"])
        self.data(self.h.restore("isolated", "before_edit"))
        self.assertAlmostEqual(self.data(self.h.call("isolated", "inspect", shape="original"))["volume"], 6000)
        self.assertEqual(self.h.memory("isolated")["memory"]["goal"]["value"]["尺寸"], [10, 20, 30])
        self.assertFalse(self.h.execute("isolated", "set transient", [])["ok"])
        self.assertFalse(self.h.call("geometry", "inspect", shape="original")["ok"])

    def test_06_errors_do_not_claim_rollback(self):
        result = self.h.execute("geometry", 'box partial 1 2 3; error "intentional failure"', ["partial"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["code"], 1)
        self.assertIn("intentional failure", result["data"]["error_info"])
        self.assertTrue(result["data"]["state_may_have_changed"])
        self.assertAlmostEqual(self.data(self.h.call("geometry", "inspect", shape="partial"))["volume"], 6)
        self.assertFalse(self.h.execute("geometry", "set x 1", ["missing_output"])["ok"])
        self.assertFalse(self.h.call("geometry", "select", shape="partial", type="edge", index=500, name="bad_edge")["ok"])

    def test_07_timeout_stops_process_without_replay(self):
        self.h.start("timeout")
        short = Harness(self.state, timeout=0.2)
        result = short.execute("timeout", "after 5000; box should_not_exist 1 1 1", [])
        self.assertFalse(result["ok"])
        self.assertTrue(result["session_invalidated"])
        self.assertFalse(self.h.context("timeout")["session"]["alive"])
        with self.assertRaises(HarnessError):
            self.h.call("timeout", "inspect", shape="should_not_exist")
        self.h.start("timeout")
        self.assertFalse(self.h.call("timeout", "inspect", shape="should_not_exist")["ok"])

    def test_08_authentication_and_client_serialization(self):
        meta = read_json(self.h.directory("geometry") / "session.json")
        with socket.create_connection(("127.0.0.1", meta["port"]), timeout=3) as sock:
            sock.sendall(json.dumps({"op": "eval", "script": "box unauthorized 1 1 1", "token": "wrong"}).encode() + b"\n")
            response = json.loads(sock.makefile("rb").readline())
        self.assertFalse(response["ok"])
        self.assertFalse(self.h.call("geometry", "inspect", shape="unauthorized")["ok"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda i: Harness(self.state).execute("geometry", f"box concurrent_{i} 1 2 3", [f"concurrent_{i}"]), range(3)))
        self.assertTrue(all(r["ok"] for r in results), results)

    def test_09_output_limit_and_real_help(self):
        result = self.data(self.h.execute("geometry", 'puts [string repeat x 100000]; set done 1', []))
        self.assertEqual(len(result["stdout"]), 65536)
        result = self.data(self.h.help("geometry", "blend"))
        self.assertIn("blend result object", result["stdout"] + result["native_output"])

    def test_10_mcp_wire_and_tools(self):
        command = [sys.executable, "-m", "occ_harness", "--state-dir", str(self.state), "mcp"]
        with subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", bufsize=1) as process:
            def request(identifier, method, params=None):
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}) + "\n")
                process.stdin.flush()
                return json.loads(process.stdout.readline())
            init = request(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
            self.assertEqual(init["result"]["protocolVersion"], "2025-11-25")
            process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            process.stdin.flush()
            listing = request(2, "tools/list")
            self.assertIn("occ_topology_graph", {t["name"] for t in listing["result"]["tools"]})
            result = request(3, "tools/call", {"name": "occ_exec", "arguments": {"session": "geometry", "script": "box mcp_box 3 4 5", "check": ["mcp_box"]}})
            self.assertFalse(result["result"]["isError"])
            self.assertAlmostEqual(result["result"]["structuredContent"]["checks"]["mcp_box"]["data"]["volume"], 60)
            invalid = request(4, "tools/call", {"name": "occ_inspect", "arguments": {"session": "geometry", "shape": "mcp_box", "unexpected": True}})
            self.assertEqual(invalid["error"]["code"], -32602)
            prompt = request(5, "prompts/get", {"name": "occ-modeling"})
            self.assertIn("gpt-6-luna", prompt["result"]["messages"][0]["content"]["text"])
            graph = request(6, "tools/call", {"name": "occ_topology_graph", "arguments": {"session": "geometry", "shape": "mcp_box"}})
            self.assertFalse(graph["result"]["isError"])
            self.assertEqual(graph["result"]["structuredContent"]["data"]["node_count"], 34)
            path = self.state / "MCP图.json"
            exported = request(7, "tools/call", {"name": "occ_topology_graph", "arguments": {"session": "geometry", "shape": "mcp_box", "path": path.as_posix()}})
            self.assertFalse(exported["result"]["isError"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["use_count"], 61)
            process.stdin.close()
            process.wait(timeout=5)
            self.assertEqual(process.stderr.read(), "")
            self.assertEqual(process.returncode, 0)

    def test_11_powershell_mcp_entrypoint_unicode(self):
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(ROOT / "occ-harness.ps1"), "--state-dir", str(self.state), "mcp"]
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "launcher-test", "version": "1"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "occ_exec", "arguments": {"session": "geometry", "script": "puts 启动入口中文正确; box launcher_box 2 3 4", "check": ["launcher_box"]}}},
        ]
        completed = subprocess.run(command, cwd=ROOT, input="".join(json.dumps(x, ensure_ascii=False) + "\n" for x in messages),
                                   capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        replies = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(len(replies), 2)
        data = replies[1]["result"]["structuredContent"]
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["data"]["stdout"], "启动入口中文正确\n")
        self.assertAlmostEqual(data["checks"]["launcher_box"]["data"]["volume"], 24)


if __name__ == "__main__":
    unittest.main(verbosity=2)
