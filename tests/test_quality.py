"""Reading the saturation index again on firmware 3.x (no Home Assistant needed).

Run with: python -m pytest tests
"""

import asyncio
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "intellicenter"),
)
sys.path.insert(0, os.path.dirname(__file__))

from fake_panel import FakePanel  # noqa: E402
import pyintellicenter.controller as controller_module  # noqa: E402
from pyintellicenter import ModelController, PoolModel  # noqa: E402

ATTRIBUTES = {"SYSTEM": {"MODE"}, "CHEM": set()}


def _quality_reads(panel):
    return [
        r
        for r in panel.requests
        if r.get("command") == "GetParamList"
        and r["objectList"][0]["objnam"] == "CHM01"
        and r["objectList"][0]["keys"] == ["QUALTY"]
    ]


async def _run(firmware, scenario):
    panel = FakePanel()
    panel.objects["_5451"]["VER"] = firmware
    await panel.start()
    controller = ModelController(
        "127.0.0.1",
        PoolModel(ATTRIBUTES),
        port=panel.port,
        loop=asyncio.get_running_loop(),
        keepAliveInterval=0,
    )
    try:
        await controller.start()
        return await scenario(panel, controller)
    finally:
        controller.stop()
        await panel.close()


def test_read_again_once_after_changes_on_firmware_3(monkeypatch):
    """Changes in a row lead to one read, which updates the model."""
    monkeypatch.setattr(controller_module, "QUALITY_REFRESH_DELAY", 0.1)

    async def scenario(panel, controller):
        panel.objects["CHM01"]["QUALTY"] = "0.2"
        for orp in ("630", "640", "650"):
            panel.set_params("CHM01", {"ORPVAL": orp})
        for _ in range(100):
            if controller.model["CHM01"]["QUALTY"] == "0.2":
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.2)
        return controller.model["CHM01"]["QUALTY"], len(_quality_reads(panel))

    assert asyncio.run(_run("IC: 3.014 , ICWEB:2026-04-22 3.014", scenario)) == (
        "0.2",
        1,
    )


def test_not_read_on_firmware_1(monkeypatch):
    """IC 1.064 pushes it: never read again."""
    monkeypatch.setattr(controller_module, "QUALITY_REFRESH_DELAY", 0.05)

    async def scenario(panel, controller):
        panel.set_params("CHM01", {"PHVAL": "7.50"})
        await asyncio.sleep(0.3)
        return controller.pushesQuality, _quality_reads(panel)

    assert asyncio.run(_run("IC: 1.064 , ICWEB:2021-10-19 1.007", scenario)) == (
        True,
        [],
    )


def test_stop_cancels_a_pending_read(monkeypatch):
    """Stopping the controller cancels a read that is waiting."""
    monkeypatch.setattr(controller_module, "QUALITY_REFRESH_DELAY", 30)

    async def scenario(panel, controller):
        panel.set_params("CHM01", {"PHVAL": "7.50"})
        for _ in range(100):
            if controller._qualityRefreshes:
                break
            await asyncio.sleep(0.01)
        task = controller._qualityRefreshes["CHM01"]
        controller.stop()
        await asyncio.sleep(0)
        return task.cancelled(), controller._qualityRefreshes

    assert asyncio.run(_run("IC: 3.014 , ICWEB:2026-04-22 3.014", scenario)) == (
        True,
        {},
    )
