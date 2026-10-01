"""Shared pool/spa equipment, with the spa's heat turned off."""

import copy

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from fake_panel import DEFAULT_OBJECTS


@pytest.fixture
def panel_objects():
    """The default system, with no heat source selected for the spa."""
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    objects["B1202"]["HEATER"] = "00000"
    objects["B1202"]["HTSRC"] = "00000"
    return objects


async def test_spa_water_heater_exists_while_its_heat_is_off(
    hass: HomeAssistant, integration
) -> None:
    """The shared heater still serves the spa when the spa's heat is off.

    Only the heater's SHARE=SHARE flag and the spa's SHARE partner say so; the
    flag looks exactly like an undefined value and must not be pruned.
    """
    registry = er.async_get(hass)
    unique_id = f"{integration.entry_id}B1202LOTMP"
    assert registry.async_get_entity_id("water_heater", "intellicenter", unique_id)
    assert hass.states.get("water_heater.test_pool_spa").state == "off"
