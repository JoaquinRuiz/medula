#!/usr/bin/env bash
# Repite de verdad el merge y los tests de una ejecución del modo B, sin agentes.
# Parte del commit base, fusiona las ramas task/T1..T6 que dejaron los agentes y
# ejecuta los tests de aceptación. Si en la ejecución original hubo un conflicto
# textual, aplica la resolución que hizo entonces el agente (sin volver a pagarla).
#
# Uso: repetir_merge.sh <run-id>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

[[ $# -eq 1 ]] || die "uso: $0 <run-id>"
RUN="$(runs_dir)/$1"
ORIG="$RUN/repo"
[[ -d "$ORIG/.git" ]] || die "no encuentro $ORIG; ¿MEDULA_RUNS_DIR es el mismo que en la ejecución?"
BASE="$(py -c 'import json,sys; print(json.load(open(sys.argv[1]))["base_sha"])' "$RUN/logs/base.json")"
DEST="$RUN/replay-$(date +%H%M%S)"

verde() { printf '\033[32m%s\033[0m\n' "$*"; }
rojo() { printf '\033[31m%s\033[0m\n' "$*"; }
gris() { printf '\033[2m%s\033[0m\n' "$*"; }

git clone -q "$ORIG" "$DEST"
git -C "$DEST" checkout -q -B main "$BASE"
git -C "$DEST" fetch -q "$ORIG" 'refs/heads/task/*:refs/heads/task/*'
git -C "$DEST" config user.name medula-bench
git -C "$DEST" config user.email bench@medula.local

echo "Modo B · merge de las seis ramas sobre el commit base"
echo
for t in T1 T2 T3 T4 T5 T6; do
  gris "\$ git merge task/$t"
  if git -C "$DEST" merge -q --no-ff --no-edit -m "merge $t" "task/$t" >/dev/null 2>&1; then
    verde "  ✓ limpio"
    continue
  fi
  files=$(git -C "$DEST" diff --name-only --diff-filter=U | tr '\n' ' ')
  resolucion=$(git -C "$ORIG" log main --format=%H --grep="^merge $t\$" -1 || true)
  if [[ -n "$resolucion" ]]; then
    # Ficheros que el agente cambió además de los que estaban en conflicto.
    extra=$(git -C "$DEST" diff --name-only "$resolucion" | grep -vxF -f <(tr ' ' '\n' <<< "$files" | sed '/^$/d') | tr '\n' ' ' || true)
    # La resolución completa del agente: mismo base, mismas ramas y mismo orden que en la ejecución original.
    git -C "$DEST" read-tree -u --reset "$resolucion"
    git -C "$DEST" commit -q --no-edit
    rojo "  ✗ conflicto textual en $files"
    verde "  ✓ resuelto por el agente de resolución${extra:+ (que además cambió $extra)}"
  else
    git -C "$DEST" merge --abort
    rojo "  ✗ conflicto textual en $files → el agente no pudo resolverlo; rama descartada"
  fi
done

echo
echo "git: todas las ramas integradas. Tests de aceptación:"
echo
COLUMNS=160 "$MEDULA_ROOT/bench/evaluate.sh" "$DEST" "$DEST/../replay-evaluation.json" 2>&1 \
  | grep -E '^(FAILED|ERROR)|passed|failed' | sed -E 's/^FAILED _acceptance\//✗ /; s/ - / — /' \
  | while IFS= read -r l; do case "$l" in ✗*|*failed*) rojo "$l" ;; *) verde "$l" ;; esac; done
