"""Devices, entity names and unique IDs, and their migration from earlier versions."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

DOMAIN = "intellicenter"
SYSTEM_ID = "test-unique-id"


def device_of(hass, entity_id):
    entity = er.async_get(hass).async_get(entity_id)
    assert entity is not None, entity_id
    return dr.async_get(hass).async_get(entity.device_id)


def friendly_name(hass, entity_id):
    return hass.states.get(entity_id).attributes["friendly_name"]


async def test_devices(hass: HomeAssistant, integration) -> None:
    """Bodies, pumps, heaters and chemistry controllers are devices of their own."""
    system = device_of(hass, "switch.test_pool_waterfall")
    assert system.identifiers == {(DOMAIN, SYSTEM_ID)}
    assert system.name == "Test Pool"
    assert system.model == "IntelliCenter"
    assert system.sw_version == "IC: 1.064 , ICWEB:2021-10-19 1.007"
    assert system.configuration_url == "http://127.0.0.1"

    expected = {
        # entity: (device name, device model)
        "switch.pool": ("Pool", "Pool"),
        "water_heater.pool_heater": ("Pool", "Pool"),
        "sensor.pool_temperature": ("Pool", "Pool"),
        "sensor.pool_target_temperature": ("Pool", "Pool"),
        "switch.spa": ("Spa", "Spa"),
        "binary_sensor.vsf": ("VSF", "Variable speed and flow pump"),
        "sensor.vsf_power": ("VSF", "Variable speed and flow pump"),
        "sensor.vsf_speed": ("VSF", "Variable speed and flow pump"),
        "sensor.vsf_flow": ("VSF", "Variable speed and flow pump"),
        "binary_sensor.gas_heater": ("Gas Heater", "Gas heater"),
        "sensor.intellichlor_1_salt": ("IntelliChlor 1", "IntelliChlor"),
        "switch.intellichlor_1_superchlorinate": ("IntelliChlor 1", "IntelliChlor"),
        "number.intellichlor_1_pool_output": ("IntelliChlor 1", "IntelliChlor"),
        "sensor.intellichem_1_ph": ("IntelliChem 1", "IntelliChem"),
        "sensor.intellichem_1_ph_tank_level": ("IntelliChem 1", "IntelliChem"),
    }
    for entity_id, (name, model) in expected.items():
        device = device_of(hass, entity_id)
        assert (device.name, device.model) == (name, model), entity_id
        assert device.via_device_id == system.id, entity_id

    for entity_id in (
        "light.test_pool_pool_light",
        "sensor.test_pool_air_sensor",
        "binary_sensor.test_pool_service_mode",
        "switch.test_pool_vacation_mode",
    ):
        assert device_of(hass, entity_id).id == system.id, entity_id


async def test_entity_names(hass: HomeAssistant, integration) -> None:
    """Entities are named the way Home Assistant names them today."""
    assert friendly_name(hass, "switch.pool") == "Pool"
    assert friendly_name(hass, "water_heater.pool_heater") == "Pool Heater"
    assert friendly_name(hass, "sensor.pool_temperature") == "Pool Temperature"
    assert friendly_name(hass, "binary_sensor.vsf") == "VSF"
    assert friendly_name(hass, "sensor.vsf_power") == "VSF Power"
    assert friendly_name(hass, "number.intellichlor_1_pool_output") == (
        "IntelliChlor 1 Pool output"
    )
    assert friendly_name(hass, "switch.test_pool_waterfall") == "Test Pool Waterfall"


async def test_renamed_circuit(hass: HomeAssistant, integration, panel) -> None:
    """A circuit renamed at the IntelliCenter is renamed in Home Assistant."""
    from conftest import wait_for

    panel.set_params("C0004", {"SNAME": "Cascade"})
    await wait_for(
        lambda: friendly_name(hass, "switch.test_pool_waterfall") == "Test Pool Cascade"
    )


async def test_unique_ids_come_from_the_system(hass: HomeAssistant, integration) -> None:
    """Unique IDs don't depend on the config entry (they survive a remove + add)."""
    registry = er.async_get(hass)
    assert registry.async_get("switch.pool").unique_id == f"{SYSTEM_ID}B1101"
    assert registry.async_get("sensor.vsf_power").unique_id == f"{SYSTEM_ID}PMP01PWR"
    assert (
        registry.async_get("water_heater.pool_heater").unique_id
        == f"{SYSTEM_ID}B1101LOTMP"
    )


async def test_removing_devices(hass: HomeAssistant, integration) -> None:
    """Only devices of equipment the IntelliCenter no longer has can be removed."""
    from custom_components.intellicenter import async_remove_config_entry_device

    registry = dr.async_get(hass)
    system = device_of(hass, "switch.test_pool_waterfall")
    pool = device_of(hass, "switch.pool")
    assert not await async_remove_config_entry_device(hass, integration, system)
    assert not await async_remove_config_entry_device(hass, integration, pool)

    gone = registry.async_get_or_create(
        config_entry_id=integration.entry_id,
        identifiers={(DOMAIN, f"{SYSTEM_ID}_PMP09")},
        name="Old pump",
    )
    assert await async_remove_config_entry_device(hass, integration, gone)

    # a device left by another version
    stale = registry.async_get_or_create(
        config_entry_id=integration.entry_id,
        identifiers={(DOMAIN, integration.entry_id)},
        name="Old system device",
    )
    assert await async_remove_config_entry_device(hass, integration, stale)

    # while the integration isn't loaded
    assert await hass.config_entries.async_unload(integration.entry_id)
    assert await async_remove_config_entry_device(hass, integration, gone)
    assert not await async_remove_config_entry_device(hass, integration, system)


