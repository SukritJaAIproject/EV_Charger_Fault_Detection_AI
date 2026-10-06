from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import worker  # noqa: E402


class WorkerProgressTests(unittest.TestCase):
    """The PCAP worker writes progress.json while the sidecar reads it for status polls."""

    def test_a_replace_refused_while_the_file_is_read_is_retried(self) -> None:
        real_replace = worker.os.replace
        calls = {"n": 0}

        def busy_twice(source, target):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(5, "Access is denied")
            real_replace(source, target)

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "progress.json"
            with mock.patch.object(worker.os, "replace", side_effect=busy_twice), mock.patch.object(worker.time, "sleep"):
                worker.update_progress(target, "extracting", 12, "Decoding PCAP with TShark")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["stage"], "extracting")
            self.assertEqual(calls["n"], 3)

    def test_progress_never_fails_the_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "progress.json"
            with mock.patch.object(worker.os, "replace", side_effect=PermissionError(5, "Access is denied")), \
                    mock.patch.object(worker.time, "sleep"):
                worker.update_progress(target, "extracting", 12, "Decoding PCAP with TShark")
            self.assertFalse(target.exists())

    def test_the_result_write_still_reports_a_lasting_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(worker.os, "replace", side_effect=PermissionError(5, "Access is denied")), \
                    mock.patch.object(worker.time, "sleep"):
                with self.assertRaises(PermissionError):
                    worker.write_json_atomic(Path(temp) / "result.json", {"ok": True})


if __name__ == "__main__":
    unittest.main()
