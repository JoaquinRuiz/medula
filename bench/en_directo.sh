#!/usr/bin/env bash
# Lanza una ejecución de los modos C-F y muestra el htop de Médula en la misma terminal,
# a pantalla completa, con las últimas líneas de la ejecución abajo. Sale solo al terminar
# y deja en pantalla el estado final y el resultado de los tests.
#
# Uso: MEDULA_RUNS_DIR=/tmp/mr bench/en_directo.sh --modo D --run-id d2 [resto de opciones de run_mode.sh]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

RUN_ID=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  [[ "${args[$i]}" == --run-id ]] && RUN_ID="${args[$((i + 1))]:-}"
done
[[ -n "$RUN_ID" ]] || die "pasa --run-id (hace falta para saber dónde mirar)"
RUN="$(runs_dir)/$RUN_ID"
[[ -e "$RUN" ]] && die "$RUN ya existe"
SALIDA="$(mktemp -t medula-en-directo.XXXXXX)"

"$MEDULA_ROOT/bench/run_mode.sh" "$@" > "$SALIDA" 2>&1 &
PID=$!
env -u VIRTUAL_ENV uv run --quiet --project "$MEDULA_ROOT/medula" medula htop \
  --db "$RUN/medula.db" --log "$SALIDA" --mientras-pid "$PID" || true
wait "$PID" || true
echo
grep -E '^\[|^FAILED| passed| failed' "$SALIDA" | tail -25
