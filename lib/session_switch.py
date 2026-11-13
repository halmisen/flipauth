"""Replace same-service CLIs, stop the old daemon, then return to the caller's terminal.

Only the official CLI owns authentication. No background switch worker, pane
relaunch, conversation resume, credential copy or SIGKILL is involved.

Codex restores its terminal (raw mode, alternate screen, focus/paste/mouse
reporting) only when it quits from its own keyboard input; every external signal
kills it with those modes still enabled in the old terminal. Codex CLIs are
therefore closed with Ctrl+C delivered through Herdr's supported key API, and a
Codex CLI outside a Herdr pane is refused before anything is stopped. Claude
restores its terminal on SIGTERM, so Claude CLIs keep the pidfd path.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import time

import directory_accounts as accounts
from process_state import (ancestor_pids, daemon_stop_order, identity,
                           processes, verified_daemons)


def terminate(pid, start, timeout):
    """Signal exactly the admitted process birth, then wait for its exit."""
    current = identity(pid)
    if current is None:
        return
    if current != start:
        accounts.refuse("process PID changed since preflight; no signal sent")
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        current = identity(pid)
        if current is None:
            return
        if current != start:
            accounts.refuse("process PID reused; no signal sent")
        try:
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        except ProcessLookupError:
            pass
    finally:
        os.close(fd)
    deadline = time.monotonic() + timeout
    while identity(pid) == start and time.monotonic() < deadline:
        time.sleep(.05)
    if identity(pid) is not None:
        accounts.refuse("process did not exit; no new CLI started")


# Services whose interactive CLI must quit in-band to restore its terminal.
IN_BAND_EXIT = {"codex"}
KEY_INTERVAL = .5


class Herdr:
    """Herdr CLI access. Only pane lookup and supported key delivery are used."""

    def __init__(self):
        self.binary = os.environ.get("FLIPAUTH_HERDR_BIN", "herdr")

    def call(self, session, *arguments):
        command = [self.binary] + (["--session", session] if session is not None else [])
        try:
            result = subprocess.run([*command, *arguments], capture_output=True, text=True,
                                    timeout=5, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            accounts.refuse("Herdr unavailable; Codex CLIs left untouched")
        if result.returncode:
            accounts.refuse("Herdr command failed; inspect receipt before retrying")
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except ValueError:
            accounts.refuse("Herdr returned unreadable output; inspect receipt before retrying")

    def foreground(self, session, pane):
        info = self.call(session, "pane", "process-info", "--pane", pane)["result"]["process_info"]
        return {row.get("pid") for row in info.get("foreground_processes", [])}

    def locate(self, pids):
        """Map each CLI PID to exactly one (session, pane) whose foreground holds it."""
        found = {}
        for session in self.call(None, "session", "list", "--json").get("sessions", []):
            if not session.get("running"):
                continue
            name = session["name"]
            snapshot = self.call(name, "api", "snapshot")["result"]["snapshot"]
            for pane in snapshot.get("panes", []):
                for pid in self.foreground(name, pane["pane_id"]) & set(pids):
                    if pid in found:
                        accounts.refuse("one CLI appears in several Herdr panes; all sessions left untouched")
                    found[pid] = {"session": name, "pane": pane["pane_id"]}
        return found

    def send_ctrl_c(self, target):
        # Agent input (unlike pane input) is rejected by Herdr when the detected agent
        # no longer controls the pane, narrowing the check-then-send window.
        self.call(target["session"], "agent", "send-keys", target["pane"], "ctrl+c")


def locate_in_band(service, clients):
    """Preflight: every CLI that must quit in-band needs a Herdr pane first."""
    if service not in IN_BAND_EXIT or not clients:
        return {}
    found = Herdr().locate(clients)
    if set(clients) - set(found):
        accounts.refuse("a Codex CLI runs outside Herdr and would leave its terminal broken if "
                        "signaled; exit it with Ctrl+C, then retry; all sessions left untouched")
    return found


def exit_in_band(clients, timeout, changed=lambda: None):
    """Quit TUIs from their own input so they restore their terminals. Never signals them.

    Ctrl+C goes to every pending pane each round, so several sessions close in
    parallel. Ctrl+C interrupts a running turn or clears a draft, and a repeated
    Ctrl+C quits. It is the only key sent; its effect on an approval overlay is
    expected to be rejection but is not yet observed.
    """
    herdr = Herdr()
    deadline = time.monotonic() + timeout

    def alive(client):
        return identity(client["pid"]) == client["start"]

    def settle(group):
        remaining = []
        for client in group:
            if alive(client):
                remaining.append(client)
            elif client["state"] != "exited":
                client["state"] = "exited"
                changed()
        return remaining

    pending = settle(clients)
    while pending and time.monotonic() < deadline:
        for client in pending:
            if not alive(client):
                continue
            foreground = herdr.foreground(client["session"], client["pane"])
            # The foreground sample may predate an exit: recheck the birth right before sending.
            if not alive(client):
                continue
            if client["pid"] not in foreground:
                accounts.refuse("pane/process ownership changed; no keys sent")
            client["key_delivery"] = "unconfirmed"
            herdr.send_ctrl_c(client)
            client["key_delivery"] = "acknowledged"
            client["keys_sent"] = client.get("keys_sent", 0) + 1
        pause = time.monotonic() + KEY_INTERVAL
        while any(alive(client) for client in pending) and time.monotonic() < pause:
            time.sleep(.05)
        pending = settle(pending)
    if pending:
        accounts.refuse("CLI did not quit after Ctrl+C; no signal sent and no new CLI started")
    for client in clients:
        while client["pid"] in herdr.foreground(client["session"], client["pane"]):
            if time.monotonic() >= deadline:
                accounts.refuse("old pane did not return to its shell; no new CLI started")
            time.sleep(.05)


def stop_managed_daemons(service, root, daemon_starts, timeout):
    remaining = processes(service)
    fresh = verified_daemons(service, root)
    if set(remaining) - fresh or fresh - set(daemon_starts):
        accounts.refuse("unexpected same-service process appeared; selection unchanged")
    for pid in daemon_stop_order(set(daemon_starts) & set(remaining), remaining):
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
        terminate(pid, start, timeout)
    deadline = time.monotonic() + timeout
    while processes(service) and time.monotonic() < deadline:
        time.sleep(.1)
    if processes(service):
        accounts.refuse("same-service processes remain; no restart")


def switch_timeout():
    timeout = float(os.environ.get("FLIPAUTH_SWITCH_STOP_TIMEOUT", "15"))
    if not 0 < timeout <= 60:
        accounts.refuse("switch timeout must be between 0 and 60 seconds")
    return timeout


def replace_processes(plan, root, record, receipt):
    """Preflight the whole service before sending the first termination signal."""
    from short_commands import receipt_write
    timeout = switch_timeout()
    service = plan.service
    data = accounts.load_registry(root)
    running = processes(service)
    daemons = verified_daemons(service, root)
    if daemons - set(running):
        accounts.refuse("managed daemon appeared during preflight; no sessions stopped")
    if set(running) & ancestor_pids():
        accounts.refuse("switch must run in a separate terminal, outside a running CLI")
    allowed = {str(Path.home() / ("." + service))}
    allowed.update(entry["directory"] for entry in data["accounts"][service].values())
    clients = {pid: fact for pid, fact in running.items() if pid not in daemons}
    for fact in clients.values():
        if fact["home"] not in allowed:
            accounts.refuse("unregistered CLI home; all sessions left untouched")
        if any(fact["environment"].get(key.encode()) for key in accounts.ENV_CONFLICTS[service]):
            accounts.refuse("a running CLI has authentication/state overrides; all sessions left untouched")
        command = fact["command"]
        options = command[:command.index("--")] if "--" in command else command
        if any(argument in {"app-server", "remote-control"} for argument in options):
            accounts.refuse("unmanaged background server found; all sessions left untouched")
    panes = locate_in_band(service, clients)
    # All births must still match before any admitted client is stopped.
    if any(identity(pid) not in (None, fact["start"]) for pid, fact in running.items()):
        accounts.refuse("process birth changed during preflight; all sessions left untouched")
    record["stopped_cli"] = [{"pid": pid, "start": fact["start"], "home": fact["home"],
                              "state": "planned", **({"exit": "ctrl+c", **panes[pid]}
                                                     if pid in panes else {"exit": "SIGTERM"})}
                             for pid, fact in clients.items()]
    record["stopped_daemon"] = [{"pid": pid, "start": running[pid]["start"],
                                 "home": running[pid]["home"], "state": "planned"} for pid in daemons]
    record["state"] = "stopping"
    receipt_write(receipt, record)
    try:
        in_band = [client for client in record["stopped_cli"] if client["exit"] == "ctrl+c"]
        exit_in_band(in_band, timeout, lambda: receipt_write(receipt, record))
        for client in record["stopped_cli"]:
            if client["exit"] != "ctrl+c":
                terminate(client["pid"], client["start"], timeout)
            client["state"] = "exited"
            receipt_write(receipt, record)
        stop_managed_daemons(service, root,
                             {pid: running[pid]["start"] for pid in daemons}, timeout)
    finally:
        reconcile(record)
        receipt_write(receipt, record)


def reconcile(record):
    """Record each admitted birth's actual outcome, also when stopping failed midway."""
    for row in record["stopped_cli"] + record["stopped_daemon"]:
        try:
            current = identity(row["pid"])
        except (accounts.Refused, OSError):
            row["state"] = "unknown"
            continue
        row["state"] = "running" if current == row["start"] else "exited"
