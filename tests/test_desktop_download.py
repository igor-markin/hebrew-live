import hashlib
import io
import errno
import multiprocessing
import os
from pathlib import Path
import socket
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from hebrew_live.desktop_download import (
    DesktopDownloadError,
    ModelFile,
    download_one,
    prepare_models,
)
from hebrew_live.model_store import preparation_lock


class Response(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 200, headers: dict[str, str] | None = None):
        super().__init__(payload)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class StalledResponse(Response):
    def __init__(self, first: bytes):
        super().__init__(first)
        self.stalled = False

    def read(self, size=-1):
        if not self.stalled:
            self.stalled = True
            return super().read(size)
        raise socket.timeout("no progress")


def model_file(payload=b"abcdef"):
    return ModelFile("vad", "VAD", Path("silero.onnx"), len(payload),
                     hashlib.sha256(payload).hexdigest(), "https://example.invalid/model")


def inventory(payload=b"abcdef"):
    return {
        "schema_version": 1,
        "total_bytes": len(payload),
        "components": [{
            "key": "vad", "label": "VAD", "url": "https://example.invalid/model",
            "revision": "test", "terms_url": "https://example.invalid/terms",
            "files": [{"path": "silero.onnx", "bytes": len(payload),
                       "sha256": hashlib.sha256(payload).hexdigest()}],
        }],
    }


def _crash_during_download(folder: str):
    with preparation_lock(Path(folder)):
        download_one(Path(folder), model_file(), cancelled=lambda: False,
                     progress=lambda _size: os._exit(17),
                     opener=lambda *_args: Response(b"abcdef"))


