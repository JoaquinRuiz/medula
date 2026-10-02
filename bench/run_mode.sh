#!/usr/bin/env bash
# Modos A y C-F, sobre un MISMO directorio de trabajo compartido.
#   A = secuencial: un agente detrás de otro, sin Médula.
# Modos C-F: los agentes trabajan a la vez en el MISMO directorio, coordinados por Médula.
#   C = locks (lock clásico por fichero)   D = jev   E = haiku   F = sonnet
#   Ronda 1: T1-T4 en paralelo. Ronda 2: T5-T6 en paralelo (igual que el modo B).
#   Los agentes no hacen commit; el banco hace uno al final y evalúa.
#
# Uso: run_mode.sh --modo A|C|D|E|F [--run-id ID] [--model M] [--effort E]
#                  [--umbral-bajo 0.2] [--umbral-alto 0.8] [--umbral-aviso 0.5] [--espera-max 600]
#                  [--pregunta choca|direccional] [--regla-simbolos] [--demo] [--skip-effort-check]
#   --demo  ejecución de demostración (E-08): se guarda en results/runs pero no entra en summary.csv.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
source "$(dirname "$0")/lib/agent.sh"

json_items() { [[ $# -eq 0 ]] || printf '"%s",' "$@" | sed 's/,$//'; }

load_env
MODEL="${MEDULA_AGENT_MODEL:-}"
EFFORT="${MEDULA_AGENT_EFFORT:-}"
MODO=""
RUN_ID=""
EFFORT_CHECK="passed"
UMBRAL_BAJO=0.2; UMBRAL_ALTO=0.8; UMBRAL_AVISO=0.5; ESPERA_MAX=600
PREGUNTA=choca; REGLA=""; DEMO=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --modo) MODO="$(tr '[:lower:]' '[:upper:]' <<< "$2")"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --effort) EFFORT="$2"; shift 2 ;;
    --umbral-bajo) UMBRAL_BAJO="$2"; shift 2 ;;
    --umbral-alto) UMBRAL_ALTO="$2"; shift 2 ;;
    --umbral-aviso) UMBRAL_AVISO="$2"; shift 2 ;;
    --espera-max) ESPERA_MAX="$2"; shift 2 ;;
    --pregunta) PREGUNTA="$2"; shift 2 ;;
    --regla-simbolos) REGLA="--regla-simbolos"; shift ;;
    --demo) DEMO=true; shift ;;
    --skip-effort-check) EFFORT_CHECK="skipped"; shift ;;
    *) die "opción desconocida: $1" ;;
  esac
done
case "$MODO" in
  A) DECISOR=ninguno ;; C) DECISOR=locks ;; D) DECISOR=jev ;; E) DECISOR=haiku ;; F) DECISOR=sonnet ;;
  *) die "uso: $0 --modo A|C|D|E|F  (el modo B es run_mode_b.sh)" ;;
esac
RUN_ID="${RUN_ID:-$(tr '[:upper:]' '[:lower:]' <<< "$MODO")-$(date +%Y%m%d-%H%M%S)}"

# --- Comprobaciones previas -------------------------------------------------
[[ -n "$MODEL" && -n "$EFFORT" ]] || die "faltan modelo y esfuerzo de los agentes (.env o --model/--effort)"
PROVEEDOR="${MEDULA_AGENT_PROVEEDOR:-openrouter}"
case "$PROVEEDOR" in
  openrouter) [[ -n "${OPENROUTER_API_KEY:-}" ]] || die "falta OPENROUTER_API_KEY en .env" ;;
  suscripcion)
    [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] || die "falta CLAUDE_CODE_OAUTH_TOKEN en .env (claude setup-token)"
    EFFORT_CHECK="no_aplica"  # la comprobación del esfuerzo es la del paso por OpenRouter
    MODEL="${MODEL#anthropic/}"  # id de Anthropic: anthropic/claude-sonnet-5 -> claude-sonnet-5
    ;;
  *) die "MEDULA_AGENT_PROVEEDOR desconocido: $PROVEEDOR (openrouter | suscripcion)" ;;
esac
export MEDULA_AGENT_PROVEEDOR="$PROVEEDOR"
# Médula (modos D-F) llama a los decisores por OpenRouter, sea cual sea el proveedor de los agentes.
[[ "$DECISOR" =~ ^(jev|haiku|sonnet)$ && -z "${OPENROUTER_API_KEY:-}" ]] && die "falta OPENROUTER_API_KEY en .env (decisores de Médula)"
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
mkdir -p "$LOGS/agents" "$LOGS/prompts" "$EVID"
export AGENT_CONFIG_DIR="$RUN/claude-config"
mkdir -p "$AGENT_CONFIG_DIR"
export MODEL EFFORT
CLAUDE_VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
REPO="$RUN/repo"
MEDULA_PID=""

