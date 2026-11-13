#!/usr/bin/env python3
"""Short user commands and an optional native-CLI wrapper. No credentials move."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

import directory_accounts as accounts


def arguments(label, command="run", values=()):
    return argparse.Namespace(name=label, command=command, arguments=list(values))


def selected(data, service):
    label = data.get("selected", {}).get(service) or data.get("defaults", {}).get(service)
    if not label:
        accounts.refuse("no selection; register your default home with account add NAME DIRECTORY --default")
    return label


def select(root, service, label):
    with accounts.registry_writer(root) as data:
        accounts.account(data, service, label)
        data.setdefault("selected", {})[service] = label
        accounts.write_registry(root, data)


def current(service, script, root, values):
    # Unlike a switch, a plain CLI startup never closes another process.
    with accounts.service_lock(root, service):
        data = accounts.load_registry(root)
        label = selected(data, service)
        args = arguments(label, values=values)
        accounts.prepare_launch(service, script, data, args).exec()


def bind_current(service, script, root, data, value):
    selected(data, service)
    accounts.bind_launcher(service, script, root, value)


def ensure_named_home(service, root, label):
    data = accounts.load_registry(root)
    if label in data["accounts"][service]:
        return
    path = Path.home() / ("." + service + "-" + label)
    args = argparse.Namespace(name=label, directory=str(path), create=True,
                              bare=True, template=None, default=False)
    # Never infer ownership of an existing directory from its name.
    accounts.add(service, root, args)


def receipt_write(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".switch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, indent=2)
            out.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def require_login(service, data, label):
    _, directory = accounts.account(data, service, label)
    if not (directory / ("auth.json" if service == "codex" else ".credentials.json")).is_file():
        accounts.refuse("no local login file; run flipauth " + ("cod" if service == "codex" else "cc") +
                        " " + label + " login first; no sessions stopped")
    return directory


# Invocations that never open the interactive UI: run them in the named home without
# switching. Only the first argument is checked; put subcommands first.
PASS_THROUGH = {
    "codex": {"exec", "e", "review", "login", "logout", "mcp", "plugin", "app-server",
              "remote-control", "completion", "update", "doctor", "sandbox", "debug", "apply",
              "a", "queue", "archive", "delete", "migrate-rollouts", "migrate-nfs-db",
              "unarchive", "exec-server", "features", "help"},
    "claude": {"auth", "config", "doctor", "install", "mcp", "migrate-installer", "plugin",
               "setup-token", "update", "help"},
}
PASS_THROUGH_FLAGS = {"--version", "-V", "-v", "--help", "-h"}


def passes_through(service, values):
    if values[:1] and values[0] in PASS_THROUGH[service]:
        return True
    # After the official "--", every argument is literal prompt text, never a flag.
    options = values[:values.index("--")] if "--" in values else values
    if any(value in PASS_THROUGH_FLAGS for value in options):
        return True
    return service == "claude" and any(value in {"-p", "--print"} for value in options)


def switch(service, script, root, label, values):
    from process_state import identity
    from session_switch import replace_processes
    from process_state import processes
    if passes_through(service, values):
        # No selection change and nothing stopped: like account run for this home.
        accounts.launch(service, script, accounts.load_registry(root), arguments(label, values=values))
        return
    if not os.isatty(0):
        accounts.refuse("switch requires a terminal; run the named launcher in a new terminal")
    with accounts.service_lock(root, service + "-operation", exclusive=True), accounts.service_lock(root, service, exclusive=True):
        data = accounts.load_registry(root)
        plan = accounts.prepare_launch(service, script, data, arguments(label, values=values))
        directory = require_login(service, data, label)
        jobs = root / "switches"
        accounts.private_directory(jobs)
        receipt = jobs / (service + "-" + uuid.uuid4().hex + ".json")
        record = {"service": service, "target": label, "state": "checking",
                  "cwd": os.getcwd(), "stopped_cli": []}
        receipt_write(receipt, record)
        try:
            target = Path(directory).resolve()
            running = processes(service)
            if all(Path(fact["home"]).resolve() == target for fact in running.values()):
                # Same account (or nothing running): join it; stop nothing, keep its daemon.
                record["mode"] = "same-account"
            else:
                record["mode"] = "account-change"
                replace_processes(plan, root, record, receipt)
            if any(Path(fact["home"]).resolve() != target for fact in processes(service).values()):
                accounts.refuse("same-service process appeared before launch; no new CLI started")
            select(root, service, label)
            record.update(state="exec-admitted", pid=os.getpid(), start=identity(os.getpid()))
            receipt_write(receipt, record)
            # Both CLOEXEC locks are held until the new official process replaces us.
            plan.exec()
        except (accounts.Refused, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            record.update(state="failed", error=str(exc) if isinstance(exc, accounts.Refused)
                          else type(exc).__name__)
            receipt_write(receipt, record)
            raise


def status(service, root, as_json=False):
    from process_state import processes, home_of, identity
    data = accounts.load_registry(root)
    label = data.get("selected", {}).get(service) or data.get("defaults", {}).get(service)
    report = {"service": service, "selected": data.get("selected", {}).get(service),
              "initial_default": data.get("defaults", {}).get(service),
              "identity": "unverified", "processes": [], "observation_error": None,
              "last_switch": None}
    if label:
        _, directory = accounts.account(data, service, label)
        filename = "auth.json" if service == "codex" else ".credentials.json"
        report.update(directory=str(directory), login_file_present=(directory / filename).is_file())
    homes = {entry["directory"]: name for name, entry in data["accounts"][service].items()}
    try:
        for pid, process in processes(service).items():
            try:
                start = identity(pid)
                if start is None:
                    continue
                home = str(home_of(pid, service))
                if identity(pid) != start:
                    continue
                report["processes"].append({"pid": pid, "start_ticks": start, "home": home,
                    "account": homes.get(home),
                    "role": "app-server" if "app-server" in process["argv"] else "cli"})
            except FileNotFoundError:
                continue
    except (accounts.Refused, OSError, ValueError) as exc:
        report["observation_error"] = str(exc) if isinstance(exc, accounts.Refused) else type(exc).__name__
    receipts = sorted((root / "switches").glob(service + "-*.json"), key=lambda p: p.stat().st_mtime)
    if receipts:
        try:
            record = json.loads(receipts[-1].read_text())
            report["last_switch"] = {"state": record["state"], "target": record["target"],
                "error": record.get("error"), "receipt": str(receipts[-1])}
            if record["state"] == "exec-admitted":
                report["last_switch"]["launch_observed"] = any(
                    row["pid"] == record.get("pid") and row["start_ticks"] == record.get("start")
                    and row["account"] == record["target"] for row in report["processes"])
            if record["state"] in {"queued", "checking", "stopping", "starting"}:
                worker_start = record.get("worker_start")
                report["last_switch"]["worker_alive"] = (
                    identity(record["worker_pid"]) == worker_start if worker_start is not None else None)
        except (ValueError, KeyError, OSError):
            report["last_switch"] = {"state": "unreadable", "target": None,
                                     "receipt": str(receipts[-1]), "error": None}
    report["selection_matches_processes"] = (None if report["observation_error"] or not report["processes"] else
        all(row["account"] == label for row in report["processes"]))
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print("selected: " + str(report["selected"]))
    print("initial default: " + str(report["initial_default"]))
    print("identity: unverified")
    if label:
        print("directory: " + report["directory"])
        print("local login file: " + ("present (identity unverified)" if report["login_file_present"] else "missing"))
        print("launch selected: flipauth " + service + " account current --")
    print("Plain " + service + " follows selection only after bind-current is installed on PATH.")
    print("running processes: " + str(len(report["processes"])))
    for row in report["processes"]:
        print(f"  pid={row['pid']} account={row['account'] or 'unregistered'} role={row['role']} home={row['home']}")
    if report["observation_error"]:
        print("process observation unavailable: " + report["observation_error"])
    elif report["selection_matches_processes"] is False:
        print("selection differs from running process homes; selection is a launch preference, not request identity")
    if report["last_switch"]:
        record = report["last_switch"]
        print("last switch: " + record["state"] + " -> " + str(record["target"]))
        if record.get("error"):
            print("reason: " + record["error"])
        print("receipt: " + record["receipt"])
        if "launch_observed" in record:
            print("target CLI currently observed: " + str(record["launch_observed"]).lower())
        if record.get("worker_alive") is False:
            print("switch worker is no longer running; inspect this receipt before retrying")
        print("Login does not update the last switch receipt.")


def main():
    service, executable = sys.argv[1:3]
    values = sys.argv[3:]
    script = Path(executable).resolve()
    root = accounts.local_path(os.environ.get("FLIPAUTH_ACCOUNTS_DIR", str(Path.home() / ".local/state/flipauth")))
    if not values or values == ["--help"]:
        print("Usage: flipauth <cod|cc> <NAME> [login] [-- CLI arguments]\n"
              "       flipauth <cod|cc> new <NAME>\n"
              "       flipauth <cod|cc> status [--json]|list\n"
              "Same account: opens one more CLI. Another account running: stops all same-service CLIs and\n"
              "daemons first. Subcommands such as exec/login/--version run without switching.\n"
              "Login creates a fresh named directory if absent. No legacy snapshots are imported.")
        return
    if values in (["status"], ["status", "--json"]):
        status(service, root, "--json" in values)
    elif values == ["list"]:
        accounts.listing(service, accounts.load_registry(root), False)
    elif values[:1] == ["new"]:
        if len(values) != 2:
            accounts.refuse("new requires one name")
        ensure_named_home(service, root, accounts.name(values[1]))
    else:
        label = accounts.name(values[0])
        rest = values[1:]
        if rest[:1] == ["login"]:
            ensure_named_home(service, root, label)
            login_args = rest[1:]
            if login_args[:1] == ["--"]:
                login_args = login_args[1:]
            accounts.launch(service, script, accounts.load_registry(root), arguments(label, "login", login_args))
        else:
            if rest[:1] == ["--"]:
                rest = rest[1:]
            switch(service, script, root, label, rest)


if __name__ == "__main__":
    try:
        main()
    except (accounts.Refused, OSError, ValueError, argparse.ArgumentTypeError) as exc:
        print("flipauth: " + str(exc), file=sys.stderr)
        sys.exit(1)
