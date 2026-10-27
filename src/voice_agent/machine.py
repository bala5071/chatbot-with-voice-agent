"""This machine's hardware, recorded with every measurement (CLAUDE.md, hard rule 4)."""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any


def hardware() -> dict[str, Any]:
    info: dict[str, Any] = {
        "cpu": platform.processor(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
    }
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        info["gpu"] = out
    except (OSError, subprocess.CalledProcessError):
        info["gpu"] = None
    return info
