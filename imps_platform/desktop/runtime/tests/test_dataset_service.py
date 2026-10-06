from __future__ import annotations

import io
import json
import stat
import struct
import sys
import threading
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import dataset_service  # noqa: E402
from dataset_service import DatasetServiceError, TrainingDatasetService  # noqa: E402


PCAP_BYTES = b"\xd4\xc3\xb2\xa1" + b"\x00" * 20
PCAPNG_BYTES = b"\x0a\x0d\x0d\x0a" + b"\x00" * 8


class DatasetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = TrainingDatasetService(self.root / "datasets")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def upload(self, import_id: str, name: str, payload: bytes, relative: str | None = None) -> dict:
        upload = self.service.begin_upload(
            import_id,
            name,
            relative or name,
            content_length=len(payload),
        )
        self.service.write_upload(upload, payload)
        return self.service.finish_upload(upload)

    def test_folder_batch_deduplicates_captures_and_stays_unapproved(self) -> None:
        batch = self.service.create_import("October 2026", "folder")
        first = self.upload(batch["importId"], "one.pcap", PCAP_BYTES, "station-a/one.pcap")
        second = self.upload(batch["importId"], "copy.pcap", PCAP_BYTES, "station-b/copy.pcap")
        complete = self.service.complete_import(batch["importId"])

        self.assertEqual(first["fileCount"], 1)
        self.assertEqual(second["fileCount"], 1)
        self.assertEqual(second["duplicateCount"], 1)
        self.assertEqual(complete["status"], "ready")
        self.assertFalse(complete["readyForRetrain"])

        summary = self.service.summary()
        self.assertEqual(summary["totals"]["imports"], 1)
        self.assertEqual(summary["totals"]["files"], 1)
        self.assertEqual(summary["totals"]["bytes"], len(PCAP_BYTES))
        self.assertEqual(summary["blocker"], "labels_and_training_pipeline_required")

    def test_later_batch_can_reference_existing_capture_without_storing_it_twice(self) -> None:
        first = self.service.create_import("September 2026", "folder")
        self.upload(first["importId"], "capture.pcap", PCAP_BYTES)
        self.service.complete_import(first["importId"])

        second = self.service.create_import("October 2026", "folder")
        uploaded = self.upload(second["importId"], "same-capture.pcap", PCAP_BYTES)
        completed = self.service.complete_import(second["importId"])

        self.assertEqual(uploaded["fileCount"], 1)
        self.assertEqual(uploaded["duplicateCount"], 1)
        self.assertEqual(completed["status"], "ready")
        stored = list((self.root / "datasets" / "files").glob("*/*.pcap"))
        self.assertEqual(len(stored), 1)
        summary = self.service.summary()
        self.assertEqual(summary["totals"]["files"], 2)
        self.assertEqual(summary["totals"]["bytes"], len(PCAP_BYTES))

    def test_upload_cannot_finish_after_batch_was_finalised(self) -> None:
        batch = self.service.create_import("Race guard", "folder")
        self.upload(batch["importId"], "first.pcap", PCAP_BYTES)
        late_payload = PCAP_BYTES + b"late"
        late = self.service.begin_upload(
            batch["importId"],
            "late.pcap",
            "late.pcap",
            content_length=len(late_payload),
        )
        self.service.write_upload(late, late_payload)
        self.service.complete_import(batch["importId"])

        with self.assertRaises(DatasetServiceError) as caught:
            self.service.finish_upload(late)
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse(late.temp_path.exists())
        self.assertEqual(self.service.summary()["totals"]["files"], 1)

    def test_ground_truth_label_updates_progress_and_retraining_blocker(self) -> None:
        batch = self.service.create_import("Label review", "folder")
        self.upload(batch["importId"], "capture.pcap", PCAP_BYTES)
        self.service.complete_import(batch["importId"])
        before = self.service.label_batch(batch["importId"])
        digest = before["files"][0]["sha256"]

        label = self.service.save_label(
            batch["importId"],
            digest=digest,
            classification="fault",
            fault_family="PROTOCOL_FAILED",
            reviewer="QA Operator",
            notes="Confirmed from the packet sequence.",
            expected_revision=0,
        )

        self.assertEqual(label["revision"], 1)
        self.assertEqual(label["faultFamily"], "PROTOCOL_FAILED")
        reviewed = self.service.label_batch(batch["importId"])
        self.assertEqual(reviewed["labelStatus"], "reviewed")
        self.assertEqual(reviewed["labeledFileCount"], 1)
        self.assertEqual(reviewed["faultFileCount"], 1)
        summary = self.service.summary()
        self.assertEqual(summary["totals"]["labeledFiles"], 1)
        self.assertEqual(summary["blocker"], "training_pipeline_required")
        self.assertFalse(summary["readyForRetrain"])

    def test_ground_truth_label_is_reused_by_duplicate_capture_batches(self) -> None:
        first = self.service.create_import("First", "folder")
        self.upload(first["importId"], "capture.pcap", PCAP_BYTES)
        self.service.complete_import(first["importId"])
        digest = self.service.label_batch(first["importId"])["files"][0]["sha256"]
        self.service.save_label(
            first["importId"],
            digest=digest,
            classification="normal",
            fault_family=None,
            reviewer="Reviewer",
            notes="Healthy exchange.",
            expected_revision=0,
        )

        second = self.service.create_import("Second", "folder")
        self.upload(second["importId"], "same.pcap", PCAP_BYTES)
        self.service.complete_import(second["importId"])
        reused = self.service.label_batch(second["importId"])

        self.assertEqual(reused["labelStatus"], "reviewed")
        self.assertEqual(reused["normalFileCount"], 1)
        self.assertEqual(reused["files"][0]["label"]["reviewer"], "Reviewer")

    def test_ground_truth_label_uses_optimistic_revision_and_keeps_history(self) -> None:
        batch = self.service.create_import("Revision", "folder")
        self.upload(batch["importId"], "capture.pcap", PCAP_BYTES)
        self.service.complete_import(batch["importId"])
        digest = self.service.label_batch(batch["importId"])["files"][0]["sha256"]
        self.service.save_label(
            batch["importId"],
            digest=digest,
            classification="normal",
            fault_family=None,
            reviewer="First Reviewer",
            notes="Initial review.",
            expected_revision=0,
        )
        with self.assertRaises(DatasetServiceError) as caught:
            self.service.save_label(
                batch["importId"],
                digest=digest,
                classification="exclude",
                fault_family=None,
                reviewer="Stale Reviewer",
                notes="Stale edit.",
                expected_revision=0,
            )
        self.assertEqual(caught.exception.status, 409)

        updated = self.service.save_label(
            batch["importId"],
            digest=digest,
            classification="exclude",
            fault_family=None,
            reviewer="Second Reviewer",
            notes="Capture is incomplete.",
            expected_revision=1,
        )
        self.assertEqual(updated["revision"], 2)
        label_path = self.root / "datasets" / "labels" / digest[:2] / f"{digest}.json"
        self.assertIn('"history":[{', label_path.read_text(encoding="utf-8"))

    def test_fault_label_requires_a_supported_family(self) -> None:
        batch = self.service.create_import("Invalid label", "folder")
        self.upload(batch["importId"], "capture.pcap", PCAP_BYTES)
        self.service.complete_import(batch["importId"])
        digest = self.service.label_batch(batch["importId"])["files"][0]["sha256"]
        with self.assertRaises(DatasetServiceError) as caught:
            self.service.save_label(
                batch["importId"],
                digest=digest,
                classification="fault",
                fault_family="MADE_UP_FAULT",
                reviewer="Reviewer",
                notes="",
                expected_revision=0,
            )
        self.assertEqual(caught.exception.status, 400)

    def test_ground_truth_label_rejects_non_string_fields(self) -> None:
        batch = self.service.create_import("Typed label", "folder")
        self.upload(batch["importId"], "capture.pcap", PCAP_BYTES)
        self.service.complete_import(batch["importId"])
        digest = self.service.label_batch(batch["importId"])["files"][0]["sha256"]

        with self.assertRaises(DatasetServiceError) as caught:
            self.service.save_label(
                batch["importId"],
                digest=digest,
                classification="normal",
                fault_family=None,
                reviewer={"name": "not text"},  # type: ignore[arg-type]
                notes="",
                expected_revision=0,
            )
        self.assertEqual(caught.exception.status, 400)

    def test_zip_import_ignores_metadata_and_rejects_traversal_without_extracting_it(self) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("station-a/good.pcapng", PCAPNG_BYTES)
            output.writestr("notes.txt", "metadata")
            output.writestr("../escape.pcap", PCAP_BYTES + b"different")

        batch = self.service.create_import("ZIP import", "zip")
        state = self.upload(batch["importId"], "captures.zip", archive.getvalue())
        complete = self.service.complete_import(batch["importId"])

        self.assertEqual(state["fileCount"], 1)
        self.assertEqual(state["rejectedCount"], 1)
        self.assertTrue(any("unsafe ZIP path" in item for item in state["warnings"]))
        self.assertTrue(any("non-PCAP" in item for item in state["warnings"]))
        self.assertEqual(complete["status"], "ready")
        self.assertFalse((self.root / "escape.pcap").exists())

    def test_invalid_capture_cannot_complete_a_batch(self) -> None:
        batch = self.service.create_import("Broken", "folder")
        state = self.upload(batch["importId"], "broken.pcap", b"not a capture")
        self.assertEqual(state["fileCount"], 0)
        self.assertEqual(state["rejectedCount"], 1)
        with self.assertRaises(DatasetServiceError) as caught:
            self.service.complete_import(batch["importId"])
        self.assertEqual(caught.exception.status, 422)

    def test_folder_paths_cannot_escape_the_batch(self) -> None:
        batch = self.service.create_import("Unsafe", "folder")
        with self.assertRaises(DatasetServiceError) as caught:
            self.service.begin_upload(
                batch["importId"],
                "capture.pcap",
                "../capture.pcap",
                content_length=len(PCAP_BYTES),
            )
        self.assertEqual(caught.exception.status, 400)


