"""One-shot, receipted Herdr shutdown/restart. Never migrates credentials."""

import contextlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time

import directory_accounts as accounts

from process_state import (home_of, identity, process_environment, processes,
                           daemon_stop_order, verified_daemons)


class Herdr:
    def __init__(self):
        self.binary = os.environ.get("FLIPAUTH_HERDR_BIN", "herdr")

    def call(self, session, *arguments):
        command = [self.binary]
        if session is not None:
            command += ["--session", session]
        try:
            result = subprocess.run([*command, *arguments], capture_output=True, text=True, timeout=5)
            if result.returncode:
                accounts.refuse("Herdr command failed; inspect receipt before retrying")
            return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, ValueError):
            accounts.refuse("Herdr receipt unavailable; action outcome needs readback")

    def snapshot(self, session):
        return self.call(session, "api", "snapshot")["result"]["snapshot"]

    def foreground(self, session, pane):
        return self.call(session, "pane", "process-info", "--pane", pane)["result"]["process_info"]

    def plan(self, service, running):
        targets = []
        covered = set()
        for session in self.call(None, "session", "list", "--json")["sessions"]:
            if not session["running"]:
                continue
            snapshot = self.snapshot(session["name"])
            for agent in snapshot["agents"]:
                if agent.get("agent") != service:
                    continue
                pane = agent["pane_id"]
                info = self.foreground(session["name"], pane)
                matched = [p for p in info["foreground_processes"] if p.get("pid") in running]
                if not matched and not any(p.get("name") == service for p in info["foreground_processes"]):
                    continue
                if len(matched) != 1:
                    accounts.refuse("cannot associate each CLI pane with exactly one live process")
                process = matched[0]
                pid = process["pid"]
                if pid in covered:
                    accounts.refuse("one process appears in multiple panes")
                cwd = accounts.local_path(process.get("cwd") or agent.get("foreground_cwd") or agent["cwd"])
                if not cwd.is_dir():
                    accounts.refuse("restart working directory no longer exists")
                start = identity(pid)
                if start is None:
                    accounts.refuse("CLI exited during preflight; no sessions stopped, retry from a shell")
                targets.append({"session": session["name"], "pane": pane, "pid": pid,
                                "start": start, "cwd": str(cwd), "state": "planned"})
                covered.add(pid)
        return targets, covered

    def still_original(self, target, service):
        info = self.foreground(target["session"], target["pane"])
        pids = {p.get("pid") for p in info["foreground_processes"]}
        if target["pid"] not in processes(service):
            return False
        start = identity(target["pid"])
        if start is None:
            return False
        if target["pid"] not in pids or start != target["start"]:
            accounts.refuse("pane/process ownership changed during switch")
        return True

    def exit(self, target, service, timeout):
        if not self.still_original(target, service):
            return
        # Cancellation applies to working, idle and blocked states alike. Never answer
        # an approval dialog. No retry if delivery has an uncertain outcome.
        try:
            self.call(target["session"], "agent", "send-keys", target["pane"], "ctrl+c")
        except accounts.Refused:
            target["cancel_receipt"] = "unconfirmed"
        deadline = time.monotonic() + timeout
        sent_exit = False
        while time.monotonic() < deadline:
            if not self.still_original(target, service):
                return
            agents = self.snapshot(target["session"])["agents"]
            state = next((a.get("agent_status") for a in agents if a.get("pane_id") == target["pane"]), None)
            if state in {"idle", "done"} and not sent_exit:
                sent_exit = True
                try:
                    self.call(target["session"], "agent", "prompt", target["pane"], "/exit")
                except accounts.Refused:
                    target["exit_receipt"] = "unconfirmed"
            time.sleep(.1)
        accounts.refuse("CLI did not exit after cancellation; no target account started")


