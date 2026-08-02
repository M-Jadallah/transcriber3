from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.formatting.opencode_client import OpenCodeClient, OpenCodeUnavailable


class OpenCodeClientTests(unittest.TestCase):
    def client(self) -> OpenCodeClient:
        return OpenCodeClient(
            SimpleNamespace(
                opencode_url="http://opencode:4096",
                opencode_control_url="http://opencode:4097",
                opencode_username="user",
                opencode_password="secret",
            )
        )

    @staticmethod
    def response(data: object, *, status: int = 200, text: str = "") -> Mock:
        response = Mock()
        response.ok = 200 <= status < 300
        response.status_code = status
        response.text = text
        response.content = b"json"
        response.json.return_value = data
        return response

    @patch("app.formatting.opencode_client.requests.request")
    def test_start_oauth_validates_and_normalizes_contract(self, request: Mock) -> None:
        request.return_value = self.response(
            {
                "url": "HTTPS://accounts.example.test/authorize?x=1",
                "method": "code",
                "instructions": "Enter the code",
                "internal": "not-public",
            }
        )

        result = self.client().start_oauth("open-ai_1", 2)

        self.assertEqual(
            result,
            {
                "url": "https://accounts.example.test/authorize?x=1",
                "method": "code",
                "instructions": "Enter the code",
            },
        )
        self.assertIn("/provider/open-ai_1/oauth/authorize", request.call_args.args[1])

    @patch("app.formatting.opencode_client.requests.request")
    def test_start_oauth_rejects_non_http_url(self, request: Mock) -> None:
        request.return_value = self.response({"url": "javascript:alert(1)"})
        with self.assertRaises(OpenCodeUnavailable):
            self.client().start_oauth("openai", 0)

    @patch("app.formatting.opencode_client.requests.request")
    def test_provider_id_rejects_path_injection(self, request: Mock) -> None:
        with self.assertRaises(ValueError):
            self.client().start_oauth("../provider", 0)
        request.assert_not_called()

    @patch("app.formatting.opencode_client.requests.request")
    def test_callback_requires_explicit_success(self, request: Mock) -> None:
        request.return_value = self.response({"message": "looks nonempty"})
        with self.assertRaises(OpenCodeUnavailable):
            self.client().finish_oauth("openai", 0, "code")

        request.return_value = self.response({"success": False})
        self.assertFalse(self.client().finish_oauth("openai", 0, "code"))

    @patch("app.formatting.opencode_client.requests.request")
    def test_upstream_error_does_not_expose_response_body(self, request: Mock) -> None:
        request.return_value = self.response(
            {"error": True}, status=401, text="access_token=super-secret"
        )
        with self.assertRaises(OpenCodeUnavailable) as raised:
            self.client().providers()
        self.assertNotIn("super-secret", str(raised.exception))
        self.assertIn("401", str(raised.exception))

    @patch("app.formatting.opencode_client.requests.post")
    def test_logout_returns_stable_public_contract(self, post: Mock) -> None:
        post.return_value = self.response(
            {
                "success": True,
                "removed": True,
                "restarting": True,
                "path": "/private/auth.json",
            }
        )
        self.assertEqual(
            self.client().logout(),
            {"success": True, "removed": True, "restarting": True},
        )


if __name__ == "__main__":
    unittest.main()
