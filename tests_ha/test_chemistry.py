"""IntelliChem and IntelliChlor settings, alarms and values."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from conftest import wait_for


async def set_value(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


@pytest.mark.parametrize(
    ("entity_id", "shown", "value", "sent"),
    [
        ("number.intellichem_1_ph_target", "7.4", 7.5, {"PHSET": "7.5"}),
        ("number.intellichem_1_orp_target", "650", 700, {"ORPSET": "700"}),
        ("number.intellichem_1_total_alkalinity", "100", 90, {"ALK": "90"}),
        ("number.intellichem_1_calcium_hardness", "348", 300, {"CALC": "300"}),
        ("number.intellichem_1_cyanuric_acid", "58", 30, {"CYACID": "30"}),
        (
            "number.intellichlor_1_superchlorinate_duration",
            "24",
            12,
            {"TIMOUT": "43200"},
        ),
    ],
)
async def test_settings(
    hass: HomeAssistant, integration, panel, entity_id, shown, value, sent
) -> None:
    """Settings show the IntelliCenter's values and change them in its format."""
    assert hass.states.get(entity_id).state == shown
    entity = er.async_get(hass).async_get(entity_id)
    assert entity.entity_category is er.EntityCategory.CONFIG

    await set_value(hass, entity_id, value)
    await wait_for(lambda: sent in panel.changes())


async def test_setting_ranges(hass: HomeAssistant, integration) -> None:
    """Setpoints are limited to what the IntelliChem accepts."""
    ph = hass.states.get("number.intellichem_1_ph_target").attributes
    assert (ph["min"], ph["max"], ph["step"]) == (7.0, 7.8, 0.1)
    orp = hass.states.get("number.intellichem_1_orp_target").attributes
    assert (orp["min"], orp["max"], orp["step"], orp["unit_of_measurement"]) == (
        400,
        800,
        10,
        "mV",
    )
    duration = hass.states.get("number.intellichlor_1_superchlorinate_duration")
    assert duration.attributes["unit_of_measurement"] == "h"


@pytest.mark.parametrize(
    ("attribute", "entity_id"),
    [
        ("PHHI", "binary_sensor.intellichem_1_ph_high_alarm"),
        ("PHLO", "binary_sensor.intellichem_1_ph_low_alarm"),
        ("ORPHI", "binary_sensor.intellichem_1_orp_high_alarm"),
        ("ORPLO", "binary_sensor.intellichem_1_orp_low_alarm"),
    ],
)
async def test_alarms(
    hass: HomeAssistant, integration, panel, attribute, entity_id
) -> None:
    """An IntelliChem alarm is a problem sensor, on while raised."""
    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["device_class"] == "problem"

    panel.set_params("CHM01", {attribute: "ON"})
    await wait_for(lambda: hass.states.get(entity_id).state == "on")


async def test_saturation_index(hass: HomeAssistant, integration, panel) -> None:
    """The saturation index is named as such; PHVOL/ORPVOL get no sensor.

    PHVOL and ORPVOL restart at every dose (seen on a real IntelliChem), so
    they aren't the running totals 3.2.0 to 3.4.0 showed them as.
    """
    index = hass.states.get("sensor.intellichem_1_saturation_index")
    assert index.state == "-0.1"
    assert index.attributes["friendly_name"] == "IntelliChem 1 Saturation index"

    unique_ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(
            er.async_get(hass), integration.entry_id
        )
    }
    assert "test-unique-idCHM01PHVOL" not in unique_ids
    assert "test-unique-idCHM01ORPVOL" not in unique_ids


async def test_feed_totals_of_earlier_versions_are_removed(
    hass: HomeAssistant, config_entry, use_panel
) -> None:
    """The feed total sensors of 3.2.0 to 3.4.0 are removed at setup."""
    from custom_components.intellicenter.const import DOMAIN

    registry = er.async_get(hass)
    kept = registry.async_get_or_create(
        "sensor", DOMAIN, "test-unique-idCHM01PHVAL", config_entry=config_entry,
        suggested_object_id="intellichem_1_ph",
    ).entity_id
    retired = [
        registry.async_get_or_create(
            "sensor", DOMAIN, f"test-unique-idCHM01{attribute}",
            config_entry=config_entry, suggested_object_id=object_id,
        ).entity_id
        for attribute, object_id in (
            ("PHVOL", "intellichem_1_ph_feed_total"),
            ("ORPVOL", "intellichem_1_orp_feed_total"),
        )
    ]

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in retired:
        assert registry.async_get(entity_id) is None, entity_id
        assert hass.states.get(entity_id) is None
    assert hass.states.get(kept).state == "7.4"
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_refused_setting_is_reported(
    hass: HomeAssistant, integration, panel
) -> None:
    """A value the IntelliChem refuses shows an error."""
    from homeassistant.exceptions import HomeAssistantError

    panel.refuse_changes["CHM01"] = "400"
    with pytest.raises(HomeAssistantError) as err:
        await set_value(hass, "number.intellichem_1_ph_target", 7.6)
    assert err.value.translation_key == "command_refused"