class DesktopDownloadTests(unittest.TestCase):
    def test_forced_process_exit_keeps_part_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = multiprocessing.get_context("spawn").Process(
                target=_crash_during_download, args=(tmp,))
            process.start()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
            self.assertEqual(process.exitcode, 17)
            models = Path(tmp)
            self.assertTrue((models / "silero.onnx.part").is_file())
            self.assertFalse((models / "silero.onnx").exists())
            with preparation_lock(models):
                self.assertEqual(download_one(models, model_file(), cancelled=lambda: False,
                                              progress=lambda _size: None,
                                              opener=lambda *_args: self.fail("unexpected network request")), 0)

    def test_desktop_preparation_downloads_translation_and_copies_bundled_vad(self):
        selected = {"schema_version": 1, "total_bytes": 5, "components": [
            {"key": "fast_asr", "label": "ASR", "folder": "fast-asr", "files": [
                {"path": "model.onnx", "bytes": 1, "sha256": hashlib.sha256(b"a").hexdigest()}]},
            {"key": "translation", "label": "MT", "folder": "milmmt-4b-4bit",
             "url": "https://example.invalid/model", "files": [
                {"path": "model.safetensors", "bytes": 1, "sha256": hashlib.sha256(b"b").hexdigest()}]},
            {"key": "vad", "label": "VAD", "files": [
                {"path": "silero.onnx", "bytes": 3, "sha256": hashlib.sha256(b"vad").hexdigest()}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hebrew_live.desktop_download.ensure_free_space", return_value=None
        ):
            root = Path(tmp)
            bundle = root / "bundle"
            (bundle / "fast-asr").mkdir(parents=True)
            (bundle / "fast-asr/model.onnx").write_bytes(b"a")
            (bundle / "silero.onnx").write_bytes(b"vad")
            requests, events = [], []

            def opener(request, _timeout):
                requests.append(request)
                return Response(b"b")

            models = root / "models"
            prepare_models(models, cancelled=lambda: False,
                           emit=lambda event, data: events.append((event, data)),
                           inventory=selected, bundled_root=bundle, opener=opener)
            self.assertEqual(len(requests), 1)
            self.assertEqual((models / "silero.onnx").read_bytes(), b"vad")
            self.assertFalse((models / "fast-asr").exists())
            self.assertEqual((models / "milmmt-4b-4bit/model.safetensors").read_bytes(), b"b")
            progress = [data for event, data in events if event == "download_file_complete"][-1]
            self.assertEqual(progress["transferred_bytes"], 1)
            self.assertEqual(progress["verified_bytes"], 1)
            self.assertEqual(progress["staged_bytes"], 0)

    def test_partial_download_survives_restart_and_uses_range(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            requests = []

            def first(request, _timeout):
                requests.append(request)
                return Response(b"abc")

            with self.assertRaisesRegex(DesktopDownloadError, "before all bytes"):
                download_one(models, item, cancelled=lambda: False, progress=lambda _size: None, opener=first)
            self.assertEqual((models / "silero.onnx.part").read_bytes(), b"abc")

            def second(request, _timeout):
                requests.append(request)
                return Response(b"def", 206, {"Content-Range": "bytes 3-5/6"})

            download_one(models, item, cancelled=lambda: False, progress=lambda _size: None, opener=second)
            self.assertEqual(requests[1].get_header("Range"), "bytes=3-")
            self.assertEqual((models / "silero.onnx").read_bytes(), b"abcdef")
            self.assertFalse((models / "silero.onnx.part").exists())

    def test_server_without_range_replaces_only_the_incomplete_file(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "silero.onnx.part").write_bytes(b"abc")
            request_seen = []

            def opener(request, _timeout):
                request_seen.append(request)
                return Response(b"abcdef", 200)

            download_one(models, item, cancelled=lambda: False, progress=lambda _size: None, opener=opener)
            self.assertEqual(request_seen[0].get_header("Range"), "bytes=3-")
            self.assertEqual((models / "silero.onnx").read_bytes(), b"abcdef")

    def test_complete_part_is_verified_without_a_network_request(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "silero.onnx.part").write_bytes(b"abcdef")
            transferred = download_one(models, item, cancelled=lambda: False,
                                       progress=lambda _size: None,
                                       opener=lambda *_args: self.fail("network request was unnecessary"))
            self.assertEqual(transferred, 0)
            self.assertEqual((models / "silero.onnx").read_bytes(), b"abcdef")

    def test_optional_accurate_download_preserves_invalid_cli_file_until_verified(self):
        payload = b"correct"
        item = ModelFile("asr", "Whisper", Path("asr/weights.safetensors"), len(payload),
                         hashlib.sha256(payload).hexdigest(), "https://example.invalid/weights")
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            target = models / item.relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b"previous invalid bytes")
            download_one(models, item, cancelled=lambda: False, progress=lambda _size: None,
                         opener=lambda *_args: Response(payload))
            self.assertEqual(target.read_bytes(), payload)
            preserved = list(target.parent.glob("weights.safetensors.previous-invalid-*"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), b"previous invalid bytes")

    def test_bad_content_range_never_appends_and_restarts_from_zero(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "silero.onnx.part").write_bytes(b"abc")
            requests = []

            def opener(request, _timeout):
                requests.append(request)
                if len(requests) == 1:
                    return Response(b"def", 206, {"Content-Range": "bytes 2-5/6"})
                return Response(b"abcdef")

            download_one(models, item, cancelled=lambda: False, progress=lambda _size: None, opener=opener)
            self.assertEqual([request.get_header("Range") for request in requests], ["bytes=3-", None])
            self.assertEqual((models / "silero.onnx").read_bytes(), b"abcdef")

    def test_416_on_incomplete_part_restarts_full_request(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "silero.onnx.part").write_bytes(b"abc")
            requests = []

            def opener(request, _timeout):
                requests.append(request)
                if len(requests) == 1:
                    raise urllib.error.HTTPError(request.full_url, 416, "range", {}, None)
                return Response(b"abcdef")

            download_one(models, item, cancelled=lambda: False, progress=lambda _size: None, opener=opener)
            self.assertEqual([request.get_header("Range") for request in requests], ["bytes=3-", None])
            self.assertEqual((models / "silero.onnx").read_bytes(), b"abcdef")

    def test_disk_full_keeps_partial_for_next_run(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            call = [0]

            def progress(_size):
                call[0] += 1
                raise OSError(errno.ENOSPC, "disk full")

            with self.assertRaises(DesktopDownloadError) as caught:
                download_one(models, item, cancelled=lambda: False, progress=progress,
                             opener=lambda *_args: Response(b"abcdef"))
            self.assertEqual(caught.exception.code, "disk_full")
            self.assertFalse((models / "silero.onnx").exists())
            self.assertTrue((models / "silero.onnx.part").exists())

    def test_corrupt_file_is_quarantined_and_not_retried_as_network(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            with self.assertRaisesRegex(DesktopDownloadError, "checksum") as caught:
                download_one(models, item, cancelled=lambda: False, progress=lambda _size: None,
                             opener=lambda _request, _timeout: Response(b"abcdeg"))
            self.assertEqual(caught.exception.code, "corrupt_download")
            self.assertTrue((models / "silero.onnx.part.corrupt").is_file())

    def test_network_retry_budget_is_exactly_three_delays_then_pauses(self):
        now = [0.0]
        sleeps = []
        attempts = []

        def opener(_request, _timeout):
            attempts.append(1)
            raise urllib.error.URLError("offline")

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        with tempfile.TemporaryDirectory() as tmp, patch(
            "hebrew_live.desktop_download.ensure_free_space", return_value=None
        ):
            with self.assertRaises(DesktopDownloadError) as caught:
                prepare_models(Path(tmp), cancelled=lambda: False, emit=lambda *_args: None,
                               inventory=inventory(), opener=opener, sleep=sleep, clock=lambda: now[0])
        self.assertEqual(caught.exception.code, "network_exhausted")
        self.assertEqual(len(attempts), 4)
        self.assertAlmostEqual(sum(sleeps), 22.0)

    def test_read_timeout_is_retryable_and_preserves_partial_data(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            with self.assertRaises(DesktopDownloadError) as caught:
                download_one(models, item, cancelled=lambda: False, progress=lambda _size: None,
                             opener=lambda _request, _timeout: StalledResponse(b"abc"))
            self.assertEqual((models / "silero.onnx.part").read_bytes(), b"abc")
            self.assertEqual(caught.exception.code, "network")
            self.assertTrue(caught.exception.retryable)

    def test_full_connection_drop_is_retryable_network_failure(self):
        item = model_file()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(DesktopDownloadError) as caught:
            download_one(Path(tmp), item, cancelled=lambda: False, progress=lambda _size: None,
                         opener=lambda _request, _timeout: (_ for _ in ()).throw(ConnectionResetError()))
        self.assertEqual(caught.exception.code, "network")
        self.assertTrue(caught.exception.retryable)

    def test_access_denial_is_distinct_and_not_retried(self):
        item = model_file()
        attempts = []

        def opener(request, _timeout):
            attempts.append(1)
            raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, None)

        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(DesktopDownloadError) as caught:
            download_one(Path(tmp), item, cancelled=lambda: False, progress=lambda _size: None, opener=opener)
        self.assertEqual(caught.exception.code, "access_denied")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
