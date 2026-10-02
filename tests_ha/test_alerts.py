"""The IntelliCenter's alerts, as IC 3.x raises and clears them."""

import copy
import logging

import pytest

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS

ENTITY_ID = "sensor.test_pool_alerts"
MESSAGE = "IntelliChlor 1: Communication Lost"
FIRMWARE_1 = "IC: 1.064 , ICWEB:2021-10-19 1.007"
FIRMWARE_3 = "IC: 3.014 , ICWEB:2026-04-22 3.014"


def objects(firmware=FIRMWARE_3, **extra):
    """Return the default objects, with this firmware and extra objects."""
    result = copy.deepcopy(DEFAULT_OBJECTS)
    result["_5451"]["VER"] = firmware
    result.update(extra)
    return result


@pytest.fixture
def panel_objects():
    """A panel with firmware 3.x, which pushes its alerts."""
    return objects()


def alert(message, parent, raised=None):
    """Return the object of an alert, as the IntelliCenter reports it."""
    params = {"OBJTYP": "STATUS", "SNAME": message, "PARENT": parent, "MODE": "0"}
    if raised is not None:
        params["TIME"] = str(raised)
    return params


async def test_alerts_follow_what_the_panel_raises_and_clears(
    hass: HomeAssistant, integration, panel, caplog
) -> None:
    """The sensor counts the active alerts and lists them, oldest first."""
    state = hass.states.get(ENTITY_ID)
    assert state.state == "0"
    assert state.attributes["alerts"] == []
    assert state.attributes["icon"] == "mdi:check-circle-outline"
    assert state.attributes["friendly_name"] == "Test Pool Alerts"
    entry = er.async_get(hass).async_get(ENTITY_ID)
    assert entry.unique_id == "test-unique-id_5451ALERTS"
    assert entry.entity_category is None

    panel.raise_alert("tCA05", MESSAGE, "CHR01", raised=1790963580)
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "1")
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["alerts"] == [
        {
            "message": MESSAGE,
            "equipment": "IntelliChlor 1",
            "since": "2026-10-02T17:53:00+00:00",
            "id": "tCA05",
        }
    ]
    assert state.attributes["icon"] == "mdi:alert-circle"

    # an older one is listed first
    panel.raise_alert("tCA06", "Pool: Low Flow", "B1101", raised=1790960000)
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "2")
    alerts = hass.states.get(ENTITY_ID).attributes["alerts"]
    assert [a["id"] for a in alerts] == ["tCA06", "tCA05"]
    assert alerts[0]["equipment"] == "Pool"

    panel.clear_alert("tCA05")
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "1")
    panel.clear_alert("tCA06")
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "0")

    errors = [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR and "intellicenter" in record.name
    ]
    assert not errors


@pytest.mark.parametrize(
    "panel_objects",
    [
        objects(
            tCA01=alert("IntelliChem 1: pH Tank Low", "CHM01", 1790900000),
            # about an object Home Assistant doesn't know, raised when unknown
            tCA02=alert("Panel 1: Battery Low", "PNL01"),
        )
    ],
)
async def test_alerts_active_at_setup(hass: HomeAssistant, integration) -> None:
    """Alerts raised before Home Assistant connected are shown too."""
    state = hass.states.get(ENTITY_ID)
    assert state.state == "2"
    assert state.attributes["alerts"] == [
        {"message": "Panel 1: Battery Low", "id": "tCA02"},
        {
            "message": "IntelliChem 1: pH Tank Low",
            "equipment": "IntelliChem 1",
            "since": "2026-10-02T00:13:20+00:00",
            "id": "tCA01",
        },
    ]
    # alerts aren't equipment: no entity or device of their own
    assert not [
        entry
        for entry in er.async_entries_for_config_entry(
            er.async_get(hass), integration.entry_id
        )
        if "tCA0" in entry.unique_id
    ]


@pytest.mark.parametrize(
    "connection_settings", [{"keepAliveInterval": 0.2, "keepAliveTimeout": 0.2}]
)
async def test_alerts_are_read_again_after_reconnecting(
    hass: HomeAssistant, integration, panel
) -> None:
    """Alerts raised or cleared while disconnected show once reconnected."""
    handler = integration.runtime_data
    handler._timeBetweenReconnects = 0.2
    panel.raise_alert("tCA05", MESSAGE, "CHR01")
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "1")

    panel.silent = True
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE)
    # raised and cleared without Home Assistant hearing of it
    del panel.objects["tCA05"]
    panel.objects["tCA07"] = alert("VSF: Pump Fault", "PMP01", 1790963000)

    panel.silent = False
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "1", timeout=10)
    alerts = hass.states.get(ENTITY_ID).attributes["alerts"]
    assert [(a["id"], a["equipment"]) for a in alerts] == [("tCA07", "VSF")]


async def test_alerts_in_diagnostics(hass: HomeAssistant, integration, panel) -> None:
    """Diagnostics list the active alerts."""
    from custom_components.intellicenter.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    assert (await async_get_config_entry_diagnostics(hass, integration))[
        "alerts"
    ] == {}
    panel.raise_alert("tCA05", MESSAGE, "CHR01")
    await wait_for(lambda: hass.states.get(ENTITY_ID).state == "1")
    result = await async_get_config_entry_diagnostics(hass, integration)
    assert result["alerts"]["tCA05"]["SNAME"] == MESSAGE


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_1)])
async def test_no_alerts_sensor_with_older_firmware(
    hass: HomeAssistant, integration, panel
) -> None:
    """IC 1.064 doesn't report its alerts as they come and go: no sensor."""
    assert hass.states.get(ENTITY_ID) is None
    assert not [r for r in panel.requests if r.get("condition") == "OBJTYP=STATUS"]


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_1)])
@pytest.mark.parametrize(
    "connection_settings", [{"keepAliveInterval": 0.2, "keepAliveTimeout": 0.2}]
)
async def test_firmware_update_is_picked_up(
    hass: HomeAssistant, integration, panel
) -> None:
    """After a firmware update (the panel restarts), the integration reloads."""
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr

    handler = integration.runtime_data
    handler._timeBetweenReconnects = 0.2
    handler.watcher.delay = 0.1
    assert hass.states.get(ENTITY_ID) is None

    panel.silent = True
    await wait_for(lambda: hass.states.get("switch.pool").state == STATE_UNAVAILABLE)
    panel.objects["_5451"]["VER"] = FIRMWARE_3
    panel.objects["tCA05"] = alert(MESSAGE, "CHR01", 1790963580)
    panel.silent = False

    await wait_for(
        lambda: integration.state is ConfigEntryState.LOADED
        and getattr(integration, "runtime_data", None) not in (None, handler),
        timeout=10,
    )
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "1"
    from custom_components.intellicenter.entity import get_device

    device = get_device(
        dr.async_get(hass),
        ("intellicenter", "test-unique-id"),
        integration.entry_id,
    )
    assert device.sw_version == FIRMWARE_3
