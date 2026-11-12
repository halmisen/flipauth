"""Public dispatch. Every active command uses directory accounts."""

import argparse
from pathlib import Path
import sys

import directory_accounts as accounts
import short_commands


RETIRED = {"legacy", "save", "activate", "login", "quota", "doctor", "_managed-daemons"}


def main():
    invocation, script, *values = sys.argv[1:]
    alias = Path(invocation).name in {"claude-switch", "codex-switch"}
    if alias:
        service = Path(invocation).name.removesuffix("-switch")
    else:
        if not values or values == ["--help"]:
            print("Usage: flipauth <cod|cc> NAME [login] [-- CLI arguments]\n"
                  "       flipauth <cod|cc> status [--json]\n"
                  "       flipauth <codex|claude> account --help\n"
                  "Independent account homes; official CLIs own login, refresh and requests.")
            return
        service, *values = values
    service = {"cod": "codex", "cc": "claude"}.get(service, service)
    if service not in {"claude", "codex"}:
        accounts.refuse("unknown service (expected cod/cc or codex/claude)")
    # Existing statusLine hooks may still pipe their payload to observe. There is
    # no snapshot cache or attribution marker in the directory-account model.
    if values[:1] == ["observe"]:
        if not sys.stdin.isatty():
            sys.stdin.buffer.read(1024 * 1024)
        return
    if (values and values[0] in RETIRED) or (alias and values[:1] != ["account"]):
        accounts.refuse("credential snapshots are retired; existing files were left untouched. "
                        "Use flipauth " + service + " account add/run/login with an independent home")
    if values[:1] == ["account"]:
        sys.argv = [sys.argv[0], service, script, *values[1:]]
        accounts.main()
    else:
        sys.argv = [sys.argv[0], service, script, *values]
        short_commands.main()


if __name__ == "__main__":
    try:
        main()
    except (accounts.Refused, OSError, ValueError, argparse.ArgumentTypeError) as exc:
        print("flipauth: " + str(exc), file=sys.stderr)
        sys.exit(1)
