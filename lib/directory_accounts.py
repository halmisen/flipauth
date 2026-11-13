#!/usr/bin/env python3
"""Account ownership, reviewed configuration and native launch plans."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile


class Refused(Exception):
    pass


def refuse(message):
    raise Refused(message)


def local_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        refuse("use an absolute path (or ~/path)")
    path = path.resolve()
    if any(c in str(path) for c in "\n\r\0"):
        refuse("paths cannot contain line breaks or NUL")
    if path == Path("/") or path.parts[1:2] in [("mnt",), ("media",)]:
        refuse("refusing a Windows filesystem or filesystem root; use a WSL directory")
    probe = path
    while not probe.exists():
        probe = probe.parent
    try:
        result = subprocess.run(
            ["findmnt", "-no", "FSTYPE", "--target", str(probe)],
            capture_output=True, text=True, check=False,
        )
        if result.stdout.strip() in {"drvfs", "9p", "virtiofs", "cifs", "smb3"}:
            refuse("refusing a Windows filesystem; use a WSL directory")
    except FileNotFoundError:
        pass
    return path


def name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise argparse.ArgumentTypeError("names use letters, digits, underscores and hyphens")
    return value


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def regular(path):
    if path.is_symlink():
        refuse(f"refusing shared/symlinked file: {path.name}")
    if path.exists() and not path.is_file():
        refuse(f"expected a regular file: {path.name}")
    if path.is_file() and path.stat().st_nlink > 1:
        refuse(f"refusing shared/hardlinked file: {path.name}")


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = path.stat()
    if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.getuid() or mode.st_mode & 0o077:
        refuse("registry directory must be owned by you with mode 700")


def owned_home(directory):
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        refuse("account home must be owned by you and not writable by group or others; no permissions changed")


def load_registry(root):
    path = root / "accounts.json"
    regular(path)
    if not path.exists():
        return {"schema": 1, "accounts": {"claude": {}, "codex": {}}}
    try:
        data = json.loads(path.read_text())
        if (not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1 or
                not isinstance(data.get("accounts"), dict) or set(data["accounts"]) != {"claude", "codex"}):
            raise ValueError
        directories = []
        for group in data["accounts"].values():
            if not isinstance(group, dict):
                raise ValueError
            for label, entry in group.items():
                name(label)
                if not isinstance(entry, dict) or not isinstance(entry.get("directory"), str):
                    raise ValueError
                directory = Path(entry["directory"])
                if not directory.is_absolute() or entry["configuration"] not in {"existing", "bare", "template"}:
                    raise ValueError
                if any(overlaps(directory, other) for other in directories):
                    raise ValueError
                directories.append(directory)
        for field in ("defaults", "selected"):
            if not isinstance(data.get(field, {}), dict):
                raise ValueError
            for service, label in data.get(field, {}).items():
                if service not in data["accounts"] or label not in data["accounts"][service]:
                    raise ValueError
        if not isinstance(data.get("executables", {}), dict):
            raise ValueError
        for service, entry in data.get("executables", {}).items():
            if service not in data["accounts"] or not isinstance(entry, str):
                raise ValueError
            if not Path(entry).is_absolute() or any(c in entry for c in "\n\r\0"):
                raise ValueError
        return data
    except (ValueError, KeyError, TypeError, argparse.ArgumentTypeError):
        refuse("invalid account registry; restore it before writing (nothing replaced)")


@contextlib.contextmanager
def registry_writer(root):
    private_directory(root)
    lock_path = root / ".accounts.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield load_registry(root)


def write_registry(root, data):
    fd, tmp = tempfile.mkstemp(prefix=".accounts-", dir=root)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, indent=2, sort_keys=True)
            out.write("\n")
        os.replace(tmp, root / "accounts.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


ENV_CONFLICTS = {
    "claude": {
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_API_KEY_HELPER", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_BASE_URL",
        "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
        "ANTHROPIC_CUSTOM_HEADERS", "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    },
    "codex": {
        "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL",
        "OPENAI_API_BASE", "CHATGPT_BASE_URL", "CODEX_EXEC_SERVER_URL",
        "CODEX_SQLITE_HOME", "CODEX_LOG_DIR", "OPENAI_IDENTITY_TOKEN_FILE",
        "OPENAI_FEDERATION_RULE_ID",
    },
}
PROTECTED = {
    "apiKeyHelper", "forceLoginMethod", "model_provider", "model_providers",
    "openai_base_url", "chatgpt_base_url", "experimental_realtime_ws_base_url",
    "sqlite_home", "log_dir", "forced_login_method",
    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "forceLoginOrgUUID",
}


def check_config(service, path, template=False):
    regular(path)
    if not path.exists():
        return
    try:
        if service == "claude":
            data = json.loads(path.read_text())
        else:
            try:
                import tomllib
            except ImportError:
                refuse("checking Codex config.toml requires Python 3.11+ (no config was changed)")
            data = tomllib.loads(path.read_text())
        if not isinstance(data, dict):
            refuse("configuration must be an object/table")
    except (ValueError, UnicodeError):
        refuse(f"invalid {path.name}; configuration contents withheld")

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in PROTECTED or key in ENV_CONFLICTS[service]:
                    refuse(f"configuration override conflicts with directory login: {key}")
                if (template and key != "cli_auth_credentials_store" and
                        re.search(r"token|secret|password|api.?key|credential|oauth", key, re.I)):
                    refuse("template contains a credential-related key; supply a clean template")
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    if service == "codex":
        store = data.get("cli_auth_credentials_store", "file")
        if store != "file":
            refuse("directory mode requires file credential storage; review it with the owner, no setting changed")


def config_name(service):
    return "settings.json" if service == "claude" else "config.toml"


def template_files(service, source):
    allowed = {config_name(service), "CLAUDE.md" if service == "claude" else "AGENTS.md"}
    if not source.is_dir():
        refuse("template must be a directory containing only reviewed rules/config files")
    files = {}
    for path in source.iterdir():
        if path.name not in allowed:
            refuse("template contains files outside the rules/config allow-list")
        regular(path)
        if path.name == config_name(service):
            check_config(service, path, template=True)
        files[path.name] = path.read_bytes()
    if not files:
        refuse("template is empty; use --bare to explicitly choose a fresh setup")
    return files


def add(service, root, args):
    directory = local_path(args.directory)
    if directory.is_dir():
        owned_home(directory)
    if overlaps(root, directory):
        refuse("account and registry directories must not overlap")
    # The default CLI homes have implicit owners, even before registration.
    for owner in ("claude", "codex"):
        default = Path.home() / ("." + owner)
        if overlaps(default.resolve(), directory) and (directory != default.resolve() or service != owner):
            refuse("account directory overlaps a default CLI home")
    if args.create != bool(args.bare or args.template):
        refuse("--create requires exactly one of --bare or --template; existing directories use neither")
    files = template_files(service, local_path(args.template)) if args.template else {}
    if args.create and service == "codex" and "config.toml" not in files:
        files["config.toml"] = b'cli_auth_credentials_store = "file"\n'
    with registry_writer(root) as data:
        accounts = data["accounts"][service]
        old = accounts.get(args.name)
        if old:
            if old["directory"] == str(directory) and not args.create:
                if getattr(args, "default", False):
                    data.setdefault("defaults", {})[service] = args.name
                    data.setdefault("selected", {}).setdefault(service, args.name)
                    write_registry(root, data)
                    print("default recorded; account files unchanged")
                else:
                    print("already registered (no changes)")
                return
            refuse("name already registered; nothing replaced")
        for group in data["accounts"].values():
            if any(overlaps(Path(entry["directory"]), directory) for entry in group.values()):
                refuse("directory already owned by another account, or overlaps one")
        if args.create:
            if directory.exists():
                refuse("--create refuses an existing directory, including an empty one")
            directory.mkdir(mode=0o700)  # Parent must exist; never claim a broad tree.
            for filename, contents in files.items():
                fd = os.open(directory / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as out:
                    out.write(contents)
        elif not directory.is_dir():
            refuse("directory missing; use --create with --bare or a reviewed --template")
        accounts[args.name] = {"directory": str(directory),
                               "configuration": "template" if args.template else "bare" if args.bare else "existing"}
        if getattr(args, "default", False):
            data.setdefault("defaults", {})[service] = args.name
            data.setdefault("selected", {}).setdefault(service, args.name)
        write_registry(root, data)
    print(f"registered {service} {args.name}: {directory} (identity unverified)")
    if args.create:
        print("No credentials, sessions, permissions databases or plugin state copied. "
              "Review rules, permissions, hooks and plugin setup before use.", file=sys.stderr)


def account(data, service, label):
    entry = data["accounts"][service].get(label)
    if entry is None:
        refuse("unknown directory account; use account add first (legacy snapshots are separate)")
    directory = local_path(entry["directory"])
    if str(directory) != entry["directory"]:
        refuse("registered directory changed through a symlink; review ownership before use")
    if directory.is_dir():
        owned_home(directory)
    return entry, directory


def listing(service, data, as_json):
    rows = []
    for label in sorted(data["accounts"][service]):
        entry, directory = account(data, service, label)
        credential = directory / (".credentials.json" if service == "claude" else "auth.json")
        rows.append({"name": label, **entry, "directory_exists": directory.is_dir(),
                     "credential_file": "symlink" if credential.is_symlink() else "present" if credential.is_file() else "missing",
                     "config_present": (directory / config_name(service)).is_file(),
                     "rules_present": (directory / ("CLAUDE.md" if service == "claude" else "AGENTS.md")).is_file(),
                     "identity": "unverified"})
    if as_json:
        print(json.dumps({"service": service, "accounts": rows}, indent=2))
    elif not rows:
        print("No directory accounts registered. Legacy snapshots are separate.")
    else:
        for row in rows:
            print(f"{row['name']}\t{row['directory']}\tdirectory={row['directory_exists']} "
                  f"credential_file={row['credential_file']} config={row['config_present']} "
                  f"rules={row['rules_present']} identity=unverified")


def cli_binary(service, script):
    from official_cli import executable
    return executable(service, script)


def check_arguments(service, arguments):
    for index, arg in enumerate(arguments):
        if arg == "--":
            break
        option = arg.split("=", 1)[0]
        if service == "claude" and option in {"--settings", "--setting-sources"}:
            refuse("--settings/--setting-sources bypass directory configuration review")
        if service == "codex":
            if option in {"--remote", "--remote-auth-token-env"}:
                refuse("remote servers bypass the account home; launch a local CLI")
            if arg in {"app-server", "remote-control"}:
                refuse("background servers are outside the interactive account launcher")
            if option in {"--profile", "-p", "--oss", "--local-provider"} or arg.startswith("-p"):
                refuse("provider/profile overrides bypass directory configuration review")
            value = None
            if arg in {"-c", "--config"} and index + 1 < len(arguments):
                value = arguments[index + 1]
            elif arg.startswith("--config="):
                value = arg[len("--config="):]
            elif arg.startswith("-c") and arg != "-c":
                value = arg[2:]
            if value is not None:
                key = value.split("=", 1)[0].strip().strip('"\'').split(".")[0]
                if key in PROTECTED or key in {"cli_auth_credentials_store", "profiles"}:
                    refuse("CLI config override conflicts with directory login")


def prepare_launch(service, script, data, args):
    from official_cli import LaunchPlan
    _, directory = account(data, service, args.name)
    if not directory.is_dir():
        refuse("registered directory is missing; nothing created")
    collisions = sorted(key for key in ENV_CONFLICTS[service] if os.environ.get(key))
    if collisions:
        refuse("inherited overrides conflict with directory login: " + ", ".join(collisions) +
               "; unset them explicitly (values withheld)")
    # Do not inspect credential contents. Reject pointers to shared writable state.
    for filename in ("auth.json", ".credentials.json", ".claude.json", "sessions", "plugins",
                     "history.jsonl", "settings.local.json", "archived_sessions", "logs", "projects"):
        if (directory / filename).is_symlink():
            refuse(f"shared/symlinked runtime state refused: {filename}")
        path = directory / filename
        if path.is_file() and path.stat().st_nlink > 1:
            refuse(f"shared/hardlinked runtime file refused: {filename}")
    for path in directory.glob("*.sqlite*"):
        if path.is_symlink() or (path.is_file() and path.stat().st_nlink > 1):
            refuse("shared/symlinked/hardlinked database refused")
    check_config(service, directory / config_name(service))
    if service == "claude":
        check_config(service, directory / "settings.local.json")
    # argparse consumes the launcher separator once; retain a CLI's own `--`.
    arguments = args.arguments
    check_arguments(service, arguments)
    binary = cli_binary(service, script)
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR" if service == "claude" else "CODEX_HOME"] = str(directory)
    # Herdr can identify the official process even if an explicitly configured
    # executable has a version-number basename. Scope the hint to this child.
    env["HERDR_AGENT"] = service
    prefix = (["auth", "login"] if service == "claude" else ["login"]) if args.command == "login" else []
    return LaunchPlan(service, args.name, directory, binary,
                      (str(binary), *prefix, *arguments), env)


@contextlib.contextmanager
def service_lock(root, service, exclusive=False):
    private_directory(root)
    fd = os.open(root / ("." + service + "-switch.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def launch(service, script, data, args):
    # CLOEXEC keeps the startup lock until the actual CLI replaces this process.
    root = local_path(os.environ.get("FLIPAUTH_ACCOUNTS_DIR", str(Path.home() / ".local/state/flipauth")))
    with service_lock(root, service):
        prepare_launch(service, script, data, args).exec()


def bind(service, script, root, data, args):
    account(data, service, args.name)
    bind_launcher(service, script, root, args.path, args.name, args.switch, args.check)


def bind_launcher(service, script, root, value, label=None, switch=False, check=False):
    target_input = Path(value).expanduser()
    if target_input.is_symlink():
        refuse("launcher target is a symlink; nothing replaced")
    target = local_path(value)
    try:
        name(target.name)
    except argparse.ArgumentTypeError:
        refuse("launcher names use letters, digits, underscores and hyphens")
    if label is not None and target.name in {"claude", "codex", "flipauth", "claude-switch", "codex-switch"}:
        refuse("cannot shadow a CLI or FlipAuth command")
    if label is None and target.name != service:
        refuse("current-account wrapper must be named " + service)
    found = shutil.which(target.name)
    if label is not None and found and Path(found).resolve() != target:
        refuse("command name already exists on PATH; nothing replaced")
    binary = cli_binary(service, script)
    if target == binary or target.resolve() == binary.resolve():
        refuse("cannot replace the official executable; choose a separate PATH directory")
    if switch:
        words = [str(script), service, label]
        marker = "switch"
    else:
        words = [str(script), service, "account", "current"] if label is None else [str(script), service, "account", "run", label]
        marker = "current" if label is None else "directory"
    body = ("#!/bin/sh\n# flipauth " + marker + " launcher v1\n" +
            "export FLIPAUTH_ACCOUNTS_DIR=" + shlex.quote(str(root)) + "\n" +
            "exec " + " ".join(map(shlex.quote, [*words, "--"])) + ' "$@"\n')
    if check:
        if not target.is_file() or target.read_text() != body or not os.access(target, os.X_OK):
            refuse("launcher missing or differs from source: " + str(target))
        print("verified: " + str(target))
        return
    existed = target.exists()
    if existed:
        regular(target)
        if target.read_text() != body or not os.access(target, os.X_OK):
            refuse("launcher path already exists with different contents; nothing replaced")
    else:
        # O_EXCL also protects against concurrent bind and dangling symlink races.
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o700)
        with os.fdopen(fd, "w") as out:
            out.write(body)
    # The binding records the official stable entry for *all* callers, not just
    # the wrapper's child environment. No shell script needs to be parsed later.
    with registry_writer(root) as latest:
        if latest.setdefault("executables", {}).get(service) != str(binary):
            latest["executables"][service] = str(binary)
            write_registry(root, latest)
    print(f"{'already bound' if existed else 'bound'}: {target}")


def main():
    service, executable = sys.argv[1:3]
    parser = argparse.ArgumentParser(prog=f"flipauth {service} account",
                                     description="Directory accounts. No credential copying; official CLI owns login/refresh.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add", help="register an existing directory, or explicitly create a fresh one")
    p.add_argument("name", type=name)
    p.add_argument("directory")
    p.add_argument("--create", action="store_true")
    p.add_argument("--default", action="store_true", help="initial default; selection can subsequently change")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--bare", action="store_true", help="acknowledge no rules/settings/plugins inherited")
    mode.add_argument("--template", help="reviewed config/rules-only directory; copied, never linked")
    p = sub.add_parser("list", help="offline local file presence; identity always unverified")
    p.add_argument("--json", action="store_true")
    for command in ("run", "login"):
        p = sub.add_parser(command, help="exec the official CLI in the registered home")
        p.add_argument("name", type=name)
        p.add_argument("arguments", nargs=argparse.REMAINDER)
    p = sub.add_parser("bind", help="create an optional executable launcher at an explicit path")
    p.add_argument("name", type=name)
    p.add_argument("path")
    p.add_argument("--switch", action="store_true",
                   help="on an account change, close all same-service sessions and daemons first; "
                        "same account just opens one more")
    p.add_argument("--check", action="store_true", help="read-only launcher drift check")
    p = sub.add_parser("current", help="launch the selected directory; used by the optional CLI wrapper")
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    p = sub.add_parser("bind-current", help="create an optional codex/claude wrapper that follows selection")
    p.add_argument("path")
    args = parser.parse_args(sys.argv[3:])
    root = local_path(os.environ.get("FLIPAUTH_ACCOUNTS_DIR", str(Path.home() / ".local/state/flipauth")))
    script = Path(executable).resolve()
    if args.command == "add":
        add(service, root, args)
    else:
        data = load_registry(root)
        if args.command == "list":
            listing(service, data, args.json)
        elif args.command == "bind":
            bind(service, script, root, data, args)
        elif args.command in {"current", "bind-current"}:
            from short_commands import current, bind_current
            if args.command == "current":
                values = args.arguments
                if values[:1] == ["--"]:
                    values = values[1:]
                current(service, script, root, values)
            else:
                bind_current(service, script, root, data, args.path)
        else:
            launch(service, script, data, args)


if __name__ == "__main__":
    # Optional short-command helpers import this module; share its exception type.
    sys.modules["directory_accounts"] = sys.modules[__name__]
    try:
        main()
    except (Refused, OSError) as exc:
        print(f"flipauth account: {exc}", file=sys.stderr)
        sys.exit(1)
