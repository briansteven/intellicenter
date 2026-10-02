"""Schedules: a device each, enabled from Home Assistant, settings opt-in."""

import copy
from datetime import time

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS

SYSTEM_ID = "test-unique-id"
SCHEDULE = "switch.pool_schedule"

SETTINGS = [
    "select.pool_schedule_start",
    "time.pool_schedule_start_time",
    "select.pool_schedule_stop",
    "time.pool_schedule_stop_time",
    "select.pool_schedule_heater",
    "number.pool_schedule_heat_to",
    "switch.pool_schedule_vacation_only",
    "switch.pool_schedule_run_once",
] + [
    f"switch.pool_schedule_{day}"
    for day in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
]


async def enable_all(hass, entry):
    registry = er.async_get(hass)
    for entity_id in SETTINGS + ["binary_sensor.pool_schedule_running"]:
        registry.async_update_entity(entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, **data}, blocking=True
    )


async def test_schedule_device(hass: HomeAssistant, integration, panel) -> None:
    """A schedule is a device, connected through the IntelliCenter, whose main
    entity says whether it's enabled and what it does."""
    registry = er.async_get(hass)
    entity = registry.async_get(SCHEDULE)
    assert entity.unique_id == f"{SYSTEM_ID}SCH01"
    assert entity.disabled_by is None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.name == "Pool schedule"
    assert device.model == "Schedule"
    assert device.via_device_id is not None

    state = hass.states.get(SCHEDULE)
    assert state.state == "on"
    assert state.attributes["friendly_name"] == "Pool schedule"
    assert {
        key: state.attributes[key]
        for key in (
            "circuit",
            "days",
            "start",
            "stop",
            "heater",
            "heat_to",
            "vacation_only",
            "run_once",
            "running",
        )
    } == {
        "circuit": "Pool",
        "days": [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ],
        "start": "sunrise (06:49)",
        "stop": "sunset (18:35)",
        "heater": "Don't change",
        "heat_to": 78,
        "vacation_only": False,
        "run_once": False,
        "running": True,
    }

    # the settings exist, disabled until the user enables them
    for entity_id in SETTINGS + ["binary_sensor.pool_schedule_running"]:
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, entity_id
        assert entry.device_id == entity.device_id, entity_id
    assert registry.async_get("switch.pool_schedule_monday").unique_id == (
        f"{SYSTEM_ID}SCH01DAYM"
    )


async def test_enable_and_disable(hass: HomeAssistant, integration, panel) -> None:
    """The main switch enables and disables the schedule (STATUS)."""
    await call(hass, "switch", "turn_off", SCHEDULE)
    await wait_for(lambda: {"STATUS": "OFF"} in panel.changes("SCH01"))
    await wait_for(lambda: hass.states.get(SCHEDULE).state == "off")
    await call(hass, "switch", "turn_on", SCHEDULE)
    await wait_for(lambda: hass.states.get(SCHEDULE).state == "on")
    assert panel.changes("SCH01")[-1] == {"STATUS": "ON"}


async def test_start_and_stop(hass: HomeAssistant, integration, panel) -> None:
    """Start and stop follow the sun or a time; setting a time uses it."""
    await enable_all(hass, integration)
    assert hass.states.get("select.pool_schedule_start").state == "Sunrise"
    assert hass.states.get("select.pool_schedule_start").attributes["options"] == [
        "Time",
        "Sunrise",
        "Sunset",
    ]
    assert hass.states.get("time.pool_schedule_start_time").state == "06:49:00"
    assert hass.states.get("select.pool_schedule_stop").state == "Sunset"
    assert hass.states.get("time.pool_schedule_stop_time").state == "18:35:00"

    await call(hass, "time", "set_value", "time.pool_schedule_start_time", time="07:30")
    assert panel.changes("SCH01")[-1] == {"START": "ABSTIM", "TIME": "07,30,00"}
    await wait_for(lambda: hass.states.get("select.pool_schedule_start").state == "Time")
    assert hass.states.get("time.pool_schedule_start_time").state == "07:30:00"
    assert hass.states.get(SCHEDULE).attributes["start"] == "07:30"

    await call(
        hass, "select", "select_option", "select.pool_schedule_stop", option="Sunrise"
    )
    assert panel.changes("SCH01")[-1] == {"STOP": "SRIS"}
    await call(
        hass, "select", "select_option", "select.pool_schedule_stop", option="Time"
    )
    assert panel.changes("SCH01")[-1] == {"STOP": "ABSTIM"}
    await call(hass, "time", "set_value", "time.pool_schedule_stop_time", time=time(21, 5))
    assert panel.changes("SCH01")[-1] == {"STOP": "ABSTIM", "TIMOUT": "21,05,00"}


