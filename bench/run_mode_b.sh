#!/usr/bin/env bash
# Modo B: cada tarea en su rama, merge al final.
#   Ronda 1: T1-T4 en paralelo. Ronda 2: T5-T6 en paralelo.
#   Merge en orden T1..T6; un conflicto textual lo resuelve un agente con el
#   mismo modelo y esfuerzo. Si no lo consigue, esa rama se aborta.
#
# Uso: run_mode_b.sh [--model M] [--effort E] [--run-id ID] [--skip-effort-check]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
source "$(dirname "$0")/lib/agent.sh"

# Elementos de un array JSON de strings, sin corchetes; vacío si no hay argumentos.
json_items() { [[ $# -eq 0 ]] || printf '"%s",' "$@" | sed 's/,$//'; }

load_env
MODEL="${MEDULA_AGENT_MODEL:-}"
EFFORT="${MEDULA_AGENT_EFFORT:-}"
RUN_ID="b-$(date +%Y%m%d-%H%M%S)"
EFFORT_CHECK="passed"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --effort) EFFORT="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --skip-effort-check) EFFORT_CHECK="skipped"; shift ;;
    *) die "opción desconocida: $1" ;;
  esac
done

# --- Comprobaciones previas -------------------------------------------------
[[ -n "$MODEL" ]] || die "falta el modelo: --model o MEDULA_AGENT_MODEL en .env"
[[ -n "$EFFORT" ]] || die "falta el esfuerzo: --effort o MEDULA_AGENT_EFFORT en .env"
[[ -n "${OPENROUTER_API_KEY:-}" ]] || die "falta OPENROUTER_API_KEY en .env"
command -v claude >/dev/null || die "no encuentro claude en el PATH"

if [[ "$EFFORT_CHECK" == "passed" ]]; then
  check="$MEDULA_ROOT/results/openrouter_check.json"
  [[ -f "$check" ]] || die "falta $check; ejecuta bench/check_openrouter.sh o usa --skip-effort-check"
  py - "$check" "$MODEL" <<'PY' || die "openrouter_check.json no confirma el paso del esfuerzo para este modelo"
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if d.get("effort_passthrough") is True and d.get("model") == sys.argv[2] else 1)
PY
fi

RUN="$(runs_dir)/$RUN_ID"
[[ -e "$RUN" ]] && die "$RUN ya existe"
mkdir -p "$RUN"
assert_isolated_path "$RUN"

EVID="$MEDULA_ROOT/results/runs/$RUN_ID"
LOGS="$RUN/logs"
mkdir -p "$LOGS/agents" "$LOGS/resolvers" "$LOGS/prompts" "$EVID"
export AGENT_CONFIG_DIR="$RUN/claude-config"
mkdir -p "$AGENT_CONFIG_DIR"
export MODEL EFFORT

CLAUDE_VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
TASKS=(T1 T2 T3 T4 T5 T6)
ROUND1=(T1 T2 T3 T4)
ROUND2=(T5 T6)

# Evidencia: se copia pase lo que pase.
finalize() {
  local rc=$?
  set +e
  if [[ -d "$RUN/repo/.git" && -n "${BASE_SHA:-}" ]]; then
    git -C "$RUN/repo" diff "$BASE_SHA" HEAD > "$LOGS/final.diff" 2>/dev/null
  fi
  printf '{"exit_code": %d, "finished_at": %s}\n' "$rc" "$(now_s)" > "$LOGS/finish.json"
  py "$MEDULA_ROOT/bench/lib/mode_b_report.py" "$LOGS" > "$LOGS/mode_b.json" 2> "$LOGS/report.err"
  [[ -s "$LOGS/mode_b.json" ]] && py "$MEDULA_ROOT/bench/lib/summary.py" "$LOGS/mode_b.json"
  rsync -a "$LOGS/" "$EVID/"
  log "evidencia copiada a $EVID"
  [[ -s "$LOGS/mode_b.json" ]] && log "resumen: $EVID/mode_b.json"
  exit "$rc"
}
trap finalize EXIT

