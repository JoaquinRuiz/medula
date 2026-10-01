<div align="center">

# Médula

**Several coding agents, one repository, at the same time. Who should wait for whom, and when?**

A small, fully reproducible lab for measuring how coding agents coordinate, and **Médula**, a kernel
that coordinates them: before every write it asks a fast decider whether the change collides with
what the other agents are doing.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Bash](https://img.shields.io/badge/Bash-4EAA25?logo=gnubash&logoColor=white)](./bench/)
<br>
[![Claude Code](https://img.shields.io/badge/agents-Claude%20Code-D97757?logo=anthropic&logoColor=white)](https://claude.com/claude-code)
[![Sonnet 5](https://img.shields.io/badge/model-claude--sonnet--5-D97757?logo=anthropic&logoColor=white)](https://openrouter.ai/anthropic/claude-sonnet-5)
[![OpenRouter](https://img.shields.io/badge/via-OpenRouter-6566F1?logo=openrouter&logoColor=white)](https://openrouter.ai/)
[![Jev](https://img.shields.io/badge/fast%20decider-TypeSafe%20Jev-555555)](https://openrouter.ai/typesafe/jev-1.13)
<br>
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Tests need no API key](https://img.shields.io/badge/tests-no%20API%20key%20needed-brightgreen.svg)](#try-it-in-two-minutes-no-api-key)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#help-wanted-the-open-problems)
[![Raw evidence](https://img.shields.io/badge/runs-raw%20evidence%20published-informational)](./results/)

</div>

---

Six tasks on a room-booking API, written to collide in known ways. Six coordination modes. The same
agents (Claude Code, `anthropic/claude-sonnet-5`) in every mode, and every run published raw: agent
sessions, diffs, evaluations and each decision the kernel took.

What the first matrix of runs says:

- **Branches hide semantic conflicts.** Git merges the six branches without a single conflict on the
  code, and the result is broken: `/export` still calls `login(username, password)` after `login()`
  started requiring a second factor. 6 red tests in every mode B run.
- **With Médula, both real conflicts are caught in every run with no unnecessary blocks** (mode D),
  at the same total cost as classic per-file locks, which block things that don't collide.
- **The fast decider is almost free but unsure on real states.** Jev decides in about 0.3 s for
  $0.00006, yet 61 % of its decisions on real write requests fall in the "not sure" band and go to
  the slow path (Sonnet, then Opus). That is the biggest open problem, and where you can help.

## Try it in two minutes (no API key)

Everything below runs offline and costs nothing: the tests mock the model provider.

```sh
git clone https://github.com/JoaquinRuiz/medula.git && cd medula
uv sync && (cd demo-app && uv sync) && (cd medula && uv sync)

(cd medula && uv run pytest)     # the kernel: 69 tests, simulated provider, a real server and hook script
bench/self_check.sh              # the collision design: every pair merges cleanly in git,
                                 # yet merging all six breaks exactly T2, T4 and integration
```

Then look at a real decision: `results/runs/d1/medula.db` is a SQLite file with every question Médula
asked, the answer, the probability, the latency and the cost.

## Help wanted: the open problems

These come straight out of the published runs. Each one is concrete, has data behind it and a
place in the code to start from. Comment on its issue to claim it or to discuss an approach
([all open issues](https://github.com/JoaquinRuiz/medula/issues/?q=is%3Aopen+label%3A%22help+wanted%22), [good first issues](https://github.com/JoaquinRuiz/medula/issues/?q=is%3Aopen+label%3A%22good+first+issue%22)).

1. **Human labels for the calibration set** ([#1](https://github.com/JoaquinRuiz/medula/issues/1)) · *no code, highest value.* The 100 calibration pairs
   and their labels were written by a model of the same family as two of the deciders, which likely
   flatters them. Label them yourself, blind, in your own file:
   `uv run bench/e04_etiquetar.py --salida calibration/etiquetas_humanas/<your-github-user>.yaml`
   (about 20–30 minutes; `c` collides, `n` doesn't, `d` unsure). `uv run bench/acuerdo_etiquetas.py`
   shows how you agree with the model and with other people.
2. **Calibration pairs that look like real runs** ([#2](https://github.com/JoaquinRuiz/medula/issues/2)) · *no code or light code.* In calibration, 13 % of
   Jev's decisions were unsure; in real runs, 61 %. Real states have several agents and long
   intentions; the calibration pairs have one of each. New pairs in `calibration/candidatas.yaml`,
   or a script that extracts them from the `medula.db` of past runs, would close that gap.
3. **Signature changes on the fast path** ([#3](https://github.com/JoaquinRuiz/medula/issues/3)) · *code.* Jev ranks the real T1–T2 conflict (`login()` gaining a
   required parameter) below a false one, and it's the slow path that catches it. Two ideas were measured and rejected
   (`bench/e04b_firma.py`: a shared-symbol rule and a directional question); better ones are welcome.
   Start at `medula/src/medula/intencion.py` (how the intent is built) and `decisores/jev.py`.
4. **A new decider** ([#4](https://github.com/JoaquinRuiz/medula/issues/4)) · *code.* Any model or rule that answers "does this collide?" with a
   probability fits the same interface (`medula/src/medula/decisores/`): a local model, another
   provider, a static analyser. Measure it on the calibration set and it can run the whole matrix.
5. **A robust slow path** ([#5](https://github.com/JoaquinRuiz/medula/issues/5)) · *light code.* In the published runs, Sonnet sometimes answered with JSON
   the kernel couldn't parse, or hit the 30 s timeout, and the decision escalated for nothing. See `medula/src/medula/camino_lento.py`.
6. **More scenarios** ([#6](https://github.com/JoaquinRuiz/medula/issues/6)) · *no code, mostly tests.* The six tasks cover a changed signature and a
   renamed field. A changed behaviour with the same signature, a schema migration, a dependency
   bump: each one needs a task, acceptance tests and a line in `ground_truth.yaml`.
7. **More runs** ([#7](https://github.com/JoaquinRuiz/medula/issues/7)) · *costs money, no code.* Modes E and F have few runs, and F's only run had agents
   messaging each other (see the caveats). If you have credit, `bench/run_matrix.sh` resumes the
   matrix and records everything; send the evidence in a PR.

### Good first contributions

| Difficulty | What | Where |
|---|---|---|
| 🟢 No code | Label the calibration pairs (blind, in your own file) | `calibration/etiquetas_humanas/` |
| 🟢 No code | Argue a label you disagree with, in an issue | `calibration/etiquetas.yaml`, `ground_truth.yaml` |
| 🟢 No code | Propose new calibration pairs | `calibration/candidatas.yaml` |
| 🟡 No code | Add a scenario: task, acceptance tests, ground truth | `tasks/`, `acceptance/`, `ground_truth.yaml` |
| 🟡 Light | Make the slow path robust to unparseable answers and timeouts | `medula/src/medula/camino_lento.py` |
| 🔴 Code | Extract calibration pairs from real runs | `results/runs/*/medula.db` → `calibration/` |
| 🔴 Code | A new decider, or a better intent for signature changes | `medula/src/medula/decisores/`, `intencion.py` |

Disagree with a label or with how a conflict is defined? **That's a contribution, not a complaint**:
the ground truth is opinion made inspectable. Open an issue with your reasoning.

### Before you send a PR

```sh
(cd medula && uv run pytest)                    # kernel; the model provider is simulated
(cd demo-app && uv run pytest)                  # the demo app
bench/self_check.sh                             # the collision design still holds
uv run python bench/lib/check_ground_truth.py   # the ground truth covers the 15 pairs
```

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the data formats, how to add a decider or a scenario,
and how to contribute runs.

### What won't be merged

- **Tests that need an API key or money.** Anyone must be able to check a change for free.
- **Hand edits to published results.** A run's evidence is what the run produced. Fixing a test and
  re-evaluating is fine (`bench/reevaluar.sh` records why); editing `summary.csv` or a log is not.
- **Hiding a caveat.** If a run is flawed, it gets flagged, not quietly dropped.

## How it works

### The six tasks

| Task | What it does | Collides with | Kind |
|---|---|---|---|
| T1 | Adds a TOTP second factor; `login()` now requires `otp` | T2 | semantic: different file, same contract |
| T2 | `GET /export` in CSV, authenticating via `login(username, password)` | T1 | semantic |
| T3 | Renames the booking field `fecha` → `inicio` in model, DB and API | T4 | semantic |
| T4 | `GET /reservas?desde=YYYY-MM-DD`, filtering on `fecha` in SQL | T3 | semantic |
| T5 | Rewrites the error messages of `validar_sala()` | — | false conflict: same file as T6 |
| T6 | Adds the 8:00–20:00 rule to `validar_horario()` | — | false conflict |

Acceptance tests are always evaluated on the final state with all six tasks applied, so they target
the final contract: every authenticated call sends the OTP, and bookings use `inicio`.

### The modes

| Mode | What it is |
|---|---|
| A | Sequential: one agent after another in the same directory |
| B | One branch per task, merge at the end; textual conflicts are resolved by an agent |
| C | Shared directory, classic per-file locks (Médula with the `locks` decider) |
| D | Shared directory, Médula with Jev as the fast decider |
| E | Shared directory, Médula with Haiku as the fast decider |
| F | Shared directory, Médula with Sonnet as the fast decider |

Same spec, same agents (Claude Code, `anthropic/claude-sonnet-5`, effort high) and same model in every
mode. Rounds: T1–T4 in parallel, then T5–T6.

### What Médula does

```
agent wants to Edit / Write / Bash
        │  PreToolUse hook
        ▼
  Médula builds the intent: the agent's task + the file, diff or command
        │  reads never wait
        ▼
  fast decider: "does this collide with what each other agent is doing?"  → probability p
        │
        ├── p below the low threshold  → go ahead
        ├── p above the high threshold → wait until the other agent finishes
        └── in between                 → slow path: Sonnet proposes a way out, Opus if it can't
                                         (never one that breaks a task's acceptance criteria)
after every write (PostToolUse): "does this change invalidate another agent's plan?" → notice in its mailbox
```

The kernel's design, decisions and trade-offs are in [`medula/SPEC.md`](./medula/SPEC.md) and
[`medula/README.md`](./medula/README.md).

## Results

Per-run data is in `results/summary.csv`; everything behind it (agent sessions, final diff,
evaluation, Médula's SQLite with every decision) is in `results/runs/<run-id>/`. Charts in
`results/graficos/`. Averages over the valid runs of the matrix:

| Mode | Runs | Tests green / red | Real conflicts detected (of 2) | Unnecessary blocks | Total time | Agents cost | Decision cost | Decisions | Slow-path escalations |
|---|---|---|---|---|---|---|---|---|---|
| A | a1, a2 | 30 / 7 | — | — | 341 s | $0.86 | — | — | — |
| B | b1–b5 | 31 / 6 | — (git: 2 textual conflicts per run, resolved) | — | 329 s | $1.20 | $0.40 (conflict resolution) | — | — |
| C | c1–c3 | 37 / 0 | 1.7 | 1.7 | 452 s | $1.65 | $0 | 88 | 0 |
| D | d2–d4 | 37 / 0 | 2.0 | 0 | 415 s | $1.36 | $0.29 | 118 | 20 |
| E | e1–e3 | 37 / 0 | 2.0 | 1.0 | 824 s | $1.74 | $0.55 | 149 | 22 |
| F | f1 | 37 / 0 | 2.0 | 0 | 376 s | $1.40 | $0.59 | 114 | 9 |

Times use only runs that did not overlap with another run (`tiempo_fiable` in `summary.csv`).

- **A shared directory changes the game.** In modes C–F agents see each other's code and adapt, so
  all of them end green. What Médula changes is how they get there: fewer unnecessary blocks than
  locks, and conflicts caught before the code is written.
- **In sequential mode A, the T2 agent detects the conflict and refuses** to implement a login
  without the second factor, asking for a confirmation that never comes in non-interactive mode.
- **Most of mode D's decision cost is the slow path**: about 20 escalations per run, one in six of
  all decisions. Only write requests can escalate, and 61 % of Jev's decisions on write requests
  fell in the uncertain band.

### Calibration

The kernel asks each decider for a collision probability. On the 100 calibration pairs
(`calibration/`, 2 repetitions): Jev 92.5 %, Haiku 91.5 %, Sonnet 98.5 % accuracy at p > 0.5. Jev
ranks cases very well but its probabilities are compressed towards the middle (chart:
`results/e04b/calibracion/`). Thresholds per decider (`calibration/umbrales.yaml`) were chosen with one
rule: maximum fast-path coverage with ≥ 95 % accuracy, no more missed conflicts than with 0.2/0.8,
and at most one extra false alarm.

### Caveats

- **Unreliable times: a1, b2, b3.** These runs overlapped in time with another run, so they count for
  tests and cost but not for time (`tiempo_fiable = False` in `summary.csv`). Mode A's time comes
  from a2; mode B's from b1, b4 and b5.
- **Agent-to-agent channels in e1 and f1.** Some agents used Claude Code's `ListAgents`/`SendMessage`
  tools to reach each other outside Médula: in f1, five messages (T3 told T4 about the
  `fecha` → `inicio` rename); in e1, a single listing with no message. Both runs are kept and flagged
  (`canal_entre_agentes` in `summary.csv`). Those tools are now disabled for every agent.
- **Thresholds fitted on the same pairs they are measured on.** There is no separate validation set.
  In real runs, 61 % of Jev's decisions on write requests fell in the uncertain band and went to the
  slow path, versus 13 % of the calibration pairs.
- **Origin of the calibration labels.** The 100 pairs and their labels were written by Claude, a
  model of the same family as Haiku and Sonnet, with no human review (`calibration/README.md`,
  `calibration/etiquetas.yaml`). This likely favours Haiku and Sonnet in the accuracy comparison
  (Sonnet 98.5 %). Human labels are the first open problem above.
- d1 and d2-sin-calibrar are mode D runs with the initial, uncalibrated thresholds; e08-demo is a demo
  run with a short wait. None of them is in the averages above. `results/runs/_invalidas/` holds runs
  lost to an exhausted API credit.
- Agent cost is Claude Code's own estimate at the provider's list prices; decision cost is what
  OpenRouter reports.

## Reproduce

Python is managed with [uv](https://docs.astral.sh/uv/); there are three uv projects (repo root for the
bench tooling, `demo-app/`, `medula/`). Agents and deciders go through OpenRouter, so paid experiments
need an OpenRouter key in `.env`.

```sh
cp .env.example .env                    # add OPENROUTER_API_KEY; MEDULA_AGENT_MODEL and MEDULA_AGENT_EFFORT are preset
export MEDULA_RUNS_DIR=/tmp/runs        # where workspaces go (outside the repo)
```

Costs are approximate, at September 2026 prices.

| Experiment | What it produces | Command | Cost |
|---|---|---|---|
| Collision design | untouched app red; each task alone green; the 15 pairs merge cleanly in git; merging all six leaves T2, T4 and integration red; the correct integration green | `bench/self_check.sh` | free |
| Kernel | Médula's tests against a simulated provider, plus an end-to-end test with a real server and the hook script | `(cd medula && uv run pytest)` | free |
| Effort check | confirms `--effort high` reaches the model through OpenRouter (required by the runners) | `bench/check_openrouter.sh` | cents |
| Decider micro-benchmark | latency and cost per decision for Jev, Haiku and Sonnet (`results/e03/`) | `uv run --env-file .env bench/e03_decisores.py` | ~$1 |
| Calibration | accuracy of each decider on the labelled pairs, and the fast-path thresholds | `uv run --project medula --env-file .env python bench/e04b_firma.py --variantes base,haiku,sonnet` | ~$2.5 |
| Calibration chart | declared collision probability vs. observed frequency | `uv run --project medula --with matplotlib python bench/grafico_calibracion.py` | free |
| Signature experiments | shared-symbol rule and directional question, each measured separately | `uv run --project medula --env-file .env python bench/e04b_firma.py --variantes base,regla,direccional` | cents |
| One run of mode B | branches, merge, agent conflict resolution, evaluation | `bench/run_mode_b.sh --run-id b1` (live panel: `uv run python bench/modo_b_en_directo.py --run-id b1`) | ~$1.6 |
| One run of modes A, C–F | shared directory; C–F coordinated by Médula | `bench/run_mode.sh --modo D --run-id d1 --umbral-bajo 0.25 --umbral-alto 0.5` (with Médula's terminal UI: `bench/en_directo.sh …`) | ~$0.9–2.3 |
| The run matrix | A×1, B×3, C×3, D×3, E×3, F×1 into `results/summary.csv`, each mode with its decider's thresholds; resumable, stops on API errors | `bench/run_matrix.sh` (estimate first: `bench/run_matrix.sh --estimar`) | ~$20, ~1 h |
| Wait demo | a run where an agent is blocked with a reason it can see, outside the statistics | `bench/en_directo.sh --modo D --run-id demo --demo --espera-max 30 --umbral-bajo 0.25 --umbral-alto 0.5`, and `uv run python bench/ver_agente.py --run-id demo T2` | ~$1.5–3 |
| Replay a mode B merge | the merge and the acceptance tests of a finished run, without agents | `bench/repetir_merge.sh b1` | free |
| Re-evaluate a run | acceptance tests on a finished run's final state (e.g. after fixing a test) | `bench/reevaluar.sh d1 "reason"` | free |

Agents are stochastic: expect the same pattern, not identical numbers.

### Isolation of agent runs

- Workspaces live outside the repo, in `$MEDULA_RUNS_DIR` (default `$TMPDIR/medula-runs`). The scripts
  refuse a path inside the repo, or one with a `CLAUDE.md` or `.claude/` in any parent directory.
- Each run uses an empty `CLAUDE_CONFIG_DIR`, so agents don't inherit the user's plugins, skills, MCP
  servers, hooks or memory.
- Agents cannot use tools that end the session waiting for a wake-up, talk to other sessions or leave
  the working directory (`bench/lib/agent.sh`).
- In mode B each task gets its own clone, not a worktree, so an agent can't see other tasks' branches
  before the merge.
- Paths in the published logs are anonymised (`<repo>`, `<runs>`, `<home>`, `<tmp>`).

## Layout

```
demo-app/            Room-booking API (FastAPI, SQLite, pytest) in its initial state; its own uv project
tasks/T1.md … T6.md  The six tasks, written as an agent receives them
acceptance/          Acceptance tests per task + integration test (never copied into agent workspaces)
ground_truth.yaml    The 15 task pairs, labelled conflict / no conflict
calibration/         Calibration pairs, their labels, human labels and the calibrated thresholds
reference/           Reference solutions: each task done in isolation and all six integrated correctly
medula/              The coordination kernel (its own uv project; see medula/README.md)
bench/               Runners, evaluation, calibration and analysis scripts
results/             Raw evidence of every run, summary.csv and charts
SPEC.md              Spec of the lab (in Spanish); medula/SPEC.md is the kernel's spec
```

Code comments and specs are in Spanish; issues and PRs are welcome in English or Spanish.

## About the author

**Joaquín Ruiz** — [jokiruiz.com](https://jokiruiz.com) ·
[youtube.com/@jokioki](https://youtube.com/@jokioki)

📗 [Del vibe coding al Spec-Driven Development](https://amzn.eu/d/02csLpKC)
📙 [El motor de la Inteligencia Artificial](https://amzn.eu/d/083CTN3U)
📘 [Programar con Inteligencia Artificial](https://amzn.eu/d/eK4f73N)
📙 [Explora la Inteligencia Artificial](https://amzn.eu/d/dSwYhue)

## License

[MIT](./LICENSE) © Joaquín Ruiz

<div align="center">
<sub>If Médula helped you think about agents working together, consider giving it a ⭐</sub>
</div>
