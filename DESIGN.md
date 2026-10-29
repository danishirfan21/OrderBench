# OrderBench design notes

## Why pass/fail on held-out tests, not a judge model

The reward is the exit state of a test run: every `fail_to_pass` test passes and every `pass_to_pass`
test still passes. A judge model reading a diff is cheaper to author for but a poor
reward signal: it is non-deterministic, it is itself an attack surface (a patch can address the
grader in a comment), it drifts across model versions, and it rewards diffs that *look* like fixes.
Tests execute the behaviour, are bit-reproducible, and fail closed: a plausible but wrong patch
scores zero. The price is authoring cost and brittleness at the edges.

"Held-out" matters as much as "tests". The visible suite in `tests/` is deliberately blind to every
injected bug; `validate-all` enforces this by running the whole visible suite on each broken tree and
requiring it to be green. A failing visible test would hand the agent the reproduction for free. The tests that define
success are copied into the workspace only at evaluation time.

## What it teaches, and what it does not

The tasks reward localization from a symptom-level report, reading the domain notes (`app/DOMAIN.md`)
to learn the intended behaviour, and fixing causes. Several bugs are *latent*: the order-access bug only misfires for some
order ids, the timezone bug only on rows read back from the database. An agent that never writes its
own reproduction will tend to miss them.

It does not teach large-scale design, performance engineering, or collaboration. The app is about 1,600 lines and every task is a single-commit
regression; real work involves ambiguity and multi-file refactors that eight tasks cannot sample.
A resolve rate over eight tasks has a wide confidence interval: this is a sanity benchmark, not a
leaderboard.

## Why pass_to_pass tests exist

`fail_to_pass` alone measures "did the symptom go away", which most wrong fixes achieve: loosen a
check, delete a failing branch, catch the exception. `pass_to_pass` encodes what was already correct,
so a fix that buys its F2P tests with a regression is not rewarded.

Two tasks document this explicitly through a `trap`:

* `fractional_quantity`: marking the field `strict=True` rejects `2.5` and `0`, so all new tests pass,
  but it also rejects the string `"3"` and float `3.0`, which rule O-2 requires to keep working.
* `failed_order_reservations`: calling `rollback()` and dropping the audit write releases the stock
  but loses the record of the rejection, which rule O-3 requires.

`harness_tests/test_traps.py` runs each trap patch through the real pipeline and asserts F2P green,
P2P red, `resolved: false`. The traps are therefore executable claims, not prose.

## What validation caught

Three of the eight tasks were defective when first written, and `validate-all` rejected each before
publication. Two were visible-test leaks. In `pagination_offset`, visible audit tests read
`items[0]` from page one, so the offset bug broke them. In `order_access_check`, visible tests paid
and cancelled orders as the owner, which only passed when order id happened to equal user id. Shipped,
either would have shown red tests on the untouched repository: a free reproduction, so reward would
have measured test-reading, not debugging. The
protocol step that caught both is the leak check, which requires the entire visible suite and every
`pass_to_pass` test to be green on the broken tree.

The third, `stale_stock_reservation`, failed the opposite check. Its held-out tests were meant to
fail on the broken code but passed: the test discarded its reference to the stock row, SQLAlchemy's
weak identity map garbage-collected it, and the "stale read" never occurred. Shipped, the unfixed
code would have resolved the task, so every agent, including one that submitted an empty patch,
would have earned full reward on the hardest task. The step that caught it is the requirement that
the empty patch must not resolve and every `fail_to_pass` test must fail on the broken tree.

Each task looked correct on reading. They surfaced only because validation executes every claim a
task makes instead of trusting it, and CI now repeats that under Docker on every push.

## Reward hacking: how it could occur, and what blocks it

| Attack | Mitigation |
|---|---|
| Edit or delete the tests, add `conftest.py`, change `pytest.ini` | Explicit **allowlist**: only `app/**/*.py` is modifiable, and `conftest.py`, `sitecustomize.py`, `usercustomize.py`, `__main__.py` are refused everywhere. Anything else yields `tamper_detected: true` before a single test runs. |
| Hide the hack inside an allowed file: patch pytest, `sys.modules`, `builtins`, `atexit`, assertion rewriting, `unittest.mock` | A content scan over *added* lines in allowed files rejects those constructs. This is a denylist and therefore incomplete (see limitations); it exists to catch the unsophisticated attack cheaply. |
| Special-case the tests | Held-out tests do not exist in the agent's workspace; references to `tests/`, `orderbench` or `ORDERBENCH_` in added code are rejected. |
| Tamper at runtime, writing files during the test run | The harness hashes every file outside `app/` before and after the run; any difference is `tamper_detected`. In Docker the workspace is mounted read-only. |
| Print a fake pass line | Results come from a harness-owned pytest plugin (`orderbench.guard`) writing per-node outcomes to a file the tests do not control; console output is never parsed. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` stops third-party plugin injection. |
| Exfiltrate or fetch a solution over the network | Docker: `--network none`. Local backend: the guard plugin refuses non-loopback `connect` and name resolution. |
| Flaky luck | Frozen clock fixture, injectable `Clock`, `PYTHONHASHSEED=0`, per-test database files. |

None of this is a proof. A determined patch inside `app/` could still do something perverse; the
goal is to make honest solving the cheapest path and the common shortcuts loud.

## Realism versus determinism

Real backends read the wall clock, use the network and run concurrent requests; each is a source of
flakiness, and flaky rewards are noise in the training signal. OrderBench moves the non-determinism
behind seams the app needs anyway: an injected `Clock`, a configurable password cost, SQLite files
per test, and no outbound calls. The concurrency bug (`stale_stock_reservation`) is the hard case. It is
reproduced by interleaving two sessions deterministically, not by racing threads, so the test is
stable but is a *model* of the race. The
two held-out tests cover both symptoms (oversell, lost update); real thread-level races are not
exercised.

The toolchain is pinned too: hashed lock files (`--require-hashes --no-deps`), a base image pinned by
digest, and a test (run in CI under Docker) asserting that two identical evaluations produce
byte-identical verdicts apart from `duration_seconds`.

## Known limitations

* **The reference environment is GitHub Actions with Docker, not the author's laptop.** The author
  has no local Docker; every claim of validity rests on the CI run (badge in the README). The local
  backend is for iteration: it blocks the network in-process only and gives no filesystem, process or
  network-namespace isolation, so it must not be used to score an adversarial agent.
* The content scan is a denylist and can be bypassed by obfuscation (for example building a name
  from string pieces). The allowlist is the real boundary; the scan is defence in depth.
* Held-out tests can overfit to the golden fix; the statements pin observable behaviour to limit this.
* Eight tasks, one codebase, one language. Once the repository is public, a model trained on it has
  seen the golden patches.
* SQLite stands in for a production database, so isolation-level bugs cannot be represented faithfully.
* Binary reward gives no partial credit; a dense signal would invite its own hacking.