finalize() {
  local rc=$?
  set +e
  [[ -n "$MEDULA_PID" ]] && kill "$MEDULA_PID" 2>/dev/null
  if [[ -d "$REPO/.git" && -n "${BASE_SHA:-}" ]]; then
    git -C "$REPO" diff "$BASE_SHA" HEAD > "$LOGS/final.diff" 2>/dev/null
  fi
  [[ -f "$RUN/medula.db" ]] && py - "$RUN/medula.db" "$LOGS/medula.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2]); src.backup(dst)
PY
  printf '{"exit_code": %d, "finished_at": %s}\n' "$rc" "$(now_s)" > "$LOGS/finish.json"
  py "$MEDULA_ROOT/bench/lib/mode_medula_report.py" "$LOGS" > "$LOGS/mode_$MODO.json" 2> "$LOGS/report.err"
  [[ -s "$LOGS/mode_$MODO.json" ]] && py "$MEDULA_ROOT/bench/lib/summary.py" "$LOGS/mode_$MODO.json"
  rsync -a "$LOGS/" "$EVID/"
  log "evidencia copiada a $EVID"
  [[ -s "$LOGS/mode_$MODO.json" ]] && log "resumen: $EVID/mode_$MODO.json · fila añadida a results/summary.csv"
  exit "$rc"
}
trap finalize EXIT

