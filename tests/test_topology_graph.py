"""Topology identity and incidence invariants, checked with the real OCCT kernel."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from occ_harness.engine import Harness, ROOT


class TopologyGraphIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="occ-graph-test-")
        cls.state = Path(cls.temp.name)
        cls.h = Harness(cls.state, timeout=30)
        cls.h.start("graph")

    @classmethod
    def tearDownClass(cls):
        cls.h.stop("graph")
        cls.temp.cleanup()

    def data(self, response):
        self.assertTrue(response["ok"], response)
        return response.get("data", response)

    def make(self, script, name):
        self.data(self.h.execute("graph", script, [name]))
        return self.data(self.h.call("graph", "topology_graph", shape=name))

    def invariants(self, graph):
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertEqual(len(nodes), graph["node_count"])
        self.assertEqual(len(graph["uses"]), graph["use_count"])
        self.assertEqual(len({n["definition_id"] for n in nodes.values()}), graph["definition_count"])
        self.assertIn(graph["root"], nodes)
        children = defaultdict(list)
        for i, use in enumerate(graph["uses"], 1):
            self.assertEqual(use["id"], i)
            self.assertIn(use["parent"], nodes)
            self.assertIn(use["child"], nodes)
            self.assertIn(use["orientation"], ("FORWARD", "REVERSED", "INTERNAL", "EXTERNAL"))
            children[use["parent"]].append(use["child"])
            self.assertEqual(use["ordinal"], len(children[use["parent"]]))
            # Every reference must reproduce the child's accumulated transform.
            parent, local = nodes[use["parent"]]["location"], use["location"]
            world = nodes[use["child"]]["location"]
            for r in range(4):
                for c in range(4):
                    self.assertAlmostEqual(sum(parent[r][k] * local[k][c] for k in range(4)), world[r][c], places=9)
        seen, pending = set(), [graph["root"]]
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(children[node])
        self.assertEqual(seen, set(nodes))
        for field, kind, parent_kind in (("edge_faces", "edge", "face"), ("vertex_edges", "vertex", "edge")):
            self.assertEqual(set(graph[field]), {str(i) for i, n in nodes.items() if n["type"] == kind})
            for parents in graph[field].values():
                self.assertEqual(len(parents), len(set(parents)))
                self.assertTrue(all(nodes[i]["type"] == parent_kind for i in parents))
        return nodes

    def test_01_box_shared_edges_and_selection_indices(self):
        graph = self.make("box graph_box 10 20 30", "graph_box")
        nodes = self.invariants(graph)
        self.assertEqual(graph["node_count"], 34)
        self.assertEqual(graph["use_count"], 61)
        self.assertEqual(Counter(n["type"] for n in nodes.values()), {"solid": 1, "shell": 1, "face": 6, "wire": 6, "edge": 12, "vertex": 8})
        self.assertTrue(all(len(faces) == 2 for faces in graph["edge_faces"].values()))
        self.assertTrue(all(len(edges) == 3 for edges in graph["vertex_edges"].values()))
        vertices = self.data(self.h.call("graph", "subshapes", shape="graph_box", type="vertex"))["items"]
        positions = {v["index"]: v["bbox"]["min"] for v in vertices}
        for node in (n for n in nodes.values() if n["type"] == "edge"):
            endpoints = [positions[nodes[u["child"]]["type_index"]] for u in graph["uses"] if u["parent"] == node["id"]]
            selected = self.data(self.h.call("graph", "select", shape="graph_box", type="edge", index=node["type_index"], name="graph_selected_edge"))
            self.assertEqual(selected["bbox"]["min"], [min(p[i] for p in endpoints) for i in range(3)])
            self.assertEqual(selected["bbox"]["max"], [max(p[i] for p in endpoints) for i in range(3)])

    def test_02_cylinder_seam_and_closed_edge_uses(self):
        graph = self.make("pcylinder graph_cylinder 5 12", "graph_cylinder")
        nodes = self.invariants(graph)
        groups = defaultdict(list)
        for use in graph["uses"]:
            groups[use["parent"], use["child"]].append(use)
        seam = [uses for (parent, child), uses in groups.items()
                if nodes[parent]["type"] == "wire" and nodes[child]["type"] == "edge" and len(uses) == 2]
        self.assertEqual(len(seam), 1)
        self.assertEqual({u["orientation"] for u in seam[0]}, {"FORWARD", "REVERSED"})
        seam_edge = seam[0][0]["child"]
        self.assertEqual(len(graph["edge_faces"][str(seam_edge)]), 1)
        closed_edges = [uses for (parent, child), uses in groups.items()
                        if nodes[parent]["type"] == "edge" and nodes[child]["type"] == "vertex" and len(uses) == 2]
        self.assertEqual(len(closed_edges), 2)
        for uses in closed_edges:
            self.assertEqual({u["orientation"] for u in uses}, {"FORWARD", "REVERSED"})

    def test_03_located_instances_and_noncommuting_transforms(self):
        graph = self.make("box instance_base 1 2 3; compound instance_base instances; ttranslate instance_base 10 0 0; add instance_base instances; trotate instances 0 0 0 0 0 1 90; ttranslate instances 5 7 0", "instances")
        nodes = self.invariants(graph)
        self.assertEqual(graph["node_count"], 69)
        self.assertEqual(graph["definition_count"], 35)
        solids = [n for n in nodes.values() if n["type"] == "solid"]
        self.assertEqual(len(solids), 2)
        self.assertEqual(solids[0]["definition_id"], solids[1]["definition_id"])
        self.assertEqual({round(n["location"][1][3], 8) for n in solids}, {7, 17})
        for node in solids:
            self.assertAlmostEqual(node["location"][0][3], 5)
            selected = self.data(self.h.call("graph", "select", shape="instances", type="solid", index=node["type_index"], name="instance_solid"))
            self.assertAlmostEqual(selected["bbox"]["min"][0], 3)
            self.assertAlmostEqual(selected["bbox"]["min"][1], node["location"][1][3])
        # Two uses at the SAME location collapse to a node, but their uses remain distinct.
        duplicate = self.make("compound instance_base instance_base repeated", "repeated")
        self.invariants(duplicate)
        root_uses = [u for u in duplicate["uses"] if u["parent"] == duplicate["root"]]
        self.assertEqual(len(root_uses), 2)
        self.assertEqual(root_uses[0]["child"], root_uses[1]["child"])
        self.assertEqual(duplicate["node_count"], 35)

    def test_04_coincident_geometry_and_root_orientation(self):
        graph = self.make("box separate_a 1 2 3; box separate_b 1 2 3; compound separate_a separate_b coincident", "coincident")
        self.invariants(graph)
        self.assertEqual(graph["node_count"], 69)
        self.assertEqual(graph["definition_count"], 69)
        graph = self.make("box reversed_box 1 2 3; treverse reversed_box", "reversed_box")
        self.invariants(graph)
        self.assertEqual(graph["root_orientation"], "REVERSED")
        forward = self.make("box forward_box 1 2 3", "forward_box")
        # Canonical node definitions/uses do not absorb the root's orientation.
        self.assertEqual([u["orientation"] for u in graph["uses"]], [u["orientation"] for u in forward["uses"]])

    def test_05_free_edges_isolated_vertices_and_nonmanifold_adjacency(self):
        self.data(self.h.execute("graph", "box adjacency_box 10 20 30", ["adjacency_box"]))
        self.data(self.h.call("graph", "select", shape="adjacency_box", type="edge", index=1, name="free_edge"))
        self.data(self.h.call("graph", "select", shape="adjacency_box", type="vertex", index=1, name="isolated_vertex"))
        free = self.data(self.h.call("graph", "topology_graph", shape="free_edge"))
        self.invariants(free)
        self.assertEqual(free["edge_faces"], {"1": []})
        isolated = self.data(self.h.call("graph", "topology_graph", shape="isolated_vertex"))
        self.invariants(isolated)
        self.assertEqual(isolated["vertex_edges"], {"1": []})
        self.data(self.h.call("graph", "select", shape="adjacency_box", type="wire", index=1, name="shared_wire"))
        graph = self.make("mkplane third_face shared_wire; compound adjacency_box third_face nonmanifold", "nonmanifold")
        self.invariants(graph)
        self.assertEqual(sum(len(faces) == 3 for faces in graph["edge_faces"].values()), 4)

    def test_06_json_export_cli_and_tcl(self):
        graph = self.make("box export_graph_box 2 3 4", "export_graph_box")
        output = self.state / "中文 graph.json"
        summary = self.data(self.h.call("graph", "topology_graph", shape="export_graph_box", path=output.as_posix()))
        self.assertEqual(summary["bytes"], output.stat().st_size)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), graph)
        denied = self.h.call("graph", "topology_graph", shape="export_graph_box", path=output.as_posix())
        self.assertFalse(denied["ok"])
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), graph)
        self.data(self.h.call("graph", "topology_graph", shape="export_graph_box", path=output.as_posix(), overwrite=True))
        for args in ({"shape": "absent_graph_shape"}, {"shape": "export_graph_box", "path": "relative.json"}, {"shape": "export_graph_box", "overwrite": True}):
            self.assertFalse(self.h.call("graph", "topology_graph", **args)["ok"])
        raw = self.data(self.h.execute("graph", "ah_topology_graph export_graph_box", []))
        self.assertEqual(json.loads(raw["result"]), graph)
        completed = subprocess.run([sys.executable, "-m", "occ_harness", "--state-dir", str(self.state), "topology_graph", "graph", "export_graph_box"],
                                   cwd=ROOT, capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["data"], graph)

    def test_07_large_graph_uses_file_without_invalidating_session(self):
        self.data(self.h.execute("graph", "set parts {}; for {set i 0} {$i < 400} {incr i} {box large_$i 1 2 3; lappend parts large_$i}; compound {*}$parts large_graph", ["large_graph"]))
        inline = self.h.call("graph", "topology_graph", shape="large_graph")
        self.assertFalse(inline["ok"])
        self.assertIn("inline limit", inline["error"])
        self.assertTrue(self.h.context("graph")["session"]["alive"])
        output = self.state / "large.json"
        summary = self.data(self.h.call("graph", "topology_graph", shape="large_graph", path=output.as_posix()))
        self.assertGreater(summary["bytes"], 4 * 1024 * 1024)
        large = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(large["node_count"], 400 * 34 + 1)
        self.assertEqual(large["use_count"], 400 * 62)


if __name__ == "__main__":
    unittest.main(verbosity=2)
