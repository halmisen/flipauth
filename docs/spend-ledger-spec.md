# Spec: `run` / `spend` — a cost ledger for delegated `claude -p` calls

Status: **proposed, not implemented.** Written for adversarial review before any code.

Companion to the shipped quota cache (see `README.md` → *Cached quota in `status`*).
That feature answers *"which account has runway?"*. This one answers *"what did the
automation actually spend?"* — a different question with a different instrument.

---

## 1. Problem

When two coding agents review each other's work, one of them ends up invoking
`claude -p` non-interactively, in a loop, unattended. If the account has overage
billing enabled, exceeding the subscription window does not stop the loop — it starts
charging money. Nothing in that path currently records what was spent, so the first
signal is the invoice.

The naive fix is a threshold that stops the agent at some utilization percentage. That
fix is wrong twice over:

1. **Utilization is not cost.** The percentage describes a rolling window, not dollars.
   It cannot express "how far past the limit did I go".
2. **A threshold decides for you, silently.** What is missing is not an automatic brake,
   it is a number you can see.

## 2. Verified facts this design rests on

Measured against Claude Code `2.1.220` with two live `claude -p` calls. Each fact below
was observed, not inferred.

**`claude -p --output-format json` already reports cost in-band.** The `result` event
carries:

```json
{ "type": "result", "total_cost_usd": 0.0033947, "num_turns": 1, "is_error": false,
  "usage": { "input_tokens": 10, "output_tokens": 39, "cache_read_input_tokens": 31897, ... },
  "modelUsage": { "<model-id>": { "costUSD": 0.0033947, "inputTokens": 10, ... } } }
```

**The same stream reports overage state in-band.** A `rate_limit_event` carries:

```json
{ "type": "rate_limit_event",
  "rate_limit_info": { "status": "allowed", "rateLimitType": "five_hour",
                       "resetsAt": 1790000000, "overageStatus": "allowed",
                       "overageResetsAt": 1790046000, "isUsingOverage": false } }
```

`isUsingOverage` is a direct boolean answer to *"is this call costing money beyond the
subscription?"*. **This is the signal the whole design is built on**, and obtaining it
costs zero extra network requests — it arrives with work you were doing anyway.

**Every `claude -p` call has a fixed cost floor.** In the measurement above the prompt
was 10 input tokens and 39 output tokens, but 31,897 cache-read tokens of system prompt
dominated the price. Cost is therefore close to **independent of task size**: forty
trivial delegated calls can cost more than five substantial ones. Any budgeting
intuition based on "how big was the task" is wrong, which is precisely why the ledger
must count calls, not estimate them.

Scope of that last claim: one sampling, one model (`claude-haiku-4-5`), one machine's
configuration. The absolute floor differs per model — a default of
`--model opus --effort high` will be materially higher. The *shape* of the finding
(fixed floor dominates) is what the design depends on, not the exact figure.

## 3. Non-goals

Stated explicitly because the obvious next step is the wrong one.

- **No automatic stopping, killing, or account rotation.** This tool records; it does not
  decide. Policy belongs to whatever orchestrates the agents.
- **No model downgrading or prompt rewriting.** `run` is a transparent wrapper.
- **No new network calls.** Everything recorded is already in the subprocess output.
- **No dependence on `/api/oauth/usage`.** That endpoint stays where it belongs — the
  offline `status` snapshot. It must not become a cost meter.

## 4. Proposed interface

```sh
flipauth claude run -- <args passed to claude -p>
flipauth claude spend
flipauth claude spend --since 7d
flipauth claude spend --since 24h --by model
```

### `run`

Exactly four responsibilities, in order:

1. Ensure `--output-format json` is present in the child invocation.
2. Execute `claude -p` as a child process, passing through its exit code.
3. Extract an allow-listed set of fields from the `result` and `rate_limit_event`
   events.
4. Append one line to the ledger.

It does not interpret, gate, retry, or modify. If step 3 or 4 fails, the child's exit
code and output still reach the caller unchanged — **recording must never be able to
break the thing it is recording**.

