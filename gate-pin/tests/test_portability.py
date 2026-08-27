"""The portable core must stay portable.

gate_pin/ is what a future custom-integration wrapper would reuse verbatim. The
moment it imports FastAPI or reads SUPERVISOR_TOKEN, that stops being a
packaging job and becomes a rewrite. This test is the only thing keeping it
honest, because the violation is a one-line import that looks harmless.
"""

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "rootfs" / "app" / "gate_pin"

FORBIDDEN = [
    (re.compile(r"\bimport\s+fastapi|\bfrom\s+fastapi\b"), "FastAPI"),
    (re.compile(r"\bimport\s+uvicorn|\bfrom\s+uvicorn\b"), "uvicorn"),
    (re.compile(r"SUPERVISOR_TOKEN"), "the Supervisor token"),
    (re.compile(r"\bfrom\s+addon\b|\bimport\s+addon\b"), "the addon package"),
]


def test_core_imports_nothing_addon_specific():
    offenders = []
    for path in CORE.rglob("*.py"):
        text = path.read_text()
        for pattern, what in FORBIDDEN:
            if pattern.search(text):
                offenders.append(f"{path.name} references {what}")
    assert not offenders, "gate_pin/ must stay Supervisor- and framework-agnostic: " + "; ".join(offenders)
