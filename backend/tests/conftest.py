from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.helpers import Rig


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    rig = Rig()
    yield rig
    await rig.close()
