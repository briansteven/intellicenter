"""Entities added or changed in 3.0, and diagnostics."""

import copy

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS


async def test_service_mode(hass: HomeAssistant, integration, panel) -> None:
    """On while the IntelliCenter is in service (or timeout) mode."""
    entity_id = "binary_sensor.test_pool_service_mode"
    assert hass.states.get(entity_id).state == "off"

    panel.set_params("_5451", {"SERVICE": "MANUAL"})
    await wait_for(lambda: hass.states.get(entity_id).state == "on")

    panel.set_params("_5451", {"SERVICE": "TIMOUT"})
    panel.set_params("_5451", {"SERVICE": "AUTO"})
    await wait_for(lambda: hass.states.get(entity_id).state == "off")


async def test_tank_levels(hass: HomeAssistant, integration, panel) -> None:
    """IntelliChem tank levels show as the IntelliChem does: 0 to 6."""
    assert hass.states.get("sensor.intellichem_1_ph_tank_level").state == "6"
    panel.set_params("CHM01", {"PHTNK": "1"})
    await wait_for(
        lambda: hass.states.get("sensor.intellichem_1_ph_tank_level").state == "0"
    )


async def test_pump_sensors(hass: HomeAssistant, integration) -> None:
    """Pump speed in rpm, flow as a flow rate (converted for metric systems)."""
    flow = hass.states.get("sensor.vsf_flow")
    assert flow.state == "62"
    assert flow.attributes["unit_of_measurement"] == "gal/min"
    assert flow.attributes["device_class"] == "volume_flow_rate"
    assert hass.states.get("sensor.vsf_speed").attributes["unit_of_measurement"] == "rpm"
    assert hass.states.get("sensor.vsf_power").state == "1350"


async def test_light_effects(hass: HomeAssistant, integration) -> None:
    """Color lights offer the IntelliCenter's shows, SAm included."""
    effects = hass.states.get("light.test_pool_pool_light").attributes["effect_list"]
    assert "SAm" in effects
    assert "Caribbean" in effects


async def test_schedule_running_is_disabled_by_default(
    hass: HomeAssistant, integration
) -> None:
    """A schedule's running sensor exists, disabled until the user enables it."""
    entity = er.async_get(hass).async_get("binary_sensor.pool_schedule_running")
    assert entity is not None
    assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_no_cover_without_a_position(hass: HomeAssistant, integration) -> None:
    """Cover objects without a position (IC 1.064) don't become entities."""
    assert hass.states.async_entity_ids("cover") == []


def objects_with_covers():
    """The default system with one cover that reports its position, one that doesn't."""
    result = copy.deepcopy(DEFAULT_OBJECTS)
    result["CVR01"].update({"POSIT": "ON", "NORMAL": "ON", "STATUS": "ON"})
    result["CVR02"] = {
        "OBJTYP": "EXTINSTR",
        "SUBTYP": "COVER",
        "SNAME": "Cover 2",
        "BODY": "B1202",
        "STATUS": "OFF",
    }
    return result


@pytest.mark.parametrize("panel_objects", [objects_with_covers()])
async def test_cover_position(hass: HomeAssistant, integration, panel) -> None:
    """A cover that reports its position shows it (read-only), once enabled.

    IC 3.x reports a position for every cover object, installed or not, so
    covers are disabled by default.
    """
    registry = er.async_get(hass)
    entries = [
        entry
        for entry in er.async_entries_for_config_entry(registry, integration.entry_id)
        if entry.domain == "cover"
    ]
    assert [entry.entity_id for entry in entries] == ["cover.test_pool_cover_1"]
    assert entries[0].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.async_entity_ids("cover") == []

    registry.async_update_entity("cover.test_pool_cover_1", disabled_by=None)
    assert await hass.config_entries.async_reload(integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids("cover") == ["cover.test_pool_cover_1"]
    state = hass.states.get("cover.test_pool_cover_1")
    assert state.state == "closed"
    assert state.attributes["supported_features"] == 0

    panel.set_params("CVR01", {"POSIT": "OFF"})
    await wait_for(lambda: hass.states.get("cover.test_pool_cover_1").state == "open")


async def test_diagnostics(hass: HomeAssistant, integration) -> None:
    """Diagnostics describe the system and connection, without identifying data."""
    from homeassistant.components.diagnostics import REDACTED

    from custom_components.intellicenter.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    result = await async_get_config_entry_diagnostics(hass, integration)

    import json
    import os

    import custom_components.intellicenter as ic

    with open(os.path.join(os.path.dirname(ic.__file__), "manifest.json")) as f:
        assert result["integration_version"] == json.load(f)["version"]
    assert result["entry"]["data"] == {"host": REDACTED}
    assert result["entry"]["unique_id"] == REDACTED
    assert result["entry"]["title"] == REDACTED
    assert result["system"]["firmware"] == "IC: 1.064 , ICWEB:2021-10-19 1.007"
    assert result["connection"]["connected"] is True
    assert result["connection"]["seconds_since_last_answer"] >= 0
    assert result["connection"]["keep_alive_interval"] == 60

    objects = {obj["objnam"]: obj for obj in result["objects"]}
    assert objects["_5451"]["properties"]["SNAME"] == REDACTED
    assert objects["B1101"]["properties"]["SNAME"] == "Pool"
    text = str(result)
    assert "test-system-sname" not in text
    assert "127.0.0.1" not in text
    assert "test-unique-id" not in text
