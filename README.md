# flipauth

A CLI that switches between multiple saved OAuth login profiles for the official
**Claude Code CLI** and **official Codex CLI**.

**Supported platform: Windows WSL only.**
macOS and native Windows are not supported or tested.

---

## What it does

`flipauth` copies your live credential file(s) into per-profile snapshots stored
under `~/.claude/oauth-accounts/` or `~/.codex/oauth-accounts/`, then swaps them
atomically when you activate a different profile.  It also provides `status` and
`doctor` subcommands to inspect the current state.

---

## Install

```sh
git clone https://github.com/your-org/flipauth.git ~/flipauth

# Option A — add repo dir to PATH
echo 'export PATH="$HOME/flipauth:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Option B — symlink into an existing bin dir
ln -s ~/flipauth/flipauth       ~/bin/flipauth
ln -s ~/flipauth/claude-switch  ~/bin/claude-switch
ln -s ~/flipauth/codex-switch   ~/bin/codex-switch
```

---

## Usage

### Invocation forms

`flipauth` dispatches on the program name used to invoke it:

| Invocation | Service resolved |
|---|---|
| `flipauth claude <cmd>` | Claude Code |
| `flipauth codex <cmd>`  | Codex |
| `claude-switch <cmd>`   | Claude Code (shorthand) |
| `codex-switch <cmd>`    | Codex (shorthand) |

### Commands

#### Save the currently active credentials as a named profile

```sh
flipauth claude save A
flipauth codex  save A

# or with shorthands
claude-switch save A
codex-switch  save A
```

#### Activate a saved profile

```sh
flipauth claude A
flipauth codex  B

claude-switch A
codex-switch  B
```

#### Show which profile is active and list all saved profiles

```sh
flipauth claude status
flipauth codex  status

claude-switch status
codex-switch  status
```

#### Diagnose the local credential state

```sh
flipauth claude doctor
flipauth codex  doctor

claude-switch doctor
codex-switch  doctor
```

#### Log in fresh and save directly as a named profile (Claude only)

```sh
flipauth claude login A
claude-switch login A
```

Runs `claude auth login` in a temporary isolated config dir, then copies the
resulting credentials into profile `A`.  If `A` is already the active profile
it also refreshes the live credential file.

---

## Windows-side Codex auth path

`codex doctor` can compare the WSL credential against the Windows-side
`auth.json` to tell you whether both sides are logged in to the same account.

To enable this, set the path explicitly:

```sh
export CODEX_SWITCH_WINDOWS_AUTH="/mnt/c/Users/<YourWindowsUser>/.codex/auth.json"
```

If the variable is unset, `flipauth` attempts auto-detection via `wslvar` /
`cmd.exe`.  If detection fails the field is reported as `not configured` and
the cross-side comparison is simply skipped — no error.

---

## How it works / safety

* Profiles are stored under `~/.{claude,codex}/oauth-accounts/<profile>.<suffix>`
  with mode `600`.  The directory is `700`.  Credential files are never written
  world-readable.
* Copies are atomic: written to a temp file with `mktemp`, then `mv`-renamed
  into place.
* **Always exit the running claude / codex session before switching.**
  A live process keeps its token in memory; if you swap the file while it is
  running the process may re-save its in-memory token and overwrite the profile
  you just activated.
* OAuth refresh tokens are single-use / rotating.  Never have the same account
  active in two places simultaneously — the second refresh will invalidate the
  first session's token.
* Credential files are secrets.  They are listed in `.gitignore` and must never
  be committed.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_SWITCH_CLAUDE_DIR` | `~/.claude` | Claude config directory |
| `CLAUDE_SWITCH_STATE_DIR` | `$CLAUDE_SWITCH_CLAUDE_DIR/oauth-accounts` | Where profiles are stored |
| `CLAUDE_SWITCH_CREDENTIALS_FILE` | `~/.claude/.credentials.json` | Live Claude credential file |
| `CODEX_SWITCH_CODEX_DIR` | `~/.codex` | Codex config directory |
| `CODEX_SWITCH_STATE_DIR` | `$CODEX_SWITCH_CODEX_DIR/oauth-accounts` | Where profiles are stored |
| `CODEX_SWITCH_AUTH_FILE` | `~/.codex/auth.json` | Live Codex auth file |
| `CODEX_SWITCH_CREDENTIALS_FILE` | `~/.codex/.credentials.json` | Live Codex credentials file |
| `CODEX_SWITCH_WINDOWS_AUTH` | *(auto-detect)* | Path to Windows-side `.codex/auth.json` |

---

## License

MIT — see [LICENSE](LICENSE).
