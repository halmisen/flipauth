#!/usr/bin/env python3
"""Offline checks for /proc-backed process facts and daemon ownership."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO / "lib"))
import process_state


class ProcFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="flipauth-process-", dir=REPO / "work")
        self.root = Path(self.tmp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        boot_file = self.proc / "sys/kernel/random/boot_id"
        boot_file.parent.mkdir(parents=True)
        boot_file.write_text("fixture-boot")
        self.bin = self.root / "bin"
        (self.bin / "versions").mkdir(parents=True)
        self.claude = self.bin / "versions" / "2.1.319"
        self.claude.write_text("fake")
        self.claude.chmod(0o700)
        self.stable_claude = self.bin / "claude"
        os.symlink(self.claude, self.stable_claude)
        self.ps = self.root / "ps"
        self.pid = 4171
        self.ps.write_text(f"#!/bin/sh\nprintf '%s\\n' {self.pid}\n")
        self.ps.chmod(0o700)
        self.env = {
            "FLIPAUTH_PROC_ROOT": str(self.proc),
            "FLIPAUTH_PS_BIN": str(self.ps),
            "FLIPAUTH_CLAUDE_BIN": str(self.claude),
            "FLIPAUTH_CODEX_BIN": str(self.claude),
            "FLIPAUTH_ACCOUNTS_DIR": str(self.root / "registry"),
            "HOME": str(self.root / "home"),
        }
        self.old = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def add_proc(self, argv, env, *, ticks=123, pid=None, exe=None):
        pid = self.pid if pid is None else pid
        directory = self.proc / str(pid)
        directory.mkdir()
        directory.chmod(0o755)
        # After the closing ')' Linux stat exposes state plus 19 fields before
        # starttime (field 22, index 19 in this suffix).
        (directory / "stat").write_text(f"{pid} (fixture) S " + " ".join(["0"] * 18 + [str(ticks)]))
        (directory / "cmdline").write_bytes(b"\0".join(item.encode() for item in argv) + b"\0")
        (directory / "environ").write_bytes(b"\0".join((k + "=" + v).encode() for k, v in env.items()) + b"\0")
        os.symlink(self.claude if exe is None else exe, directory / "exe")

    def test_versioned_claude_uses_real_proc_argv_and_ignores_ps_text(self):
        self.add_proc(
            [str(self.claude), "--prompt", "don't parse me"],
            {"HOME": str(self.root / "home"), "CLAUDE_CONFIG_DIR": str(self.root / "claude-alpha")},
        )
        facts = process_state.processes("claude")
        self.assertEqual(set(facts), {self.pid})
        self.assertEqual(facts[self.pid]["argv"][-1], "don't parse me")
        self.assertEqual(facts[self.pid]["home"], str((self.root / "claude-alpha").resolve()))

    def test_proc_read_reports_a_process_that_just_disappeared(self):
        self.add_proc([str(self.claude)], {"HOME": str(self.root / "home")})
        with mock.patch.object(Path, "read_text", side_effect=ProcessLookupError):
            self.assertIsNone(process_state.identity(self.pid))
        with mock.patch.object(Path, "read_bytes", side_effect=ProcessLookupError):
            self.assertEqual(process_state.process_environment(self.pid), {})
            self.assertEqual(process_state._argv(self.pid), [])

    def test_wrapper_before_path_does_not_hide_old_claude_release(self):
        newer = self.bin / "versions" / "2.1.322"
        newer.write_text("new fake")
        newer.chmod(0o700)
        self.stable_claude.unlink()
        self.stable_claude.symlink_to(newer)
        shadow = self.root / "shadow"
        shadow.mkdir()
        wrapper = shadow / "claude"
        wrapper.write_text("#!/bin/sh\n# flipauth current launcher v1\n")
        wrapper.chmod(0o700)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(shadow) + os.pathsep + str(self.bin) + os.pathsep + old_path
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old_path))
        old_override = os.environ.pop("FLIPAUTH_CLAUDE_BIN", None)
        self.addCleanup(lambda: os.environ.__setitem__("FLIPAUTH_CLAUDE_BIN", old_override)
                        if old_override is not None else os.environ.pop("FLIPAUTH_CLAUDE_BIN", None))
        self.add_proc(
            [str(self.claude), "--prompt", "old release"],
            {"HOME": str(self.root / "home"), "CLAUDE_CONFIG_DIR": str(self.root / "claude-alpha")},
        )
        facts = process_state.processes("claude")
        self.assertEqual(set(facts), {self.pid})

    def test_same_home_child_is_not_called_claude_without_service_executable(self):
        self.add_proc(
            ["sleep", "60"],
            {"HOME": str(self.root / "home"), "CLAUDE_CONFIG_DIR": str(self.root / "claude-alpha")},
        )
        (self.proc / str(self.pid) / "exe").unlink()
        os.symlink("/usr/bin/sleep", self.proc / str(self.pid) / "exe")
        self.assertEqual(process_state.processes("claude"), {})

    def test_default_codex_home_uses_HOME_and_missing_home_refuses(self):
        self.add_proc(["codex", "--version"], {"HOME": str(self.root / "home")})
        facts = process_state.processes("codex")
        self.assertEqual(facts[self.pid]["home"], str((self.root / "home" / ".codex").resolve()))
        (self.proc / str(self.pid) / "environ").write_bytes(b"PATH=/usr/bin\0")
        with self.assertRaises(process_state.accounts.Refused):
            process_state.processes("codex")

    def test_exit_during_fact_read_is_gone_and_reused_pid_is_refused(self):
        self.add_proc(["codex"], {"HOME": str(self.root / "home")})
        with mock.patch.object(process_state, "identity", side_effect=[123, None]):
            self.assertIsNone(process_state.process_fact(self.pid, "codex"))
        with mock.patch.object(process_state, "identity", side_effect=[123, 999]):
            with self.assertRaises(process_state.accounts.Refused):
                process_state.process_fact(self.pid, "codex")

    def test_python_tool_with_codex_argument_and_unreadable_env_is_ignored(self):
        self.add_proc(
            ["/usr/bin/python3", str(self.root / "ordinary-tool.py"), "codex", "--prompt"],
            {"HOME": str(self.root / "home"), "CODEX_HOME": str(self.root / "codex")},
            exe="/usr/bin/python3",
        )
        self.ps.write_text(f"#!/bin/sh\nprintf '%s\\n' {self.pid}\n")
        with mock.patch.object(process_state, "process_environment",
                               side_effect=AssertionError("unrelated environment was read")):
            self.assertEqual(process_state.processes("codex"), {})

    def test_forged_argv0_and_daemon_record_cannot_authorize_an_unrelated_executable(self):
        home = self.root / "forged-home"
        records = home / "app-server-daemon"
        records.mkdir(parents=True)
        self.add_proc(["codex", "app-server", "--managed-daemon", "--listen", "unix:///fixture.sock"],
                      {"HOME": str(self.root / "home"), "CODEX_HOME": str(home)},
                      exe=self.root / "ordinary-program")
        with mock.patch.object(process_state, "process_environment",
                               side_effect=AssertionError("unrelated environment was read")):
            self.assertEqual(process_state.processes("codex"), {})
        (records / "daemon.pid").write_text(json.dumps({
            "pid": self.pid, "processIdentity": {"startTicks": 123, "bootId": "fixture-boot"}}))
        registry = {"accounts": {"codex": {"alpha": {"directory": str(home)}}}}
        self.assertEqual(process_state.verified_daemons("codex", self.root / "registry", registry), set())

    def test_codex_release_family_covers_old_nested_native_binary(self):
        releases = self.root / "packages/standalone/releases"
        latest = releases / "new/bin/codex"
        latest.parent.mkdir(parents=True)
        latest.write_text("new fake")
        latest.chmod(0o700)
        old = releases / "old/bin/codex"
        old.parent.mkdir(parents=True)
        old.write_text("old fake")
        os.environ["FLIPAUTH_CODEX_BIN"] = str(latest)
        self.add_proc([str(old)], {"HOME": str(self.root / "home")}, exe=old)
        self.assertEqual(set(process_state.processes("codex")), {self.pid})

    def test_codex_code_mode_helper_in_official_release_is_not_a_cli(self):
        releases = self.root / "packages/app-server-daemon/releases"
        cli = releases / "current/bin/codex"
        cli.parent.mkdir(parents=True)
        cli.write_text("fake cli")
        cli.chmod(0o700)
        helper = cli.with_name("codex-code-mode-host")
        helper.write_text("fake helper")
        os.environ["FLIPAUTH_CODEX_BIN"] = str(cli)
        self.add_proc([str(helper)], {"HOME": str(self.root / "home")}, exe=helper)
        self.assertEqual(process_state.processes("codex"), {})

    def test_daemon_pid_record_requires_boot_start_home_and_argv(self):
        home = self.root / "codex-beta"
        daemon_dir = home / "app-server-daemon"
        daemon_dir.mkdir(parents=True)
        self.claude.unlink()
        self.claude.write_text("fake-codex")
        self.claude.chmod(0o700)
        self.ps.write_text(f"#!/bin/sh\nprintf '%s\\n' {self.pid}\n")
        self.add_proc(
            ["codex", "app-server", "--managed-daemon", "--listen", "unix:///tmp/codex.sock"],
            {"HOME": str(self.root / "home"), "CODEX_HOME": str(home)},
            ticks=456,
        )
        boot_id = (self.proc / "sys/kernel/random/boot_id").read_text().strip()
        (daemon_dir / "daemon.pid").write_text(json.dumps({
            "pid": self.pid,
            "processIdentity": {"startTicks": 456, "bootId": boot_id},
        }))
        registry = self.root / "registry"
        registry.mkdir()
        (registry / "accounts.json").write_text(json.dumps({
            "schema": 1,
            "accounts": {"claude": {}, "codex": {"beta": {"directory": str(home), "configuration": "bare"}}},
            "defaults": {"codex": "beta"}, "selected": {"codex": "beta"},
        }))
        self.assertEqual(process_state.verified_daemons("codex", registry), {self.pid})
        record = json.loads((daemon_dir / "daemon.pid").read_text())
        record["processIdentity"]["startTicks"] = 999
        (daemon_dir / "daemon.pid").write_text(json.dumps(record))
        self.assertEqual(process_state.verified_daemons("codex", registry), set())
        record["processIdentity"]["startTicks"] = 456
        record["processIdentity"]["bootId"] = "wrong-boot"
        (daemon_dir / "daemon.pid").write_text(json.dumps(record))
        self.assertEqual(process_state.verified_daemons("codex", registry), set())
        record["processIdentity"]["bootId"] = boot_id
        (daemon_dir / "daemon.pid").write_text(json.dumps(record))
        (self.proc / str(self.pid) / "environ").write_bytes(
            ("HOME=" + str(self.root / "home") + "\0CODEX_HOME=" + str(self.root / "other") + "\0").encode()
        )
        self.assertEqual(process_state.verified_daemons("codex", registry), set())
        (self.proc / str(self.pid) / "environ").write_bytes(
            ("HOME=" + str(self.root / "home") + "\0CODEX_HOME=" + str(home) + "\0").encode()
        )
        (self.proc / str(self.pid) / "cmdline").write_bytes(
            b"codex\0not-app-server\0--managed-daemon\0--listen\0unix:///tmp/codex.sock\0"
        )
        self.assertEqual(process_state.verified_daemons("codex", registry), set())

    def test_daemon_stop_order_keeps_updater_before_server(self):
        facts = {
            10: {"command": ["app-server", "--managed-daemon"]},
            20: {"command": ["app-server", "daemon", "pid-update-loop"]},
        }
        self.assertEqual(process_state.daemon_stop_order({10, 20}, facts), [20, 10])


if __name__ == "__main__":
    unittest.main(verbosity=2)
