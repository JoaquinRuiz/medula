# Contributing to Médula

Thanks for helping. This lab is only useful if its data is honest and anyone can check it, so most of
the rules below are about that.

Issues and PRs are welcome in English or Spanish. Code comments, specs and data files are in Spanish.

## Setup

```sh
uv sync && (cd demo-app && uv sync) && (cd medula && uv sync)
```

Everything in [Before you send a PR](#before-you-send-a-pr) runs offline. You only need an OpenRouter
key (`cp .env.example .env`) to measure a decider or launch agent runs.

## Labelling the calibration set (no code)

The 100 pairs in `calibration/candidatas.yaml` each describe what one agent is about to do (the
*requester*: task, tool, target and change) and what another agent is doing (the *other*: its task,
the files it holds and its intent). The question is always the same: **does it collide?** The
definition is in `calibration/README.md`; please read it before you start.

```sh
uv run bench/e04_etiquetar.py --salida calibration/etiquetas_humanas/<your-github-user>.yaml
```

- Keys: `c` collides, `n` doesn't collide, `d` unsure, `s` skip, `q` quit. You can stop at any time
  and pick up where you left off.
- It is **blind**: you don't see the model's label unless you ask for it (`--ver-propuesta`). Please
  don't, and don't look at `calibration/etiquetas.yaml` or other people's files first. Independent
  labels are the whole point.
- Add a note when a pair is ambiguous; the note is the most useful part of a disagreement.
- `uv run bench/acuerdo_etiquetas.py` prints raw agreement and Cohen's kappa between you, the model
  and other people, plus the pairs where you differ.

Send your file in a PR. Partial files are fine.

## Adding calibration pairs

Add entries to `calibration/candidatas.yaml` following the existing ones:

```yaml
- id: C101                         # next free id
  categoria: firma                 # an existing category, or a new one explained in the PR
  dificultad: dificil              # facil | dificil
  propuesta: choca                 # your proposed label: choca | no_choca
  motivo: "Why, in one sentence."
  solicitante: {agente: A1, tarea: "…", accion: {herramienta: Edit, objetivo: "app/auth.py", cambio: "…"}}
  otro: {agente: A2, tarea: "…", tiene: ["app/routes_export.py"], intencion: "…"}
```

Most useful right now: pairs that look like real runs, with long intentions, several files held, and
Bash commands. Pairs taken from the `medula.db` of published runs (table `decisiones`) are welcome;
say which run and decision id they come from.

## Adding a scenario

A scenario is a new task that collides (or looks like it collides) with an existing one in a way the
current six don't cover. It needs:

1. `tasks/T7.md`, written as an agent receives it (look at the existing ones for tone and scope);
2. `acceptance/test_t7.py`, targeting the **final** contract with every task applied;
3. a reference solution in `reference/tasks/T7.patch`, and `reference/all_tasks.patch` updated;
4. one line per new pair in `ground_truth.yaml`, with `conflict`, `type` and a `reason`;
5. `bench/self_check.sh` still passing, with the new expectations added.

Open an issue first. Adding a task changes the whole matrix, so the design is worth discussing
before you write it.

## Adding a decider

A decider answers, for each other agent, "does this collide?" with a probability. The interface is
in `medula/src/medula/decisores/base.py`:

```python
class Decisor:
    nombre = "base"
    def acquire(self, estado: dict, otros: list[str]) -> Lote: ...   # before a write
    def invalida(self, estado: dict, otros: list[str]) -> Lote: ...  # after a write
```

`Lote.veredictos` maps each other agent to a `Veredicto(p, remedio, confianza, motivo)`. On failure,
raise `ErrorDecisor`; the fallback chain (`decisores/cadena.py`) will ask the next decider.

1. Implement it next to `jev.py` or `llm.py`, and register it in `decisores/__init__.py` (`uno`) and
   in `CADENAS` in `medula/src/medula/config.py`, with a fallback (usually `locks`).
2. Add tests to `medula/tests/test_decisores.py` using the simulated transport. **No real network.**
3. Measure it on the calibration set (add a variant to `bench/e04b_firma.py`) and report accuracy,
   coverage and cost per decision in the PR.
4. If it's promising, propose thresholds for `calibration/umbrales.yaml`, chosen with the same rule
   as the others (see the README).

## Contributing runs

If you have credit and want to add runs to the matrix:

- use the same model and effort as the published runs (`.env.example`), or say clearly that you
  didn't;
- run `bench/check_openrouter.sh` first, then `bench/run_matrix.sh`, which resumes and stops on API
  errors;
- send the whole `results/runs/<run-id>/` directory and the new rows of `results/summary.csv`,
  exactly as the scripts wrote them. Paths are anonymised when the logs are written, but check for
  anything personal before you push;
- if something went wrong (overlapping runs, an outage, a flaky test), add a `NOTA.md` to the run
  explaining it. Flag it; don't delete it.

## Before you send a PR

```sh
(cd medula && uv run pytest)                    # kernel; the model provider is simulated
(cd demo-app && uv run pytest)                  # the demo app
bench/self_check.sh                             # the collision design still holds
uv run python bench/lib/check_ground_truth.py   # the ground truth covers every pair
```

## What won't be merged

- **Tests that need an API key or money.** Anyone must be able to check a change for free.
- **Hand edits to published results.** A run's evidence is what the run produced. Fixing a test and
  re-evaluating is fine (`bench/reevaluar.sh` records why); editing `summary.csv` or a log is not.
- **Hiding a caveat.** If a run is flawed, it gets flagged in the README and in its `NOTA.md`, not
  quietly dropped.
- **API keys, personal paths or tokens** in any file, including logs.