async def test_days(hass: HomeAssistant, integration, panel) -> None:
    """A switch per day; the last day can't be removed."""
    await enable_all(hass, integration)
    await call(hass, "switch", "turn_off", "switch.pool_schedule_monday")
    assert panel.changes("SCH01")[-1] == {"DAY": "TWRFAU"}
    await wait_for(lambda: hass.states.get("switch.pool_schedule_monday").state == "off")
    await call(hass, "switch", "turn_on", "switch.pool_schedule_monday")
    assert panel.changes("SCH01")[-1] == {"DAY": "MTWRFAU"}

    panel.set_params("SCH01", {"DAY": "A"})
    await wait_for(lambda: hass.states.get("switch.pool_schedule_sunday").state == "off")
    assert hass.states.get(SCHEDULE).attributes["days"] == ["Saturday"]
    await call(hass, "switch", "turn_on", "switch.pool_schedule_sunday")
    assert panel.changes("SCH01")[-1] == {"DAY": "AU"}
    await wait_for(lambda: hass.states.get("switch.pool_schedule_sunday").state == "on")

    panel.set_params("SCH01", {"DAY": "U"})
    await wait_for(lambda: hass.states.get("switch.pool_schedule_saturday").state == "off")
    sent = len(panel.changes("SCH01"))
    with pytest.raises(HomeAssistantError, match="turn Pool schedule off"):
        await call(hass, "switch", "turn_off", "switch.pool_schedule_sunday")
    assert len(panel.changes("SCH01")) == sent


async def test_heating(hass: HomeAssistant, integration, panel) -> None:
    """The heating a schedule sets: off, don't change (written 00001) or a heater."""
    await enable_all(hass, integration)
    heater = "select.pool_schedule_heater"
    assert hass.states.get(heater).state == "Don't change"
    assert hass.states.get(heater).attributes["options"] == [
        "Off",
        "Don't change",
        "Gas Heater",
    ]
    await call(hass, "select", "select_option", heater, option="Gas Heater")
    assert panel.changes("SCH01")[-1] == {"HEATER": "H0001"}
    await wait_for(lambda: hass.states.get(heater).state == "Gas Heater")
    await call(hass, "select", "select_option", heater, option="Off")
    assert panel.changes("SCH01")[-1] == {"HEATER": "00000"}
    await call(hass, "select", "select_option", heater, option="Don't change")
    assert panel.changes("SCH01")[-1] == {"HEATER": "00001"}
    await wait_for(lambda: hass.states.get(heater).state == "Don't change")

    heat_to = "number.pool_schedule_heat_to"
    state = hass.states.get(heat_to)
    assert state.state == "78"
    assert (state.attributes["min"], state.attributes["max"]) == (40, 104)
    assert state.attributes["unit_of_measurement"] == "°F"
    await call(hass, "number", "set_value", heat_to, value=85)
    assert panel.changes("SCH01")[-1] == {"LOTMP": "85"}


async def test_vacation_only_and_run_once(hass: HomeAssistant, integration, panel) -> None:
    """ON/OFF settings of a schedule."""
    await enable_all(hass, integration)
    await call(hass, "switch", "turn_on", "switch.pool_schedule_vacation_only")
    assert panel.changes("SCH01")[-1] == {"VACFLO": "ON"}
    await call(hass, "switch", "turn_on", "switch.pool_schedule_run_once")
    assert panel.changes("SCH01")[-1] == {"SINGLE": "ON"}
    await wait_for(lambda: hass.states.get(SCHEDULE).attributes["run_once"] is True)


