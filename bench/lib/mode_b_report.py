"""Compone mode_b.json a partir de los ficheros que deja run_mode_b.sh en logs/."""
import json
import sys
from pathlib import Path

TASKS = [f"T{i}" for i in range(1, 7)]


def load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def agent_summary(meta: dict | None, out: dict | None) -> dict:
    meta, out = meta or {}, out or {}
    res = {
        "exit_code": meta.get("exit_code"),
        "duration_s": round(meta["end"] - meta["start"], 1) if "end" in meta else None,
        "cost_usd": out.get("total_cost_usd"),
        "num_turns": out.get("num_turns"),
        "session_id": out.get("session_id"),
        "is_error": out.get("is_error"),
        "terminal_reason": out.get("terminal_reason"),
        # p. ej. «API Error: 402 … credits»: el agente no llegó a trabajar y la ejecución no vale
        "api_error": bool(out.get("is_error") and "API Error" in str(out.get("result"))),
    }
    usage = out.get("usage") or {}
    if usage:
        res["tokens"] = {
            k: usage.get(k)
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        }
    return res


def main(logs: Path) -> None:
    run = load(logs / "run.json") or {}
    t0 = run.get("t0")
    end = (load(logs / "end.json") or {}).get("t_end") or (load(logs / "finish.json") or {}).get("finished_at")

    agents = {}
    for t in TASKS:
        a = agent_summary(load(logs / "agents" / f"{t}.meta.json"), load(logs / "agents" / f"{t}.json"))
        a.update({k: v for k, v in (load(logs / "agents" / f"{t}.git.json") or {}).items() if k != "task"})
        agents[t] = a

    rounds = []
    for n in (1, 2):
        r = load(logs / f"round-{n}.json")
        if r:
            rounds.append({"tasks": r["tasks"], "wall_time_s": round(r["end"] - r["start"], 1)})

    merge_rows = []
    if (logs / "merge.jsonl").exists():
        merge_rows = [json.loads(line) for line in (logs / "merge.jsonl").read_text().splitlines() if line.strip()]
    conflicts = []
    for row in merge_rows:
        if row["status"] in ("resolved", "failed_merge"):
            t = row["task"]
            conflicts.append({
                "branch": f"task/{t}", "task": t, "against": row.get("against", []),
                "files": row.get("files", []), "resolved": row["status"] == "resolved",
                "resolver": agent_summary(
                    load(logs / "resolvers" / f"resolve-{t}.meta.json"),
                    load(logs / "resolvers" / f"resolve-{t}.json"),
                ),
                "failure_reason": row.get("reason"),
            })

    agents_cost = sum(a["cost_usd"] or 0 for a in agents.values())
    resolver_cost = sum(c["resolver"]["cost_usd"] or 0 for c in conflicts)
    evaluation = load(logs / "evaluation.json")

    report = {
        "mode": "B",
        "run_id": run.get("run_id"),
        "model": run.get("model"),
        "effort": run.get("effort"),
        "d61": f"{run.get('model')} · effort {run.get('effort')}",
        "claude_version": run.get("claude_version"),
        "effort_check": run.get("effort_check"),
        "started_at": run.get("started_at"),
        "completed": (load(logs / "finish.json") or {}).get("exit_code") == 0
                     and not any(a.get("api_error") for a in agents.values()),
        "agentes_con_error_api": sorted(t for t, a in agents.items() if a.get("api_error")),
        "wall_time_s": round(end - t0, 1) if t0 and end else None,
        "base_sha": (load(logs / "base.json") or {}).get("base_sha"),
        "rounds": rounds,
        "agents": agents,
        "merge": {
            "order": TASKS,
            "merged": [r["task"] for r in merge_rows if r["status"] in ("clean", "resolved")],
            "failed": [r["task"] for r in merge_rows if r["status"] in ("failed", "failed_merge")],
            "textual_conflicts": conflicts,
            "textual_conflict_count": len(conflicts),
            "resolved_count": sum(c["resolved"] for c in conflicts),
        },
        "totals": {
            "agents_cost_usd": round(agents_cost, 4),
            "resolver_cost_usd": round(resolver_cost, 4),
            "cost_usd": round(agents_cost + resolver_cost, 4),
            "cost_note": "total_cost_usd de Claude Code (tarifa de Anthropic); cuadrar con OpenRouter por session_id",
        },
        "evaluation": evaluation,
    }
    if evaluation:
        report["red_tests"] = evaluation["total"]["failed"]
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
