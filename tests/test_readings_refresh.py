"""Readings read again in case the IntelliCenter stops pushing them.

Some IntelliCenters push a value subscribed under two names (a sensor's SOURCE
and PROBE) for the first name only, so a reading can freeze while the
connection is fine (joyfulhouse/intellicenter issue 212).

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
from pyintellicenter import ModelController, PoolModel  # noqa: E402
from pyintellicenter.model import orderedAttributes  # noqa: E402

ATTRIBUTES = {
    "BODY": {"SNAME", "STATUS", "LSTTMP"},
    "CHEM": set(),
    "SENSE": {"SNAME", "SOURCE", "PROBE"},
    "PUMP": {"SNAME", "RPM"},
}


async def _wait_for(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


def _reads(panel):
    """Return the objectLists of the readings' GetParamList requests."""
    return [
        request["objectList"]
        for request in panel.requests
        if request.get("command") == "GetParamList"
        and request.get("condition") == ""
        and any(item["objnam"] == "SSW11" for item in request["objectList"])
    ]


async def _run(scenario, interval=0.05):
    panel = FakePanel()
    await panel.start()
    controller = ModelController(
        "127.0.0.1",
        PoolModel(ATTRIBUTES),
        port=panel.port,
        loop=asyncio.get_running_loop(),
        keepAliveInterval=0,
        readingsRefreshInterval=interval,
    )
    updates = []
    controller._updatedCallback = lambda ctrl, changes: updates.append(changes)
    try:
        await controller.start()
        return await scenario(panel, controller, updates)
    finally:
        controller.stop()
        await panel.close()


def test_readings_not_pushed_are_read_again():
    """Temperatures and salt changed without a push show up at the next read."""

    async def scenario(panel, controller, updates):
        # changed at the panel, not pushed
        panel.objects["SSW11"]["SOURCE"] = "75"
        panel.objects["_A135"]["SOURCE"] = "64"
        panel.objects["B1101"]["LSTTMP"] = "75"
        panel.objects["CHR01"]["SALT"] = "3300"
        await _wait_for(lambda: controller.model["CHR01"]["SALT"] == "3300")
        return controller, updates

    controller, updates = asyncio.run(_run(scenario))
    assert controller.model["SSW11"]["SOURCE"] == "75"
    assert controller.model["_A135"]["SOURCE"] == "64"
    assert controller.model["B1101"]["LSTTMP"] == "75"
    # reported like a push, so that the entities update
    changed = {}
    for update in updates:
        for objnam, params in update.items():
            changed.setdefault(objnam, {}).update(params)
    assert changed["SSW11"]["SOURCE"] == "75"
    assert changed["CHR01"]["SALT"] == "3300"


def test_only_the_readings_are_read():
    """Each read asks for the tracked readings only, not other values."""

    async def scenario(panel, controller, updates):
        await _wait_for(lambda: len(_reads(panel)) >= 2)
        return _reads(panel)[0]

    read = {item["objnam"]: item["keys"] for item in asyncio.run(_run(scenario))}
    assert read["_A135"] == ["SOURCE", "PROBE"]
    assert read["SSW11"] == ["SOURCE", "PROBE"]
    assert read["CHR01"] == ["SALT"]
    for body in ("B1101", "B1202"):
        assert read[body] == ["LSTTMP"]
    # not the IntelliChem (its values are pushed), not the pump
    assert "CHM01" not in read
    assert not any(objnam.startswith("PMP") for objnam in read)


def test_no_reads_when_disabled():
    """An interval of 0 reads nothing again."""

    async def scenario(panel, controller, updates):
        await asyncio.sleep(0.2)
        return _reads(panel)

    assert asyncio.run(_run(scenario, interval=0)) == []


def test_reads_stop_with_the_connection():
    """Stopping the controller ends the reads (no request without a connection)."""

    async def scenario(panel, controller, updates):
        await _wait_for(lambda: len(_reads(panel)) >= 1)
        task = controller._readingsTask
        controller.stop()
        await asyncio.sleep(0.01)
        return task

    task = asyncio.run(_run(scenario))
    assert task.cancelled()


def test_subscription_order_is_fixed():
    """The shown SOURCE is subscribed before PROBE, the same in every process."""
    assert orderedAttributes({"PROBE", "SNAME", "SOURCE"}) == [
        "SNAME",
        "SOURCE",
        "PROBE",
    ]
    model = PoolModel(ATTRIBUTES)
    model.addObjects(
        [{"objnam": "SSW11", "params": {"OBJTYP": "SENSE", "SNAME": "Water"}}]
    )
    assert model.attributesToTrack() == [
        {"objnam": "SSW11", "keys": ["SNAME", "SOURCE", "PROBE"]}
    ]
