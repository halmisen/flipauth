#!/usr/bin/env python3
"""Observe isolated fake CLI processes without conflating preference and identity."""

import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("short_tests", Path(__file__).with_name("short-commands-test.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class Observation(unittest.TestCase):
    setUpBase = fixtures.ShortCommands.setUpBase
    setUp = fixtures.ShortCommands.setUp
    call = fixtures.ShortCommands.call
    create = fixtures.ShortCommands.create
    record = fixtures.ShortCommands.record
    wait_file = fixtures.ShortCommands.wait_file
    state = fixtures.ShortCommands.state
    cleanup_processes = fixtures.ShortCommands.cleanup_processes
    short = fixtures.ShortCommands.short
    setup_accounts = fixtures.ShortCommands.setup_accounts
    start = fixtures.ShortCommands.start
    pump_terminals = fixtures.ShortCommands.pump_terminals
    stop_pump = fixtures.ShortCommands.stop_pump
    locked_state = fixtures.ShortCommands.locked_state

    def test_status_observes_other_home_without_changing_selection_or_credentials(self):
        first, second = self.setup_accounts()
        original = (first / "auth.json").read_bytes()
        process = self.start("other", "codex", second)
        registry = self.root / "registry/accounts.json"
        before = registry.read_bytes()
        report = json.loads(self.short("cod", "status", "--json").stdout)
        self.assertEqual(report["selected"], "primary")
        self.assertFalse(report["selection_matches_processes"])
        self.assertEqual([(p["pid"], p["account"], p["home"]) for p in report["processes"] if p["role"] == "cli"],
                         [(process.pid, "secondary", str(second))])
        self.assertEqual(len(report["processes"]), 3)  # CLI plus native server/updater stand-ins.
        self.assertEqual(report["identity"], "unverified")
        self.assertIn("selection differs", self.short("cod", "status").stdout)
        status_text = self.short("cod", "status").stdout
        self.assertIn("will refuse by default", status_text)
        self.assertIn("--replace", status_text)
        self.assertEqual(before, registry.read_bytes())
        self.assertEqual(original, (first / "auth.json").read_bytes())
        self.assertIsNone(process.poll())

    def test_status_reports_whether_plain_cli_on_path_follows_selection(self):
        self.setup_accounts()
        before = json.loads(self.short("cod", "status", "--json").stdout)
        self.assertEqual(before["plain_cli"], {"path": str(self.bin / "codex"), "follows_selection": False})
        self.assertIn("Current PATH entry does not follow selection", self.short("cod", "status").stdout)

        wrappers = self.root / "wrappers"
        wrappers.mkdir()
        wrapper = wrappers / "codex"
        self.call("codex", "bind-current", wrapper)
        saved_path = self.env["PATH"]
        self.env["PATH"] = str(wrappers) + ":" + saved_path
        try:
            after = json.loads(self.short("cod", "status", "--json").stdout)
            self.assertEqual(after["plain_cli"], {"path": str(wrapper), "follows_selection": True})
            text = self.short("cod", "status").stdout
            self.assertIn(f"Plain codex on PATH: {wrapper} (follows selection via bind-current)", text)
        finally:
            self.env["PATH"] = saved_path
        self.assertFalse((self.home / "tripwire").exists())

    def test_empty_process_list_is_not_a_verified_match_and_dead_worker_is_visible(self):
        self.setup_accounts()
        jobs = self.root / "registry/switches"
        jobs.mkdir()
        # A PID outside Linux's valid range cannot accidentally be a real peer.
        (jobs / "codex-lost.json").write_text(json.dumps({
            "state": "starting", "target": "secondary", "worker_pid": 2 ** 40, "worker_start": 1}))
        report = json.loads(self.short("cod", "status", "--json").stdout)
        self.assertEqual(report["processes"], [])
        self.assertIsNone(report["selection_matches_processes"])
        self.assertFalse(report["last_switch"]["worker_alive"])
        self.assertIn("worker is no longer running", self.short("cod", "status").stdout)
        self.assertEqual(json.loads((jobs / "codex-lost.json").read_text())["state"], "starting")

    def test_unreadable_receipt_does_not_hide_process_observation(self):
        first, _ = self.setup_accounts()
        process = self.start("one", "codex", first)
        jobs = self.root / "registry/switches"
        jobs.mkdir()
        (jobs / "codex-corrupt.json").write_text("broken")
        report = json.loads(self.short("cod", "status", "--json").stdout)
        self.assertEqual(report["last_switch"]["state"], "unreadable")
        self.assertEqual(report["processes"][0]["pid"], process.pid)
        self.assertTrue(report["selection_matches_processes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