### `spend`

Reads the ledger and prints a summary. Strictly offline, like `status`.

```text
Spend (last 7d, 23 calls):
  Total                                    $1.87
  Of which billed as overage (4 calls)     $0.62

  By model
    claude-opus-4-...       11 calls      $1.44
    claude-haiku-4-5        12 calls      $0.43

  Most expensive single call    $0.31   2026-07-29 14:02  (opus, 6 turns)
  Last call                     just now  overage=no
```

## 5. Ledger format

`$STATE_DIR/.spend-ledger.jsonl` — append-only JSONL, mode `600`, state dir stays `700`.
One line per completed call:

```json
{"schema":1,"ts":"2026-07-31T16:12:03+00:00","profile":"work","label":"review",
 "model":"claude-haiku-4-5","cost_usd":0.0033947,"input":10,"output":39,
 "cache_read":31897,"cache_creation":0,"turns":1,"is_error":false,"duration_ms":4481,
 "using_overage":false,"rate_limit_status":"allowed","overage_status":"allowed",
 "resets_at":1790000000}
```

JSONL rather than a single JSON document so that appending is a single `O_APPEND` write
and a crash mid-write costs at most the last line, never the history.

Same discipline as the quota cache: **fields are copied by an explicit allow-list**, never
by passing the child's output through. Prompts, results, file paths, and tool arguments
are not recorded — the ledger answers *how much*, never *what about*.

## 6. Behaviour contract

1. `run` passes the child's exit code through unchanged.
2. A failed call is still recorded, with `is_error: true` and whatever cost was incurred.
3. If the child produces no parseable `result` event (crash, kill, malformed output), a
   line is still appended with `cost_usd: null` and a `note` field, so a gap in the
   ledger never silently reads as "spent nothing".
4. Ledger write failures print a note to stderr and do not affect the child's exit code.
5. `spend` on a missing ledger prints "no calls recorded", not an error.
6. A corrupt line is skipped with a count of skipped lines in the output — one bad line
   must not hide the rest of the history.
7. `spend` makes no network calls.
8. Neither command records or prints a token.
9. Codex is rejected for both, as it is for `quota`.
10. `run` without `--` is a usage error; arguments are never re-interpreted.

## 7. Deliberately unresolved

**What `status` / `overageStatus` become when a limit is actually reached.** Both
sampled values were `allowed`; the exhausted-state vocabulary was not observed. The
ledger therefore stores these as **opaque strings** and `spend` displays them verbatim.
Encoding a guessed enum now would bake in a fiction. The first real exhaustion event
populates the answer, and only then is it worth branching on.

This is also why the offline pre-flight gate — *"refuse to start a call if the previous
one reported `using_overage: true` and its window has not reset"* — is described here but
**not specified as part of this change**. It is a natural consequence of the ledger and
needs no new data source, but it is a policy decision, and policy is a non-goal above.

## 8. Review questions

For an adversarial reviewer, in descending order of how much a wrong answer costs:

1. Is `isUsingOverage` truly per-call state, or could it be stale within a session such
   that a call that *did* incur overage reports `false`? A false negative here defeats the
   entire purpose.
2. Does `total_cost_usd` cover subagents spawned inside the delegated call, or only the
   top-level turns? If it under-counts, the ledger under-reports exactly when spend is
   highest.
3. Is appending to JSONL from concurrent `run` invocations safe in practice? Lines are
   written with a single `O_APPEND` write, but is the line size reliably under the atomic
   write limit once `modelUsage` grows?
4. Does wrapping `claude -p` change its behaviour in any way that matters — TTY detection,
   signal handling on Ctrl-C, stdin passthrough for `--input-format stream-json`?
5. Is putting this in `flipauth` right at all? It was a credential switcher. The argument
   for is that it already owns the profile model and the same offline-replay shape; the
   argument against is that "records agent spend" is a different job, and the boundary is
   held only by the non-goals in §3.
