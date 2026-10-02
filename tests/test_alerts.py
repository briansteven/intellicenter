"""Alerts raised and cleared by the IntelliCenter (no Home Assistant needed).

IC 3.x pushes them as a WriteParamList whose items hold "created" (the new
STATUS object) or "deleted" (its objnam) instead of "changes". Seen on IC 3.014:

    {"command": "WriteParamList", "messageID": "<random>", "response": "200",
     "objectList": [{"created": [{"objnam": "tCA05", "params": {"OBJTYP": "STATUS",
     "PARENT": "CHR01", "SNAME": "IntelliChlor 1: Communication Lost",
     "TIME": "1790963580", ...}}]}]}
    {"command": "WriteParamList", ..., "objectList": [{"deleted": ["tCA05"]}]}

Run with: python -m pytest tests
"""

import asyncio
import logging
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "intellicenter"),
)
sys.path.insert(0, os.path.dirname(__file__))

from fake_panel import FakePanel  # noqa: E402
from pyintellicenter import ModelController, PoolModel  # noqa: E402

ATTRIBUTES = {
    "SYSTEM": {"MODE", "VACFLO"},
    "BODY": {"SNAME", "STATUS", "LSTTMP"},
    "CHEM": set(),
}

MESSAGE = "IntelliChlor 1: Communication Lost"
FIRMWARE_3 = "IC: 3.014 , ICWEB:2026-04-22 3.014"


