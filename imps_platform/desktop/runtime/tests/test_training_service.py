from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from dataset_service import TrainingDatasetService  # noqa: E402
from training_service import ModelTrainingService, TrainingServiceError  # noqa: E402


PCAP_BYTES = b"\xd4\xc3\xb2\xa1" + b"\x00" * 20


FAKE_WORKER = r'''
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
for name in ("snapshot", "output", "work", "progress", "result", "portable-runtime-dir", "ai-project", "baseline-artifacts", "tshark", "epochs"):
    parser.add_argument("--" + name, required=True)
args = parser.parse_args()
mode = os.environ.get("FAKE_WORKER_MODE", "")
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
Path(args.work).mkdir(parents=True, exist_ok=True)
(Path(args.work) / "decoded.csv").write_text("t,kind\n", encoding="utf-8")
Path(args.progress).write_text(json.dumps({"stage":"training_lstm","progress":75,"detail":"fake training"}), encoding="utf-8")
files = {}
for name, payload in (("lstm_ae.npz", b"fake-lstm"), ("gru_fore.npz", b"fake-gru")):
    path = output / name
    path.write_bytes(payload)
    files[name] = {"sha256": hashlib.sha256(payload).hexdigest(), "sizeBytes": len(payload)}
if mode == "tamper":
    (output / "gru_fore.npz").write_bytes(b"swapped after hashing")
created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
manifest = {"schemaVersion":1,"artifactVersion":"0123456789abcdef","format":"numpy-npz-no-pickle","createdAt":created,"files":files}
(output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
approval = "approved" if mode == "approval" else "manual_validation_required"
candidate = {"artifactVersion":"0123456789abcdef","createdAt":created,"approvalStatus":approval,"training":{"device":"cpu","deviceName":"CPU","epochs":int(args.epochs),"normalCaptures":1,"faultReserveCaptures":0,"normalSessions":1,"faultReserveSessions":0,"extractedEvents":10,"aeWindows":1,"forecasterWindows":1,"aeWindowsAvailable":1,"forecasterWindowsAvailable":1,"contributingCaptures":1,"contributingSessions":1,"aeLossInitial":1.0,"aeLossFinal":0.5,"forecasterLossInitial":1.0,"forecasterLossFinal":0.5,"durationSeconds":0.1},"files":files}
Path(args.result).write_text(json.dumps({"schemaVersion":1,"candidate":candidate}), encoding="utf-8")
'''


class ModelTrainingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.datasets = TrainingDatasetService(self.root / "datasets")
        self.worker = self.root / "training" / "train_candidate.py"
        self.worker.parent.mkdir(parents=True)
        self.worker.write_text(FAKE_WORKER, encoding="utf-8")
        self.runtime_dir = self.root / "runtime"
        self.runtime_dir.mkdir()
        (self.runtime_dir / "capture.py").write_text("# fake", encoding="utf-8")
        self.tshark = self.root / "tshark.exe"
        self.tshark.write_bytes(b"fake")
        self.models = self.root / "models"
        self.models.mkdir()
        self.project = self.root / "ai-project"
        for relative in ("models/nn_tools.py", "core/feature_tracker.py", "core/schema.py"):
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fake", encoding="utf-8")
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        (self.artifacts / "lstm_ae.pt").write_bytes(b"fake")
        (self.artifacts / "gru_fore.pt").write_bytes(b"fake")
        source_digest = hashlib.sha256()
        for name in ("lstm_ae.pt", "gru_fore.pt"):
            path = self.artifacts / name
            source_digest.update(name.encode("ascii"))
            source_digest.update(str(path.stat().st_size).encode("ascii"))
            source_digest.update(hashlib.sha256(path.read_bytes()).digest())
        self.base_version = source_digest.hexdigest()[:16]
        (self.models / "manifest.json").write_text(
            json.dumps({"artifactVersion": self.base_version}), encoding="utf-8"
        )
        self.service = ModelTrainingService(
            root=self.root / "training-jobs",
            dataset_service=self.datasets,
            worker_script=self.worker,
            portable_runtime_dir=self.runtime_dir,
            tshark=self.tshark,
            base_model_dir=self.models,
            python_executable=Path(sys.executable),
            ai_project=self.project,
            baseline_artifacts=self.artifacts,
            timeout_seconds=30,
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self.temp.cleanup()

    def upload_and_complete(self, name: str = "capture.pcap") -> tuple[str, str]:
        batch = self.datasets.create_import("Training batch", "folder")
        upload = self.datasets.begin_upload(
            batch["importId"], name, name, content_length=len(PCAP_BYTES)
        )
        self.datasets.write_upload(upload, PCAP_BYTES)
        self.datasets.finish_upload(upload)
        self.datasets.complete_import(batch["importId"])
        digest = self.datasets.label_batch(batch["importId"])["files"][0]["sha256"]
        return batch["importId"], digest

    def test_completed_reviewed_batch_can_create_a_candidate_job(self) -> None:
        import_id, digest = self.upload_and_complete()
        self.datasets.save_label(
            import_id,
            digest=digest,
            classification="normal",
            fault_family=None,
            reviewer="QA",
            notes="Verified normal capture.",
            expected_revision=0,
        )
        summary = self.service.summary()
        self.assertTrue(summary["engine"]["available"])
        self.assertEqual(len(summary["eligibleImports"]), 1)

        created = self.service.create_job(
            name="October candidate", import_ids=[import_id], epochs=2
        )
        self.assertEqual(created["status"], "queued")
        deadline = time.time() + 10
        completed = created
        while time.time() < deadline:
            completed = self.service.get_job(created["jobId"])
            if completed["status"] in {"complete", "failed"}:
                break
            time.sleep(0.05)
        self.assertEqual(completed["status"], "complete", completed.get("error"))
        self.assertEqual(completed["candidate"]["artifactVersion"], "0123456789abcdef")
        self.assertEqual(completed["candidate"]["training"]["epochs"], 2)

    def test_unreviewed_batch_is_not_eligible_for_training(self) -> None:
        import_id, _digest = self.upload_and_complete()
        self.assertEqual(self.service.summary()["eligibleImports"], [])
        with self.assertRaises(TrainingServiceError) as caught:
            self.service.create_job(name="Blocked", import_ids=[import_id], epochs=1)
        self.assertEqual(caught.exception.status, 409)

    def test_fault_only_batch_cannot_train_anomaly_models(self) -> None:
        import_id, digest = self.upload_and_complete()
        self.datasets.save_label(
            import_id,
            digest=digest,
            classification="fault",
            fault_family="PROTOCOL_FAILED",
            reviewer="QA",
            notes="Verified fault.",
            expected_revision=0,
        )
        with self.assertRaises(TrainingServiceError) as caught:
            self.service.create_job(name="No normals", import_ids=[import_id], epochs=1)
        self.assertEqual(caught.exception.status, 422)

    def test_mismatched_external_checkpoints_disable_training(self) -> None:
        (self.artifacts / "lstm_ae.pt").write_bytes(b"changed")
        health = self.service.health()
        self.assertFalse(health["available"])
        self.assertTrue(any("do not match" in item for item in health["missing"]))

    def label(self, import_id: str, digest: str, classification: str = "normal", revision: int = 0) -> None:
        self.datasets.save_label(
            import_id,
            digest=digest,
            classification=classification,
            fault_family="PROTOCOL_FAILED" if classification == "fault" else None,
            reviewer="QA",
            notes="",
            expected_revision=revision,
        )

    def run_job(self, import_id: str) -> dict:
        created = self.service.create_job(name="Run", import_ids=[import_id], epochs=1)
        deadline = time.time() + 15
        job = created
        while time.time() < deadline:
            job = self.service.get_job(created["jobId"])
            if job["status"] in {"complete", "failed"}:
                return job
            time.sleep(0.05)
        self.fail("training job did not finish")

    def test_tampered_candidate_artifact_fails_the_run(self) -> None:
        import_id, digest = self.upload_and_complete()
        self.label(import_id, digest)
        with mock.patch.dict(os.environ, {"FAKE_WORKER_MODE": "tamper"}):
            job = self.run_job(import_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("failed validation", job["error"])
        self.assertIsNone(job["candidate"])

    def test_candidate_claiming_approval_fails_the_run(self) -> None:
        import_id, digest = self.upload_and_complete()
        self.label(import_id, digest)
        with mock.patch.dict(os.environ, {"FAKE_WORKER_MODE": "approval"}):
            job = self.run_job(import_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("approval status", job["error"])

    def test_decoded_telemetry_is_removed_after_a_run_and_on_restart(self) -> None:
        import_id, digest = self.upload_and_complete()
        self.label(import_id, digest)
        job = self.run_job(import_id)
        self.assertEqual(job["status"], "complete", job.get("error"))
        job_dir = self.root / "training-jobs" / "jobs" / job["jobId"]
        self.assertFalse((job_dir / "work").exists())

        stale = self.root / "training-jobs" / "jobs" / ("a" * 32) / "work"
        stale.mkdir(parents=True)
        (stale / "left.csv").write_text("x", encoding="utf-8")
        restarted = ModelTrainingService(
            root=self.root / "training-jobs",
            dataset_service=self.datasets,
            worker_script=self.worker,
            portable_runtime_dir=self.runtime_dir,
            tshark=self.tshark,
            base_model_dir=self.models,
        )
        try:
            self.assertFalse(stale.exists())
        finally:
            restarted.shutdown()

    def test_preview_counts_captures_shared_between_batches_once(self) -> None:
        first, digest = self.upload_and_complete()
        second, same_digest = self.upload_and_complete("copy.pcap")
        self.assertEqual(digest, same_digest)
        self.label(first, digest)
        preview = self.service.preview([first, second])
        self.assertEqual(preview["fileCount"], 1)
        self.assertEqual(preview["normalFileCount"], 1)
        self.assertEqual(preview["captureBytes"], len(PCAP_BYTES))
        self.assertTrue(preview["withinLimit"])
        self.assertTrue(preview["hasNormal"])

    def test_preview_of_an_unreviewed_batch_is_refused(self) -> None:
        import_id, _digest = self.upload_and_complete()
        with self.assertRaises(TrainingServiceError) as caught:
            self.service.preview([import_id])
        self.assertEqual(caught.exception.status, 409)

    def unconfigured_service(self) -> ModelTrainingService:
        return ModelTrainingService(
            root=self.root / "training-jobs",
            dataset_service=self.datasets,
            worker_script=self.worker,
            portable_runtime_dir=self.runtime_dir,
            tshark=self.tshark,
            base_model_dir=self.models,
        )

    def test_engine_paths_come_from_engine_json_unless_the_environment_overrides_them(self) -> None:
        cleared = {key: value for key, value in os.environ.items() if not key.startswith("IMPS_TRAINING_")}
        (self.root / "training-jobs" / "engine.json").write_text(json.dumps({
            "python": sys.executable,
            "aiProject": str(self.project),
            "baselineArtifacts": str(self.artifacts),
        }), encoding="utf-8")
        with mock.patch.dict(os.environ, cleared, clear=True):
            service = self.unconfigured_service()
            try:
                health = service.health()
                self.assertTrue(health["available"], health["missing"])
                self.assertEqual(health["configSource"]["aiProject"], "config_file")
                self.assertTrue(health["configFile"].endswith("engine.json"))
                self.assertTrue(all(item["ok"] for item in health["requirements"]))

                os.environ["IMPS_TRAINING_AI_PROJECT"] = str(self.root / "nowhere")
                health = service.health()
                self.assertFalse(health["available"])
                self.assertEqual(health["configSource"]["aiProject"], "environment")
                failed = [item["id"] for item in health["requirements"] if not item["ok"]]
                self.assertEqual(failed, ["aiProject", "baselineMatch"])
            finally:
                service.shutdown()

    def test_unreadable_engine_json_is_reported(self) -> None:
        (self.root / "training-jobs" / "engine.json").write_text("{not json", encoding="utf-8")
        health = self.service.health()
        self.assertFalse(health["available"])
        self.assertIn("engine.json", health["configError"])


def _load_worker_module():
    worker = Path(__file__).resolve().parents[2] / "training" / "train_candidate.py"
    spec = importlib.util.spec_from_file_location("train_candidate_under_test", worker)
    module = importlib.util.module_from_spec(spec)
    # desktop/training ships as is inside the installer: leave no __pycache__ there
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


try:
    import numpy as np
except ImportError:  # the window tests need NumPy, the sidecar's only dependency
    np = None


@unittest.skipIf(np is None, "NumPy is not installed")
class WorkerWindowSamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = _load_worker_module()

    def sample(self, sessions: list[int], capacity: int) -> tuple[object, object]:
        ae = self.worker.WindowReservoir(capacity, 0, np)
        fore = self.worker.WindowReservoir(capacity, 1, np)
        for index, length in enumerate(sessions):
            values = np.arange(length * 40, dtype=np.float32).reshape(length, 40)
            self.worker.session_windows(values, np, ae, fore, (index, 0))
        return ae, fore

    def test_window_counts_match_the_original_strides(self) -> None:
        for length in (10, 16, 17, 20, 31, 32, 33, 40, 100):
            ae, fore = self.sample([length], 10_000)
            self.assertEqual(ae.seen, len(range(0, length - 32 + 1, 8)), length)
            self.assertEqual(fore.seen, len(range(0, length - 16, 4)), length)

    def test_capped_sample_is_spread_over_every_session_not_the_first_ones(self) -> None:
        ae, fore = self.sample([2_000] * 50, 500)
        self.assertEqual(len(ae.items), 500)
        self.assertEqual(ae.seen, 50 * len(range(0, 2_000 - 32 + 1, 8)))
        self.assertGreaterEqual(len({source for source in ae.sources}), 45)
        self.assertGreaterEqual(len({source for source in fore.sources}), 45)
        later_half = sum(1 for capture, _ in ae.sources if capture >= 25)
        self.assertGreater(later_half, 150)

    def test_sample_is_deterministic(self) -> None:
        first, _ = self.sample([300] * 20, 50)
        second, _ = self.sample([300] * 20, 50)
        self.assertEqual(first.sources, second.sources)
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(first.items, second.items)))

    def test_progress_write_failures_never_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "progress.json"
            with mock.patch.object(self.worker.os, "replace", side_effect=PermissionError(5, "in use")), \
                    mock.patch.object(self.worker.time, "sleep"):
                self.worker.update_progress(target, "extracting", 10, "busy")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
