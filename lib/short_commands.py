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


def switch(service, script, root, label, values):
    from process_state import processes, identity
    with accounts.service_lock(root, service + "-operation", exclusive=True), accounts.service_lock(root, service, exclusive=True):
        data = accounts.load_registry(root)
        args = arguments(label, values=values)
        plan = accounts.prepare_launch(service, script, data, args)
        require_login(service, data, label)
        running = processes(service)
        if not running:
            select(root, service, label)
            # SH lock cannot be acquired while holding our own EX lock. This FD is
            # CLOEXEC and remains held through the native program replacement.
            plan.exec()
        jobs = root / "switches"
        accounts.private_directory(jobs)
        receipt = jobs / (service + "-" + uuid.uuid4().hex + ".json")
        record = {"service": service, "target": label, "state": "queued",
                  "arguments": list(values), "panes": []}
        receipt_write(receipt, record)
        log = receipt.with_suffix(".log")
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        child_env = os.environ.copy()
        child_env["FLIPAUTH_ACCOUNTS_DIR"] = str(root)
        child_env["FLIPAUTH_" + service.upper() + "_BIN"] = str(plan.executable)
        with os.fdopen(fd, "w") as out:
            worker = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), service, str(script),
                 "--worker", str(receipt)], env=child_env, stdin=subprocess.DEVNULL,
                stdout=out, stderr=out, start_new_session=True,
            )
        record["worker_pid"] = worker.pid
        record["worker_start"] = identity(worker.pid)
        receipt_write(receipt, record)
        print("Switch queued; completion is not yet confirmed. Receipt: " + str(receipt), flush=True)
        print("Check: flipauth " + ("cod" if service == "codex" else "cc") + " status", flush=True)


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
        if record.get("worker_alive") is False:
            print("switch worker is no longer running; inspect this receipt before retrying")
        print("Login does not update the last switch receipt.")


def main():
    service, executable = sys.argv[1:3]
    values = sys.argv[3:]
    script = Path(executable).resolve()
    root = accounts.local_path(os.environ.get("FLIPAUTH_ACCOUNTS_DIR", str(Path.home() / ".local/state/flipauth")))
    if values[:1] == ["--worker"]:
        from session_switch import run_worker
        path = accounts.local_path(values[1])
        if path.parent != root / "switches" or not path.name.startswith(service + "-"):
            accounts.refuse("invalid worker receipt")
        run_worker(service, script, root, path)
        return
    if not values or values == ["--help"]:
        print("Usage: flipauth <cod|cc> <NAME> [login] [-- CLI arguments]\n"
              "       flipauth <cod|cc> new <NAME>\n"
              "       flipauth <cod|cc> status [--json]|list\n"
              "Switch replaces all verified same-service Herdr CLI sessions, including busy ones.\n"
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
