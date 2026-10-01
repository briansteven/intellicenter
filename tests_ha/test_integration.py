"""End-to-end tests: the integration running in Home Assistant against a fake panel."""

import pytest

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from conftest import wait_for


async def test_entities_are_created(hass: HomeAssistant, integration) -> None:
    """The main entities exist and report the panel's values."""
    assert hass.states.get("switch.test_pool_pool").state == "on"
    assert hass.states.get("switch.test_pool_spa").state == "off"
    assert hass.states.get("light.test_pool_pool_light").state == "off"
    assert hass.states.get("binary_sensor.test_pool_vsf").state == "on"

    salt = hass.states.get("sensor.test_pool_intellichlor_1_salt")
    assert salt.state == "3500"
    assert salt.attributes["unit_of_measurement"] == "ppm"


async def test_shared_heater_creates_both_water_heaters(
    hass: HomeAssistant, integration
) -> None:
    """A heater shared by pool and spa yields a water heater for each body.

    The panel lists only the pool in the heater's BODY attribute and flags the
    heater SHARE=SHARE; the spa names the pool as its SHARE partner.
    """
    registry = er.async_get(hass)
    for body in ("B1101", "B1202"):
        unique_id = f"{integration.entry_id}{body}LOTMP"
        assert registry.async_get_entity_id("water_heater", "intellicenter", unique_id)

    spa = hass.states.get("water_heater.test_pool_spa")
    assert spa.attributes["operation_list"] == ["off", "Gas Heater"]


async def test_state_follows_panel_changes(
    hass: HomeAssistant, integration, panel
) -> None:
    """A change made at the panel shows up in Home Assistant."""
    panel.set_params("C0004", {"STATUS": "ON"})
    await wait_for(lambda: hass.states.get("switch.test_pool_waterfall").state == "on")


@pytest.mark.parametrize(
    "connection_settings", [{"keepAliveInterval": 0.2, "keepAliveTimeout": 0.2}]
)
async def test_silent_panel_goes_unavailable_then_recovers(
    hass: HomeAssistant, integration, panel
) -> None:
    """A panel that stops answering is detected and reconnected when it's back."""
    import custom_components.intellicenter as ic

    handler = hass.data[ic.DOMAIN][integration.entry_id]
    handler._timeBetweenReconnects = 0.2

    panel.silent = True
    await wait_for(
        lambda: hass.states.get("switch.test_pool_pool").state == STATE_UNAVAILABLE
    )

    panel.silent = False
    await wait_for(
        lambda: hass.states.get("switch.test_pool_pool").state == "on", timeout=10
    )