async def test_running(hass: HomeAssistant, integration, panel) -> None:
    """On while the schedule runs."""
    await enable_all(hass, integration)
    assert hass.states.get("binary_sensor.pool_schedule_running").state == "on"
    panel.set_params("SCH01", {"ACT": "OFF"})
    await wait_for(
        lambda: hass.states.get("binary_sensor.pool_schedule_running").state == "off"
    )
    assert hass.states.get(SCHEDULE).attributes["running"] is False


async def test_renamed_schedule_renames_its_device(
    hass: HomeAssistant, integration, panel
) -> None:
    """Renamed at the IntelliCenter, the schedule's device follows."""
    panel.set_params("SCH01", {"SNAME": "Morning"})
    device_id = er.async_get(hass).async_get(SCHEDULE).device_id
    registry = dr.async_get(hass)
    await wait_for(lambda: registry.async_get(device_id).name == "Morning schedule")


def named_schedule():
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    objects["SCH01"]["SNAME"] = "Cleaner Schedule"
    return objects


@pytest.mark.parametrize("panel_objects", [named_schedule()])
async def test_schedule_named_schedule(hass: HomeAssistant, integration) -> None:
    """A schedule already called "... schedule" keeps its name."""
    assert hass.states.get("switch.cleaner_schedule").attributes["friendly_name"] == (
        "Cleaner Schedule"
    )


async def test_several_days_at_once(hass: HomeAssistant, integration, panel) -> None:
    """One action on several days changes them all."""
    await enable_all(hass, integration)
    await call(
        hass,
        "switch",
        "turn_off",
        ["switch.pool_schedule_saturday", "switch.pool_schedule_sunday"],
    )
    await wait_for(lambda: panel.objects["SCH01"]["DAY"] == "MTWRF")
    await wait_for(lambda: hass.states.get("switch.pool_schedule_sunday").state == "off")
    assert hass.states.get("switch.pool_schedule_saturday").state == "off"


async def test_days_changed_before_the_panel_reports(
    hass: HomeAssistant, integration, panel
) -> None:
    """A day changed before the panel reported the previous change keeps it."""
    await enable_all(hass, integration)
    panel.hold_notify = True
    await call(hass, "switch", "turn_off", "switch.pool_schedule_saturday")
    await call(hass, "switch", "turn_off", "switch.pool_schedule_sunday")
    assert [change["DAY"] for change in panel.changes("SCH01")] == ["MTWRFU", "MTWRF"]
    panel.hold_notify = False
    panel.release_notify()
    await wait_for(lambda: hass.states.get("switch.pool_schedule_saturday").state == "off")
    assert hass.states.get("switch.pool_schedule_sunday").state == "off"

    # what the panel reports later (changed in the Pentair app) is used again
    panel.set_params("SCH01", {"DAY": "AU"})
    await wait_for(lambda: hass.states.get("switch.pool_schedule_sunday").state == "on")
    await call(hass, "switch", "turn_on", "switch.pool_schedule_monday")
    assert panel.changes("SCH01")[-1] == {"DAY": "MAU"}


def metric():
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    objects["_5451"]["MODE"] = "METRIC"
    objects["SCH01"]["LOTMP"] = "26"
    return objects


@pytest.mark.parametrize("panel_objects", [metric()])
async def test_heat_to_in_celsius(hass: HomeAssistant, integration, panel) -> None:
    """The temperature is in the IntelliCenter's unit."""
    await enable_all(hass, integration)
    heat_to = hass.data["entity_components"]["number"].get_entity(
        "number.pool_schedule_heat_to"
    )
    assert heat_to.native_unit_of_measurement == "°C"
    assert (heat_to.native_min_value, heat_to.native_max_value) == (5, 40)
    assert heat_to.native_value == 26


