"""Pump speeds, and equipment changed while Home Assistant runs."""

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from conftest import wait_for

SYSTEM_ID = "test-unique-id"


@pytest.fixture(autouse=True)
def quick_reload(monkeypatch):
    """Reload right after an equipment change (instead of after a minute)."""
    import custom_components.intellicenter.equipment as equipment

    monkeypatch.setattr(equipment, "SETTLE_DELAY", 0.1)


async def enable(hass, entry, *entity_ids):
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_pump_speeds_are_disabled_by_default(hass: HomeAssistant, integration) -> None:
    """Each circuit's pump speed is a setting the user has to enable."""
    registry = er.async_get(hass)
    for entity_id in ("number.vsf_pool_speed", "number.vsf_spa_speed"):
        entity = registry.async_get(entity_id)
        assert entity is not None, entity_id
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert entity.entity_category is er.EntityCategory.CONFIG
        device = dr.async_get(hass).async_get(entity.device_id)
        assert device.name == "VSF"


async def test_pump_speeds(hass: HomeAssistant, integration, panel) -> None:
    """A pump speed is in RPM or GPM, within the pump's limits, and can be set."""
    await enable(hass, integration, "number.vsf_pool_speed", "number.vsf_spa_speed")

    pool = hass.states.get("number.vsf_pool_speed")
    assert pool.state == "3000"
    assert pool.attributes["friendly_name"] == "VSF Pool speed"
    assert pool.attributes["unit_of_measurement"] == "rpm"
    assert (pool.attributes["min"], pool.attributes["max"], pool.attributes["step"]) == (
        450,
        3450,
        10,
    )
    spa = hass.states.get("number.vsf_spa_speed")
    assert spa.state == "50"
    assert spa.attributes["unit_of_measurement"] == "gal/min"
    assert (spa.attributes["min"], spa.attributes["max"], spa.attributes["step"]) == (
        20,
        140,
        1,
    )

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.vsf_pool_speed", "value": 2500},
        blocking=True,
    )
    await wait_for(lambda: {"SPEED": "2500"} in panel.changes("p0101"))
    await wait_for(lambda: hass.states.get("number.vsf_pool_speed").state == "2500")

    # switched to flow at the panel
    panel.set_params("p0101", {"SELECT": "GPM", "SPEED": "60"})
    await wait_for(
        lambda: hass.states.get("number.vsf_pool_speed").attributes[
            "unit_of_measurement"
        ]
        == "gal/min"
    )
    assert hass.states.get("number.vsf_pool_speed").state == "60"


async def reloaded(hass, entry, old_handler):
    """Wait until the entry was set up again (with a new handler)."""
    await wait_for(
        lambda: entry.state is ConfigEntryState.LOADED
        and getattr(entry, "runtime_data", None) not in (None, old_handler)
    )
    await hass.async_block_till_done()


def unique_ids(hass, entry):
    return {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_added_equipment_is_picked_up(
    hass: HomeAssistant, integration, panel
) -> None:
    """A circuit added at the IntelliCenter shows up without a manual reload."""
    watcher = integration.runtime_data.watcher
    await watcher.async_check()
    assert watcher._reloadTimer is None  # nothing changed

    panel.objects["C0007"] = {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "GENERIC",
        "SNAME": "Cleaner",
        "STATUS": "OFF",
        "FEATR": "ON",
    }
    handler = integration.runtime_data
    await watcher.async_check()
    await reloaded(hass, integration, handler)
    assert hass.states.get("switch.test_pool_cleaner").state == "off"


async def test_removed_equipment_is_dropped(
    hass: HomeAssistant, integration, panel
) -> None:
    """A circuit removed at the IntelliCenter goes away from Home Assistant."""
    handler = integration.runtime_data
    del panel.objects["C0004"]
    await handler.watcher.async_check()
    await reloaded(hass, integration, handler)
    assert hass.states.get("switch.test_pool_waterfall").state == "unavailable"
    assert integration.runtime_data.controller.model["C0004"] is None


async def test_featured_circuit_becomes_a_switch(
    hass: HomeAssistant, integration, panel
) -> None:
    """A circuit made featured at the IntelliCenter gets its switch."""
    assert f"{SYSTEM_ID}C0005" not in unique_ids(hass, integration)
    panel.objects["C0005"] = {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "GENERIC",
        "SNAME": "Blower",
        "STATUS": "OFF",
        "FEATR": "OFF",
    }
    handler = integration.runtime_data
    await handler.watcher.async_check()  # added: reload
    await reloaded(hass, integration, handler)
    assert integration.runtime_data.controller.model["C0005"] is not None
    assert f"{SYSTEM_ID}C0005" not in unique_ids(hass, integration)

    panel.set_params("C0005", {"FEATR": "ON"})
    await wait_for(lambda: f"{SYSTEM_ID}C0005" in unique_ids(hass, integration))


async def test_renamed_body_renames_its_device(
    hass: HomeAssistant, integration, panel
) -> None:
    """A body renamed at the IntelliCenter renames its device (and entities)."""
    panel.set_params("B1202", {"SNAME": "Hot Tub"})
    await wait_for(
        lambda: hass.states.get("switch.spa").attributes["friendly_name"] == "Hot Tub"
    )
    assert hass.states.get("water_heater.spa_heater").attributes["friendly_name"] == (
        "Hot Tub Heater"
    )
    assert integration.runtime_data.watcher._reloadTimer is None


async def test_unload_cancels_a_pending_reload(
    hass: HomeAssistant, integration, panel, monkeypatch
) -> None:
    """Unloading while a reload is pending leaves nothing behind."""
    import custom_components.intellicenter.equipment as equipment

    watcher = integration.runtime_data.watcher
    watcher.delay = 60
    del panel.objects["C0004"]
    await watcher.async_check()
    assert watcher._reloadTimer is not None
    assert await hass.config_entries.async_unload(integration.entry_id)
    assert watcher._reloadTimer is None
    assert equipment  # (module patched by the fixture)