async def _wait_for(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


async def _run(scenario, prepare=None, firmware=FIRMWARE_3):
    panel = FakePanel()
    panel.objects["_5451"]["VER"] = firmware
    if prepare:
        prepare(panel)
    await panel.start()
    controller = ModelController(
        "127.0.0.1",
        PoolModel(ATTRIBUTES),
        port=panel.port,
        loop=asyncio.get_running_loop(),
        keepAliveInterval=0,
    )
    calls = []
    controller._alertsCallback = lambda ctrl, alerts: calls.append(alerts)
    try:
        await controller.start()
        return await scenario(panel, controller, calls)
    finally:
        controller.stop()
        await panel.close()


def test_alerts_active_when_connecting_are_read():
    """The alerts already raised are read with the model (not added to it)."""

    def prepare(panel):
        panel.objects["tCA05"] = {
            "OBJTYP": "STATUS",
            "PARENT": "CHR01",
            "SNAME": MESSAGE,
            "TIME": "1790963580",
            "MODE": "0",
            "COUNT": "1",
        }

    async def scenario(panel, controller, calls):
        assert controller.model["tCA05"] is None
        requests = [
            r for r in panel.requests if r.get("condition") == "OBJTYP=STATUS"
        ]
        assert len(requests) == 1
        return controller.alerts, calls

    alerts, calls = asyncio.run(_run(scenario, prepare))
    expected = {
        "tCA05": {
            "OBJTYP": "STATUS",
            "PARENT": "CHR01",
            "SNAME": MESSAGE,
            "TIME": "1790963580",
            "MODE": "0",
        }
    }
    assert alerts == expected
    assert calls == [expected]


def test_raised_and_cleared_alerts_are_followed(caplog):
    """Alerts pushed as created and deleted objects update the alerts, no error."""

    async def scenario(panel, controller, calls):
        assert controller.alerts == {}
        panel.raise_alert("tCA05", MESSAGE, "CHR01")
        await _wait_for(lambda: "tCA05" in controller.alerts)
        raised = controller.alerts
        panel.clear_alert("tCA05")
        await _wait_for(lambda: controller.alerts == {})
        return raised, calls

    with caplog.at_level(logging.DEBUG):
        raised, calls = asyncio.run(_run(scenario))

    assert raised["tCA05"]["SNAME"] == MESSAGE
    assert raised["tCA05"]["PARENT"] == "CHR01"
    assert raised["tCA05"]["TIME"] == "1790963580"
    # only the attributes that are kept (not COUNT, SHOMNU, PARTY...)
    assert set(raised["tCA05"]) == {"OBJTYP", "SNAME", "PARENT", "TIME", "MODE"}
    assert [list(alerts) for alerts in calls] == [["tCA05"], []]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_changes_pushed_as_write_param_list_are_applied():
    """A WriteParamList with changes still updates the model."""

    async def scenario(panel, controller, calls):
        panel.push_write_param_list(
            {"changes": [{"objnam": "B1101", "params": {"LSTTMP": "81"}}]}
        )
        await _wait_for(lambda: controller.model["B1101"]["LSTTMP"] == "81")
        return calls

    assert asyncio.run(_run(scenario)) == []


def test_other_objects_created_or_deleted_are_not_alerts(caplog):
    """Created or deleted objects of other types aren't alerts (and aren't errors)."""

    async def scenario(panel, controller, calls):
        panel.push_write_param_list(
            {"created": [{"objnam": "SCH09", "params": {"OBJTYP": "SCHED"}}]},
            {"deleted": ["SCH08"]},
        )
        panel.raise_alert("tCA05", MESSAGE, "CHR01")
        await _wait_for(lambda: "tCA05" in controller.alerts)
        return controller.alerts

    with caplog.at_level(logging.DEBUG):
        alerts = asyncio.run(_run(scenario))

    assert list(alerts) == ["tCA05"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_refused_alert_query_does_not_stop_the_start():
    """A system refusing to list its alerts is still loaded, without alerts."""

    def prepare(panel):
        panel.refuse_conditions.add("OBJTYP=STATUS")

    async def scenario(panel, controller, calls):
        return controller.model.numObjects, controller.alerts

    numObjects, alerts = asyncio.run(_run(scenario, prepare))
    assert numObjects > 0
    assert alerts == {}


def _alert_requests(panel):
    return [r for r in panel.requests if r.get("condition") == "OBJTYP=STATUS"]


def test_older_firmware_is_not_asked_for_alerts():
    """IC 1.064 doesn't push alerts: they aren't read either."""

    async def scenario(panel, controller, calls):
        return controller.supportsAlerts, _alert_requests(panel), controller.alerts

    supported, requests, alerts = asyncio.run(
        _run(scenario, firmware="IC: 1.064 , ICWEB:2021-10-19 1.007")
    )
    assert (supported, requests, alerts) == (False, [], {})


def test_firmware_major_version():
    """The major version is read from the system's VER."""
    from pyintellicenter import SystemInfo

    def major(version):
        return SystemInfo(
            "_5451",
            {"PROPNAME": "p", "VER": version, "MODE": "ENGLISH", "SNAME": "s"},
        ).firmwareMajor

    assert major(FIRMWARE_3) == 3
    assert major("IC: 1.064 , ICWEB:2021-10-19 1.007") == 1
    assert major("IC:2.017") == 2
    assert major("VER") is None
    assert major(None) is None


def _pushing_during_the_query(controller, reply, *pushes):
    """Make the alert query answer reply, after pushes arrived meanwhile.

    The answer is processed first and the reader carries on later: pushes
    that arrive in between must not be lost.
    """
    real = controller.sendCmd

    async def sendCmd(cmd, extra=None):
        if (extra or {}).get("condition") != "OBJTYP=STATUS":
            return await real(cmd, extra)
        for push in pushes:
            controller.receivedWriteParamList([push])
        if isinstance(reply, Exception):
            raise reply
        return {"objectList": reply}

    controller.sendCmd = sendCmd


def _status(objnam):
    return {
        "objnam": objnam,
        "params": {"OBJTYP": "STATUS", "SNAME": MESSAGE, "PARENT": "CHR01"},
    }


def test_alert_raised_while_the_alerts_are_read_is_kept():
    """An alert pushed right after an (empty) list of alerts isn't lost."""

    async def scenario():
        controller = ModelController("127.0.0.1", PoolModel(ATTRIBUTES))
        _pushing_during_the_query(controller, [], {"created": [_status("tCA05")]})
        await controller._loadAlerts()
        return controller.alerts

    assert list(asyncio.run(scenario())) == ["tCA05"]


def test_alert_cleared_while_the_alerts_are_read_is_dropped():
    """An alert listed, then deleted before the list is applied, is gone."""

    async def scenario():
        controller = ModelController("127.0.0.1", PoolModel(ATTRIBUTES))
        _pushing_during_the_query(
            controller, [_status("tCA05")], {"deleted": ["tCA05"]}
        )
        await controller._loadAlerts()
        return controller.alerts, controller._alertPushes

    alerts, pushes = asyncio.run(scenario())
    assert alerts == {}
    assert pushes is None  # pushes are only recorded while the alerts are read


def test_refused_alert_query_forgets_the_previous_alerts():
    """When the alerts can't be read again, the old ones aren't kept."""
    from pyintellicenter import CommandError

    async def scenario():
        controller = ModelController("127.0.0.1", PoolModel(ATTRIBUTES))
        controller._alerts = {"tCA05": _status("tCA05")["params"]}
        _pushing_during_the_query(
            controller, CommandError("400"), {"created": [_status("tCA06")]}
        )
        await controller._loadAlerts()
        return controller.alerts

    assert list(asyncio.run(scenario())) == ["tCA06"]
