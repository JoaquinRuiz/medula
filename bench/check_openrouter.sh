#!/usr/bin/env bash
# Comprueba la ruta de OpenRouter antes de lanzar agentes:
#   1. check_openrouter.py: el modelo existe y el esfuerzo llega a Anthropic.
#   2. Un `claude -p` de humo por OpenRouter con --effort y config vacía.
# Escribe results/openrouter_check.json, que run_mode_b.sh exige.
# Uso: check_openrouter.sh [--model M] [--effort E]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

load_env
MODEL="${MEDULA_AGENT_MODEL:-}"
EFFORT="${MEDULA_AGENT_EFFORT:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --effort) EFFORT="$2"; shift 2 ;;
    *) die "opción desconocida: $1" ;;
  esac
done
[[ -n "$MODEL" && -n "$EFFORT" ]] || die "faltan modelo y esfuerzo (.env o --model/--effort)"
[[ -n "${OPENROUTER_API_KEY:-}" ]] || die "falta OPENROUTER_API_KEY en .env"

out="$MEDULA_ROOT/results/openrouter_check.json"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

log "comparando effort low/high en $MODEL por /api/v1/messages (tarda un par de minutos)"
py "$MEDULA_ROOT/bench/lib/check_openrouter.py" "$MODEL" > "$tmp/api.json"

log "humo con claude -p por OpenRouter"
mkdir -p "$tmp/cfg" "$tmp/cwd"
set +e
(cd "$tmp/cwd" && env -u CLAUDE_EFFORT -u ANTHROPIC_MODEL CLAUDE_CONFIG_DIR="$tmp/cfg" \
  ANTHROPIC_BASE_URL="https://openrouter.ai/api" ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY" ANTHROPIC_API_KEY="" \
  claude -p "Responde solo con la palabra: ok" --model "$MODEL" --effort "$EFFORT" \
  --output-format json < /dev/null > "$tmp/claude.json" 2> "$tmp/claude.log")
set -e

py - "$tmp/api.json" "$tmp/claude.json" "$EFFORT" "$(claude --version | awk '{print $1}')" > "$out" <<'PY'
import json, sys
api = json.load(open(sys.argv[1]))
try:
    cc = json.load(open(sys.argv[2]))
except ValueError:
    cc = {"is_error": True, "result": open(sys.argv[2]).read()[:500]}
api["agent_effort"] = sys.argv[3]
api["claude_version"] = sys.argv[4]
api["claude_smoke"] = {k: cc.get(k) for k in ("is_error", "result", "total_cost_usd", "session_id", "terminal_reason")}
api["claude_smoke_ok"] = not cc.get("is_error") and "ok" in str(cc.get("result", "")).lower()
api["effort_passthrough"] = bool(api["effort_passthrough"] and api["claude_smoke_ok"])
json.dump(api, sys.stdout, indent=2, ensure_ascii=False)
print()
PY
py -c "
import json; d=json.load(open('$out'))
print('modelo listado:', d['model_listed'], '| tokens low/high:', d['output_tokens'], '| ratio:', d['ratio_high_low'])
print('esfuerzo inválido rechazado:', d['invalid_effort_rejected'], '| humo claude:', d['claude_smoke_ok'])
print('effort_passthrough:', d['effort_passthrough'])"
log "escrito $out"
