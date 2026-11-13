#!/usr/bin/env python3
"""Reproduce native TUI terminal cleanup in disposable, unauthenticated PTYs.

Manual diagnostic, outside the offline suite. Only signals children created here.
Never launches a named account, switches peers, or reads credential contents.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
from official_cli import executable


def probe(service, binary, method):
    with tempfile.TemporaryDirectory(prefix="native-terminal-probe-", dir=ROOT / "work") as tmp:
        home = Path(tmp).resolve()
        if service == "codex":
            (home / "config.toml").write_text(
                'cli_auth_credentials_store = "file"\ncheck_for_update_on_startup = false\n')
        pid, master = pty.fork()
        if pid == 0:
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("OPENAI_", "ANTHROPIC_", "CODEX_", "CLAUDE_"))}
            env.update(TERM="xterm-256color")
            env["CODEX_HOME" if service == "codex" else "CLAUDE_CONFIG_DIR"] = str(home)
            os.chdir(home)
            os.execve(binary, [str(binary)] + (["--no-daemon"] if service == "codex" else []), env)
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        output = bytearray()
        status = None

        def drain(duration):
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                if not select.select([master], [], [], .05)[0]:
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                output.extend(data)
                replies = ((b"\x1b]10;?", b"\x1b]10;rgb:ffff/ffff/ffff\x1b\\"),
                           (b"\x1b]11;?", b"\x1b]11;rgb:0000/0000/0000\x1b\\"),
                           (b"\x1b[6n", b"\x1b[1;1R"), (b"\x1b[?u", b"\x1b[?0u"),
                           (b"\x1b[c", b"\x1b[?1;2c"))
                for query, reply in replies:
                    if query in data:
                        os.write(master, reply)

        try:
            drain(2)
            before = termios.tcgetattr(master)[3]
            if method == "keyboard-ctrl-c":
                os.write(master, b"\x03")
                drain(.3)
                waited, code = os.waitpid(pid, os.WNOHANG)
                if waited:
                    status = code
                else:
                    os.write(master, b"\x03")
            else:
                os.kill(pid, getattr(signal, method))
            drain(2)
            if status is None:
                waited, code = os.waitpid(pid, os.WNOHANG)
                if waited:
                    status = code
            needed_fallback = status is None
            if needed_fallback:
                os.kill(pid, signal.SIGTERM)
                _, status = os.waitpid(pid, 0)
            drain(.1)
            after = termios.tcgetattr(master)[3]
            states, seen = {}, set()
            for mode, value in re.findall(rb"\x1b\[\?([0-9;]+)([hl])", output):
                states[mode.decode()] = value == b"h"
                if value == b"h":
                    seen.add(mode.decode())
            important = ("1000", "1002", "1003", "1006", "1004", "2004", "1049")
            return {"service": service, "method": method, "exit_code": os.waitstatus_to_exitcode(status),
                    "fallback_sigterm": needed_fallback, "capture_bytes": len(output),
                    "canonical_before": bool(before & termios.ICANON),
                    "canonical_after": bool(after & termios.ICANON),
                    "echo_after": bool(after & termios.ECHO),
                    # Positive control: an empty "left" list means nothing unless modes were seen.
                    "modes_seen": sorted(seen),
                    "modes_left_enabled": [mode for mode in important if states.get(mode)],
                    "kitty_push": len(re.findall(rb"\x1b\[>[0-9]*u", output)),
                    "kitty_pop": len(re.findall(rb"\x1b\[<[0-9]*u", output)),
                    "login_file_created": any((home / name).exists()
                                              for name in ("auth.json", ".credentials.json"))}
        finally:
            if status is None:
                try:
                    os.kill(pid, signal.SIGTERM)
                    os.waitpid(pid, 0)
                except ProcessLookupError:
                    pass
            os.close(master)


if __name__ == "__main__":
    for service in ("codex", "claude"):
        binary = executable(service, ROOT / "flipauth")
        for method in ("SIGTERM", "SIGINT", "SIGHUP", "keyboard-ctrl-c"):
            print(json.dumps(probe(service, binary, method)), flush=True)
