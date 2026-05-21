import asyncio

import pytest
from looptime import LoopTimeProxy
from wandb.sdk.lib import asyncio_compat, ratelimit


@pytest.mark.asyncio
@pytest.mark.looptime
async def test_allows_first_event(looptime: LoopTimeProxy):
    cooldown = ratelimit.Cooldown(13)

    await cooldown.wait()

    # Should not sleep, so no time should pass.
    assert looptime == 0


@pytest.mark.asyncio
@pytest.mark.looptime
async def test_waits_for_cooldown(looptime: LoopTimeProxy):
    cooldown = ratelimit.Cooldown(10)

    # First event allowed immediately.
    await cooldown.wait()
    assert looptime == 0

    # No sleeping after the cooldown passes.
    await asyncio.sleep(11)
    await cooldown.wait()
    assert looptime == 11

    # The next event must wait the cooldown (10s) after the last event,
    # not from the last unblock time. This rate limiter does not adjust
    # for drift.
    await cooldown.wait()
    assert looptime == 21


@pytest.mark.asyncio
@pytest.mark.looptime
async def test_concurrent_wait(looptime: LoopTimeProxy):
    cooldown = ratelimit.Cooldown(3)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(cooldown.wait())  # Completes immediately (time = 0)
        group.start_soon(cooldown.wait())  # Completes at time = 3
        group.start_soon(cooldown.wait())  # Completes at time = 6

    assert looptime == 6
