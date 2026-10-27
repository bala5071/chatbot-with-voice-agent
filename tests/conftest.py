from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("VOICE_REAL_MODELS") == "1":
        return
    skip = pytest.mark.skip(reason="needs the downloaded models; set VOICE_REAL_MODELS=1")
    for item in items:
        if "real_models" in item.keywords:
            item.add_marker(skip)
