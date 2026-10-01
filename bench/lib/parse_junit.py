"""Convierte el junit de pytest en el JSON de evaluación por tarea."""
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

TASKS = [f"T{i}" for i in range(1, 7)]


def grupo(classname: str, file: str | None) -> str | None:
    fuente = file or classname
    m = re.search(r"test_(t[1-6]|integration)\b", fuente)
    if not m:
        return None
    return "integration" if m.group(1) == "integration" else m.group(1).upper()


def main(junit_path: str, workspace: str) -> None:
    grupos = {g: {"passed": 0, "failed": 0, "failed_tests": []} for g in [*TASKS, "integration"]}
    otros = {"passed": 0, "failed": 0, "failed_tests": []}
    for case in ET.parse(junit_path).getroot().iter("testcase"):
        g = grupo(case.get("classname", ""), case.get("file"))
        dest = grupos.get(g, otros)
        nombre = f"{case.get('classname')}::{case.get('name')}"
        if case.find("skipped") is not None:
            continue
        if case.find("failure") is not None or case.find("error") is not None:
            dest["failed"] += 1
            dest["failed_tests"].append(nombre)
        else:
            dest["passed"] += 1
    total_p = sum(g["passed"] for g in grupos.values()) + otros["passed"]
    total_f = sum(g["failed"] for g in grupos.values()) + otros["failed"]
    res = {
        "workspace": workspace,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tasks": {t: grupos[t] for t in TASKS},
        "integration": grupos["integration"],
        "total": {"passed": total_p, "failed": total_f},
        "all_green": total_f == 0 and total_p > 0,
    }
    if otros["passed"] or otros["failed"]:
        res["other"] = otros
    json.dump(res, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
