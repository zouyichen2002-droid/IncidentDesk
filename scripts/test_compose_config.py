#!/usr/bin/env python3
"""Render-only regression checks: never start services or contact GitHub."""

import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def api_environment(overrides):
    env = dict(os.environ)
    for key in (
        "GITHUB_API_URL", "GITHUB_TOKEN",
        "INCIDENT_GITHUB_API_URL", "INCIDENT_GITHUB_TOKEN",
        "COMPOSE_FILE", "COMPOSE_ENV_FILES",
    ):
        env.pop(key, None)
    env.update(overrides)
    rendered = subprocess.check_output(
        ["docker", "compose", "--env-file", os.devnull,
         "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"],
        cwd=ROOT, env=env, text=True,
    )
    return json.loads(rendered)["services"]["api"]["environment"]


class ComposeIntegrationConfigTests(unittest.TestCase):
    def test_default_uses_local_stub_without_token(self):
        env = api_environment({})
        self.assertEqual(env["GITHUB_API_URL"], "http://demo:8090/github")
        self.assertEqual(env["GITHUB_TOKEN"], "")

    def test_runner_variables_do_not_redirect_fixture_requests(self):
        env = api_environment({
            "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_TOKEN": "runner-fixture-not-a-real-token",
        })
        self.assertEqual(env["GITHUB_API_URL"], "http://demo:8090/github")
        self.assertEqual(env["GITHUB_TOKEN"], "")

    def test_explicit_project_integration_is_respected(self):
        env = api_environment({
            "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_TOKEN": "runner-fixture-not-a-real-token",
            "INCIDENT_GITHUB_API_URL": "https://git.example.test/api/v3",
            "INCIDENT_GITHUB_TOKEN": "project-fixture-not-a-real-token",
        })
        self.assertEqual(env["GITHUB_API_URL"], "https://git.example.test/api/v3")
        self.assertEqual(env["GITHUB_TOKEN"], "project-fixture-not-a-real-token")


if __name__ == "__main__":
    unittest.main(verbosity=2)
