"""Read-only process facts used by directory-account switching.

This module deliberately does not infer a process from a formatted ``ps args``
string.  ``ps`` is only an inexpensive PID index; command line, executable,
environment and start identity come from ``/proc``.  The distinction matters
for versioned Claude installations and for arguments containing shell quotes.
"""

import json
import os
from pathlib import Path
import re
import subprocess

import directory_accounts as accounts


def _proc_root():
    return Path(os.environ.get("FLIPAUTH_PROC_ROOT", "/proc"))


def _proc(pid):
    return _proc_root() / str(int(pid))


def identity(pid):
    """Return Linux starttime ticks, or ``None`` if the process is gone/zombie."""
    proc = _proc(pid)
    try:
        if proc.stat().st_uid != os.getuid():
            accounts.refuse("process belongs to another user")
        fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        if not fields or fields[0] in {"Z", "X"}:
            return None
        return int(fields[19])
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (IndexError, ValueError):
        accounts.refuse("cannot inspect process identity")


def process_environment(pid):
    proc = _proc(pid)
    try:
        return dict(item.split(b"=", 1) for item in
                    (proc / "environ").read_bytes().split(b"\0") if b"=" in item)
    except (FileNotFoundError, ProcessLookupError):
        return {}
    except PermissionError:
        accounts.refuse("cannot inspect process environment")