def _zip_bytes(entries: list[tuple[zipfile.ZipInfo | str, bytes]], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=compression) as output:
        for name, payload in entries:
            output.writestr(name, payload)
    return archive.getvalue()


def _capture(tag: bytes, padding: int = 0) -> bytes:
    return PCAP_BYTES + tag + b"\x00" * padding


class DatasetHardeningTests(unittest.TestCase):
    """Review fixes for 1.7.0: archive limits, recovery, discard, summary, bad labels."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = self.root / "datasets"
        self.service = TrainingDatasetService(self.storage)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def upload(self, import_id: str, name: str, payload: bytes, relative: str | None = None) -> dict:
        upload = self.service.begin_upload(import_id, name, relative or name, content_length=len(payload))
        self.service.write_upload(upload, payload)
        return self.service.finish_upload(upload)

    def zip_import(self, payload: bytes) -> dict:
        batch = self.service.create_import("ZIP", "zip")
        return self.upload(batch["importId"], "captures.zip", payload)

    def stored_blobs(self) -> list[Path]:
        return list((self.storage / "files").glob("*/*.pcap*"))

    def test_encrypted_entry_is_rejected_before_it_is_read(self) -> None:
        raw = bytearray(_zip_bytes([("secret.pcap", _capture(b"e"))], zipfile.ZIP_STORED))
        for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            at = raw.find(signature)
            raw[at + flag_offset] |= 0x1
        state = self.zip_import(bytes(raw))
        self.assertEqual(state["fileCount"], 0)
        self.assertEqual(state["rejectedCount"], 1)
        self.assertTrue(any("encrypted" in item for item in state["warnings"]))

    def test_symlink_entry_is_rejected(self) -> None:
        link = zipfile.ZipInfo("link.pcap")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        state = self.zip_import(_zip_bytes([(link, b"/etc/passwd"), ("good.pcap", _capture(b"g"))]))
        self.assertEqual(state["fileCount"], 1)
        self.assertEqual(state["rejectedCount"], 1)

    def test_bzip2_and_lzma_entries_are_rejected(self) -> None:
        for method in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(method=method):
                state = self.zip_import(_zip_bytes([("capture.pcap", _capture(b"b", 4096))], method))
                self.assertEqual(state["fileCount"], 0)
                self.assertTrue(any("compression method" in item for item in state["warnings"]))

    def test_deflate_ratio_bomb_is_rejected_but_small_compressible_capture_is_kept(self) -> None:
        bomb = _capture(b"bomb", 2 * 1024 * 1024)
        small = _capture(b"small", 32 * 1024)
        state = self.zip_import(_zip_bytes([("bomb.pcap", bomb), ("small.pcap", small)]))
        self.assertEqual(state["fileCount"], 1)
        self.assertEqual(state["rejectedCount"], 1)
        self.assertTrue(any("compression ratio" in item for item in state["warnings"]))

    def test_archive_with_too_many_entries_is_refused_from_its_end_record(self) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            for index in range(dataset_service.MAX_ARCHIVE_ENTRIES + 1):
                output.writestr(f"n/{index}.txt", b"")
        payload = archive.getvalue()
        with mock.patch.object(dataset_service.zipfile, "ZipFile", side_effect=AssertionError("parsed")):
            state = self.zip_import(payload)
        self.assertEqual(state["fileCount"], 0)
        self.assertTrue(any("10,000 entries" in item for item in state["warnings"]))

    def test_archive_declaring_more_than_the_import_limit_is_refused(self) -> None:
        payload = _zip_bytes([("a.pcap", _capture(b"a", 600)), ("b.pcap", _capture(b"b", 600))])
        with mock.patch.object(dataset_service, "MAX_IMPORT_BYTES", 1_000):
            state = self.zip_import(payload)
        self.assertEqual(state["fileCount"], 0)
        self.assertTrue(any("20 GiB" in item for item in state["warnings"]))
        self.assertEqual(self.stored_blobs(), [])

    def test_drive_qualified_entry_is_rejected(self) -> None:
        state = self.zip_import(_zip_bytes([("C:/evil.pcap", _capture(b"c")), ("ok.pcap", _capture(b"o"))]))
        self.assertEqual(state["fileCount"], 1)
        self.assertEqual(state["rejectedCount"], 1)

    def test_corrupt_entry_is_skipped_and_good_entries_are_kept_and_recorded(self) -> None:
        bad = _capture(b"BADBADBAD")
        raw = bytearray(_zip_bytes([("bad.pcap", bad), ("good.pcap", _capture(b"good"))], zipfile.ZIP_STORED))
        at = raw.find(b"BADBADBAD")
        raw[at] ^= 0xFF  # data no longer matches the stored CRC-32
        batch = self.service.create_import("Damaged", "zip")
        state = self.upload(batch["importId"], "captures.zip", bytes(raw))
        self.assertEqual(state["fileCount"], 1)
        self.assertEqual(state["rejectedCount"], 1)
        manifest = json.loads((self.storage / "imports" / batch["importId"] / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["fileCount"], 1)
        self.assertEqual(len(self.stored_blobs()), 1)
        self.assertEqual(list((self.storage / "imports" / batch["importId"]).glob(".*.tmp")), [])

    def test_interrupted_import_is_failed_on_restart_and_its_leftovers_are_removed(self) -> None:
        batch = self.service.create_import("Interrupted", "folder")
        self.upload(batch["importId"], "one.pcap", _capture(b"1"))  # not flushed yet
        import_dir = self.storage / "imports" / batch["importId"]
        (import_dir / ".upload-dead.tmp").write_bytes(b"partial")
        self.assertEqual(len(self.stored_blobs()), 1)

        restarted = TrainingDatasetService(self.storage)

        summary = restarted.summary()
        self.assertEqual(summary["imports"][0]["status"], "failed")
        self.assertEqual(summary["imports"][0]["failureReason"], dataset_service.INTERRUPTED_REASON)
        self.assertFalse((import_dir / ".upload-dead.tmp").exists())
        self.assertEqual(self.stored_blobs(), [])  # the unflushed capture was never referenced

    def test_empty_import_is_persisted_as_failed_and_can_be_discarded(self) -> None:
        batch = self.service.create_import("Empty", "folder")
        with self.assertRaises(DatasetServiceError) as caught:
            self.service.complete_import(batch["importId"])
        self.assertEqual(caught.exception.status, 422)
        listed = self.service.summary()["imports"][0]
        self.assertEqual(listed["status"], "failed")
        self.assertEqual(listed["failureReason"], dataset_service.EMPTY_IMPORT_REASON)

        result = self.service.discard_import(batch["importId"])
        self.assertTrue(result["discarded"])
        self.assertEqual(self.service.summary()["imports"], [])

    def test_discard_removes_only_content_no_other_batch_references(self) -> None:
        shared = _capture(b"shared")
        kept = self.service.create_import("Kept", "folder")
        self.upload(kept["importId"], "shared.pcap", shared)
        self.service.complete_import(kept["importId"])

        dropped = self.service.create_import("Dropped", "folder")
        self.upload(dropped["importId"], "shared.pcap", shared)
        self.upload(dropped["importId"], "own.pcap", _capture(b"own"))
        self.assertEqual(len(self.stored_blobs()), 2)

        result = self.service.discard_import(dropped["importId"])
        self.assertEqual(result["removedContentFiles"], 1)
        self.assertEqual(len(self.stored_blobs()), 1)
        self.assertEqual(self.service.label_batch(kept["importId"])["fileCount"], 1)

    def test_ready_batch_cannot_be_discarded(self) -> None:
        batch = self.service.create_import("Ready", "folder")
        self.upload(batch["importId"], "one.pcap", _capture(b"r"))
        self.service.complete_import(batch["importId"])
        with self.assertRaises(DatasetServiceError) as caught:
            self.service.discard_import(batch["importId"])
        self.assertEqual(caught.exception.status, 409)

    @unittest.skipUnless(sys.platform == "win32", "open files block a directory rename only on Windows")
    def test_discard_is_refused_while_a_file_is_still_uploading(self) -> None:
        batch = self.service.create_import("Busy", "folder")
        payload = _capture(b"busy")
        upload = self.service.begin_upload(batch["importId"], "busy.pcap", "busy.pcap", content_length=len(payload))
        try:
            with self.assertRaises(DatasetServiceError) as caught:
                self.service.discard_import(batch["importId"])
            self.assertEqual(caught.exception.status, 409)
            self.service.write_upload(upload, payload)
            self.assertEqual(self.service.finish_upload(upload)["fileCount"], 1)
        finally:
            self.service.abort_upload(upload)

    def test_summary_lists_every_import_and_counts_unreadable_ones(self) -> None:
        for index in range(30):
            batch = self.service.create_import(f"Batch {index}", "folder")
            self.upload(batch["importId"], "c.pcap", _capture(str(index).encode()))
            self.service.complete_import(batch["importId"])
        broken = self.storage / "imports" / ("f" * 32)
        broken.mkdir()
        (broken / "manifest.json").write_text("{not json", encoding="utf-8")

        summary = self.service.summary()
        self.assertEqual(len(summary["imports"]), 30)
        self.assertEqual(summary["totals"]["imports"], 30)
        self.assertEqual(summary["unreadableImports"], 1)

    def test_unreadable_label_needs_review_and_is_moved_aside_when_relabelled(self) -> None:
        batch = self.service.create_import("Labels", "folder")
        self.upload(batch["importId"], "one.pcap", _capture(b"l"))
        self.service.complete_import(batch["importId"])
        digest = self.service.label_batch(batch["importId"])["files"][0]["sha256"]
        label_file = self.storage / "labels" / digest[:2] / f"{digest}.json"
        label_file.parent.mkdir(parents=True, exist_ok=True)
        label_file.write_text("{broken", encoding="utf-8")
        fresh = TrainingDatasetService(self.storage)

        listed = fresh.label_batch(batch["importId"])
        self.assertEqual(listed["invalidLabelCount"], 1)
        self.assertTrue(listed["files"][0]["labelInvalid"])
        self.assertIsNone(listed["files"][0]["label"])
        with self.assertRaises(DatasetServiceError):
            fresh.training_snapshot([batch["importId"]])

        with self.assertRaises(DatasetServiceError) as stale:
            fresh.save_label(batch["importId"], digest=digest, classification="normal", fault_family=None,
                             reviewer="Reviewer", notes="", expected_revision=3)
        self.assertEqual(stale.exception.status, 409)
        self.assertTrue(label_file.exists())  # a refused save leaves the evidence where it was

        saved = fresh.save_label(batch["importId"], digest=digest, classification="normal", fault_family=None,
                                 reviewer="Reviewer", notes="", expected_revision=0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(len(list(label_file.parent.glob(f"{digest}.invalid-*.json"))), 1)
        self.assertEqual(fresh.label_batch(batch["importId"])["invalidLabelCount"], 0)

    def test_open_import_progress_is_visible_before_the_manifest_is_flushed(self) -> None:
        batch = self.service.create_import("Progress", "folder")
        for index in range(3):
            self.upload(batch["importId"], f"{index}.pcap", _capture(bytes([65 + index])))
        listed = self.service.summary()["imports"][0]
        self.assertEqual(listed["status"], "uploading")
        self.assertEqual(listed["fileCount"], 3)
        self.assertEqual(self.service.complete_import(batch["importId"])["fileCount"], 3)

    @unittest.skipUnless(sys.platform == "win32", "directory junctions are Windows-only")
    def test_storage_behind_a_junction_is_refused(self) -> None:
        import _winapi

        real = self.root / "elsewhere"
        real.mkdir()
        junction = self.root / "linked"
        _winapi.CreateJunction(str(real), str(junction))
        with self.assertRaises(DatasetServiceError):
            TrainingDatasetService(junction)


class DatasetSecondReviewTests(unittest.TestCase):
    """Second review of 1.7.0: cleanup with unreadable manifests, ZIP64 records, failed writes, threads."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = self.root / "datasets"
        self.service = TrainingDatasetService(self.storage)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def upload(self, service: TrainingDatasetService, import_id: str, name: str, payload: bytes) -> dict:
        upload = service.begin_upload(import_id, name, name, content_length=len(payload))
        service.write_upload(upload, payload)
        return service.finish_upload(upload)

    def stored_blobs(self) -> list[Path]:
        return list((self.storage / "files").glob("*/*.pcap*"))

    def test_an_unreadable_manifest_never_costs_its_captures(self) -> None:
        batch = self.service.create_import("Reviewed", "folder")
        self.upload(self.service, batch["importId"], "one.pcap", _capture(b"kept"))
        self.service.complete_import(batch["importId"])
        manifest = self.storage / "imports" / batch["importId"] / "manifest.json"
        good = manifest.read_text(encoding="utf-8")
        manifest.write_text(good[:20], encoding="utf-8")  # damaged, or locked by a scanner

        restarted = TrainingDatasetService(self.storage)
        self.assertEqual(len(self.stored_blobs()), 1)
        self.assertEqual(restarted.summary()["unreadableImports"], 1)

        empty = restarted.create_import("Empty", "folder")
        with self.assertRaises(DatasetServiceError):
            restarted.complete_import(empty["importId"])
        restarted.discard_import(empty["importId"])
        self.assertEqual(len(self.stored_blobs()), 1)  # discard cleanup skipped too

        manifest.write_text(good, encoding="utf-8")
        self.assertEqual(TrainingDatasetService(self.storage).label_batch(batch["importId"])["fileCount"], 1)

    def test_a_zip64_record_cannot_hide_a_huge_central_directory(self) -> None:
        raw = _zip_bytes([("a.pcap", _capture(b"z"))], zipfile.ZIP_STORED)
        end = raw.rfind(b"PK\x05\x06")
        zip64_record = struct.pack(
            "<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 1_000_000, 1_000_000, 64 * 1024 * 1024, 0,
        )
        locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, end, 1)
        crafted = raw[:end] + zip64_record + locator + raw[end:]
        try:
            entries, cd_size = dataset_service._central_directory_bounds(self._write(crafted))
            # the bounds are the ZIP64 values zipfile would parse, not the plain record's
            self.assertEqual((entries, cd_size), (1_000_000, 64 * 1024 * 1024))
        except zipfile.BadZipFile:
            pass  # newer patch releases refuse the inconsistent ZIP64 record outright

        batch = self.service.create_import("ZIP64", "zip")
        with mock.patch.object(dataset_service.zipfile, "ZipFile", side_effect=AssertionError("parsed")):
            state = self.upload(self.service, batch["importId"], "crafted.zip", crafted)
        self.assertEqual(state["fileCount"], 0)
        self.assertTrue(any(
            "10,000 entries" in item or "directory is too large" in item or "ZIP archive is invalid" in item
            for item in state["warnings"]
        ))

    def _write(self, payload: bytes) -> Path:
        path = self.root / "probe.zip"
        path.write_bytes(payload)
        return path

    def test_a_failed_completion_write_leaves_the_batch_uploading_and_can_be_retried(self) -> None:
        batch = self.service.create_import("Retry", "folder")
        self.upload(self.service, batch["importId"], "one.pcap", _capture(b"retry"))
        real_write = dataset_service._write_json_atomic
        calls = {"n": 0}

        def failing_once(path: Path, payload: dict) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(5, "locked by a scanner")
            real_write(path, payload)

        with mock.patch.object(dataset_service, "_write_json_atomic", side_effect=failing_once):
            with self.assertRaises(PermissionError):
                self.service.complete_import(batch["importId"])
            self.assertEqual(self.service.summary()["imports"][0]["status"], "uploading")
            completed = self.service.complete_import(batch["importId"])
        self.assertEqual(completed["status"], "ready")
        manifest = json.loads((self.storage / "imports" / batch["importId"] / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["status"], "ready")

    def test_a_failed_manifest_flush_does_not_fail_the_upload(self) -> None:
        batch = self.service.create_import("Flush", "zip")
        with mock.patch.object(self.service, "_write_state", side_effect=PermissionError(5, "locked")):
            state = self.upload(self.service, batch["importId"], "captures.zip", _zip_bytes([("a.pcap", _capture(b"f"))]))
        self.assertEqual(state["fileCount"], 1)
        self.assertEqual(self.service.complete_import(batch["importId"])["fileCount"], 1)

    def test_parallel_uploads_summaries_and_discards_stay_consistent(self) -> None:
        batches = [self.service.create_import(f"Parallel {index}", "folder")["importId"] for index in range(3)]
        errors: list[BaseException] = []
        stop = threading.Event()

        def uploader(import_id: str, tag: int) -> None:
            try:
                for index in range(40):
                    self.upload(self.service, import_id, f"{index}.pcap", _capture(f"{tag}-{index}".encode()))
                # one capture shared by every batch
                self.upload(self.service, import_id, "shared.pcap", _capture(b"shared"))
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(exc)

        def poller() -> None:
            try:
                while not stop.is_set():
                    self.service.summary()
                    empty = self.service.create_import("Throwaway", "folder")
                    with self.assertRaises(DatasetServiceError):
                        self.service.complete_import(empty["importId"])
                    self.service.discard_import(empty["importId"])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=uploader, args=(import_id, tag)) for tag, import_id in enumerate(batches)]
        watcher = threading.Thread(target=poller)
        watcher.start()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        stop.set()
        watcher.join(60)
        self.assertEqual(errors, [])
        for import_id in batches:
            self.assertEqual(self.service.complete_import(import_id)["fileCount"], 41)
        self.assertEqual(len(self.stored_blobs()), 3 * 40 + 1)
        restarted = TrainingDatasetService(self.storage)
        self.assertEqual(len(self.stored_blobs()), 3 * 40 + 1)
        self.assertEqual(restarted.summary()["totals"]["files"], 3 * 41)


if __name__ == "__main__":
    unittest.main()
