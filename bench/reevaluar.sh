#!/usr/bin/env bash
# Vuelve a pasar los tests de aceptación sobre el estado final de una ejecución ya hecha
# (por ejemplo, tras corregir un test), regenera su informe y su fila de results/summary.csv,
# y deja constancia en logs/reevaluaciones.txt.
# Uso: reevaluar.sh <run-id> "<motivo>"
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
[[ $# -eq 2 ]] || die "uso: $0 <run-id> \"<motivo>\""
RUN="$(runs_dir)/$1"; LOGS="$RUN/logs"; EVID="$MEDULA_ROOT/results/runs/$1"
[[ -d "$RUN/repo/.git" ]] || die "no encuentro $RUN/repo; ¿MEDULA_RUNS_DIR es el mismo que en la ejecución?"
modo="$(py -c 'import json,sys; print(json.load(open(sys.argv[1]))["mode"])' "$LOGS/run.json")"
git -C "$RUN/repo" diff --quiet HEAD || die "$RUN/repo tiene cambios sin commit; no es el estado final"
"$MEDULA_ROOT/bench/evaluate.sh" "$RUN/repo" "$LOGS/evaluation.json" >/dev/null 2>&1
if [[ "$modo" == B ]]; then
  py "$MEDULA_ROOT/bench/lib/mode_b_report.py" "$LOGS" > "$LOGS/mode_b.json"; informe="$LOGS/mode_b.json"
else
  py "$MEDULA_ROOT/bench/lib/mode_medula_report.py" "$LOGS" > "$LOGS/mode_$modo.json"; informe="$LOGS/mode_$modo.json"
fi
py "$MEDULA_ROOT/bench/lib/summary.py" "$informe"
printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" >> "$LOGS/reevaluaciones.txt"
rsync -a "$LOGS/" "$EVID/"
py - "$LOGS/evaluation.json" "$1" <<'PY'
import json, sys
e = json.load(open(sys.argv[1]))["total"]
print(f"{sys.argv[2]}: {e['passed']} verdes, {e['failed']} rojos")
PY
