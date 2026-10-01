#!/usr/bin/env bash
# Ejecuta los tests de aceptación sobre un workspace y escribe un JSON por tarea.
# Uso: evaluate.sh <workspace> [salida.json]
# Sale con 0 si la evaluación se pudo hacer, aunque haya tests en rojo.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

[[ $# -ge 1 && $# -le 2 ]] || die "uso: $0 <workspace> [salida.json]"
ws="$(cd "$1" && pwd -P)"
out="${2:-$ws/../evaluation.json}"
[[ -d "$ws/app" ]] || die "$ws no parece un workspace de demo-app (falta app/)"

acc="$ws/_acceptance"
[[ -e "$acc" ]] && die "$acc ya existe; ¿evaluación a medias?"
junit="$(mktemp -t medula-junit.XXXXXX)"
cleanup() { rm -rf "$acc" "$junit"; }
trap cleanup EXIT

rsync -a --exclude '__pycache__' "$MEDULA_ROOT/acceptance/" "$acc/"

set +e
# El workspace es un proyecto uv propio (el de demo-app): uv run pytest usa su entorno.
(cd "$ws" && env -u VIRTUAL_ENV PYTHONPATH="$ws" MEDULA_DB_PATH="$ws/_acceptance/unused.db" \
  uv run --quiet pytest _acceptance -q -p no:cacheprovider --junitxml="$junit" -o junit_family=xunit2 >&2)
rc=$?
set -e
# 0 = todo verde, 1 = hay fallos; otro código = pytest no pudo ejecutarse.
[[ $rc -le 1 ]] || die "pytest terminó con código $rc"

py "$MEDULA_ROOT/bench/lib/parse_junit.py" "$junit" "$ws" > "$out.tmp"
mv "$out.tmp" "$out"
log "evaluación escrita en $out"
