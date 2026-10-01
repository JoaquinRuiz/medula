#!/usr/bin/env bash
# Comprueba que el diseño de choques (E-02) se cumple de verdad con git y los tests.
#   1. App sin tocar            -> las seis tareas y la integración con tests en rojo.
#   2. Cada tarea aislada       -> sus tests de demo-app en verde (se puede hacer sola).
#   3. Los 15 pares en ramas    -> git los fusiona todos sin conflicto textual,
#                                  también T1-T2 y T3-T4 (distinto fichero) y T5-T6 (mismo fichero).
#   4. Merge de las seis ramas  -> en rojo exactamente T2, T4 e integración:
#                                  los choques semánticos que git no ve.
#   5. Integración correcta     -> todo en verde.
# Las soluciones salen de reference/ (bench/lib/make_reference.py).
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

TASKS=(T1 T2 T3 T4 T5 T6)
REF="$MEDULA_ROOT/reference"
base="$(runs_dir)/self-check-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$base"
ev() { "$MEDULA_ROOT/bench/evaluate.sh" "$1" "$2" 2>/dev/null; }
q() { py -c "import json,sys; d=json.load(open(sys.argv[1])); $2" "$1"; }
red_set() { q "$1" 'print(" ".join(sorted(k for k,v in {**d["tasks"],"integration":d["integration"]}.items() if v["failed"])))'; }
demo_tests() { (cd "$1" && env -u VIRTUAL_ENV uv run --quiet pytest -q -p no:cacheprovider >/dev/null 2>&1); }

# 1
ws=$("$MEDULA_ROOT/bench/prepare_workspace.sh" "$base/untouched")
ev "$ws" "$base/untouched.json"
[[ "$(red_set "$base/untouched.json")" == "T1 T2 T3 T4 T5 T6 integration" ]] \
  || die "la app sin tocar debería tener rojos en todas las tareas: $(red_set "$base/untouched.json")"
echo "1. app sin tocar: rojos en T1-T6 e integración"

# 2 y ramas para 3-4
repo=$("$MEDULA_ROOT/bench/prepare_workspace.sh" "$base/branches")
base_sha=$(git -C "$repo" rev-parse HEAD)
for t in "${TASKS[@]}"; do
  git -C "$repo" checkout -q -b "task/$t" "$base_sha"
  git -C "$repo" apply "$REF/tasks/$t.patch"
  demo_tests "$repo" || die "$t aislada: los tests de demo-app no pasan"
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "$t"
done
echo "2. cada tarea aislada: tests de demo-app en verde"

# 3
for ((i = 0; i < ${#TASKS[@]}; i++)); do
  for ((j = i + 1; j < ${#TASKS[@]}; j++)); do
    a=${TASKS[$i]}; b=${TASKS[$j]}
    git -C "$repo" checkout -q -B "pair" "task/$a"
    if ! git -C "$repo" merge -q --no-ff -m "pair $a $b" "task/$b" >/dev/null 2>&1; then
      files=$(git -C "$repo" diff --name-only --diff-filter=U | tr '\n' ' ')
      git -C "$repo" merge --abort
      die "$a + $b dan conflicto textual en: $files"
    fi
  done
done
echo "3. los 15 pares se fusionan sin conflicto textual"

# 4
git -C "$repo" checkout -q -B main "$base_sha"
for t in "${TASKS[@]}"; do
  git -C "$repo" merge -q --no-ff -m "merge $t" "task/$t" >/dev/null 2>&1 || die "merge de $t con conflicto"
done
ev "$repo" "$base/merged.json"
red="$(red_set "$base/merged.json")"
[[ "$red" == "T2 T4 integration" ]] || die "tras el merge ingenuo se esperaba rojo en T2 T4 integration, hay: $red"
echo "4. merge de las seis ramas sin conflictos de git, pero en rojo: $red"

# 5
ws=$("$MEDULA_ROOT/bench/prepare_workspace.sh" "$base/reference")
git -C "$ws" apply "$REF/all_tasks.patch"
ev "$ws" "$base/reference.json"
q "$base/reference.json" 'assert d["all_green"], d["total"]'
demo_tests "$ws" || die "integración correcta: los tests de demo-app no pasan"
echo "5. integración correcta: $(q "$base/reference.json" 'print(d["total"]["passed"])') tests de aceptación y demo-app en verde"
echo "OK ($base)"
