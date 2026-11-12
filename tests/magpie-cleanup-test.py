#!/usr/bin/env python3
"""Exercise the manual archive script only in disposable homes with fake processes/services."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cleanup-magpie.sh"


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="magpie-cleanup-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name)
        self.home = self.root / "home"
        self.source = self.home / ".config/magpie"
        self.source.mkdir(parents=True, mode=0o700)
        (self.source / "logins.json").write_text("PRIVATE_FIXTURE")
        self.codex = self.home / ".codex/auth.json"
        self.codex.parent.mkdir()
        self.codex.write_text("KEEP_CODEX_FIXTURE")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool, body in (("ps", "exit 0"), ("systemctl", "exit 0")):
            self.stub(tool, body)
        self.env = {**os.environ, "MAGPIE_CLEANUP_HOME": str(self.home),
                    "PATH": str(self.bin) + ":" + os.environ["PATH"]}

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o700)

    def call(self, *args):
        result = subprocess.run(["bash", str(SCRIPT), *args], env=self.env, capture_output=True, text=True)
        self.assertNotIn("PRIVATE_FIXTURE", result.stdout + result.stderr)
        return result

    def test_preview_does_not_write(self):
        self.assertEqual(self.call().returncode, 0)
        self.assertTrue(self.source.is_dir())
        self.assertFalse((self.home / ".local").exists())

    def test_apply_moves_exact_directory_and_repeat_is_noop(self):
        inode = (self.source / "logins.json").stat().st_ino
        result = self.call("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.source.exists())
        root = self.home / ".local/state/flipauth-cleanup"
        backups = list(root.glob("magpie-*"))
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        self.assertEqual((backup / "config/logins.json").stat().st_ino, inode)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / "manifest.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.codex.read_text(), "KEEP_CODEX_FIXTURE")
        self.assertEqual(self.call("--apply").returncode, 0)
        self.assertEqual(len(list(root.glob("magpie-*"))), 1)

    def test_live_process_blocks_before_move(self):
        for process in ("codex", "magpie", "magpie-web"):
            with self.subTest(process=process):
                self.stub("ps", "printf '%s\\n' '123 " + process + " " + process + "'")
                self.assertNotEqual(self.call("--apply").returncode, 0)
                self.assertTrue(self.source.exists())
                self.assertFalse((self.home / ".local").exists())

    def test_service_or_failed_inspection_blocks(self):
        for body in ("printf '%s\\n' 'magpie-web.service enabled'", "exit 1"):
            self.stub("systemctl", body)
            self.assertNotEqual(self.call("--apply").returncode, 0)
            self.assertTrue(self.source.exists())

    def test_installed_binary_blocks(self):
        self.stub("magpie", "exit 0")
        self.assertNotEqual(self.call("--apply").returncode, 0)
        self.assertTrue(self.source.exists())

    def test_linked_source_is_refused(self):
        target = self.home / "elsewhere"
        self.source.rename(target)
        self.source.symlink_to(target, target_is_directory=True)
        self.assertNotEqual(self.call("--apply").returncode, 0)
        self.assertEqual((target / "logins.json").read_text(), "PRIVATE_FIXTURE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