async def test_migration_from_earlier_versions(
    hass: HomeAssistant, config_entry, use_panel, caplog
) -> None:
    """Entities and the system's device keep their IDs, settings and area."""
    caplog.set_level(logging.INFO)
    await hass.config.async_update(unit_system="us_customary")
    entry_id = config_entry.entry_id
    entities = er.async_get(hass)
    devices = dr.async_get(hass)

    backyard = ar.async_get(hass).async_create("Backyard")
    old_device = devices.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Pentair",
        model="IntelliCenter",
        name="Test Pool",
    )
    devices.async_update_device(old_device.id, area_id=backyard.id)

    def old_entity(domain, unique_id, object_id, **kwargs):
        return entities.async_get_or_create(
            domain,
            DOMAIN,
            unique_id,
            config_entry=config_entry,
            device_id=old_device.id,
            suggested_object_id=object_id,
            **kwargs,
        ).entity_id

    # 2.x and dwradcliffe's: the entry ID, then the object (and attribute)
    pool = old_entity("switch", f"{entry_id}B1101", "pool")
    entities.async_update_entity(pool, name="My Pool")
    power = old_entity("sensor", f"{entry_id}PMP01PWR", "vsf_power")
    heater = old_entity("water_heater", f"{entry_id}B1101LOTMP", "pool")
    # an object whose name starts with an underscore
    air = old_entity("sensor", f"{entry_id}_A135SOURCE", "air_sensor")
    # joyfulhouse's: with an underscore
    waterfall = old_entity("switch", f"{entry_id}_C0004", "waterfall")
    water = old_entity("sensor", f"{entry_id}_SSW11SOURCE", "water_sensor_1")

    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()

    expected = {
        pool: f"{SYSTEM_ID}B1101",
        power: f"{SYSTEM_ID}PMP01PWR",
        heater: f"{SYSTEM_ID}B1101LOTMP",
        waterfall: f"{SYSTEM_ID}C0004",
        air: f"{SYSTEM_ID}_A135SOURCE",
        water: f"{SYSTEM_ID}SSW11SOURCE",
    }
    for entity_id, unique_id in expected.items():
        assert entities.async_get(entity_id).unique_id == unique_id
        assert hass.states.get(entity_id) is not None, entity_id

    # the same entity IDs, with their settings, and no duplicates
    assert (pool, power, heater, waterfall) == (
        "switch.pool",
        "sensor.vsf_power",
        "water_heater.pool",
        "switch.waterfall",
    )
    assert hass.states.get("switch.pool").attributes["friendly_name"] == "My Pool"
    assert hass.states.get("switch.pool_2") is None
    assert hass.states.get("water_heater.pool_heater") is None

    # the system's device is the same device (automations refer to its ID)
    system = devices.async_get(old_device.id)
    assert system.identifiers == {(DOMAIN, SYSTEM_ID)}
    assert system.area_id == backyard.id

    # the new devices start in the system's area, like their entities were
    for entity_id in (pool, power, heater, "binary_sensor.gas_heater"):
        assert device_of(hass, entity_id).area_id == backyard.id, entity_id

    assert await hass.config_entries.async_unload(entry_id)

    # it does nothing the next time
    caplog.clear()
    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()
    assert "migrating" not in caplog.text
    assert await hass.config_entries.async_unload(entry_id)


async def test_migration_skips_an_id_already_taken(
    hass: HomeAssistant, config_entry, use_panel, caplog
) -> None:
    """An old entity whose new unique ID exists already (e.g. after a downgrade) is left alone."""
    entities = er.async_get(hass)
    current = entities.async_get_or_create(
        "switch", DOMAIN, f"{SYSTEM_ID}B1101", config_entry=config_entry,
        suggested_object_id="pool",
    ).entity_id
    stale = entities.async_get_or_create(
        "switch", DOMAIN, f"{config_entry.entry_id}B1101", config_entry=config_entry,
        suggested_object_id="pool_2",
    ).entity_id

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert entities.async_get(current).unique_id == f"{SYSTEM_ID}B1101"
    assert entities.async_get(stale).unique_id == f"{config_entry.entry_id}B1101"
    assert f"not migrating {stale}" in caplog.text
    assert hass.states.get(current).state == "on"
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_entry_without_unique_id(hass: HomeAssistant, use_panel) -> None:
    """An entry without a unique ID still works (with entry-based unique IDs)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, title="Test Pool", data={"host": "127.0.0.1"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.async_get("switch.pool").unique_id == f"{entry.entry_id}B1101"
    assert device_of(hass, "switch.pool").via_device_id == device_of(
        hass, "switch.test_pool_waterfall"
    ).id
    assert await hass.config_entries.async_unload(entry.entry_id)
