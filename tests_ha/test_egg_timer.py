"""Egg timers: how long a circuit runs once turned on by hand."""

import copy

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS

SYSTEM_ID = "test-unique-id"

# entity: (unique ID, device)
EGG_TIMERS = {
    "number.spa_egg_timer": (f"{SYSTEM_ID}C0001TIME", "Spa"),
    "switch.spa_do_not_stop": (f"{SYSTEM_ID}C0001DNTSTP", "Spa"),
    "number.pool_egg_timer": (f"{SYSTEM_ID}C0006TIME", "Pool"),
    "switch.pool_do_not_stop": (f"{SYSTEM_ID}C0006DNTSTP", "Pool"),
    "number.test_pool_pool_light_egg_timer": (f"{SYSTEM_ID}C0002TIME", "Test Pool"),
    "switch.test_pool_pool_light_do_not_stop": (
        f"{SYSTEM_ID}C0002DNTSTP",
        "Test Pool",
    ),
    "number.test_pool_waterfall_egg_timer": (f"{SYSTEM_ID}C0004TIME", "Test Pool"),
    "switch.test_pool_waterfall_do_not_stop": (
        f"{SYSTEM_ID}C0004DNTSTP",
        "Test Pool",
    ),
}


async def enable(hass, entry, *entity_ids):
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


def integration_unique_ids(hass, entry):
    return {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_egg_timers_are_disabled_by_default(
    hass: HomeAssistant, integration
) -> None:
    """Bodies, lights and featured circuits get an egg timer setting, disabled.

    A body's circuit has it on the body's device; other circuits on the
    IntelliCenter's. Circuits without a switch or light (AUX 3, not featured)
    and commands ("All Lights On") get none.
    """
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    for entity_id, (unique_id, device_name) in EGG_TIMERS.items():
        entity = registry.async_get(entity_id)
        assert entity is not None, entity_id
        assert entity.unique_id == unique_id
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert entity.entity_category is er.EntityCategory.CONFIG
        assert devices.async_get(entity.device_id).name == device_name, entity_id

    unique_ids = integration_unique_ids(hass, integration)
    for objnam in ("C0003", "_A111"):
        assert f"{SYSTEM_ID}{objnam}TIME" not in unique_ids
        assert f"{SYSTEM_ID}{objnam}DNTSTP" not in unique_ids


async def test_egg_timer(hass: HomeAssistant, integration, panel) -> None:
    """The egg timer is in minutes, up to 23:59, and can be set."""
    await enable(
        hass, integration, "number.spa_egg_timer", "number.test_pool_waterfall_egg_timer"
    )

    spa = hass.states.get("number.spa_egg_timer")
    assert spa.state == "720"
    assert spa.attributes["friendly_name"] == "Spa Egg timer"
    assert spa.attributes["unit_of_measurement"] == "min"
    assert spa.attributes["device_class"] == "duration"
    assert (spa.attributes["min"], spa.attributes["max"], spa.attributes["step"]) == (
        1,
        1439,
        1,
    )
    assert (
        hass.states.get("number.test_pool_waterfall_egg_timer").attributes[
            "friendly_name"
        ]
        == "Test Pool Waterfall egg timer"
    )

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.spa_egg_timer", "value": 240},
        blocking=True,
    )
    await wait_for(lambda: {"TIME": "240"} in panel.changes("C0001"))
    await wait_for(lambda: hass.states.get("number.spa_egg_timer").state == "240")

    # changed at the panel
    panel.set_params("C0001", {"TIME": "90"})
    await wait_for(lambda: hass.states.get("number.spa_egg_timer").state == "90")


async def test_do_not_stop(hass: HomeAssistant, integration, panel) -> None:
    """Don't Stop runs the circuit until it is turned off."""
    await enable(hass, integration, "switch.spa_do_not_stop")

    assert hass.states.get("switch.spa_do_not_stop").state == "off"
    assert (
        hass.states.get("switch.spa_do_not_stop").attributes["friendly_name"]
        == "Spa Do not stop"
    )

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.spa_do_not_stop"}, blocking=True
    )
    await wait_for(lambda: {"DNTSTP": "ON"} in panel.changes("C0001"))
    await wait_for(lambda: hass.states.get("switch.spa_do_not_stop").state == "on")
    # the spa itself isn't turned on
    assert {"STATUS": "ON"} not in panel.changes("C0001")
    assert panel.changes("B1202") == []

    panel.set_params("C0001", {"DNTSTP": "OFF"})
    await wait_for(lambda: hass.states.get("switch.spa_do_not_stop").state == "off")


def without_egg_timers():
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    for obj in objects.values():
        obj.pop("TIME", None)
        obj.pop("DNTSTP", None)
    # and a body whose circuit isn't known
    del objects["B1202"]["FILTER"]
    return objects


@pytest.mark.parametrize("panel_objects", [without_egg_timers()])
async def test_no_egg_timer_where_none_is_reported(
    hass: HomeAssistant, integration
) -> None:
    """An IntelliCenter that reports no egg timers gets no settings for them."""
    unique_ids = integration_unique_ids(hass, integration)
    assert not [
        unique_id
        for unique_id in unique_ids
        if unique_id.endswith("TIME") or unique_id.endswith("DNTSTP")
    ]
    # everything else is there
    assert hass.states.get("switch.spa").state == "off"
    assert hass.states.get("switch.test_pool_waterfall").state == "off"


def spa_circuit_unknown():
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    del objects["B1202"]["FILTER"]
    return objects


@pytest.mark.parametrize("panel_objects", [spa_circuit_unknown()])
async def test_body_circuit_unknown(hass: HomeAssistant, integration) -> None:
    """Without a link to its body, a body's circuit gets no egg timer setting."""
    registry = er.async_get(hass)
    unique_ids = integration_unique_ids(hass, integration)
    assert f"{SYSTEM_ID}C0001TIME" not in unique_ids
    assert registry.async_get("number.pool_egg_timer") is not None
