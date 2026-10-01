#!/usr/bin/env bash
# Hook de Claude Code para Médula. Reenvía el JSON del hook (stdin) al servidor y
# devuelve su respuesta, que ya viene en el formato de salida de los hooks.
#
#   medula-hook.sh pre   (PreToolUse  -> /acquire)
#   medula-hook.sh post  (PostToolUse -> /notify)
#   medula-hook.sh fin   (SessionEnd  -> /release)
#
# Entorno: MEDULA_URL, MEDULA_AGENTE y MEDULA_TAREA (los fija el lanzador).
# Si Médula no responde, en `pre` sale con código 2: la herramienta queda
# bloqueada. Un hook `http` la dejaría pasar y el experimento quedaría contaminado.
set -uo pipefail

modo="${1:-}"
case "$modo" in
  pre) ruta=acquire; max=${MEDULA_HOOK_TIMEOUT:-290} ;;
  post) ruta=notify; max=55 ;;
  fin) ruta=release; max=10 ;;
  *) echo "uso: $0 pre|post|fin" >&2; exit 1 ;;
esac

if [[ -z "${MEDULA_URL:-}" || -z "${MEDULA_AGENTE:-}" ]]; then
  echo "Médula: faltan MEDULA_URL o MEDULA_AGENTE en el entorno del agente." >&2
  [[ "$modo" == pre ]] && exit 2 || exit 0
fi

respuesta=$(curl -sS --fail-with-body --max-time "$max" \
  -H 'Content-Type: application/json' \
  -H "X-Medula-Agente: ${MEDULA_AGENTE}" \
  -H "X-Medula-Tarea: ${MEDULA_TAREA:-}" \
  --data-binary @- "${MEDULA_URL%/}/$ruta" 2>&1)
rc=$?

if [[ $rc -ne 0 ]]; then
  echo "Médula no responde en ${MEDULA_URL} ($respuesta). La acción queda bloqueada hasta que vuelva." >&2
  [[ "$modo" == pre ]] && exit 2 || exit 0
fi
printf '%s' "$respuesta"
