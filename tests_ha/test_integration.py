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


async def test_reload(hass: HomeAssistant, integration, panel) -> None:
    """Reloading the entry reconnects and brings the entities back."""
    assert await hass.config_entries.async_reload(integration.entry_id)
    await wait_for(lambda: hass.states.get("switch.test_pool_pool").state == "on")
    assert panel.connections == 2


async def test_unload_before_the_panel_is_reached(
    hass: HomeAssistant, panel, caplog
) -> None:
    """An entry whose panel was never reached unloads cleanly."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from unittest.mock import patch

    import custom_components.intellicenter as ic
    from homeassistant.config_entries import ConfigEntryState

    from homeassistant.setup import async_setup_component

    # in a real installation other integrations have loaded these already
    for platform in ic.PLATFORMS:
        assert await async_setup_component(hass, platform, {})

    real_controller = ic.ModelController
    panel.silent = True

    def controller_factory(host, model, **kwargs):
        return real_controller(host, model, port=panel.port, **kwargs)

    entry = MockConfigEntry(domain="intellicenter", data={"host": "127.0.0.1"})
    entry.add_to_hass(hass)
    with patch.object(ic, "ModelController", controller_factory):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await wait_for(lambda: panel.connections == 1)
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert "Error unloading entry" not in caplog.text


@pytest.mark.parametrize("body", ["B1101", "B1202"])
async def test_shared_heater_reports_heating_either_body(
    hass: HomeAssistant, integration, panel, body
) -> None:
    """The heater sensor is on while it heats the pool or the spa."""
    entity_id = "binary_sensor.test_pool_gas_heater"
    assert hass.states.get(entity_id).state == "off"

    panel.set_params(body, {"STATUS": "ON", "HTMODE": "1"})
    await wait_for(lambda: hass.states.get(entity_id).state == "on")

    panel.set_params(body, {"HTMODE": "0"})
    await wait_for(lambda: hass.states.get(entity_id).state == "off")


async def test_temperatures_follow_home_assistant_units(
    hass: HomeAssistant, integration, panel
) -> None:
    """A Fahrenheit panel shows Celsius values in a metric Home Assistant."""
    await hass.config.async_update(unit_system="metric")
    panel.set_params("SSW11", {"SOURCE": "77"})

    entity_id = "sensor.test_pool_water_sensor_1"
    await wait_for(lambda: hass.states.get(entity_id).state not in ("78", "77"))
    state = hass.states.get(entity_id)
    assert state.attributes["unit_of_measurement"] == "°C"
    assert float(state.state) == pytest.approx(25.0, abs=0.1)


async def test_water_heater_state_is_its_operation_mode(
    hass: HomeAssistant, integration, panel
) -> None:
    """A water heater's state is the selected heater, or off, as Home Assistant expects.

    Whether the heater is actually heating is reported by the heater's binary
    sensor, not by the water heater's state.
    """
    pool = hass.states.get("water_heater.test_pool_pool")
    assert pool.state == pool.attributes["operation_mode"] == "Gas Heater"
    # the spa body is off, but its heat source is still selected
    assert hass.states.get("water_heater.test_pool_spa").state == "Gas Heater"

    panel.set_params("B1101", {"HTMODE": "1"})
    await wait_for(lambda: hass.states.get("binary_sensor.test_pool_gas_heater").state == "on")
    assert hass.states.get("water_heater.test_pool_pool").state == "Gas Heater"

    panel.set_params("B1101", {"HEATER": "00000", "HTMODE": "0"})
    await wait_for(lambda: hass.states.get("water_heater.test_pool_pool").state == "off")
    assert hass.states.get("binary_sensor.test_pool_gas_heater").state == "off"
