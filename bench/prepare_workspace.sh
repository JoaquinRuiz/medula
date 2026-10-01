#!/usr/bin/env bash
# Copia demo-app/ a un directorio nuevo, hace git init y un commit base.
# Uso: prepare_workspace.sh <destino>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

[[ $# -eq 1 ]] || die "uso: $0 <destino>"
dest="$1"
[[ -e "$dest" ]] && die "$dest ya existe"

mkdir -p "$(dirname "$dest")"
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.db' \
  "$MEDULA_ROOT/demo-app/" "$dest/"

git -C "$dest" init -q -b main
git -C "$dest" config user.name "medula-bench"
git -C "$dest" config user.email "bench@medula.local"
git -C "$dest" config commit.gpgsign false
git -C "$dest" add -A
git -C "$dest" commit -q -m "base: demo-app initial state"

(cd "$dest" && pwd -P)
