"""Job directories are found by name, whatever path Windows reports for them.

Run with:  python -m unittest discover -s desktop/runtime/tests

An app started from an MSIX-packaged app (the Claude desktop app, for one) sees
%APPDATA% through ...\\Packages\\<pkg>\\LocalCache: a job folder it creates
resolves there, while the jobs root resolves to the real Roaming path. The job
service used to compare the two and answered 404 for every job. These tests
simulate that by making resolve() map job folders to a different root.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import job_service  # noqa: E402
from job_service import JobServiceError, PcapJobService  # noqa: E402

PCAP = b"\xd4\xc3\xb2\xa1" + b"\x00" * 20  # a valid 24-byte classic pcap header


def make_service(root: Path) -> PcapJobService:
    service = PcapJobService(
        jobs_root=root,
        model_dir=root.parent / "no-models",
        tshark=root.parent / "no-tshark.exe",
        runtime_command=[sys.executable],
    )
    # models and tshark are absent here; the tests exercise the job files only
    service._dependency_errors = []
    service._run_job = lambda job_id: None  # never spawn a worker
    return service


def make_link(link: Path, target: Path) -> bool:
    """A directory junction on Windows, a symlink elsewhere. False if not possible."""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, AttributeError):
        return False


class VirtualizedPaths:
    """resolve() maps anything below `root` to the same place below `elsewhere`."""

    def __init__(self, root: Path, elsewhere: Path):
        self.root = root.resolve()
        self.elsewhere = elsewhere
        self.real = Path.resolve

    def __call__(self, path: Path, strict: bool = False) -> Path:
        resolved = self.real(path, strict=strict)
        try:
            relative = resolved.relative_to(self.root)
        except ValueError:
            return resolved
        return self.elsewhere.joinpath(relative) if relative.parts else resolved

    def active(self):
        outer = self

        def fake(path, strict=False):
            return outer(path, strict)

        return mock.patch.object(Path, "resolve", fake)


class JobPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="imps-jobs-test-"))
        self.root = self.tmp / "pcap-jobs"
        self.services: list[PcapJobService] = []

    def tearDown(self) -> None:
        for service in self.services:
            service.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def service(self) -> PcapJobService:
        service = make_service(self.root)
        self.services.append(service)
        return service

    def upload(self, service: PcapJobService) -> dict:
        upload = service.begin_upload("capture.pcap", content_length=len(PCAP))
        service.write_upload(upload, PCAP)
        return service.finish_upload(upload)

    def test_upload_and_lookup_when_job_folders_resolve_elsewhere(self) -> None:
        service = self.service()
        virtual = VirtualizedPaths(self.root, self.tmp / "LocalCache" / "pcap-jobs")
        with virtual.active():
            job = self.upload(service)
            self.assertEqual(job["status"], "queued")
            again = service.get_job(job["jobId"])
            self.assertEqual(again["jobId"], job["jobId"])
            self.assertTrue((self.root / job["jobId"] / "state.json").is_file())

    def test_ids_that_are_not_32_hex_characters_are_not_found(self) -> None:
        service = self.service()
        job = self.upload(service)
        for bad in ("..", "../pcap-jobs", job["jobId"].upper(), job["jobId"][:-1], job["jobId"] + "0",
                    "g" * 32, "", job["jobId"] + "/", "..\\" + job["jobId"]):
            with self.subTest(job_id=bad):
                with self.assertRaises(JobServiceError) as caught:
                    service.get_job(bad)
                self.assertEqual(caught.exception.status, 404)

    def test_a_link_planted_under_a_job_id_is_refused(self) -> None:
        service = self.service()
        outside = self.tmp / "outside"
        outside.mkdir()
        job_service._write_json_atomic(outside / "state.json", {"jobId": "x", "status": "complete"})
        link = self.root / ("a" * 32)
        if not make_link(link, outside):
            self.skipTest("cannot create a junction or symlink here")
        with self.assertRaises(JobServiceError) as caught:
            service.get_job("a" * 32)
        self.assertEqual(caught.exception.status, 404)

    def test_cleanup_removes_expired_jobs_even_when_they_resolve_elsewhere(self) -> None:
        service = self.service()
        virtual = VirtualizedPaths(self.root, self.tmp / "LocalCache" / "pcap-jobs")
        old = self.upload(service)["jobId"]
        fresh = self.upload(service)["jobId"]
        stale = time.time() - 40 * 24 * 60 * 60
        os.utime(self.root / old / "state.json", (stale, stale))
        with virtual.active():
            service._cleanup_expired_jobs()
        self.assertFalse((self.root / old).exists())
        self.assertTrue((self.root / fresh).exists())

    def test_cleanup_never_follows_a_link_out_of_the_jobs_root(self) -> None:
        service = self.service()
        stale = time.time() - 40 * 24 * 60 * 60
        expired = self.upload(service)["jobId"]
        os.utime(self.root / expired / "state.json", (stale, stale))
        outside = self.tmp / "outside"
        outside.mkdir()
        job_service._write_json_atomic(outside / "state.json", {"jobId": "x"})
        os.utime(outside / "state.json", (stale, stale))
        link = self.root / ("b" * 32)
        if not make_link(link, outside):
            self.skipTest("cannot create a junction or symlink here")
        # watch the decision itself: shutil.rmtree refuses a top-level link on its
        # own, which would hide a missing check in the job service
        with mock.patch.object(job_service.shutil, "rmtree", wraps=shutil.rmtree) as rmtree:
            service._cleanup_expired_jobs()
        self.assertEqual([Path(call.args[0]) for call in rmtree.call_args_list], [self.root / expired])
        self.assertFalse((self.root / expired).exists())
        self.assertTrue((outside / "state.json").is_file())
        self.assertTrue(os.path.lexists(link))

    def test_recovery_only_touches_real_job_folders(self) -> None:
        service = self.service()
        interrupted = self.upload(service)["jobId"]  # left "queued", as after a crash
        queued = {"jobId": "x", "status": "queued"}
        outside_named = self.tmp / "outside-named"
        outside_other = self.tmp / "outside-other"
        for target in (outside_named, outside_other):
            target.mkdir()
            job_service._write_json_atomic(target / "state.json", dict(queued))
        if not (make_link(self.root / ("c" * 32), outside_named) and make_link(self.root / "not-a-job", outside_other)):
            self.skipTest("cannot create a junction or symlink here")
        service._recover_interrupted_jobs()
        self.assertEqual(job_service._load_json(self.root / interrupted / "state.json")["status"], "failed")
        for target in (outside_named, outside_other):
            with self.subTest(target=target.name):
                self.assertEqual(job_service._load_json(target / "state.json"), queued)


if __name__ == "__main__":
    unittest.main()
