#!/usr/bin/env python3
"""Offline end-to-end checks of the real dispatcher and generated commands."""

import json
import os
from pathlib import Path
import pty
import signal
import subprocess
import tempfile
import time
import unittest


REPO = Path(os.environ.get("FLIPAUTH_BIN_DIR", Path(__file__).resolve().parent.parent))
FAKE = r'''#!/usr/bin/env python3
import json, os, signal, sys, time
from pathlib import Path
service = Path(sys.argv[0]).name.split('-')[0]
home = Path(os.environ['CLAUDE_CONFIG_DIR' if service == 'claude' else 'CODEX_HOME'])
arguments = sys.argv[1:]
record = {'args': arguments, 'cwd': os.getcwd(), 'home': str(home), 'pid': os.getpid(),
          'tty': [os.isatty(i) for i in range(3)]}
if '--stdin' in arguments:
    record['stdin'] = sys.stdin.read()
(home / 'called.json').write_text(json.dumps(record))
if '--wait' in arguments:
    def interrupted(signum, frame):
        (home / 'signal').write_text(str(signum))
        sys.exit(128 + signum)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    (home / 'ready').touch()
    while True: time.sleep(.05)
if arguments[:2] == ['auth', 'login'] or arguments[:1] == ['login']:
    (home / ('auth.json' if service == 'codex' else '.credentials.json')).write_text('{}')
if '--stderr' in arguments:
    print('cli-stderr', file=sys.stderr)
print('cli-stdout')
sys.exit(37 if '--fail' in arguments else 0)
'''


class Accounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flipauth-accounts-", dir=REPO / "work")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.program = REPO / "flipauth"
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = os.environ.copy()
        # The test never uses real credentials, inherited providers or a real CLI.
        for key in list(self.env):
            if key.startswith(("ANTHROPIC_", "OPENAI_", "CODEX_", "CLAUDE_", "FLIPAUTH_")):
                del self.env[key]
        self.env.update(HOME=str(self.home), PATH=str(self.bin) + ":" + os.environ["PATH"],
                        FLIPAUTH_ACCOUNTS_DIR=str(self.root / "registry"))
        for service in ("claude", "codex"):
            binary = self.bin / (service + "-official")
            binary.write_text(FAKE)
            binary.chmod(0o700)
            self.env["FLIPAUTH_" + service.upper() + "_BIN"] = str(binary)
        # Any accidental old-mode process control fails with a visible tripwire.
        for binary in ("ps", "herdr", "curl", "codex", "claude"):
            p = self.bin / binary
            p.write_text('#!/bin/sh\nprintf forbidden >> "$HOME/tripwire"\nexit 97\n')
            p.chmod(0o700)

    def call(self, service, *arguments, ok=True, env=None, **kwargs):
        result = subprocess.run([str(self.program), service, "account", *map(str, arguments)],
                                env=env or self.env, capture_output=True, text=True, **kwargs)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
        return result

    def create(self, service="codex", label="one", path=None):
        path = path or self.home / (service + "-" + label)
        self.call(service, "add", label, path, "--create", "--bare")
        return path

    def record(self, directory):
        return json.loads((directory / "called.json").read_text())

    def wait_file(self, path, process):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            self.assertIsNone(process.poll())
            time.sleep(.02)
        self.assertTrue(path.exists(), str(path))

    def test_independent_accounts_and_official_login(self):
        for service in ("claude", "codex"):
            first = self.create(service)
            second = self.create(service, "two")
            self.call(service, "login", "one", "--", "--device-auth")
            saved = {p.name: p.read_bytes() for p in first.iterdir()}
            self.call(service, "login", "two")
            self.call(service, "run", "two", "--", "resume", "--last")
            self.assertEqual(saved, {p.name: p.read_bytes() for p in first.iterdir()})
            credential = "auth.json" if service == "codex" else ".credentials.json"
            self.assertTrue((first / credential).exists())
            self.assertTrue((second / credential).exists())
            self.assertEqual(self.record(second)["home"], str(second))
        self.assertFalse((self.home / "tripwire").exists())
        registry = json.loads((self.root / "registry/accounts.json").read_text())
        self.assertNotIn("token", json.dumps(registry))
        self.assertFalse(list(self.home.rglob(".active-profile")))

    def test_codex_default_launch_keeps_the_native_home_daemon_enabled(self):
        directory = self.create()
        self.call('codex', 'run', 'one', '--', 'resume', '--last')
        self.assertEqual(self.record(directory)['args'], ['resume', '--last'])
        self.assertEqual(self.record(directory)['home'], str(directory))

    def test_named_launcher_deployment_and_check_never_start_a_cli(self):
        self.create('codex','primary')
        self.create('codex','secondary')
        script=REPO/'scripts/deploy-launchers.sh'
        check=['bash',str(script),'codex','--check',str(self.bin)]
        self.assertNotEqual(subprocess.run(check,env=self.env,capture_output=True).returncode,0)
        registry=self.root/'registry/accounts.json'
        before=registry.read_bytes()
        self.assertFalse((self.bin/'codex-primary').exists())
        apply=['bash',str(script),'codex',str(self.bin)]
        first=subprocess.run(apply,env=self.env,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr)
        saved={name:(self.bin/name).read_bytes() for name in ('codex-primary','codex-secondary')}
        self.assertTrue(all(b'# flipauth switch launcher' in body for body in saved.values()))
        for name in saved:
            body=saved[name].decode()
            self.assertNotIn('account run',body)
        registered=json.loads(registry.read_text())
        original=json.loads(before)
        self.assertEqual(registered.get('selected'),original.get('selected'))
        self.assertEqual(registered.get('defaults'),original.get('defaults'))
        snapshot=registry.read_bytes()
        for command in (apply,check):
            result=subprocess.run(command,env=self.env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(registry.read_bytes(),snapshot)
        self.assertEqual(saved,{name:(self.bin/name).read_bytes() for name in saved})
        self.assertFalse(list(self.home.rglob('called.json')))

    def test_explicit_config_and_presence_never_claim_identity(self):
        path = self.home / "new"
        self.call("codex", "add", "one", path, "--create", ok=False)
        self.assertFalse(path.exists())
        directory = self.create()
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((directory / "config.toml").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "registry/accounts.json").stat().st_mode & 0o777, 0o600)
        (directory / "auth.json").write_text('SECRET-DO-NOT-READ')
        result = self.call("codex", "list", "--json")
        entry = json.loads(result.stdout)["accounts"][0]
        self.assertEqual(entry["credential_file"], "present")
        self.assertEqual(entry["identity"], "unverified")
        self.assertNotIn("SECRET", result.stdout + result.stderr)
        self.assertFalse((self.home / "tripwire").exists())

    def test_readonly_list_does_not_create_state_or_launch_cli(self):
        self.call("claude", "list")
        self.call("codex", "list", "--json")
        self.assertFalse((self.root / "registry").exists())
        self.assertFalse((self.home / "tripwire").exists())

    def test_existing_registration_is_idempotent_and_preserves_every_byte(self):
        directory = self.home / "existing"
        directory.mkdir(mode=0o700)
        (directory / "auth.json").write_text("DO-NOT-READ")
        self.call("codex", "add", "default", directory)
        registry = (self.root / "registry/accounts.json").read_bytes()
        self.call("codex", "add", "default", directory)
        self.assertEqual(registry, (self.root / "registry/accounts.json").read_bytes())
        self.assertEqual((directory / "auth.json").read_text(), "DO-NOT-READ")
        self.call("codex", "add", "other", directory, "--create", "--bare", ok=False)
        self.call("claude", "add", "other", directory, ok=False)
        self.call("codex", "add", "other", directory / "nested", "--create", "--bare", ok=False)

    def test_templates_are_copies_and_exclude_runtime_state(self):
        for service, config, rules, contents in [
            ("claude", "settings.json", "CLAUDE.md", '{"permissions":{"allow":["Read"]},"enabledPlugins":{"example":true}}'),
            ("codex", "config.toml", "AGENTS.md", 'model = "example"\ncli_auth_credentials_store = "file"\n'),
        ]:
            template = self.root / (service + "-template")
            template.mkdir()
            (template / config).write_text(contents)
            (template / rules).write_text("Reviewed project rules\n")
            target = self.home / (service + "-from-template")
            self.call(service, "add", "one", target, "--create", "--template", template)
            self.assertEqual((target / config).read_text(), contents)
            self.assertEqual((target / rules).read_bytes(), (template / rules).read_bytes())
            self.assertNotEqual((target / config).stat().st_ino, (template / config).stat().st_ino)
            (template / config).write_text("changed")
            self.assertEqual((target / config).read_text(), contents)
            self.call(service, "run", "one")
            (template / "auth.json").write_text("not-a-template")
            refused = self.home / (service + "-rejected")
            self.call(service, "add", "two", refused, "--create", "--template", template, ok=False)
            self.assertFalse(refused.exists())

    def test_secret_and_provider_templates_are_refused_without_echoing_values(self):
        template = self.root / "template"
        template.mkdir()
        for config in ({"env": {"ANTHROPIC_API_KEY": "SECRET"}}, {"apiKeyHelper": "SECRET"}):
            (template / "settings.json").write_text(json.dumps(config))
            result = self.call("claude", "add", "one", self.home / "bad", "--create", "--template", template, ok=False)
            self.assertNotIn("SECRET", result.stderr)
        self.assertFalse((self.home / "bad").exists())

    def test_home_override_and_all_arguments_stdio_working_directory(self):
        for service, key in (("codex", "CODEX_HOME"), ("claude", "CLAUDE_CONFIG_DIR")):
            directory = self.create(service)
            env = {**self.env, key: str(self.home / "inherited-wrong-home")}
            arguments = ["--stdin", "a b", "'quoted'", '"double"', "$HOME", "$(touch nope)", "*", "", "--stderr"]
            result = self.call(service, "run", "one", "--", *arguments, env=env, input="input\n", cwd=self.root)
            record = self.record(directory)
            self.assertEqual(record["args"], arguments)
            self.assertEqual(record["cwd"], str(self.root))
            self.assertEqual(record["stdin"], "input\n")
            self.assertEqual(result.stdout, "cli-stdout\n")
            self.assertEqual(result.stderr, "cli-stderr\n")
            result = self.call(service, "run", "one", "--fail", ok=False)
            self.assertEqual(result.returncode, 37)

    def test_conflicting_environment_settings_and_cli_arguments(self):
        for service, key in (("codex", "OPENAI_API_KEY"), ("claude", "ANTHROPIC_BASE_URL")):
            directory = self.create(service)
            result = self.call(service, "run", "one", env={**self.env, key: "SECRET"}, ok=False)
            self.assertIn(key, result.stderr)
            self.assertNotIn("SECRET", result.stderr)
            self.assertFalse((directory / "called.json").exists())
        for arguments in (["-c", 'cli_auth_credentials_store="keyring"'], ["--config=model_provider='custom'"],
                          ["--profile", "other"], ["-csqlite_home='/other'"], ["--oss"]):
            self.call("codex", "run", "one", "--", *arguments, ok=False)
        self.call("claude", "run", "one", "--settings", "/other", ok=False)
        directory = self.home / "codex-one"
        (directory / "config.toml").write_text('cli_auth_credentials_store="keyring"\n')
        self.call("codex", "run", "one", ok=False)
        self.assertEqual((directory / "config.toml").read_text(), 'cli_auth_credentials_store="keyring"\n')

    def test_bind_idempotence_conflicts_recursion_and_quoting(self):
        # Exercise both the install path and registry path with shell metacharacters.
        weird = self.root / "it's $HOME; `special`"
        weird.mkdir()
        import shutil
        self.program = weird / "flipauth"
        shutil.copy2(REPO / "flipauth", self.program)
        (weird / "lib").symlink_to(REPO / "lib", target_is_directory=True)
        self.env["FLIPAUTH_ACCOUNTS_DIR"] = str(weird / "registry")
        directory = self.create()
        launcher = weird / "codex-one"
        self.call("codex", "bind", "one", launcher)
        initial = launcher.read_bytes()
        self.call("codex", "bind", "one", launcher)
        self.assertEqual(initial, launcher.read_bytes())
        subprocess.run([str(launcher), "a b", "'", "$HOME", ""], env=self.env, check=True, capture_output=True)
        self.assertEqual(self.record(directory)["args"], ["a b", "'", "$HOME", ""])
        self.call("codex", "bind", "one", self.bin / "codex", ok=False)
        user = self.bin / "user-command"
        user.write_text("mine\n")
        user.chmod(0o700)
        self.call("codex", "bind", "one", user, ok=False)
        self.assertEqual(user.read_text(), "mine\n")
        shadow = weird / "user-command"
        self.call("codex", "bind", "one", shadow, ok=False)
        self.assertFalse(shadow.exists())
        link = weird / "symlink-command"
        link.symlink_to(weird / "missing")
        self.call("codex", "bind", "one", link, ok=False)
        env = {**self.env, "FLIPAUTH_CODEX_BIN": str(launcher)}
        self.call("codex", "run", "one", env=env, ok=False)
        env["FLIPAUTH_CODEX_BIN"] = str(REPO / "codex-switch")
        self.call("codex", "run", "one", env=env, ok=False)

    def test_concurrent_add_keeps_both_entries(self):
        processes = []
        for label in ("one", "two"):
            command = [str(REPO / "flipauth"), "codex", "account", "add", label,
                       str(self.home / label), "--create", "--bare"]
            processes.append(subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for process in processes:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
        data = json.loads(self.call("codex", "list", "--json").stdout)
        self.assertEqual({r["name"] for r in data["accounts"]}, {"one", "two"})

    def test_interrupt_signals_pid_and_other_process_untouched(self):
        first = self.create()
        second = self.create("codex", "two")
        keeper = subprocess.Popen([str(REPO / "flipauth"), "codex", "account", "run", "one", "--wait"], env=self.env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: keeper.poll() is None and keeper.terminate())
        self.wait_file(first / "ready", keeper)
        before = (first / "called.json").read_bytes()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            (second / "ready").unlink(missing_ok=True)
            process = subprocess.Popen([str(REPO / "flipauth"), "codex", "account", "run", "two", "--wait"], env=self.env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(lambda p=process: p.poll() is None and p.terminate())
            self.wait_file(second / "ready", process)
            self.assertEqual(self.record(second)["pid"], process.pid)
            process.send_signal(sig)
            self.assertEqual(process.wait(timeout=5), 128 + sig)
            self.assertEqual((second / "signal").read_text(), str(sig))
            self.assertIsNone(keeper.poll())
            self.assertEqual((first / "called.json").read_bytes(), before)
        keeper.terminate()
        keeper.wait(timeout=5)
        self.assertFalse((self.home / "tripwire").exists())

    def test_terminal_is_not_replaced_with_pipes(self):
        directory = self.create("claude")
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen([str(REPO / "flipauth"), "claude", "account", "run", "one"], env=self.env,
                                       stdin=slave, stdout=slave, stderr=slave)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(self.record(directory)["tty"], [True, True, True])
        finally:
            os.close(master)
            os.close(slave)

    def test_windows_paths_binaries_symlinks_and_corrupt_registry(self):
        directory = self.create()
        self.call("codex", "add", "bad", "/mnt/flipauth-never-created", "--create", "--bare", ok=False)
        findmnt = self.bin / "findmnt"
        findmnt.write_text('#!/bin/sh\necho 9p\n')
        findmnt.chmod(0o700)
        self.call("codex", "run", "one", ok=False)
        findmnt.unlink()
        windows = self.bin / "codex.exe"
        windows.write_text(FAKE)
        windows.chmod(0o700)
        self.call("codex", "run", "one", env={**self.env, "FLIPAUTH_CODEX_BIN": str(windows)}, ok=False)
        other = self.root / "auth-elsewhere"
        other.write_text("SECRET")
        (directory / "auth.json").symlink_to(other)
        self.call("codex", "run", "one", ok=False)
        self.assertEqual(other.read_text(), "SECRET")
        (directory / "auth.json").unlink()
        os.link(other, directory / "auth.json")
        self.call("codex", "run", "one", ok=False)
        (directory / "auth.json").unlink()
        registry = self.root / "registry/accounts.json"
        registry.write_text("corrupt")
        self.call("codex", "list", ok=False)
        self.call("codex", "add", "two", self.home / "two", "--create", "--bare", ok=False)
        self.assertEqual(registry.read_text(), "corrupt")
        self.assertFalse((self.home / "two").exists())

    def test_default_homes_symlink_retarget_and_missing_directory(self):
        default = self.home / ".codex"
        default.mkdir(mode=0o700)
        self.call("codex", "add", "default", default)
        self.call("claude", "add", "wrong-service", default, ok=False)
        self.call("codex", "add", "child", default / "child", "--create", "--bare", ok=False)
        self.call("codex", "add", "parent", self.home, ok=False)
        directory = self.create()
        moved = self.home / "moved"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.call("codex", "run", "one", ok=False)
        self.assertFalse((moved / "called.json").exists())
        directory.unlink()
        self.call("codex", "run", "one", ok=False)
        self.assertFalse(directory.exists())

    def test_alias_dispatch_and_literal_prompt_after_separator(self):
        directory = self.create("claude")
        result = subprocess.run([str(REPO / "claude-switch"), "account", "run", "one", "--",
                                 "--", "--settings", "a prompt"], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record(directory)["args"], ["--", "--settings", "a prompt"])

    def test_invalid_config_and_symlinked_configuration_do_not_leak(self):
        directory = self.create("claude")
        config = directory / "settings.json"
        config.write_text('{"env": "SECRET" bad}')
        result = self.call("claude", "run", "one", ok=False)
        self.assertNotIn("SECRET", result.stderr)
        config.unlink()
        other = self.root / "shared-settings"
        other.write_text('{}')
        config.symlink_to(other)
        self.call("claude", "run", "one", ok=False)
        self.assertFalse((directory / "called.json").exists())
        config.unlink()
        os.link(other, config)
        self.call("claude", "run", "one", ok=False)

    def test_group_writable_home_is_refused_at_registration_and_launch(self):
        shared = self.home / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        before = list(shared.iterdir())
        self.call("claude", "add", "shared", shared, ok=False)
        self.assertEqual(before, list(shared.iterdir()))
        directory = self.create("claude")
        directory.chmod(0o775)
        result = self.call("claude", "run", "one", ok=False)
        self.assertIn("not writable by group", result.stderr)
        self.assertFalse((directory / "called.json").exists())

    def test_bind_current_refuses_official_binary_and_symlink_directories(self):
        first = self.create("codex", "primary")
        self.call("codex", "add", "primary", first, "--default")
        # 1) Same directory as FLIPAUTH_CODEX_BIN (self.bin/codex-official) is refused.
        result = self.call("codex", "bind-current", self.bin / "codex", ok=False)
        self.assertIn("~/.local/flipauth/bin/codex", result.stderr)

        # 2) Separate directory with an official symlink on PATH is refused (both as symlink target and dir).
        native_dir = self.root / "native-bin"
        native_dir.mkdir()
        release_dir = self.root / "releases"
        release_dir.mkdir()
        real_bin = release_dir / "codex-0.170.0"
        real_bin.write_text(FAKE)
        real_bin.chmod(0o700)
        official_link = native_dir / "codex"
        official_link.symlink_to(real_bin)
        env = {**self.env, "PATH": f"{native_dir}:{self.env['PATH']}"}
        env.pop("FLIPAUTH_CODEX_BIN", None)
        # Clear cached executable in registry by using a fresh registry root.
        env["FLIPAUTH_ACCOUNTS_DIR"] = str(self.root / "registry-iso")
        self.call("codex", "add", "primary", first, "--default", env=env)

        # Target is the official symlink itself.
        r1 = self.call("codex", "bind-current", official_link, env=env, ok=False)
        self.assertIn("~/.local/flipauth/bin/codex", r1.stderr)
        self.assertTrue(official_link.is_symlink())

        # Target is in the resolved release directory.
        r2 = self.call("codex", "bind-current", release_dir / "codex", env=env, ok=False)
        self.assertIn("~/.local/flipauth/bin/codex", r2.stderr)
        self.assertFalse((release_dir / "codex").exists())

        # Target is in a separate directory: allowed and idempotent even when prepended to PATH.
        wrappers = self.root / "flipauth-bin"
        wrappers.mkdir()
        wrapper = wrappers / "codex"
        self.call("codex", "bind-current", wrapper, env=env)
        self.assertTrue(wrapper.is_file())
        env_with_wrapper = {**env, "PATH": f"{wrappers}:{env['PATH']}"}
        self.call("codex", "bind-current", wrapper, env=env_with_wrapper)

    def test_migrate_default_moves_account_preserves_packages_and_leaves_default_fail_closed(self):
        default_dir = self.home / ".codex"
        default_dir.mkdir(mode=0o700)
        (default_dir / "auth.json").write_text("SECRET-NEVER-READ")
        (default_dir / "config.toml").write_text('cli_auth_credentials_store = "file"\n')
        (default_dir / "sessions").mkdir(mode=0o700)
        (default_dir / "sessions" / "s1.jsonl").write_text("{}\n")
        pkg_bin = default_dir / "packages" / "standalone" / "current" / "bin"
        pkg_bin.mkdir(parents=True, mode=0o700)
        (pkg_bin / "codex").write_text("#!/bin/sh\nexit 0\n")
        (pkg_bin / "codex").chmod(0o700)

        # Override fake ps to return empty (no processes running).
        empty_ps = self.root / "empty-ps"
        empty_ps.write_text("#!/bin/sh\nexit 0\n")
        empty_ps.chmod(0o700)
        env = {**self.env, "FLIPAUTH_PS_BIN": str(empty_ps)}

        self.call("codex", "add", "sen", default_dir, "--default", env=env)
        target_dir = self.home / ".codex-sen"

        # Dry-run leaves everything untouched.
        dry = self.call("codex", "migrate-default", "sen", target_dir, "--dry-run", env=env)
        self.assertIn("dry-run:", dry.stdout)
        self.assertFalse(target_dir.exists())
        self.assertTrue((default_dir / "auth.json").is_file())

        # Actual migration moves account state, preserves packages/, updates registry, never reads auth.json.
        res = self.call("codex", "migrate-default", "sen", target_dir, env=env)
        self.assertIn("default_auth.json=absent", res.stdout)
        self.assertNotIn("SECRET", res.stdout + res.stderr)
        self.assertFalse((default_dir / "auth.json").exists())
        self.assertTrue((default_dir / "packages" / "standalone" / "current" / "bin" / "codex").is_file())
        self.assertEqual((target_dir / "auth.json").read_text(), "SECRET-NEVER-READ")
        self.assertTrue((target_dir / "sessions" / "s1.jsonl").is_file())
        self.assertFalse((target_dir / "packages").exists())

        registry = json.loads((self.root / "registry/accounts.json").read_text())
        self.assertEqual(registry["accounts"]["codex"]["sen"]["directory"], str(target_dir))

        # Running again fails because sen is no longer in default home.
        self.call("codex", "migrate-default", "sen", self.home / ".codex-sen2", env=env, ok=False)

    def _codex_default_with_daemon(self, real_name=None):
        # real_name: ~/.codex is a symlink to that directory, while official links
        # keep the literal ~/.codex spelling.
        default_dir = self.home / ".codex"
        if real_name:
            (self.home / real_name).mkdir(mode=0o700)
            default_dir.symlink_to(self.home / real_name)
        else:
            default_dir.mkdir(mode=0o700)
        (default_dir / "auth.json").write_text("SECRET-NEVER-READ")
        (default_dir / "app-server-daemon").mkdir(mode=0o700)
        (default_dir / "app-server-daemon" / "server.pid").write_text("{}\n")
        packages = default_dir / "packages"
        (packages / "standalone" / "current" / "bin").mkdir(parents=True)
        (packages / "standalone" / "current" / "bin" / "codex").write_text("#!/bin/sh\nexit 0\n")
        daemon = packages / "app-server-daemon"
        release = daemon / "releases" / "0.170.0-x86_64-unknown-linux-musl"
        (release / "bin").mkdir(parents=True)
        (release / "bin" / "codex").write_text("#!/bin/sh\nexit 0\n")
        (release / "codex").symlink_to("bin/codex")
        (daemon / "current").symlink_to(release)  # absolute, like official installs
        (daemon / "selection-history").write_text("0.170.0-x86_64-unknown-linux-musl\n")
        (daemon / "auto-update-version").write_text("0.170.0-x86_64-unknown-linux-musl\n")
        empty_ps = self.root / "empty-ps"
        empty_ps.write_text("#!/bin/sh\nexit 0\n")
        empty_ps.chmod(0o700)
        env = {**self.env, "FLIPAUTH_PS_BIN": str(empty_ps)}
        self.call("codex", "add", "sen", default_dir, "--default", env=env)
        return default_dir, daemon, env

    def test_migrate_default_moves_daemon_package_and_keeps_only_standalone(self):
        default_dir, daemon, env = self._codex_default_with_daemon()
        target_dir = self.home / ".codex-sen"

        dry = self.call("codex", "migrate-default", "sen", target_dir, "--dry-run", env=env)
        self.assertIn("moving packages/app-server-daemon", dry.stdout)
        self.assertIn("keeping packages/standalone", dry.stdout)
        self.assertFalse(target_dir.exists())
        self.assertTrue(daemon.is_dir())

        res = self.call("codex", "migrate-default", "sen", target_dir, env=env)
        self.assertIn("kept_in_default=packages/standalone", res.stdout)
        self.assertEqual(sorted(p.name for p in (default_dir / "packages").iterdir()), ["standalone"])
        self.assertEqual(sorted(p.name for p in default_dir.iterdir()), ["packages"])
        new_daemon = target_dir / "packages" / "app-server-daemon"
        release = new_daemon / "releases" / "0.170.0-x86_64-unknown-linux-musl"
        self.assertEqual(os.readlink(new_daemon / "current"), str(release))
        self.assertTrue((new_daemon / "current" / "bin" / "codex").is_file())
        self.assertEqual(os.readlink(release / "codex"), "bin/codex")
        self.assertEqual((new_daemon / "selection-history").read_text(), "0.170.0-x86_64-unknown-linux-musl\n")
        self.assertTrue((new_daemon / "auto-update-version").is_file())
        self.assertTrue((target_dir / "app-server-daemon" / "server.pid").is_file())
        self.assertEqual((target_dir / "auth.json").read_text(), "SECRET-NEVER-READ")

    def test_migrate_default_refuses_unsafe_codex_packages_before_moving(self):
        default_dir, daemon, env = self._codex_default_with_daemon()
        target_dir = self.home / ".codex-sen"
        # A daemon symlink escaping into another part of the old home cannot be rewritten safely.
        (daemon / "stray").symlink_to(default_dir / "packages" / "standalone")
        res = self.call("codex", "migrate-default", "sen", target_dir, env=env, ok=False)
        self.assertIn("cannot rewrite safely", res.stderr)
        self.assertFalse(target_dir.exists())
        self.assertTrue((default_dir / "auth.json").is_file())
        (daemon / "stray").unlink()
        # Unknown package kinds: ownership unknown, so refuse rather than guess.
        (default_dir / "packages" / "mystery").mkdir()
        res = self.call("codex", "migrate-default", "sen", target_dir, env=env, ok=False)
        self.assertIn("unknown Codex packages", res.stderr)
        self.assertFalse(target_dir.exists())
        self.assertTrue((default_dir / "auth.json").is_file())

    def _migration_snapshot(self, default_dir):
        daemon = default_dir / "packages" / "app-server-daemon"
        return (sorted(p.name for p in default_dir.iterdir()),
                sorted(str(p.relative_to(daemon)) for p in daemon.rglob("*")),
                os.readlink(daemon / "current"),
                (default_dir / "auth.json").read_text(),
                (self.root / "registry/accounts.json").read_text())

    def _assert_migrated(self, target_dir):
        new_daemon = target_dir / "packages" / "app-server-daemon"
        self.assertTrue((new_daemon / "current" / "bin" / "codex").is_file())
        self.assertTrue(str(Path(os.path.realpath(new_daemon / "current"))).startswith(str(target_dir)))
        self.assertEqual((target_dir / "auth.json").read_text(), "SECRET-NEVER-READ")
        registry = json.loads((self.root / "registry/accounts.json").read_text())
        self.assertEqual(registry["accounts"]["codex"]["sen"]["directory"], str(target_dir))

    def test_migrate_default_unwritable_old_packages_moves_nothing_and_rerun_succeeds(self):
        default_dir, daemon, env = self._codex_default_with_daemon()
        target_dir = self.home / ".codex-sen"
        before = self._migration_snapshot(default_dir)
        packages = default_dir / "packages"
        packages.chmod(0o500)
        self.addCleanup(packages.chmod, 0o700)
        res = self.call("codex", "migrate-default", "sen", target_dir, env=env, ok=False)
        self.assertIn("nothing", res.stderr)
        self.assertFalse(target_dir.exists())
        self.assertEqual(self._migration_snapshot(default_dir), before)
        packages.chmod(0o700)
        self.call("codex", "migrate-default", "sen", target_dir, env=env)
        self._assert_migrated(target_dir)

    def test_migrate_default_ignores_a_preexisting_staging_name(self):
        default_dir, daemon, env = self._codex_default_with_daemon()
        (daemon / "current.flipauth-tmp").write_text("not ours\n")
        target_dir = self.home / ".codex-sen"
        self.call("codex", "migrate-default", "sen", target_dir, env=env)
        self._assert_migrated(target_dir)
        new_daemon = target_dir / "packages" / "app-server-daemon"
        self.assertEqual((new_daemon / "current.flipauth-tmp").read_text(), "not ours\n")
        self.assertEqual([p.name for p in new_daemon.iterdir() if ".flipauth-" in p.name and p.name.startswith(".")], [])

    def test_migrate_default_registry_write_failure_rolls_back_every_move(self):
        default_dir, daemon, env = self._codex_default_with_daemon()
        target_dir = self.home / ".codex-sen"
        # Dry-run creates the lock files, so only the atomic registry write fails.
        self.call("codex", "migrate-default", "sen", target_dir, "--dry-run", env=env)
        before = self._migration_snapshot(default_dir)
        registry_dir = self.root / "registry"
        registry_dir.chmod(0o500)
        self.addCleanup(registry_dir.chmod, 0o700)
        res = self.call("codex", "migrate-default", "sen", target_dir, env=env, ok=False)
        self.assertIn("rolled back, nothing changed", res.stderr)
        self.assertFalse(target_dir.exists())
        self.assertEqual(self._migration_snapshot(default_dir), before)
        registry_dir.chmod(0o700)
        self.call("codex", "migrate-default", "sen", target_dir, env=env)
        self._assert_migrated(target_dir)

    def test_migrate_default_symlinked_default_home_rewrites_literal_links(self):
        default_dir, daemon, env = self._codex_default_with_daemon(real_name="codex-real")
        self.assertTrue(os.readlink(default_dir / "packages/app-server-daemon/current").startswith(str(default_dir) + "/"))
        target_dir = self.home / ".codex-sen"
        self.call("codex", "migrate-default", "sen", target_dir, env=env)
        self._assert_migrated(target_dir)
        self.assertEqual(sorted(p.name for p in (default_dir / "packages").iterdir()), ["standalone"])

    def test_migrate_default_refuses_daemon_links_it_cannot_carry(self):
        target_dir = self.home / ".codex-sen"
        cases = {
            "absolute-root": lambda d, home: (d / "root-link").symlink_to(home),
            "relative-escape": lambda d, home: (d / "rel-link").symlink_to("../standalone"),
        }
        def unreadable_subdir(d, home):
            # A link inside an unreadable subdirectory cannot be checked.
            locked = d / "releases" / "locked"
            locked.mkdir()
            (locked / "abs").symlink_to(home / "packages" / "standalone")
            locked.chmod(0o000)

        cases = {
            "absolute-root": lambda d, home: (d / "root-link").symlink_to(home),
            "relative-escape": lambda d, home: (d / "rel-link").symlink_to("../standalone"),
            "unreadable-subdir": unreadable_subdir,
        }
        for label, plant in cases.items():
            with self.subTest(label):
                default_dir, daemon, env = self._codex_default_with_daemon()
                try:
                    plant(daemon, default_dir)
                    res = self.call("codex", "migrate-default", "sen", target_dir, env=env, ok=False)
                    self.assertIn("nothing moved", res.stderr)
                    self.assertFalse(target_dir.exists())
                    self.assertTrue((default_dir / "auth.json").is_file())
                    self.assertTrue((daemon / "current" / "bin" / "codex").is_file())
                finally:
                    subprocess.run(["chmod", "-R", "u+rwx", str(self.home)], check=True)
                    subprocess.run(["rm", "-rf", str(default_dir), str(target_dir),
                                    str(self.root / "registry")], check=True)

    def test_deploy_current_script_installs_checks_and_migrates_legacy_wrapper(self):
        first = self.create("codex", "primary")
        self.call("codex", "add", "primary", first, "--default")
        claude_home = self.create("claude", "main")
        self.call("claude", "add", "main", claude_home, "--default")

        local_bin = self.home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        # Legacy bind-current wrapper left in ~/.local/bin/codex (like halmi-home).
        legacy_codex = local_bin / "codex"
        legacy_codex.write_text("#!/bin/sh\n# flipauth current launcher v1\nexec true\n")
        legacy_codex.chmod(0o700)
        # Real official symlink in ~/.local/bin/claude must never be moved or deleted.
        official_claude = local_bin / "claude"
        official_claude.symlink_to(self.bin / "claude-official")

        (self.home / ".bashrc").write_text("# existing bashrc\n")
        (self.home / ".profile").write_text("# existing profile\n")

        empty_ps = self.root / "empty-ps"
        empty_ps.write_text("#!/bin/sh\nexit 0\n")
        empty_ps.chmod(0o700)
        env = {**self.env, "FLIPAUTH_PS_BIN": str(empty_ps)}
        script = REPO / "scripts/deploy-current.sh"

        # --check fails before deployment and modifies nothing.
        pre = subprocess.run(["bash", str(script), "--check"], env=env, capture_output=True, text=True)
        self.assertNotEqual(pre.returncode, 0)
        self.assertIn("legacy bind-current wrapper", pre.stderr)
        self.assertTrue(legacy_codex.is_file())
        self.assertFalse((self.home / ".local/flipauth/bin/codex").exists())
        self.assertEqual((self.home / ".bashrc").read_text(), "# existing bashrc\n")

        # Apply deploys both wrappers, migrates legacy codex wrapper, keeps official claude symlink, updates rc files.
        apply_res = subprocess.run(["bash", str(script), "all"], env=env, capture_output=True, text=True)
        self.assertEqual(apply_res.returncode, 0, apply_res.stderr)
        self.assertTrue((self.home / ".local/flipauth/bin/codex").is_file())
        self.assertTrue((self.home / ".local/flipauth/bin/claude").is_file())
        self.assertFalse(legacy_codex.exists())
        backups = list((self.root / "registry/launcher-backups").glob("*/codex"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(official_claude.is_symlink())
        bashrc_once = (self.home / ".bashrc").read_text()
        profile_once = (self.home / ".profile").read_text()
        self.assertIn("$HOME/.local/flipauth/bin", bashrc_once)
        self.assertIn("$HOME/.local/flipauth/bin", profile_once)

        # Idempotent re-run does not duplicate PATH blocks.
        apply_again = subprocess.run(["bash", str(script), "all"], env=env, capture_output=True, text=True)
        self.assertEqual(apply_again.returncode, 0, apply_again.stderr)
        self.assertEqual((self.home / ".bashrc").read_text(), bashrc_once)
        self.assertEqual((self.home / ".profile").read_text(), profile_once)

        # --check now passes cleanly.
        post = subprocess.run(["bash", str(script), "--check"], env=env, capture_output=True, text=True)
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertIn("verified: " + str(self.home / ".local/flipauth/bin/codex"), post.stdout)
        self.assertIn("verified: " + str(self.home / ".local/flipauth/bin/claude"), post.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
