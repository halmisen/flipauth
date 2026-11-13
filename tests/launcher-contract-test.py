#!/usr/bin/env python3
"""End-to-end contracts for directory launches and the official CLI boundary.

The binaries in this test are small local stand-ins.  Nothing here contacts a
provider, starts Herdr, reads a real credential, or writes outside a temporary
fixture under the repository's work directory.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(os.environ.get("FLIPAUTH_BIN_DIR", Path(__file__).resolve().parent.parent))
FAKE_CLI = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

service = os.environ.get("HERDR_AGENT", "unknown")
home_key = "CLAUDE_CONFIG_DIR" if service == "claude" else "CODEX_HOME"
home = Path(os.environ[home_key])
version = Path(__file__).resolve().name
record = {
    "service": service,
    "home": str(home),
    "args": sys.argv[1:],
    "version": version,
    "herdr_agent": os.environ.get("HERDR_AGENT"),
}
calls = home / ".launcher-calls.jsonl"
with calls.open("a") as out:
    out.write(json.dumps(record) + "\n")
if sys.argv[1:2] in (["login"], ["auth"]):
    (home / ("auth.json" if service == "codex" else ".credentials.json")).write_text("{}")
'''


class LauncherContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flipauth-launch-contract-", dir=REPO / "work")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "homes"
        self.home.mkdir()
        self.native = self.root / "native-bin"
        self.native.mkdir()
        self.releases = self.root / "releases"
        self.releases.mkdir()
        self.wrappers = self.root / "wrapper-bin"
        self.wrappers.mkdir()
        self.registry = self.root / "registry"
        self.empty_ps = self.root / "empty-ps"
        self.empty_ps.write_text("#!/bin/sh\nexit 0\n")
        self.empty_ps.chmod(0o700)
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(("FLIPAUTH_", "CLAUDE_", "CODEX_", "ANTHROPIC_", "OPENAI_")):
                self.env.pop(key, None)
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.wrappers}:{self.native}:{os.environ['PATH']}",
            FLIPAUTH_ACCOUNTS_DIR=str(self.registry),
            FLIPAUTH_PS_BIN=str(self.empty_ps),
            PYTHONDONTWRITEBYTECODE="1",
        )
        for service in ("claude", "codex"):
            first = self.releases / f"{service}-v1"
            first.write_text(FAKE_CLI)
            first.chmod(0o700)
            (self.native / service).symlink_to(first)

    def cli(self, *argv, env=None, check=True):
        result = subprocess.run(
            [str(REPO / "flipauth"), *map(str, argv)],
            env=env or self.env,
            capture_output=True,
            text=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def account(self, service, name, path=None, default=False):
        path = path or self.home / f"{service}-{name}"
        args = [service, "account", "add", name, path, "--create", "--bare"]
        if default:
            args.append("--default")
        self.cli(*args)
        return Path(path)

    def calls(self, path):
        marker = Path(path) / ".launcher-calls.jsonl"
        if not marker.exists():
            return []
        return [json.loads(line) for line in marker.read_text().splitlines()]

    def registry_data(self):
        return json.loads((self.registry / "accounts.json").read_text())

    def test_path_wrapper_and_every_directory_entrypoint_use_native_cli(self):
        homes = {}
        for service, short in (("claude", "cc"), ("codex", "cod")):
            homes[service] = self.account(service, "one", default=True)
            self.cli(service, "account", "bind-current", self.wrappers / service)

        # The PATH wrapper is intentionally first.  The parent has no
        # FLIPAUTH_*_BIN override, so recursion protection must skip the wrapper
        # and find the stable official symlink behind it.
        for service in ("claude", "codex"):
            self.cli(service, "account", "run", "one", "--", "direct")
            self.cli(service, "account", "login", "one", "--", "device-auth")
            self.assertEqual(self.calls(homes[service])[-1]["args"],
                             ["auth", "login", "device-auth"] if service == "claude" else
                             ["login", "device-auth"])
            self.assertEqual(self.calls(homes[service])[-1]["herdr_agent"], service)
            self.assertEqual(self.calls(homes[service])[-1]["service"], service)
            wrapper_result = subprocess.run(
                [service, "through-path-wrapper"], env=self.env,
                capture_output=True, text=True,
            )
            self.assertEqual(wrapper_result.returncode, 0, wrapper_result.stderr)
            self.assertEqual(
                self.calls(homes[service])[-1]["args"],
                ["through-path-wrapper"],
            )

        # Current selection uses the same plan, including the
        # stable executable behind the PATH wrapper.
        self.cli("claude", "account", "current", "--", "current")
        self.cli("codex", "account", "current", "--", "current")
        for service in ("claude", "codex"):
            self.assertTrue(any(call["args"][-1] == "current" for call in self.calls(homes[service])))

        # A fixed account launcher also remains usable after the dynamic PATH
        # wrapper is installed.
        fixed = self.root / f"fixed-{service}"
        self.cli("codex", "account", "bind", "one", fixed)
        self.assertEqual(subprocess.run([str(fixed), "fixed"], env=self.env, check=True).returncode, 0)
        self.assertEqual(self.calls(homes["codex"])[-1]["args"], ["fixed"])

    def test_wrapper_re_resolves_stable_symlink_after_provider_upgrade(self):
        home = self.account("claude", "one", default=True)
        self.cli("claude", "account", "bind-current", self.wrappers / "claude")
        before = subprocess.run(["claude", "before-upgrade"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(before.returncode, 0, before.stderr)
        second = self.releases / "claude-v2"
        second.write_text(FAKE_CLI)
        second.chmod(0o700)
        (self.native / "claude").unlink()
        (self.native / "claude").symlink_to(second)
        after = subprocess.run(["claude", "after-upgrade"], env=self.env,
                               capture_output=True, text=True)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(self.calls(home)[-1]["version"], "claude-v2")

    def test_explicit_run_and_login_do_not_change_selection_or_default(self):
        for service in ("claude", "codex"):
            self.account(service, "primary", default=True)
            other = self.account(service, "secondary")
            before = self.registry_data()
            self.cli(service, "account", "run", "secondary", "--", "run")
            self.cli(service, "account", "login", "secondary", "--", "device-auth")
            after = self.registry_data()
            self.assertEqual(after["selected"][service], before["selected"][service])
            self.assertEqual(after["defaults"][service], before["defaults"][service])
            self.assertTrue((other / ("auth.json" if service == "codex" else ".credentials.json")).exists())

    def test_service_homes_are_independent_and_herdr_hint_is_explicit(self):
        claude = self.account("claude", "primary", default=True)
        codex = self.account("codex", "secondary", default=True)
        self.cli("claude", "account", "run", "primary", "--", "one")
        self.cli("codex", "account", "run", "secondary", "--", "two")
        c = self.calls(claude)[-1]
        x = self.calls(codex)[-1]
        self.assertEqual((c["service"], c["home"], c["herdr_agent"]), ("claude", str(claude), "claude"))
        self.assertEqual((x["service"], x["home"], x["herdr_agent"]), ("codex", str(codex), "codex"))
        self.assertNotEqual(c["home"], x["home"])

    def test_auth_bypass_environment_settings_and_codex_remote_are_refused(self):
        claude = self.account("claude", "one")
        codex = self.account("codex", "one")
        for variable in ("ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID"):
            bad_env = {**self.env, variable: "outside-account"}
            result = self.cli("claude", "account", "run", "one", env=bad_env, check=False)
            self.assertNotEqual(result.returncode, 0, variable)
        settings = claude / "settings.local.json"
        settings.write_text(json.dumps({"env": {"ANTHROPIC_PROFILE": "outside-account"}}))
        before = settings.read_bytes()
        self.assertNotEqual(self.cli("claude", "account", "run", "one", check=False).returncode, 0)
        self.assertEqual(settings.read_bytes(), before)
        result = self.cli("codex", "account", "run", "one", "--", "--remote", "ws://127.0.0.1:1", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((codex / ".launcher-calls.jsonl").exists())

    def test_retired_observe_is_silent_and_legacy_mutators_are_rejected(self):
        observe = subprocess.run(
            [str(REPO / "flipauth"), "claude", "observe"], env=self.env,
            input='{"rate_limits": {"five_hour": {"used_percentage": 1}}}\n',
            capture_output=True, text=True,
        )
        self.assertEqual(observe.returncode, 0, observe.stderr)
        self.assertEqual(observe.stdout, "")
        self.assertEqual(observe.stderr, "")
        self.assertFalse(self.registry.exists())
        for service in ("claude", "codex"):
            for retired in ("quota", "doctor"):
                result = self.cli(service, retired, check=False)
                self.assertNotEqual(result.returncode, 0, (service, retired))

        fixtures = {}
        for service, alias, credential in (("claude", "claude-switch", ".credentials.json"),
                                            ("codex", "codex-switch", "auth.json")):
            directory = self.home / f"legacy-{service}"
            directory.mkdir()
            (directory / credential).write_text("credential-fixture")
            (directory / "sessions").mkdir()
            (directory / "sessions" / "session.json").write_text("session-fixture")
            state = directory / "legacy-state"
            state.mkdir()
            env = {**self.env,
                   ("CLAUDE_SWITCH_CLAUDE_DIR" if service == "claude" else "CODEX_SWITCH_CODEX_DIR"): str(directory),
                   ("CLAUDE_SWITCH_STATE_DIR" if service == "claude" else "CODEX_SWITCH_STATE_DIR"): str(state)}
            fixtures[service] = (directory, {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()})
            for command in (("save", "legacy"), ("activate", "legacy"),
                            ("login", "legacy"), ("legacy",), ("primary",)):
                result = subprocess.run([str(REPO / alias), *command], env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, (service, command, result.stderr))
            current = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
            self.assertEqual(current, fixtures[service][1])


if __name__ == "__main__":
    unittest.main()
