from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from app.formatting.opencode_control import health, logout


class OpenCodeControlTests(unittest.TestCase):
    def auth_header(self, username: str = "opencode", password: str = "secret") -> str:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {token}"

    def test_logout_removes_file_and_schedules_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "XDG_DATA_HOME": temp,
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": "secret",
            },
            clear=False,
        ):
            auth_file = Path(temp) / "opencode" / "auth.json"
            auth_file.parent.mkdir(parents=True)
            auth_file.write_text('{"openai": {}}', encoding="utf-8")
            tasks = BackgroundTasks()
            result = logout(tasks, authorization=self.auth_header())
            self.assertTrue(result["success"])
            self.assertFalse(auth_file.exists())
            self.assertEqual(len(tasks.tasks), 1)

    def test_invalid_credentials_are_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": "secret",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as raised:
                health(authorization=self.auth_header(password="wrong"))
            self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