def wait_for_launch(herdr, target, service, directory, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = herdr.foreground(target["session"], target["pane"])
        observed = processes(service)
        for proc in info["foreground_processes"]:
            pid = proc.get("pid")
            fact = observed.get(pid)
            if fact and Path(fact["home"]).resolve() == Path(directory).resolve():
                target["new_pid"] = pid
                target["new_start"] = fact["start"]
                return
        time.sleep(.1)
    accounts.refuse("restart admission observed, but target-home process not confirmed; do not blindly retry")


def verify_restarted_targets(herdr, targets, service, directory):
    """Perform a final sweep of every pane and reject extra service processes."""
    observed = processes(service)
    expected_home = Path(directory).resolve()
    expected_pids = {target.get("new_pid") for target in targets}
    if set(observed) - expected_pids:
        accounts.refuse("extra same-service process remains; inspect receipt before retrying")
    for target in targets:
        pid = target.get("new_pid")
        fact = observed.get(pid)
        if (fact is None or fact["start"] != target.get("new_start") or
                Path(fact["home"]).resolve() != expected_home):
            accounts.refuse("restart target changed before completion; inspect receipt before retrying")
        info = herdr.foreground(target["session"], target["pane"])
        if not any(row.get("pid") == pid for row in info.get("foreground_processes", [])):
            accounts.refuse("restart pane changed before completion; inspect receipt before retrying")


def run_worker(service, script, root, receipt):
    from short_commands import arguments, receipt_write, require_login, select
    record = json.loads(receipt.read_text())
    try:
        timeout = float(os.environ.get("FLIPAUTH_SWITCH_STOP_TIMEOUT", "15"))
        if not 0 < timeout <= 60:
            accounts.refuse("switch timeout must be between 0 and 60 seconds")
        # Parent retains the same lock through worker creation and receipt write.
        with accounts.service_lock(root, service + "-operation", exclusive=True), contextlib.ExitStack() as gate:
            gate.enter_context(accounts.service_lock(root, service, exclusive=True))
            record = json.loads(receipt.read_text())
            record["state"] = "checking"
            receipt_write(receipt, record)
            data = accounts.load_registry(root)
            label = record["target"]
            args = arguments(label, values=record["arguments"])
            plan = accounts.prepare_launch(service, script, data, args)
            binary = plan.executable
            directory = require_login(service, data, label)
            running = processes(service)
            herdr = Herdr()
            targets, covered = herdr.plan(service, running)
            daemons = verified_daemons(service, root)
            if daemons - set(running):
                accounts.refuse("managed daemon appeared during preflight; no sessions stopped")
            daemon_starts = {pid: running[pid]["start"] for pid in daemons}
            if set(running) - covered - daemons:
                accounts.refuse("unmanaged same-service CLI found; all sessions left untouched")
            if not targets:
                accounts.refuse("no restartable CLI pane; selection unchanged; launch directly: " +
                                "flipauth " + service + " account run " + shlex.quote(label) + " --" +
                                "; existing background processes are left untouched")
            for target in targets:
                environment = process_environment(target["pid"])
                if any(environment.get(key.encode()) for key in accounts.ENV_CONFLICTS[service]):
                    accounts.refuse("a target pane has authentication/state overrides; review them before switching")
            previous = data.get("selected", {}).get(service) or data.get("defaults", {}).get(service)
            if (previous == label and not daemons and
                    all(home_of(t["pid"], service) == directory for t in targets)):
                record["state"] = "already-selected"
                receipt_write(receipt, record)
                return
            record["panes"] = targets
            record["state"] = "stopping"
            receipt_write(receipt, record)
            for target in targets:
                herdr.exit(target, service, timeout)
                target["state"] = "stopped"
                receipt_write(receipt, record)
            remaining = processes(service)
            fresh = verified_daemons(service, root)
            if set(remaining) - fresh or fresh - daemons:
                accounts.refuse("unexpected same-service process appeared; selection unchanged")
            for pid in daemon_stop_order(daemons & set(remaining), remaining):
                start = identity(pid)
                if start is None:
                    continue
                if start != daemon_starts[pid]:
                    accounts.refuse("daemon PID changed since preflight; no signal sent")
                fresh = verified_daemons(service, root)
                current = identity(pid)
                if current is None:
                    continue
                if pid not in fresh or current != start:
                    accounts.refuse("managed daemon identity changed; no restart")
                try:
                    fd = os.pidfd_open(pid)
                except ProcessLookupError:
                    continue
                try:
                    current = identity(pid)
                    if current is None:
                        continue
                    if current != start:
                        accounts.refuse("daemon PID reused; no signal sent")
                    try:
                        signal.pidfd_send_signal(fd, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                finally:
                    os.close(fd)
            deadline = time.monotonic() + timeout
            while processes(service) and time.monotonic() < deadline:
                time.sleep(.1)
            if processes(service):
                accounts.refuse("same-service processes remain; no restart")
            # Ensure each destination shell is the only foreground process before
            # admitting any shell command. A newly opened editor must not receive it.
            for target in targets:
                info = herdr.foreground(target["session"], target["pane"])
                if not info["foreground_processes"] or any(p.get("pid") != info["shell_pid"] for p in info["foreground_processes"]):
                    accounts.refuse("pane is not back at its shell; no restart commands sent")
            select(root, service, label)
            record["state"] = "starting"
            receipt_write(receipt, record)
            # Keep the operation mutex while allowing new target-home CLI startups.
            gate.close()
            for target in targets:
                info = herdr.foreground(target["session"], target["pane"])
                if not info["foreground_processes"] or any(p.get("pid") != info["shell_pid"] for p in info["foreground_processes"]):
                    accounts.refuse("pane foreground changed before restart submission")
                command = ("cd -- " + shlex.quote(target["cwd"]) + " && " +
                           " ".join(map(shlex.quote, ["env", "FLIPAUTH_ACCOUNTS_DIR=" + str(root),
                              "FLIPAUTH_" + service.upper() + "_BIN=" + str(binary),
                              str(script), service, "account", "run", label, "--", *record["arguments"]])))
                target["state"] = "submitting"
                receipt_write(receipt, record)
                try:
                    herdr.call(target["session"], "pane", "run", target["pane"], command)
                    target["state"] = "admitted"
                except accounts.Refused:
                    target["state"] = "admission-unconfirmed"
                receipt_write(receipt, record)
                wait_for_launch(herdr, target, service, directory, timeout)
                target["state"] = "home-verified"
                receipt_write(receipt, record)
            verify_restarted_targets(herdr, targets, service, directory)
            record["state"] = "complete"
            receipt_write(receipt, record)
    except (accounts.Refused, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        record["state"] = "failed"
        # Our own errors never include CLI output, config values or credential data.
        record["error"] = str(exc) if isinstance(exc, accounts.Refused) else type(exc).__name__
        receipt_write(receipt, record)