T0="$(now_s)"
cat > "$LOGS/run.json" <<JSON
{"mode": "B", "run_id": "$RUN_ID", "model": "$MODEL", "effort": "$EFFORT",
 "claude_version": "$CLAUDE_VERSION", "effort_check": "$EFFORT_CHECK",
 "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "t0": $T0, "run_dir": "$RUN"}
JSON
log "run $RUN_ID en $RUN (modelo $MODEL, esfuerzo $EFFORT)"

# --- Humo: la ruta de OpenRouter responde ----------------------------------
mkdir -p "$RUN/smoke"
echo "Responde solo con la palabra: ok" > "$LOGS/prompts/smoke.txt"
run_agent smoke "$RUN/smoke" "$LOGS/prompts/smoke.txt" "$LOGS"
py - "$LOGS/smoke.json" <<'PY' || die "la llamada de humo por OpenRouter falló; mira $LOGS/smoke.json y smoke.log"
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(1 if d.get("is_error") or "ok" not in str(d.get("result", "")).lower() else 0)
PY

# --- Repo base y un clon por tarea -------------------------------------------
# Clones independientes, no worktrees: en un worktree `git log --all` dejaría
# ver las ramas de las demás tareas, y en el modo B nadie ve el trabajo ajeno
# hasta el merge.
"$MEDULA_ROOT/bench/prepare_workspace.sh" "$RUN/repo" >/dev/null
BASE_SHA="$(git -C "$RUN/repo" rev-parse HEAD)"
echo "{\"base_sha\": \"$BASE_SHA\"}" > "$LOGS/base.json"
for t in "${TASKS[@]}"; do
  git clone -q "$RUN/repo" "$RUN/ws-$t"
  git -C "$RUN/ws-$t" remote remove origin
  git -C "$RUN/ws-$t" checkout -q -b "task/$t"
  git -C "$RUN/ws-$t" config user.name "agent-$t"
  git -C "$RUN/ws-$t" config user.email "agent-$t@medula.local"
  # Cada clon es un proyecto uv propio: su .venv se crea desde su uv.lock.
  (cd "$RUN/ws-$t" && env -u VIRTUAL_ENV uv sync --quiet --frozen)
done

task_prompt() {
  local t="$1"
  cat "$MEDULA_ROOT/tasks/$t.md"
  cat <<TXT

---
Instrucciones de trabajo:
- Trabajas en un repositorio git en el directorio actual. No salgas de él.
- Es un proyecto uv con las dependencias ya instaladas. No añadas paquetes.
- Ejecuta los tests con \`uv run pytest\`.
- Cuando termines y los tests estén en verde, haz commit de tus cambios en la
  rama actual con un mensaje que empiece por "$t:". No cambies de rama ni hagas merge.
TXT
}

run_round() {
  local name="$1"; shift
  local start pids=() t
  start="$(now_s)"
  log "ronda $name: $*"
  for t in "$@"; do
    task_prompt "$t" > "$LOGS/prompts/$t.txt"
    run_agent "$t" "$RUN/ws-$t" "$LOGS/prompts/$t.txt" "$LOGS/agents" &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  # Si el agente no hizo commit, lo hace el script.
  for t in "$@"; do
    local by="agent"
    if [[ -n "$(git -C "$RUN/ws-$t" status --porcelain)" ]]; then
      git -C "$RUN/ws-$t" add -A
      git -C "$RUN/ws-$t" commit -q -m "$t: auto-commit (bench)"
      by="script"
    fi
    local n; n="$(git -C "$RUN/ws-$t" rev-list --count "$BASE_SHA..HEAD")"
    [[ "$n" -eq 0 ]] && by="none"
    printf '{"task": "%s", "commits": %d, "committed_by": "%s"}\n' "$t" "$n" "$by" \
      > "$LOGS/agents/$t.git.json"
  done
  printf '{"name": "%s", "tasks": [%s], "start": %s, "end": %s}\n' "$name" \
    "$(json_items "$@")" "$start" "$(now_s)" > "$LOGS/round-$name.json"
}

run_round 1 "${ROUND1[@]}"
run_round 2 "${ROUND2[@]}"

# --- Merge ------------------------------------------------------------------
REPO="$RUN/repo"
for t in "${TASKS[@]}"; do
  git -C "$REPO" fetch -q "$RUN/ws-$t" "task/$t:task/$t"
done

files_of() { git -C "$REPO" diff --name-only "$BASE_SHA" "task/$1"; }

app_starts() {
  (cd "$REPO" && env -u VIRTUAL_ENV MEDULA_DB_PATH="$(mktemp -t medula-smoke.XXXXXX)" \
    uv run --quiet python -c '
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    assert c.get("/reservas").status_code == 200
') >/dev/null 2>&1
}

has_markers() {
  git -C "$REPO" grep -qE '^(<<<<<<<|>>>>>>>)( |$)|^=======$' -- . 2>/dev/null
}

MERGED=()
: > "$LOGS/merge.jsonl"
for t in "${TASKS[@]}"; do
  pre="$(git -C "$REPO" rev-parse HEAD)"
  if git -C "$REPO" merge -q --no-ff --no-edit -m "merge $t" "task/$t" > "$LOGS/merge-$t.log" 2>&1; then
    log "merge $t: limpio"
    echo "{\"task\": \"$t\", \"status\": \"clean\"}" >> "$LOGS/merge.jsonl"
    MERGED+=("$t")
    continue
  fi

  conflicted=()
  while IFS= read -r f; do [[ -n "$f" ]] && conflicted+=("$f"); done \
    < <(git -C "$REPO" diff --name-only --diff-filter=U)
  if [[ ${#conflicted[@]} -eq 0 ]]; then
    log "merge $t: falló sin conflictos (ver merge-$t.log)"
    git -C "$REPO" merge --abort 2>/dev/null || git -C "$REPO" reset -q --hard "$pre"
    echo "{\"task\": \"$t\", \"status\": \"failed\", \"reason\": \"merge error\"}" >> "$LOGS/merge.jsonl"
    continue
  fi

  # Tareas ya fusionadas que tocaron los mismos ficheros.
  against=()
  for m in "${MERGED[@]+"${MERGED[@]}"}"; do
    mf="$(files_of "$m")"
    for f in "${conflicted[@]}"; do
      if grep -qxF "$f" <<< "$mf"; then against+=("$m"); break; fi
    done
  done
  log "merge $t: conflicto en ${conflicted[*]} contra ${against[*]:-?}; lanzo agente de resolución"

  rp="$LOGS/prompts/resolve-$t.txt"
  {
    echo "Estás en un repositorio git a mitad de un merge con conflictos textuales."
    echo "Se está fusionando la rama task/$t sobre main, donde ya se han integrado otras tareas."
    echo
    echo "Ficheros en conflicto:"
    printf -- '- %s\n' "${conflicted[@]}"
    echo
    echo "Objetivo: resolver los conflictos conservando la intención de todas las tareas implicadas,"
    echo "de modo que el resultado cumpla los criterios de aceptación de cada una."
    echo
    for x in "${against[@]+"${against[@]}"}" "$t"; do
      echo "=============== Tarea $x ==============="
      cat "$MEDULA_ROOT/tasks/$x.md"
      echo
    done
    cat <<TXT
Instrucciones:
- Resuelve los conflictos, quita todos los marcadores y ajusta el código y los tests que haga falta.
- Es un proyecto uv con las dependencias ya instaladas. Ejecuta los tests con \`uv run pytest\`.
- Cierra el merge con \`git add\` y \`git commit --no-edit\`. No cambies de rama, no hagas rebase y no abortes el merge.
TXT
  } > "$rp"

  run_agent "resolve-$t" "$REPO" "$rp" "$LOGS/resolvers"

  reason=""
  if has_markers; then reason="conflict markers left"
  elif git -C "$REPO" rev-parse -q --verify MERGE_HEAD >/dev/null; then reason="merge not committed"
  elif ! app_starts; then reason="app does not start"
  fi

  against_json="$(json_items "${against[@]+"${against[@]}"}")"
  files_json="$(json_items "${conflicted[@]}")"
  if [[ -z "$reason" ]]; then
    log "merge $t: resuelto por agente"
    echo "{\"task\": \"$t\", \"status\": \"resolved\", \"against\": [$against_json], \"files\": [$files_json]}" >> "$LOGS/merge.jsonl"
    MERGED+=("$t")
  else
    log "merge $t: resolución fallida ($reason); se aborta la rama"
    git -C "$REPO" merge --abort 2>/dev/null || true
    git -C "$REPO" reset -q --hard "$pre"
    echo "{\"task\": \"$t\", \"status\": \"failed_merge\", \"against\": [$against_json], \"files\": [$files_json], \"reason\": \"$reason\"}" >> "$LOGS/merge.jsonl"
  fi
done
echo "{\"end\": $(now_s)}" > "$LOGS/merge-end.json"

# --- Evaluación ---------------------------------------------------------------
"$MEDULA_ROOT/bench/evaluate.sh" "$REPO" "$LOGS/evaluation.json"
echo "{\"t_end\": $(now_s)}" > "$LOGS/end.json"
log "hecho"
