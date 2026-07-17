import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8-sig"))


class WorkflowTests(unittest.TestCase):
    def assert_links_resolve(self, graph):
        ids = set(graph)
        for node in graph.values():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], ids)

    def test_text_to_image_contract(self):
        graph = load("workflows/qwen-text-to-image.api.json")
        classes = {node["class_type"] for node in graph.values()}
        self.assertIn("EmptyLatentImage", classes)
        self.assertIn("KSampler", classes)
        self.assertNotIn("LoadImage", classes)
        serialized = json.dumps(graph)
        self.assertIn("${PROMPT}", serialized)
        self.assertIn("${NEGATIVE_PROMPT}", serialized)
        self.assertIn("${SEED}", serialized)
        self.assert_links_resolve(graph)

    def test_image_edit_contract(self):
        graph = load("workflows/qwen-image-edit.api.json")
        classes = {node["class_type"] for node in graph.values()}
        self.assertIn("LoadImage", classes)
        self.assertIn("TextEncodeQwenImageEditPlus", classes)
        serialized = json.dumps(graph)
        self.assertIn("${SOURCE_IMAGE}", serialized)
        self.assertIn("${WIDTH}", serialized)
        self.assertIn("${HEIGHT}", serialized)
        self.assertIn("${PROMPT}", serialized)
        self.assertIn("${NEGATIVE_PROMPT}", serialized)
        self.assert_links_resolve(graph)

    def test_edit_profile_matches_calibrated_qwen_path(self):
        graph = load("workflows/qwen-image-edit.api.json")
        sampler = next(node for node in graph.values() if node["class_type"] == "KSampler")
        self.assertEqual(sampler["inputs"]["denoise"], 1.0)
        self.assertEqual(sampler["inputs"]["steps"], 8)


class SchedulingSnapshotTests(unittest.TestCase):
    def test_control_plane_is_tainted_and_workers_exist(self):
        snapshot = load("docs/phase0/kubernetes-scheduling-snapshot.json")
        master = next(node for node in snapshot["nodes"] if node["name"] == "rasp-master")
        self.assertIn("control-plane", master["roles"])
        self.assertTrue(any(taint.get("effect") == "NoSchedule" for taint in master["taints"]))
        workers = [node for node in snapshot["nodes"] if "control-plane" not in node["roles"]]
        self.assertGreaterEqual(len(workers), 1)
        self.assertTrue(all(node["ready"] for node in workers))
        self.assertTrue(all(node["architecture"] == "arm64" for node in workers))


class EngineRunTests(unittest.TestCase):
    def test_eight_job_run_and_reconnect_contract(self):
        report = load("docs/test/report-eight-job.json")
        self.assertEqual(len(report["jobs"]), 8)
        self.assertEqual(report["summary"]["completed"], 8)
        self.assertTrue(report["summary"]["forced_reconnect_observed"])
        self.assertGreater(report["summary"]["events_after_reconnect"], 0)
        self.assertTrue(all(job["history_reconciled"] for job in report["jobs"]))
        self.assertTrue(all(not job["queue_after"]["queue_running"] for job in report["jobs"]))
        self.assertTrue(all(not job["queue_after"]["queue_pending"] for job in report["jobs"]))

    def test_engine_reproducibility_manifest(self):
        manifest = load("docs/phase0/aicore-comfyui-repro.json")
        self.assertEqual(manifest["repositories"][0]["commit"], "25757a53c93281e8e2462ced8795373f09e675bf")
        self.assertEqual(len(manifest["model"]["sha256"]), 64)
        self.assertGreater(manifest["model"]["size_bytes"], 1_000_000_000)
        patch = (ROOT / "docs/phase0/aicore-nodes-qwen.patch").read_text(encoding="utf-8-sig")
        self.assertIn("target_latent", patch)
        self.assertIn("poses", patch)

    def test_expanded_golden_set(self):
        report = load("docs/test/golden/report-golden.json")
        self.assertEqual(report["summary"]["jobs"], 8)
        self.assertEqual(report["summary"]["completed"], 8)
        self.assertEqual(len(report["domains"]), 4)
        output_root = ROOT / "docs/test/golden"
        for case in report["cases"]:
            self.assertTrue(case["status"].get("completed"))
            for filename in case["outputs"]:
                self.assertTrue((output_root / filename).is_file())

    def test_comfy_kitchen_portable_artifact(self):
        artifact = load("docs/phase0/comfy-kitchen-s3-artifact.json")
        wheel = ROOT / "artifacts/comfyui/comfy_kitchen-0.2.7-cp312-abi3-linux_x86_64.whl"
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        self.assertEqual(digest, artifact["sha256"])
        self.assertEqual(wheel.stat().st_size, artifact["size_bytes"])
        self.assertTrue(artifact["download_sha256_verified"])

    def test_pose_awareness_matrix(self):
        report = load("docs/test/pose-awareness/report-pose-awareness.json")
        self.assertEqual(report["summary"]["jobs"], 6)
        self.assertEqual(report["summary"]["completed"], 6)
        self.assertEqual({case["seed"] for case in report["cases"]}, {report["fixed_seed"]})
        output_root = ROOT / "docs/test/pose-awareness"
        for case in report["cases"]:
            self.assertEqual(case["denoise"], 1.0)
            self.assertTrue(case["status"].get("completed"))
            for filename in case["outputs"]:
                self.assertTrue((output_root / filename).is_file())


if __name__ == "__main__":
    unittest.main()
