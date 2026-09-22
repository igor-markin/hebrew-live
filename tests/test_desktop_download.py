import hashlib
import io
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


class Response(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 200):
        super().__init__(payload)
        self.status = status

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


class DesktopDownloadTests(unittest.TestCase):
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
                return Response(b"def", 206)

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
