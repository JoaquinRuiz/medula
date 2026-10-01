# Médula

A coordination kernel for several Claude Code agents working on the same repository at the same time.

Before every write (`Edit`, `Write`, or a `Bash` command that writes), an agent's `PreToolUse` hook asks Médula for permission (`/acquire`). Médula builds the intent itself — the agent's assigned task plus what the tool is actually about to do — and asks a decider whether it collides with what the other agents are doing. After every write (`/notify`), Médula asks whether the change invalidates any other agent's plan, and leaves a notice in that agent's mailbox.

The full design is in [SPEC.md](SPEC.md) (in Spanish).

## Deciders

| Decider | How | Fallback |
|---|---|---|
| `jev` | TypeSafe Jev via OpenRouter System One: a `noul` question (collision probability) and a `choice` question (remedy) per other agent, all in one request | haiku → locks |
| `haiku` | Claude Haiku via OpenRouter, structured output | locks |
| `sonnet` | Claude Sonnet via OpenRouter, structured output, low effort | locks |
| `locks` | classic per-file lock, no model | — |

Decision rule, with `p` the highest collision probability over the other agents:
- `p < 0.2`: grant.
- `p > 0.8` with remedy "wait": wait for that agent to finish.
- Otherwise: slow path. Sonnet proposes a way out (grant, wait, reorder or rewrite); if it can't resolve it, Opus does; if neither can, wait.

Both thresholds are configurable and are meant to be set from the E-04 calibration.

## Usage

```sh
uv sync
uv run --env-file ../.env medula servir --db run/medula.db --decisor jev --raiz <workspace> --tareas ../tasks
uv run medula htop --db run/medula.db --coste-sonnet <Sonnet cost per decision>
```

Agents get the hook through the `settings.json` of their own clean `CLAUDE_CONFIG_DIR`:

```json
{"hooks": {
  "PreToolUse":  [{"matcher": "Edit|Write|Bash", "hooks": [{"type": "command", "command": "/path/medula-hook.sh pre", "timeout": 300}]}],
  "PostToolUse": [{"matcher": "Edit|Write|Bash", "hooks": [{"type": "command", "command": "/path/medula-hook.sh post", "timeout": 60}]}],
  "SessionEnd":  [{"hooks": [{"type": "command", "command": "/path/medula-hook.sh fin"}]}]
}}
```

and the environment variables `MEDULA_URL`, `MEDULA_AGENTE` and `MEDULA_TAREA`.

The hook is a command hook, not an `http` hook, on purpose: if Médula is unreachable it exits with code 2 and blocks the tool, instead of silently letting the agent proceed uncoordinated.

## State

Everything lives in one SQLite file:
- `agentes`: agents and their state;
- `locks`: resources held, each with its intent;
- `cola`: the wait queue;
- `buzon`: per-agent mailbox;
- `decisiones`: every decision with its time, agent, question, raw answer, probability, latency, cost, decider and fallback.

## Tests

```sh
uv run pytest
```

They run against a simulated OpenRouter, plus an end-to-end test with a real uvicorn server and the hook script called through `curl`.
