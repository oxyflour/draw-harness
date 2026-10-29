"""Geometry/semantic invariants and isolated recipe execution on the actual SDK."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from occ_harness.engine import Harness, HarnessError, ROOT
from occ_harness.mcp import BY_NAME, invoke, validate


POLICY = {"target_mode": "support_geometry", "allow_breakthrough": False, "allow_new_supports": False}


class DirectEditIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="occ-direct-edit-")
        cls.h = Harness(Path(cls.temp.name), timeout=180)
        cls.h.start("edit")

    @classmethod
    def tearDownClass(cls):
        cls.h.stop("edit")
        cls.temp.cleanup()

    def data(self, r):
        self.assertTrue(r["ok"], r)
        return r.get("data", r)

    def call(self, op, **args):
        return self.data(self.h.call("edit", op, **args))

    def make_bore(self, suffix, transform=""):
        shape = "bore_" + suffix
        self.data(self.h.execute("edit", f"box stock_{suffix} 20 20 10; pcylinder tool_{suffix} 2 12; ttranslate tool_{suffix} 10 10 -1; bcut {shape} stock_{suffix} tool_{suffix}; {transform}", [shape]))
        info = self.call("surface_info", shape=shape)
        seeds = [f["index"] for f in info["items"] if f["surface"]["type"] == "cylinder"]
        self.assertEqual(len(seeds), 1)
        return shape, seeds, info["revision"]

    def test_01_surface_revision_mesh_independence_and_locations(self):
        shape, seeds, rev = self.make_bore("surface", "trotate bore_surface 0 0 0 1 0 0 90; ttranslate bore_surface 4 7 13")
        before = self.call("inspect", shape=shape)
        info = self.call("surface_info", shape=shape, faces=seeds, expected_revision=rev)["items"][0]
        self.assertAlmostEqual(info["surface"]["radius"], 2)
        self.assertTrue(info["surface"]["inward_wall"])
        self.assertAlmostEqual(info["surface"]["axis"][1], -1)
        self.assertTrue(any(u["seam"] for w in info["wires"] for u in w["edge_uses"]))
        path = Path(self.temp.name) / "coarse_mesh.stl"
        self.call("export", shape=shape, path=path.as_posix(), format="stl", deflection=1.0)
        after = self.call("inspect", shape=shape)
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["measurement_mode"], "geometry_without_triangulation")
        for field in ("area", "volume", "length"):
            self.assertAlmostEqual(before[field], after[field], places=9)
        self.assertAlmostEqual(before["volume"], 4000 - math.pi * 40, places=6)

    def test_02_local_context_stale_and_bounded_expansion(self):
        shape, seeds, rev = self.make_bore("context")
        context = self.call("patch_context", shape=shape, faces=seeds, expected_revision=rev, depth=1)
        self.assertEqual(len(context["faces"]), 3)
        truncated = self.call("patch_context", shape=shape, faces=seeds, expected_revision=rev, depth=1, max_faces=1)
        self.assertTrue(truncated["truncated"])
        self.assertEqual(len(truncated["faces"]), 1)
        feature = self.call("expand_selection", shape=shape, faces=seeds, expected_revision=rev)
        self.assertTrue(feature["supported"])
        self.assertEqual(feature["expanded_faces"], seeds)
        self.data(self.h.execute("edit", f"ttranslate {shape} 1 0 0", [shape]))
        stale = self.h.call("edit", "expand_selection", shape=shape, faces=seeds, expected_revision=rev)
        self.assertFalse(stale["ok"])
        self.assertIn("Stale", stale["error"])

    def test_03_valid_unchanged_shape_is_not_a_successful_move(self):
        shape, seeds, rev = self.make_bore("unchanged")
        result = self.call("validate_edit", source=shape, candidate=shape, faces=seeds, vector=[3, 0, 0],
                           source_revision=rev, candidate_revision=rev, policy=POLICY)
        self.assertTrue(result["checks"]["ordinary_valid_single_solid"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["checks"]["target_supports_located"])

    def test_04_recipe_from_raw_rotated_brep_and_source_preserved(self):
        shape, seeds, rev = self.make_bore("recipe", "trotate bore_recipe 0 0 0 1 1 0 37; ttranslate bore_recipe 4 7 13")
        result = self.data(self.h.edit_candidate("edit", shape=shape, faces=seeds, vector=[1, 0, 0],
                                                expected_revision=rev, policy=POLICY))
        self.assertEqual(result["status"], "accepted", result)
        self.assertTrue(result["source_unchanged"])
        self.assertTrue(result["step_roundtrip"]["pass"])
        self.assertEqual(self.call("inspect", shape=shape)["revision"], rev)
        self.assertTrue(Path(result["artifacts"]["brep"]).is_file())
        self.assertEqual([v["topology"]["face"] for v in result["calibration"].values()], [0, 0])

    def test_05_expansion_on_imported_stepped_hole_and_policy_semantics(self):
        path = ROOT / "artifacts/benchmarks/case02_part05_move_xz3/input/part_05.brep"
        source = self.call("import", shape="imported", format="brep", path=path.as_posix())
        feature = self.call("expand_selection", shape="imported", faces=[8, 317], expected_revision=source["revision"])
        self.assertTrue(feature["supported"])
        self.assertEqual(feature["expanded_faces"], [6, 7, 8, 317, 318, 319, 320])
        self.assertEqual(feature["boundary_faces"], [30, 83, 84])
        self.assertEqual(len(feature["tool_segments"]), 3)
        # Allow unclassified supports here to isolate the breakthrough criterion.
        for mode, vector, expected in [("x_minus3", [-3,0,0], True), ("z_plus3", [0,0,3], False)]:
            candidate = self.call("import", shape=mode, format="brep", path=(path.parent.parent/mode/"candidate.brep").as_posix())
            r = self.call("validate_edit", source="imported", candidate=mode, source_revision=source["revision"],
                          candidate_revision=candidate["revision"], faces=feature["expanded_faces"], vector=vector,
                          policy={**POLICY, "allow_new_supports": True})
            self.assertEqual(r["checks"]["core_transition_sections_complete"], expected, r)
            self.assertEqual(r["accepted"], expected, r)
            self.assertFalse(r["source_exact_valid"])
            self.assertFalse(r["candidate_exact_valid"])

    def test_06_mcp_and_cli_validate_real_surface_results(self):
        shape, seeds, rev = self.make_bore("protocol")
        args = {"session":"edit", "shape":shape, "faces":seeds, "expected_revision":rev}
        validate(args, BY_NAME["occ_surface_info"]["inputSchema"])
        response = self.data(invoke(self.h, "occ_surface_info", args))
        self.assertEqual(response["items"][0]["surface"]["radius"], 2)
        cli = subprocess.run([sys.executable,"-m","occ_harness","--state-dir",str(self.h.state),"surface_info","edit",shape,"--faces",str(seeds[0]),"--expected-revision",rev],
                             cwd=ROOT, capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["data"]["revision"], rev)
        for bad in ([1,1], [0], [True]):
            with self.assertRaises(ValueError):
                validate({**args, "faces":bad}, BY_NAME["occ_surface_info"]["inputSchema"])
        with self.assertRaises(ValueError):
            validate(float("nan"), {"type":"number"})

    def test_07_unsupported_and_recipe_failure_leave_source_and_evidence(self):
        self.data(self.h.execute("edit", "box unsupported 3 4 5", ["unsupported"]))
        rev=self.call("inspect",shape="unsupported")["revision"]
        result=self.data(self.h.edit_candidate("edit",shape="unsupported",faces=[1],vector=[1,0,0],policy=POLICY,expected_revision=rev))
        self.assertEqual(result["status"],"unsupported_feature")
        self.assertFalse(result["accepted"])
        self.assertTrue(result["source_unchanged"])
        with self.assertRaises(HarnessError):
            self.h.edit_candidate("edit",shape="unsupported",faces=[1],vector=[1,0,0],policy={**POLICY,"allow_breakthough":False},expected_revision=rev)

    def test_08_free_geometry_duplicate_uses_and_reversed_material_rejected(self):
        shape,seeds,rev=self.make_bore("adversarial")
        self.data(self.h.execute("edit",f"box stray 2 2 2; explode stray F; compound {shape} stray_1 extra_face; compound {shape} {shape} double_use; tcopy {shape} reversed_material; treverse reversed_material",["extra_face","double_use","reversed_material"]))
        for name in ("extra_face","double_use","reversed_material"):
            measured=self.call("inspect",shape=name)
            result=self.call("validate_edit",source=shape,candidate=name,source_revision=rev,candidate_revision=measured["revision"],
                             faces=seeds,vector=[0,0,0],policy={**POLICY,"allow_breakthrough":True,"allow_new_supports":True})
            self.assertFalse(result["accepted"],(name,result))

    def test_09_short_blind_bore_cannot_pass_as_complete_through_bore(self):
        self.data(self.h.execute("edit","box blind_stock 20 20 10; pcylinder through_tool 2 12; ttranslate through_tool 6 10 -1; bcut through_source blind_stock through_tool; pcylinder short_tool 2 3; ttranslate short_tool 14 10 3.5; bcut short_candidate blind_stock short_tool",["through_source","short_candidate"]))
        source=self.call("surface_info",shape="through_source")
        seeds=[f["index"] for f in source["items"] if f["surface"]["type"]=="cylinder"]
        candidate=self.call("inspect",shape="short_candidate")
        result=self.call("validate_edit",source="through_source",candidate="short_candidate",source_revision=source["revision"],candidate_revision=candidate["revision"],
                         faces=seeds,vector=[8,0,0],policy={**POLICY,"allow_new_supports":True})
        self.assertFalse(result["accepted"],result)
        self.assertFalse(result["checks"]["entire_moved_bore_void"])

    def test_10_unrelated_hole_cannot_disappear_outside_edit_envelope(self):
        self.data(self.h.execute("edit","box local_stock 30 20 10; pcylinder local_tool 2 12; ttranslate local_tool 6 10 -1; bcut only_one_hole local_stock local_tool; pcylinder remote_tool 2 12; ttranslate remote_tool 24 10 -1; bcut two_holes only_one_hole remote_tool",["only_one_hole","two_holes"]))
        source=self.call("surface_info",shape="two_holes")
        seeds=[f["index"] for f in source["items"] if f["surface"]["type"]=="cylinder" and abs(f["surface"]["origin"][0]-6)<1e-6]
        candidate=self.call("inspect",shape="only_one_hole")
        result=self.call("validate_edit",source="two_holes",candidate="only_one_hole",source_revision=source["revision"],candidate_revision=candidate["revision"],
                         faces=seeds,vector=[0,0,0],policy={**POLICY,"allow_new_supports":True})
        self.assertFalse(result["accepted"],result)
        self.assertFalse(result["checks"]["outside_feature_envelope_preserved"])

    def test_11_open_sector_is_rejected_before_fill_and_original_survives(self):
        source=self.call("import",shape="open_sector",format="brep",path=(ROOT/"artifacts/benchmarks/case03_move_x3/input/part_03.brep").as_posix())
        feature=self.call("expand_selection",shape="open_sector",faces=[6,727],expected_revision=source["revision"])
        self.assertFalse(feature["supported"])
        self.assertIn("partial/open",feature["reason"])
        result=self.data(self.h.edit_candidate("edit",shape="open_sector",faces=[6,727],vector=[3,0,0],policy=POLICY,expected_revision=source["revision"]))
        self.assertEqual(result["status"],"unsupported_feature")
        self.assertEqual(result["stages"],[])
        self.assertTrue(result["source_unchanged"])

    def test_12_axial_cylinder_support_translation_does_not_make_a_blind_hole(self):
        shape,seeds,rev=self.make_bore("axial")
        result=self.data(self.h.edit_candidate("edit",shape=shape,faces=seeds,vector=[0,0,5],policy=POLICY,expected_revision=rev))
        self.assertTrue(result["accepted"],result)
        self.assertTrue(result["source_unchanged"])
        self.assertTrue(result["validation"]["checks"]["entire_moved_bore_void"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
