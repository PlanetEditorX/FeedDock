from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
UPDATER_PATH = ROOT / "updater" / "updater.py"


class UpdaterSidecarTests(unittest.TestCase):
    def _load_module(self, temp: Path):
        compose = temp / "docker-compose.yml"
        compose.write_text("services:\n  feeddock:\n    image: demo:latest\n", encoding="utf-8")
        env_file = temp / ".env"
        env_file.write_text("FEEDDOCK_IMAGE=demo:latest\n", encoding="utf-8")
        token_file = temp / "state" / "token"
        values = {
            "UPDATER_TOKEN": "",
            "UPDATER_TOKEN_FILE": str(token_file),
            "UPDATER_COMPOSE_FILE": str(compose),
            "UPDATER_PROJECT_DIR": str(temp),
            "UPDATER_ENV_FILE": str(env_file),
            "UPDATER_SERVICE": "feeddock",
            "UPDATER_CONTAINER": "feeddock",
        }
        spec = importlib.util.spec_from_file_location("feeddock_updater_test", UPDATER_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, values, clear=False):
            spec.loader.exec_module(module)
        return module, token_file

    def test_generates_shared_token_file(self):
        with tempfile.TemporaryDirectory() as directory:
            module, token_file = self._load_module(Path(directory))
            self.assertTrue(token_file.is_file())
            self.assertEqual(token_file.read_text(encoding="utf-8").strip(), module.TOKEN)
            self.assertEqual(len(module.TOKEN), 64)

    def test_update_command_is_restricted_to_feeddock_service(self):
        with tempfile.TemporaryDirectory() as directory:
            module, _ = self._load_module(Path(directory))
            calls: list[tuple[str, ...]] = []

            def fake_run(*args: str, check: bool = True):
                calls.append(tuple(args))
                if args[:2] == ("docker", "inspect"):
                    return subprocess.CompletedProcess(args, 0, stdout="existing-project\n")
                return subprocess.CompletedProcess(args, 0, stdout="ok\n")

            module._run = fake_run
            module._perform_update()
            state = module._snapshot()
            self.assertTrue(state["ok"])
            compose_calls = [call for call in calls if call[:2] == ("docker", "compose")]
            self.assertEqual(len(compose_calls), 2)
            self.assertIn("pull", compose_calls[0])
            self.assertEqual(compose_calls[0][-1], "feeddock")
            self.assertIn("up", compose_calls[1])
            self.assertEqual(compose_calls[1][-1], "feeddock")
            self.assertIn("existing-project", compose_calls[0])


if __name__ == "__main__":
    unittest.main()