def ancestor_pids():
    """A switch must not terminate the CLI whose tool shell is invoking it."""
    pid = os.getpid()
    ancestors = set()
    while pid > 1 and pid not in ancestors:
        ancestors.add(pid)
        try:
            fields = (_proc(pid) / "stat").read_text().rsplit(")", 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            accounts.refuse("cannot establish switch caller ancestry; no sessions stopped")
    return ancestors


def home_of(pid, service):
    return _home_from_environment(process_environment(pid), service)


def _home_from_environment(env, service):
    key = b"CODEX_HOME" if service == "codex" else b"CLAUDE_CONFIG_DIR"
    value = env.get(key)
    if value is None:
        base = env.get(b"HOME")
        if not base:
            accounts.refuse("process has no CLI home or HOME; cannot establish ownership")
        value = base + b"/." + service.encode()
    if not value:
        accounts.refuse("process CLI home is empty; cannot establish ownership")
    return Path(os.fsdecode(value)).resolve()


def _argv(pid):
    try:
        raw = (_proc(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        return []
    return [os.fsdecode(item) for item in raw.split(b"\0") if item]


def _exe(pid):
    try:
        return Path(os.readlink(_proc(pid) / "exe"))
    except (FileNotFoundError, OSError):
        return None


def _codex_npm_vendors(target):
    """Return vendor directories belonging to an npm-installed @openai/codex package."""
    if target.parent.name != "bin":
        return set()
    package_root = target.parent.parent
    if package_root.name != "codex" or package_root.parent.name != "@openai":
        return set()
    vendors = [package_root / "vendor"]
    scopes = [package_root.parent]
    nested_scope = package_root / "node_modules" / "@openai"
    if nested_scope.is_dir():
        scopes.append(nested_scope)
    # Include sibling nvm Node versions so switching/upgrading Node does not hide running CLIs.
    node_modules = package_root.parent.parent
    node_root = node_modules.parent.parent if node_modules.name == "node_modules" and node_modules.parent.name == "lib" else None
    if node_root and node_root.parent.name == "node" and node_root.parent.parent.name == "versions":
        try:
            for sibling in node_root.parent.iterdir():
                candidate = sibling / "lib" / "node_modules" / "@openai"
                if candidate.is_dir():
                    scopes.append(candidate)
        except OSError:
            pass
    for scope in scopes:
        try:
            entries = list(scope.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name == "codex" or entry.name.startswith("codex-"):
                vendors.append(entry / "vendor")
                nested = entry / "node_modules" / "@openai"
                if nested.is_dir():
                    try:
                        for sub in nested.iterdir():
                            if sub.name == "codex" or sub.name.startswith("codex-"):
                                vendors.append(sub / "vendor")
                    except OSError:
                        pass
    resolved = set()
    for path in vendors:
        if path.is_dir():
            try:
                resolved.add(path.resolve())
            except OSError:
                continue
    return resolved


def _official_signatures(service):
    """Return exact executable paths and trusted installation families."""
    # Use the same resolver as launch. It consults registered executables and
    # walks past bind-current wrappers, so a wrapper cannot hide the official
    # install family from process inspection.
    from official_cli import executable, registry_root
    try:
        paths = [executable(service, Path(__file__).resolve().parent.parent / "flipauth")]
    except OSError:
        accounts.refuse("cannot resolve official CLI for process ownership")
    exact = set()
    families = set()
    vendor_families = set()
    for path in paths:
        try:
            target = path.resolve()
        except OSError:
            continue
        if not target.exists():
            continue
        exact.add(target)
        # Claude's installer keeps releases beside the selected version. A
        # running older version remains official after the symlink advances.
        if service == "claude" and target.parent.name == "versions":
            families.add(target.parent)
        # Codex standalone releases share a stable ``releases`` directory;
        # npm @openai/codex replaces Node via execve with vendor/<triple>/bin/codex.
        if service == "codex":
            for parent in target.parents:
                if parent.name == "releases":
                    families.add(parent)
                    break
            vendor_families.update(_codex_npm_vendors(target))
    if service == "codex":
        registry = accounts.load_registry(registry_root())
        homes = {Path.home() / ".codex"}
        homes.update(Path(row["directory"]) for row in registry["accounts"][service].values())
        for home in homes:
            for package in ("standalone", "app-server-daemon"):
                families.add((home / "packages" / package / "releases").resolve())
    return exact, families, vendor_families


_INTERPRETER_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?|node|bun|bash|dash|sh|zsh")


def _is_service_process(service, argv, exe, exact, families, vendor_families):
    if exe and exe in exact:
        return True
    if exe and any(parent in families for parent in exe.parents):
        # The Codex release also contains code-mode/sandbox helpers. Only its
        # CLI binary is a service session. Claude's native CLI uses a version
        # number as its actual filename.
        if exe.name == service or (service == "claude" and
                re.fullmatch(r"\d+\.\d+\.\d+(?:[-+].*)?", exe.name)):
            return True
    if service == "codex" and exe and exe.name == "codex" and exe.parent.name == "bin":
        try:
            vendor_root = exe.parent.parent.parent.resolve()
        except OSError:
            vendor_root = None
        if vendor_root in vendor_families:
            return True
    # A shebang launcher reports the interpreter as argv0. Only accept its
    # first script argument when that exact script is the configured official
    # entry; arbitrary prompt/argument text is never a service signal.
    interpreter = exe and _INTERPRETER_RE.fullmatch(exe.name)
    if interpreter and len(argv) > 1:
        try:
            script = Path(argv[1]).resolve()
        except OSError:
            return False
        if script in exact:
            return True
    return False


def _command_args(argv, exact):
    """Return native CLI args, stripping a known interpreter script prefix."""
    if not argv:
        return []
    first = Path(argv[0]).name
    if _INTERPRETER_RE.fullmatch(first) and len(argv) > 1:
        try:
            if Path(argv[1]).resolve() in exact:
                return argv[2:]
        except OSError:
            return []
    return argv[1:]


def _pid_index():
    command = os.environ.get("FLIPAUTH_PS_BIN", "ps")
    try:
        result = subprocess.run([command, "-u", str(os.getuid()), "-o", "pid="],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        accounts.refuse("cannot inspect same-user CLI processes")
    if result.returncode:
        accounts.refuse("cannot inspect same-user CLI processes")
    pids = []
    for line in result.stdout.splitlines():
        token = line.strip().split(None, 1)[0] if line.strip() else ""
        if token.isdecimal() and int(token) > 1:
            pids.append(int(token))
    return pids


def process_fact(pid, service, signatures=None):
    start = identity(pid)
    if start is None:
        return None
    argv = _argv(pid)
    exe = _exe(pid)
    signatures = signatures or _official_signatures(service)
    if not _is_service_process(service, argv, exe, *signatures):
        return None
    # Read environments only after executable/argv classification. A random
    # same-user process may deny /proc access and must not block a switch.
    env = process_environment(pid)
    observed_start = identity(pid)
    if observed_start is None:
        return None
    if observed_start != start:
        accounts.refuse("process changed during inspection; no switch performed")
    home = _home_from_environment(env, service)
    final_start = identity(pid)
    if final_start is None:
        return None
    if final_start != start:
        accounts.refuse("process changed during inspection; no switch performed")
    exact = signatures[0]
    return {
        "pid": int(pid),
        "start": start,
        "argv": argv,
        "exe": str(exe) if exe else None,
        "command": _command_args(argv, exact),
        "home": str(home),
        "environment": env,
    }


def processes(service):
    """Return live same-service facts keyed by PID."""
    rows = {}
    signatures = _official_signatures(service)
    for pid in _pid_index():
        fact = process_fact(pid, service, signatures)
        if fact is not None:
            rows[pid] = fact
    return rows


def _record(path):
    try:
        data = json.loads(path.read_text())
        identity_data = data["processIdentity"]
        pid = data["pid"]
        if type(pid) is not int or pid <= 1:
            return None
        if type(identity_data["startTicks"]) is not int or not identity_data["bootId"]:
            return None
        return pid, identity_data["startTicks"], identity_data["bootId"]
    except (OSError, ValueError, TypeError, KeyError):
        return None


def verified_daemons(service, root, registry=None):
    """Return only exact Codex managed daemon PIDs described by PID records."""
    if service != "codex":
        return set()
    registry = registry or accounts.load_registry(root)
    homes = {str(Path.home() / ".codex")}
    homes.update(entry["directory"] for entry in registry["accounts"]["codex"].values())
    facts = processes(service)
    boot_id = (_proc_root() / "sys/kernel/random/boot_id").read_text().strip() if \
        (_proc_root() / "sys/kernel/random/boot_id").is_file() else \
        Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    found = set()
    for home in homes:
        directory = Path(home).resolve()
        daemon_dir = directory / "app-server-daemon"
        server_records = []
        updater_records = []
        for name, kind in (("daemon.pid", "server"), ("app-server.pid", "server"),
                           ("daemon-updater.pid", "updater"),
                           ("app-server-updater.pid", "updater")):
            item = _record(daemon_dir / name)
            if item:
                (server_records if kind == "server" else updater_records).append(item)
        valid_server = set()
        for pid, ticks, record_boot in server_records:
            fact = facts.get(pid)
            command = fact.get("command", []) if fact else []
            listen_index = command.index("--listen") if "--listen" in command else -1
            listen = command[listen_index + 1] if listen_index >= 0 and listen_index + 1 < len(command) else ""
            if (record_boot == boot_id and fact and fact["start"] == ticks and
                    Path(fact["home"]).resolve() == directory and
                    command[:1] == ["app-server"] and
                    "--managed-daemon" in command and listen.startswith("unix://")):
                valid_server.add(pid)
                found.add(pid)
        # Updaters are killable only when a matching managed server exists for
        # the same home.  A stale updater must remain visible and block a switch.
        if valid_server:
            for pid, ticks, record_boot in updater_records:
                fact = facts.get(pid)
                command = fact.get("command", []) if fact else []
                if (record_boot == boot_id and fact and fact["start"] == ticks and
                        Path(fact["home"]).resolve() == directory and
                        command[:3] == ["app-server", "daemon", "pid-update-loop"]):
                    found.add(pid)
    return found


def daemon_stop_order(pids, facts):
    """Stop the updater before its server so ownership remains observable."""
    return sorted(pids, key=lambda pid: (
        0 if facts.get(pid, {}).get("command", [])[:3] ==
        ["app-server", "daemon", "pid-update-loop"] else 1,
        int(pid),
    ))

