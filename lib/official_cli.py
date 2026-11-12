"""Stable official executables and the single native-process launch contract."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil

import directory_accounts as accounts


@dataclass(frozen=True)
class LaunchPlan:
    service: str
    account: str
    home: Path
    executable: Path
    argv: tuple[str, ...]
    env: dict[str, str]

    def exec(self):
        os.umask(0o077)
        os.execve(self.executable, self.argv, self.env)


def registry_root():
    return accounts.local_path(os.environ.get(
        "FLIPAUTH_ACCOUNTS_DIR", str(Path.home() / ".local/state/flipauth")))


def checked_entry(value, script):
    """Validate the resolved file, but execute the stable spelling we were given."""
    found = shutil.which(str(value))
    if not found:
        accounts.refuse("official WSL CLI missing; review its configured executable")
    entry = Path(found).absolute()
    resolved = accounts.local_path(str(entry))
    if any(p.suffix.lower() in {".exe", ".cmd", ".bat"} for p in (entry, resolved)):
        accounts.refuse("refusing a Windows executable; use the official WSL CLI")
    if resolved == script.resolve() or resolved.parent == Path(__file__).resolve().parent:
        return None
    with resolved.open("rb") as source:
        header = source.read(256)
    if b"# flipauth " in header:
        return None
    return entry


def executable(service, script):
    key = "FLIPAUTH_" + service.upper() + "_BIN"
    override = os.environ.get(key)
    if override:
        result = checked_entry(override, script)
        if result is None:
            accounts.refuse("CLI resolves to a FlipAuth launcher; recursive launcher refused")
        return result
    data = accounts.load_registry(registry_root())
    configured = data.get("executables", {}).get(service)
    if configured:
        result = checked_entry(configured, script)
        if result is None:
            accounts.refuse("configured official executable points at FlipAuth; review the binding")
        return result
    # A current-account wrapper can precede the official CLI. Never execute or
    # parse a wrapper to discover its target; continue to the next PATH entry.
    for folder in os.get_exec_path():
        candidate = Path(folder or ".") / service
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        result = checked_entry(candidate.absolute(), script)
        if result is not None:
            return result
    accounts.refuse(f"official WSL CLI missing; set {key} to its stable executable")
