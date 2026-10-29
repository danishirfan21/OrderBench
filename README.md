# OrderBench

An RL environment for training and evaluating coding agents on realistic Python backend bugs.

## What it is

OrderBench is a small but realistic FastAPI order-and-inventory service (SQLAlchemy 2.0, Pydantic v2,
token auth, pagination and filtering, stock reservation, subscription proration, background tasks)
plus **8 bug-fixing tasks** cut from it. Each task is a regression an engineer could plausibly have
shipped: an off-by-one in pagination, a missing rollback, an authorization check applied to the wrong
object, a timezone-naive datetime, a lost update under concurrency, a billing-anchor drift.

An agent receives the broken repository and a bug report written the way a customer or colleague
would write it (no file or function names). It returns a unified diff. The environment applies the
diff to a clean checkout and runs **held-out tests** the agent never saw (`fail_to_pass`) together
with regression tests (`pass_to_pass`). The reward is binary: resolved or not.

It trains and measures: reading unfamiliar code, localizing a fault from symptoms, reproducing before
fixing, fixing the cause instead of the symptom, and not breaking neighbouring behaviour. Two tasks
carry a documented *trap* — a tempting shallow fix that satisfies the new tests but violates existing
behaviour. See [DESIGN.md](DESIGN.md) for why it is built this way and where it falls short.

| Task | Difficulty | Bug class | Trap |
|---|---|---|---|
| `pagination_offset` | easy | off-by-one in pagination offset | no |
| `fractional_quantity` | easy | validator silently coerces instead of rejecting | **yes** |
| `failed_order_reservations` | medium | missing rollback on a failure path | **yes** |
| `reservation_sweep_timezone` | medium | naive vs aware datetime comparison | no |
| `order_list_joined_totals` | medium | join "optimisation" breaks pagination and totals | no |
| `order_access_check` | medium | authorization check on the wrong object | no |
| `stale_stock_reservation` | hard | stale read / lost update in stock reservation | no |
| `subscription_anchor_drift` | hard | proration / period arithmetic at month boundaries | no |

## Quickstart

```bash
make install                      # hash-pinned dependencies + the `orderbench` CLI
make validate                     # every task: broken fails, golden passes, traps behave
python examples/run_agent.py      # score a stub agent across all 8 tasks, print the resolve rate
```

`make validate` uses Docker when a daemon is reachable and otherwise falls back to a local
subprocess sandbox (see [Backends](#backends)). Requires Python 3.12+ and `make`.

## Task format

Each task lives in `tasks/<id>/`:

```
tasks/<id>/
  task.yaml      metadata and test ids (below)
  break.patch    unified diff that introduces the bug into the clean app
  golden.patch   reference fix (never shown to an agent)
  trap.patch     (optional) the documented shallow fix, used by the harness tests
  tests/         held-out fail_to_pass tests; copied in only at evaluation time
```

`task.yaml` fields:

| Key | Type | Meaning |
|---|---|---|
| `id` | string | equals the directory name |
| `title` | string | one-line summary |
| `difficulty` | `easy` \| `medium` \| `hard` | |
| `bug_class` | string | taxonomy label |
| `statement` | string | the bug report shown to the agent; never names a file or function |
| `fail_to_pass` | list of pytest node ids | fail on the broken tree, must pass after the fix. Live under `tests/held_out/<id>/` |
| `pass_to_pass` | list of pytest node ids | pass on both trees and must still pass |
| `timeout_seconds` | int | wall-clock limit per test phase |
| `trap` | optional mapping | `shallow_patch`, `description`, `why_it_fails` |

A candidate patch is a git-style unified diff (`a/` / `b/` prefixes; modifications, additions and
deletions only; no renames, mode changes or binary files). It may only touch Python modules under
`app/`.

### CLI

```bash
orderbench list
orderbench prepare --task pagination_offset --out ./work     # broken checkout + TASK.md
orderbench evaluate --task pagination_offset --patch fix.diff --json
orderbench validate-all
```

`evaluate` exits 0 only if the task is resolved, and prints this verdict:

```json
{
  "task_id": "pagination_offset",
  "resolved": true,
  "fail_to_pass": {"passed": ["..."], "failed": []},
  "pass_to_pass": {"passed": ["..."], "failed": []},
  "patch_applied": true,
  "timed_out": false,
  "tamper_detected": false,
  "duration_seconds": 12.4,
  "image_digest": "sha256:..."
}
```

## Plugging it into an agent loop

```python
from pathlib import Path
from orderbench.evaluate import broken_checkout, evaluate, find_repo_root
from orderbench.runner import select_backend
from orderbench.tasks import load_all

root = find_repo_root()
backend = select_backend(root)
for task in load_all(root / "tasks"):
    broken_checkout(root, task, workdir := Path("/tmp") / task.id)
    patch = my_agent(workdir, task.statement)          # your agent edits files, returns a diff
    verdict = evaluate(root, task, patch, backend)
    reward = 1.0 if verdict["resolved"] else 0.0
```

[`examples/run_agent.py`](examples/run_agent.py) is the runnable version: it takes any callable
`(workspace, task) -> None`, diffs what the agent changed under `app/`, evaluates each of the 8 tasks
and prints the resolve rate. The bundled stubs are an `oracle` agent (applies the golden patch,
expect 8/8) and an `empty` agent (expect 0/8):

```bash
python examples/run_agent.py --agent oracle
python examples/run_agent.py --agent empty
```

## Backends

| Backend | Isolation | Digest in verdict |
|---|---|---|
| `docker` (reference) | image pinned by sha256 digest, `--network none`, read-only root, all capabilities dropped, non-root uid 10001, workspace mounted read-only | the image digest |
| `local` (fallback) | plain subprocess; network blocked **in-process only** by the pytest guard plugin; no filesystem isolation beyond the tamper checks | `local-sandbox` |

`--backend auto` (default) picks Docker when a daemon is reachable and warns when it falls back.
The local backend exists so the environment can be developed and validated without Docker; use Docker
for any evaluation whose result you intend to trust. Rewards from the two backends are expected to
agree on honest patches, but only Docker enforces the isolation claims in DESIGN.md.

## Development

```bash
make test      # visible app suite + harness tests
make lint      # ruff check, ruff format --check, mypy (strict)
make format
```

The patches under `tasks/` are generated from exact text edits by `scripts/build_tasks.py`;
`scripts/write_task_yaml.py` collects node ids from the real test files; `scripts/make_locks.py`
regenerates the hashed lock files. MIT licensed.
