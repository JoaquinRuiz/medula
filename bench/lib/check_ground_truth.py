"""Comprueba que ground_truth.yaml cubre los 15 pares con etiquetas coherentes."""
import itertools
import sys
from pathlib import Path

import yaml

TIPOS = {"semantic": True, "false_positive_same_file": False, "none": False}

gt = yaml.safe_load((Path(__file__).resolve().parents[2] / "ground_truth.yaml").read_text())
tasks = gt["tasks"]
esperados = set(itertools.combinations(tasks, 2))
vistos, errores = set(), []
for p in gt["pairs"]:
    par = (p["a"], p["b"])
    if par not in esperados:
        errores.append(f"par no válido o desordenado: {par}")
    if par in vistos:
        errores.append(f"par duplicado: {par}")
    vistos.add(par)
    if p.get("type") not in TIPOS:
        errores.append(f"{par}: tipo desconocido {p.get('type')!r}")
    elif TIPOS[p["type"]] != p["conflict"]:
        errores.append(f"{par}: conflict={p['conflict']} no cuadra con type={p['type']}")
    if not p.get("reason"):
        errores.append(f"{par}: falta reason")
faltan = esperados - vistos
if faltan:
    errores.append(f"faltan pares: {sorted(faltan)}")
choques = sorted((p["a"], p["b"]) for p in gt["pairs"] if p["conflict"])
if choques != [("T1", "T2"), ("T3", "T4")]:
    errores.append(f"los pares en conflicto deberían ser T1-T2 y T3-T4, son {choques}")

if errores:
    print("\n".join(errores))
    sys.exit(1)
print(f"ground_truth.yaml OK: {len(vistos)} pares, {len(choques)} en conflicto: {choques}")
