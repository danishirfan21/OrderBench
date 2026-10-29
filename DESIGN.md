# OrderBench design notes

## Why pass/fail on held-out tests, not a judge model

The reward is the exit state of a test run: every `fail_to_pass` test passes and every `pass_to_pass`
test still passes. A judge model reading a diff would be cheaper to author for, but it is a poor
reward signal. It is non-deterministic, it is itself an attack surface (a patch can contain a comment
addressed to the grader), it drifts across model versions, and it rewards diffs that *look* like fixes.
Tests execute the behaviour. They are cheap to rerun, bit-reproducible, and they fail closed: a
plausible-looking but wrong patch scores zero. The price is authoring cost and brittleness at the
edges, discussed under limitations.

"Held-out" matters as much as "tests". The visible suite in `tests/` is deliberately blind to every
injected bug; `validate-all` enforces this by running the whole visible suite on each broken tree and
requiring it to be green. If a visible test failed, the agent would be handed the reproduction for
free, and a model could also tune against it. The tests that define success are copied into the
workspace only at evaluation time.

## What it teaches, and what it does not

The tasks reward localization from a symptom-level report, reading the domain notes (`app/DOMAIN.md`)
to learn the intended behaviour, and fixing causes. Several bugs are *latent* in the code path an
agent is likely to inspect first: the order-access bug only misfires for some order ids; the
timezone bug only appears on rows read back from the database. An agent that never writes its own
reproduction will tend to miss them.

It does not teach large-scale design, working in an unfamiliar framework from scratch, performance
engineering, or collaboration. The app is about 1,600 lines and every task is a single-commit
regression; real maintenance work involves ambiguity, partial specs and multi-file refactors that
eight tasks cannot sample. Eight tasks is also a small sample: a resolve rate has a wide confidence
interval, and it is a sanity benchmark more than a leaderboard.

## Why pass_to_pass tests exist

`fail_to_pass` alone measures "did the symptom go away". Most wrong fixes make the symptom go away:
loosen a check, delete a failing branch, catch the exception. `pass_to_pass` encodes everything that
was already correct, so a fix that buys its F2P tests with a regression is not rewarded.

Two tasks document this explicitly through a `trap`:

* `fractional_quantity`: marking the field `strict=True` rejects `2.5` and `0`, so all new tests pass,
  but it also rejects the string `"3"` and float `3.0`, which rule O-2 requires to keep working.
* `failed_order_reservations`: calling `rollback()` and dropping the audit write releases the stock
  but loses the record of the rejection, which rule O-3 requires.

`harness_tests/test_traps.py` runs each trap patch through the real pipeline and asserts F2P green,
P2P red, `resolved: false`. The traps are therefore executable claims, not prose.

## Reward hacking: how it could occur, and what blocks it

| Attack | Mitigation |
|---|---|
| Edit or delete the tests, add `conftest.py`, change `pytest.ini` | Explicit **allowlist**: only `app/**/*.py` is modifiable, and `conftest.py`, `sitecustomize.py`, `usercustomize.py`, `__main__.py` are refused everywhere. Anything else yields `tamper_detected: true` before a single test runs. |
| Hide the hack inside an allowed file: patch pytest, `sys.modules`, `builtins`, `atexit`, assertion rewriting, `unittest.mock` | A content scan over *added* lines in allowed files rejects those constructs. This is a denylist and therefore incomplete (see limitations); it exists to catch the unsophisticated attack cheaply. |
| Special-case the tests (read test files or env to detect grading) | Held-out tests do not exist in the agent's workspace; references to `tests/`, `orderbench` or `ORDERBENCH_` in added code are rejected. |
| Tamper at runtime, writing files during the test run | The harness hashes every file outside `app/` before and after the run; any difference is `tamper_detected`. In Docker the workspace is mounted read-only. |
| Print a fake pass line | Results come from a harness-owned pytest plugin (`orderbench.guard`) writing per-node outcomes to a file the tests do not control; console output is never parsed. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` stops third-party plugin injection. |
| Exfiltrate or fetch a solution over the network | Docker: `--network none`. Local backend: the guard plugin refuses non-loopback `connect` and name resolution. |
| Flaky luck | Frozen clock fixture, injectable `Clock` in the app, seeded randomness, per-test database files. |

None of this is a proof. A sufficiently determined patch inside `app/` could still do something
perverse. The mitigations are meant to make honest solving the cheapest path and to make the common
shortcuts loud, not to make cheating impossible.

## Realism versus determinism

These pull against each other. Real backends read the wall clock, use the network, run concurrent
requests and depend on the OS. Each is a source of flakiness, and flaky rewards are noise in the
training signal. OrderBench resolves the tension by moving the non-determinism behind seams the app
already needs: an injected `Clock`, a configurable password cost, SQLite files per test, and no
outbound calls at all. The concurrency bug (`stale_stock_reservation`) is the hard case. It is
reproduced by interleaving two sessions deterministically (the stale read is forced between read and
write), not by racing threads, so the test is stable but is a *model* of the race, not the race. The
two held-out tests cover both symptoms (an oversell and a lost update), so only a check-and-update
that is atomic at the database passes, but real thread-level races are not exercised.

Determinism also covers the toolchain: dependencies are pinned with sha256 hashes (`requirements.lock`
installed with `--require-hashes --no-deps`), the base image is pinned by digest, and
`harness_tests/test_determinism.py` asserts that two identical evaluations produce byte-identical
verdicts apart from `duration_seconds`.

## Known limitations

* **Docker was not available where this was developed.** The Docker backend is implemented and
  wired into CI, but it has never been run by the author; the local fallback is what was run. The local backend's
  network block is in-process only and it offers no filesystem isolation, so its verdicts report
  `image_digest: "local-sandbox"` and should not be trusted for adversarial agents.
* The content scan is a denylist and can be bypassed by obfuscation (for example building a name
  from string pieces). The allowlist is the real boundary; the scan is defence in depth.
* Held-out tests can overfit to the golden fix. Alternative correct solutions that change a public
  response shape could fail them; the statements pin the observable behaviour to limit this.
* Eight tasks, one codebase, one language. Contamination is possible once the repository is public:
  a model trained on it has seen the golden patches.
* SQLite stands in for a production database, so isolation-level bugs that need a real server cannot
  be represented faithfully.
* Binary reward gives no partial credit; a dense signal would need per-test shaping, which invites
  its own hacking.
