import io
import json
import unittest
import urllib.error

from slayerbot.telegram_api import TelegramAPI, TelegramError

TOKEN = "123456:SECRET-TOKEN"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingOpener:
    """Stands in for urllib.request.urlopen: replays scripted responses and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, bytes):
            return FakeResponse(response)
        return FakeResponse(json.dumps(response).encode("utf-8"))


class ApiTests(unittest.TestCase):
    def test_get_updates_request_and_result(self):
        opener = RecordingOpener({"ok": True, "result": [{"update_id": 7}]})
        api = TelegramAPI(TOKEN, opener=opener)
        self.assertEqual(api.get_updates(offset=8, poll_timeout=20), [{"update_id": 7}])
        request, timeout = opener.requests[0]
        self.assertTrue(request.full_url.endswith(f"/bot{TOKEN}/getUpdates"))
        self.assertEqual(json.loads(request.data), {"timeout": 20, "allowed_updates": ["message"], "offset": 8})
        self.assertEqual(timeout, 30)  # HTTP timeout must outlast the long poll

    def test_api_error_carries_code_and_retry_after(self):
        opener = RecordingOpener({"ok": False, "error_code": 429, "description": "Too Many Requests",
                                  "parameters": {"retry_after": 3}})
        with self.assertRaises(TelegramError) as ctx:
            TelegramAPI(TOKEN, opener=opener).get_me()
        self.assertEqual((ctx.exception.code, ctx.exception.retry_after), (429, 3))

    def test_http_error_body_is_parsed(self):
        body = b'{"ok": false, "error_code": 401, "description": "Unauthorized"}'
        error = urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, io.BytesIO(body))
        with self.assertRaises(TelegramError) as ctx:
            TelegramAPI(TOKEN, opener=RecordingOpener(error)).get_me()
        self.assertEqual(ctx.exception.code, 401)
        self.assertIn("Unauthorized", str(ctx.exception))

    def test_network_errors_never_leak_the_token(self):
        error = urllib.error.URLError(f"cannot reach https://api.telegram.org/bot{TOKEN}/getMe")
        with self.assertRaises(TelegramError) as ctx:
            TelegramAPI(TOKEN, opener=RecordingOpener(error)).get_me()
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))
        self.assertIn("<token>", str(ctx.exception))

    def test_unreadable_response(self):
        with self.assertRaises(TelegramError):
            TelegramAPI(TOKEN, opener=RecordingOpener(b"<html>bad gateway</html>")).get_me()

    def test_send_message_truncates_long_text(self):
        opener = RecordingOpener({"ok": True, "result": True})
        TelegramAPI(TOKEN, opener=opener).send_message(5, "x" * 5000)
        self.assertEqual(len(json.loads(opener.requests[0][0].data)["text"]), 4000)

    def test_send_photo_builds_a_multipart_upload(self):
        opener = RecordingOpener({"ok": True, "result": {}})
        png = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        TelegramAPI(TOKEN, opener=opener).send_photo(42, png, caption="hello")
        request, _ = opener.requests[0]
        content_type = request.get_header("Content-type")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        boundary = content_type.split("boundary=")[1]
        data = request.data
        self.assertIn(png, data)
        self.assertIn(b'name="chat_id"\r\n\r\n42', data)
        self.assertIn(b'name="caption"\r\n\r\nhello', data)
        self.assertIn(b'name="photo"; filename="shot.png"', data)
        self.assertTrue(data.rstrip().endswith(f"--{boundary}--".encode()))
        self.assertTrue(request.full_url.endswith("/sendPhoto"))


if __name__ == "__main__":
    unittest.main()
