#!/usr/bin/env bash
# Archive the removed WSL Magpie installation's default data directory.
# No logout, process termination, credential copying or permanent deletion.
set -euo pipefail
exec python3 - "$@" <<'PY'
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


def refuse(message):
    raise RuntimeError(message)


def owned_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        refuse("directory is linked, not a directory, or owned by another user: " + str(path))


def run(command, env=None):
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    if result.returncode:
        refuse("cannot verify running processes/services; nothing moved")
    return result.stdout


def preflight(home):
    rows = run(["ps", "-u", str(os.getuid()), "-o", "pid=,comm=,args="])
    watched = {"codex", "codex.exe", "magpie", "magpie.exe", "magpie-web", "start-magpie-web.sh"}
    for line in rows.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        pid, comm, args = fields
        names = {comm.lower(), *(Path(word).name.lower() for word in args.split()[:3])}
        if watched & names:
            refuse("Codex/Magpie process still running (PID " + pid + "); exit it normally first")
    binary = home / ".local/bin/magpie"
    if shutil.which("magpie") or binary.exists() or binary.is_symlink():
        refuse("Magpie executable still installed; finish uninstalling it first")
    units = home / ".config/systemd/user"
    if units.exists() and any(units.rglob("*magpie*")):
        refuse("Magpie user service files remain; review the uninstall first")
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid()))
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=" + env["XDG_RUNTIME_DIR"] + "/bus")
    for verb in ("list-unit-files", "list-units"):
        result = run(["systemctl", "--user", verb, "--all", "--no-legend", "--no-pager", "*magpie*"], env)
        if result.strip():
            refuse("Magpie service is still registered or loaded; nothing moved")


def main():
    parser = argparse.ArgumentParser(prog="cleanup-magpie.sh", description="Preview or archive leftover WSL Magpie data after uninstall.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="move data into a private recovery directory")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = parser.parse_args()
    # Override only for isolated tests or an explicitly chosen sandbox.
    home = Path(os.environ.get("MAGPIE_CLEANUP_HOME", str(Path.home())))
    if not home.is_absolute():
        refuse("home must be an absolute path")
    owned_directory(home)
    config = home / ".config"
    if config.exists() or config.is_symlink():
        owned_directory(config)
    source = config / "magpie"
    print("Scope: only " + str(source), flush=True)
    print("Codex/Claude homes, FlipAuth registry and review snapshots are untouched.", flush=True)
    if not source.exists() and not source.is_symlink():
        print("Already clean: no default Magpie data directory. No changes.")
        return
    owned_directory(source)
    original = source.lstat()
    preflight(home)
    if not args.apply:
        print("Preview passed. --apply will MOVE this directory into a private backup; no files deleted.")
        return
    os.umask(0o077)
    parent = home
    for part in (".local", "state", "flipauth-cleanup"):
        parent = parent / part
        parent.mkdir(mode=0o700, exist_ok=True)
        owned_directory(parent)
    if parent.stat().st_mode & 0o077:
        refuse("backup root must have mode 700; nothing moved")
    lock = os.open(parent / ".cleanup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, "w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if not source.exists():
            print("Already archived by another run. No changes.")
            return
        current = source.lstat()
        if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
            refuse("source changed during checks; nothing moved")
        preflight(home)
        if source.stat().st_dev != parent.stat().st_dev:
            refuse("source and backup are on different filesystems; refusing to copy credentials")
        backup = Path(tempfile.mkdtemp(prefix="magpie-", dir=parent))
        archived = backup / "config"
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                    "source": str(source), "archive": str(archived), "operation": "rename"}
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        os.rename(source, archived)
        print("Archived: " + str(archived))
        print("Backup may contain login material. Keep it private.")
        src, dst = shlex.quote(str(archived)), shlex.quote(str(source))
        print("Recovery (only while Codex/Magpie are stopped):")
        print("test ! -e " + dst + " && test ! -L " + dst + " && mv -T -- " + src + " " + dst)


try:
    main()
except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
    print("cleanup-magpie: " + str(exc), file=sys.stderr)
    sys.exit(1)
PY
