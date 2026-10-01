"""The integration copes with objects the panel describes only partially."""

import copy

import pytest

from homeassistant.core import HomeAssistant

from fake_panel import DEFAULT_OBJECTS


@pytest.fixture
def panel_objects():
    """A system with a few incompletely defined objects."""
    objects = copy.deepcopy(DEFAULT_OBJECTS)
    # a chlorinator that doesn't say which bodies it serves
    del objects["CHR01"]["BODY"]
    # a heater without a name
    del objects["H0001"]["SNAME"]
    # a light show whose member circuit isn't part of the system
    objects["C0010"] = {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "LITSHO",
        "SNAME": "Party",
        "PARENT": "00000",
        "STATUS": "OFF",
        "USE": "WHITER",
    }
    objects["X0101"] = {"OBJTYP": "CIRCGRP", "PARENT": "C0010", "CIRCUIT": "C9999"}
    return objects


async def test_incomplete_objects_dont_break_setup(
    hass: HomeAssistant, integration
) -> None:
    """Every platform still sets up and the incomplete objects degrade gracefully."""
    assert hass.states.get("light.test_pool_party").state == "off"
    assert "effect_list" not in hass.states.get("light.test_pool_party").attributes

    spa = hass.states.get("water_heater.spa_heater")
    assert spa.attributes["operation_list"] == ["off", "H0001"]

    assert hass.states.get("binary_sensor.vsf").state == "on"