def two_pool_schedules():
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    objects["SCH02"] = {
        **objects["SCH01"],
        "START": "ABSTIM",
        "TIME": "20,00,00",
        "STOP": "ABSTIM",
        "TIMOUT": "22,00,00",
        "ACT": "OFF",
    }
    # an older one, with some settings missing
    objects["SCH03"] = {"OBJTYP": "SCHED", "SNAME": "Cleaner", "STATUS": "OFF"}
    # the same device name, written differently
    objects["SCH04"] = {"OBJTYP": "SCHED", "SNAME": "Cleaner Schedule", "STATUS": "OFF"}
    return objects


@pytest.mark.parametrize("panel_objects", [two_pool_schedules()])
async def test_schedules_with_the_same_name(
    hass: HomeAssistant, integration, panel
) -> None:
    """Two schedules called "Pool" are "Pool schedule 1" and "Pool schedule 2";
    a schedule missing settings only gets those it has."""
    registry = er.async_get(hass)
    devices = dr.async_get(hass)

    def device_name(unique_id):
        entity_id = registry.async_get_entity_id("switch", "intellicenter", unique_id)
        return devices.async_get(registry.async_get(entity_id).device_id).name

    assert device_name(f"{SYSTEM_ID}SCH01") == "Pool schedule 1"
    assert device_name(f"{SYSTEM_ID}SCH02") == "Pool schedule 2"
    assert device_name(f"{SYSTEM_ID}SCH03") == "Cleaner schedule 1"
    assert device_name(f"{SYSTEM_ID}SCH04") == "Cleaner Schedule 2"

    second = registry.async_get_entity_id("switch", "intellicenter", f"{SYSTEM_ID}SCH02")
    assert hass.states.get(second).attributes["start"] == "20:00"
    cleaner = [
        entry.unique_id
        for entry in er.async_entries_for_config_entry(registry, integration.entry_id)
        if "SCH03" in entry.unique_id
    ]
    assert sorted(cleaner) == [f"{SYSTEM_ID}SCH03", f"{SYSTEM_ID}SCH03ACT"]

    # renamed: the other one isn't numbered any more
    panel.set_params("SCH02", {"SNAME": "Evening"})
    await wait_for(lambda: device_name(f"{SYSTEM_ID}SCH02") == "Evening schedule")
    await wait_for(lambda: device_name(f"{SYSTEM_ID}SCH01") == "Pool schedule")


async def test_upgrade_moves_the_running_sensor(
    hass: HomeAssistant, config_entry, use_panel, panel
) -> None:
    """Before 3.7 the running sensor was on the IntelliCenter's device: it moves
    to the schedule's, keeping its entity ID and settings."""
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    system = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("intellicenter", SYSTEM_ID)},
        name="Test Pool",
    )
    old = registry.async_get_or_create(
        "binary_sensor",
        "intellicenter",
        f"{SYSTEM_ID}SCH01ACT",
        suggested_object_id="test_pool_pool_schedule",
        config_entry=config_entry,
        device_id=system.id,
        original_name="Pool schedule",
    )
    assert old.entity_id == "binary_sensor.test_pool_pool_schedule"

    await hass.config.async_update(unit_system="us_customary")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    moved = registry.async_get("binary_sensor.test_pool_pool_schedule")
    assert moved.unique_id == f"{SYSTEM_ID}SCH01ACT"
    assert devices.async_get(moved.device_id).name == "Pool schedule"
    assert hass.states.get("binary_sensor.test_pool_pool_schedule").state == "on"
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_refused_day_keeps_an_unreported_change(
    hass: HomeAssistant, integration, panel
) -> None:
    """A refused day change doesn't lose the previous, not yet reported, one."""
    await enable_all(hass, integration)
    panel.hold_notify = True
    await call(hass, "switch", "turn_off", "switch.pool_schedule_saturday")
    panel.refuse_changes["SCH01"] = "400"
    with pytest.raises(HomeAssistantError):
        await call(hass, "switch", "turn_off", "switch.pool_schedule_sunday")
    del panel.refuse_changes["SCH01"]
    await call(hass, "switch", "turn_off", "switch.pool_schedule_monday")
    assert panel.changes("SCH01")[-1] == {"DAY": "TWRFU"}