T0="$(now_s)"
cat > "$LOGS/run.json" <<JSON
{"mode": "$MODO", "decisor": "$DECISOR", "run_id": "$RUN_ID", "model": "$MODEL", "effort": "$EFFORT",
 "proveedor_agentes": "$PROVEEDOR", "claude_version": "$CLAUDE_VERSION", "effort_check": "$EFFORT_CHECK",
 "umbral_bajo": $UMBRAL_BAJO, "umbral_alto": $UMBRAL_ALTO, "umbral_aviso": $UMBRAL_AVISO, "espera_max": $ESPERA_MAX,
 "demo": $DEMO, "pregunta": "$PREGUNTA", "regla_simbolos": $([[ -n "$REGLA" ]] && echo true || echo false),
 "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "t0": $T0, "run_dir": "$RUN"}
JSON
log "run $RUN_ID · modo $MODO (decisor $DECISOR) en $RUN"

# --- Humo de los agentes por OpenRouter -----------------------------------------
mkdir -p "$RUN/smoke"
echo "Responde solo con la palabra: ok" > "$LOGS/prompts/smoke.txt"
run_agent smoke "$RUN/smoke" "$LOGS/prompts/smoke.txt" "$LOGS"
py - "$LOGS/smoke.json" <<'PY' || die "la llamada de humo por OpenRouter falló; mira $LOGS/smoke.json y smoke.log"
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(1 if d.get("is_error") or "ok" not in str(d.get("result", "")).lower() else 0)
PY

# --- Directorio de trabajo compartido --------------------------------------------
"$MEDULA_ROOT/bench/prepare_workspace.sh" "$REPO" >/dev/null
BASE_SHA="$(git -C "$REPO" rev-parse HEAD)"
echo "{\"base_sha\": \"$BASE_SHA\"}" > "$LOGS/base.json"
(cd "$REPO" && env -u VIRTUAL_ENV uv sync --quiet --frozen)

# --- Médula (modos C-F) ------------------------------------------------------------
if [[ "$MODO" != A ]]; then
PUERTO="$(py -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
MEDULA_URL="http://127.0.0.1:$PUERTO"
# Sin dependencias entre T1-T6: el grafo no le chiva a Médula los choques (decisión 3 de medula/SPEC.md).
printf 'tareas:\n' > "$RUN/plan.yaml"
for t in T1 T2 T3 T4 T5 T6; do printf '  %s: {agente: A%s, depende_de: []}\n' "$t" "${t#T}" >> "$RUN/plan.yaml"; done
cp "$RUN/plan.yaml" "$LOGS/plan.yaml"
(cd "$MEDULA_ROOT/medula" && env -u VIRTUAL_ENV uv sync --quiet)
env -u VIRTUAL_ENV uv run --quiet --project "$MEDULA_ROOT/medula" medula servir \
  --db "$RUN/medula.db" --decisor "$DECISOR" --raiz "$REPO" --tareas "$MEDULA_ROOT/tasks" --plan "$RUN/plan.yaml" \
  --puerto "$PUERTO" --umbral-bajo "$UMBRAL_BAJO" --umbral-alto "$UMBRAL_ALTO" --umbral-aviso "$UMBRAL_AVISO" \
  --espera-max "$ESPERA_MAX" --pregunta "$PREGUNTA" $REGLA > "$LOGS/medula.log" 2>&1 &
MEDULA_PID=$!
for _ in $(seq 1 60); do curl -sf "$MEDULA_URL/estado" >/dev/null 2>&1 && break; sleep 0.5; done
curl -sf "$MEDULA_URL/estado" >/dev/null || die "Médula no arranca; mira $LOGS/medula.log"
log "Médula en $MEDULA_URL · htop: uv run --project $MEDULA_ROOT/medula medula htop --db $RUN/medula.db"

# Hooks en la configuración limpia de los agentes (no en el repo de trabajo).
cp "$MEDULA_ROOT/medula/hook/medula-hook.sh" "$RUN/medula-hook.sh"
cat > "$AGENT_CONFIG_DIR/settings.json" <<JSON
{"hooks": {
  "PreToolUse":  [{"matcher": "Edit|Write|Bash", "hooks": [{"type": "command", "command": "$RUN/medula-hook.sh pre", "timeout": $(( ${ESPERA_MAX%.*} + 120 ))}]}],
  "PostToolUse": [{"matcher": "Edit|Write|Bash", "hooks": [{"type": "command", "command": "$RUN/medula-hook.sh post", "timeout": 60}]}],
  "SessionEnd":  [{"hooks": [{"type": "command", "command": "$RUN/medula-hook.sh fin"}]}]
}}
JSON
export MEDULA_URL
# curl del hook: lo que Médula puede tener esperando a un agente (espera_max) más margen para las decisiones;
# por debajo del timeout del hook en Claude Code (espera_max + 120).
export MEDULA_HOOK_TIMEOUT=$(( ${ESPERA_MAX%.*} + 100 ))
fi

otros_agentes() {
  if [[ "$MODO" == A ]]; then
    echo "- Otras tareas se han hecho o se harán en este mismo directorio, una detrás de otra."
  else
    cat <<'TXT'
- Otros agentes trabajan a la vez en este mismo directorio, cada uno en su tarea.
  Si una herramienta queda bloqueada con un motivo, síguelo. Si te toca esperar,
  avanza en otra parte o reinténtalo más tarde (puedes usar `sleep 60`), pero no
  termines la sesión hasta haber completado tu tarea.
TXT
  fi
}

task_prompt() {
  local t="$1"
  cat "$MEDULA_ROOT/tasks/$t.md"
  cat <<TXT

---
Instrucciones de trabajo:
- Trabajas en un repositorio git en el directorio actual. No salgas de él.
$(otros_agentes)
- Es un proyecto uv con las dependencias ya instaladas. No añadas paquetes.
- Ejecuta los tests con \`uv run pytest\`.
- No hagas commit ni cambies de rama: al terminar, el banco hace el commit.
TXT
}

registrar() {
  [[ "$MODO" == A ]] && return 0
  curl -sf -XPOST "$MEDULA_URL/registrar" -H 'Content-Type: application/json' \
    -d "{\"agente\": \"$1\", \"tarea\": \"$2\"}" >/dev/null
}
liberar() {
  [[ "$MODO" == A ]] && return 0
  curl -sf -XPOST "$MEDULA_URL/release" -H 'Content-Type: application/json' -H "X-Medula-Agente: $1" -d '{}' >/dev/null || true
}

run_round() {
  local name="$1"; shift
  local start pids=() t
  start="$(now_s)"
  log "ronda $name: $*"
  for t in "$@"; do registrar "A${t#T}" "$t"; done
  for t in "$@"; do
    task_prompt "$t" > "$LOGS/prompts/$t.txt"
    (
      export MEDULA_AGENTE="A${t#T}" MEDULA_TAREA="$t"
      run_agent "$t" "$REPO" "$LOGS/prompts/$t.txt" "$LOGS/agents"
      liberar "$MEDULA_AGENTE"  # por si el agente murió sin SessionEnd
    ) &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  printf '{"name": "%s", "tasks": [%s], "start": %s, "end": %s}\n' "$name" \
    "$(json_items "$@")" "$start" "$(now_s)" > "$LOGS/round-$name.json"
}

if [[ "$MODO" == A ]]; then
  # Secuencial: cada tarea es su propia ronda, en orden.
  for t in T1 T2 T3 T4 T5 T6; do run_round "${t#T}" "$t"; done
else
  run_round 1 T1 T2 T3 T4
  run_round 2 T5 T6
fi

# --- Commit final y evaluación ----------------------------------------------------
git -C "$REPO" add -A
git -C "$REPO" commit -q -m "modo $MODO: estado final" || true
"$MEDULA_ROOT/bench/evaluate.sh" "$REPO" "$LOGS/evaluation.json"
echo "{\"t_end\": $(now_s)}" > "$LOGS/end.json"
log "hecho"
