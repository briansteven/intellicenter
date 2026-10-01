"""Tests for commands sent from Home Assistant to the panel."""

import threading

import pytest

from homeassistant.core import HomeAssistant

from conftest import wait_for


@pytest.mark.parametrize(
    ("domain", "service", "data", "objnam", "expected"),
    [
        ("switch", "turn_on", {"entity_id": "switch.spa"}, "B1202", {"STATUS": "ON"}),
        ("switch", "turn_off", {"entity_id": "switch.test_pool_waterfall"}, "C0004", {"STATUS": "OFF"}),
        ("light", "turn_on", {"entity_id": "light.test_pool_pool_light"}, "C0002", {"STATUS": "ON"}),
        (
            "number",
            "set_value",
            {"entity_id": "number.intellichlor_1_pool_output", "value": 30},
            "CHR01",
            {"PRIM": "30"},
        ),
        (
            "water_heater",
            "set_temperature",
            {"entity_id": "water_heater.spa_heater", "temperature": 101},
            "B1202",
            {"LOTMP": "101"},
        ),
        (
            "water_heater",
            "set_operation_mode",
            {"entity_id": "water_heater.spa_heater", "operation_mode": "off"},
            "B1202",
            {"HEATER": "00000"},
        ),
    ],
)
async def test_commands_are_sent_from_the_event_loop(
    hass: HomeAssistant, integration, panel, domain, service, data, objnam, expected
) -> None:
    """Commands reach the panel, written to the socket from the event loop thread.

    asyncio transports are not thread safe: a write from an executor thread races
    with the event loop and can wedge the request queue for good.
    """
    from custom_components.intellicenter.pyintellicenter.protocol import ICProtocol

    loop_thread = threading.get_ident()
    write_threads = []
    original = ICProtocol._writeToTransport

    def recording_write(self, request):
        write_threads.append(threading.get_ident())
        return original(self, request)

    ICProtocol._writeToTransport = recording_write
    try:
        await hass.services.async_call(domain, service, data, blocking=True)
        await wait_for(lambda: expected in panel.changes(objnam))
    finally:
        ICProtocol._writeToTransport = original

    assert write_threads, "nothing was sent to the panel"
    assert set(write_threads) == {loop_thread}


async def test_water_heater_turn_on_and_off(hass: HomeAssistant, integration, panel) -> None:
    """Water heaters support on/off, turning on with the heater used last."""
    entity_id = "water_heater.spa_heater"
    await hass.services.async_call(
        "water_heater", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await wait_for(lambda: {"HEATER": "00000"} in panel.changes("B1202"))

    await hass.services.async_call(
        "water_heater", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    await wait_for(lambda: {"HEATER": "H0001"} in panel.changes("B1202"))


async def test_request_from_another_thread_is_sent_from_the_loop(
    hass: HomeAssistant, integration, panel
) -> None:
    """A change requested from a worker thread is handed over to the event loop."""
    from custom_components.intellicenter.pyintellicenter.protocol import ICProtocol

    component = hass.data["entity_components"]["switch"]
    entity = component.get_entity("switch.test_pool_waterfall")

    loop_thread = threading.get_ident()
    write_threads = []
    original = ICProtocol._writeToTransport

    def recording_write(self, request):
        write_threads.append(threading.get_ident())
        return original(self, request)

    ICProtocol._writeToTransport = recording_write
    try:
        await hass.async_add_executor_job(entity.requestChanges, {"STATUS": "ON"})
        await wait_for(lambda: {"STATUS": "ON"} in panel.changes("C0004"))
    finally:
        ICProtocol._writeToTransport = original

    assert set(write_threads) == {loop_thread}


async def call_and_catch(hass, domain, service, data):
    """Call a service and return the error it raised (None if it didn't)."""
    from homeassistant.exceptions import HomeAssistantError

    try:
        await hass.services.async_call(domain, service, data, blocking=True)
    except HomeAssistantError as err:
        return err
    return None


async def test_refused_command_is_reported(
    hass: HomeAssistant, integration, panel
) -> None:
    """A change the IntelliCenter refuses raises an error instead of vanishing.

    The panel answers an error with a messageID of its own: the answer still
    reaches the command that was waiting for it.
    """
    panel.refuse_changes["B1202"] = "406"
    err = await call_and_catch(hass, "switch", "turn_on", {"entity_id": "switch.spa"})
    assert err is not None
    assert err.translation_key == "command_refused"
    assert err.translation_placeholders == {"name": "Spa", "code": "406"}
    assert hass.states.get("switch.spa").state == "off"

    # later commands are unaffected
    del panel.refuse_changes["B1202"]
    assert await call_and_catch(
        hass, "switch", "turn_on", {"entity_id": "switch.spa"}
    ) is None
    await wait_for(lambda: hass.states.get("switch.spa").state == "on")


async def test_refused_setting_is_reported(
    hass: HomeAssistant, integration, panel
) -> None:
    """The same for water heater and chlorinator settings."""
    panel.refuse_changes["B1202"] = "400"
    panel.refuse_changes["CHR01"] = "400"
    err = await call_and_catch(
        hass,
        "water_heater",
        "set_temperature",
        {"entity_id": "water_heater.spa_heater", "temperature": 101},
    )
    assert err.translation_key == "command_refused"
    err = await call_and_catch(
        hass,
        "number",
        "set_value",
        {"entity_id": "number.intellichlor_1_pool_output", "value": 30},
    )
    assert err.translation_key == "command_refused"
    assert err.translation_placeholders["name"] == "IntelliChlor 1"


async def test_unanswered_command_is_reported(
    hass: HomeAssistant, integration, panel
) -> None:
    """A change the IntelliCenter doesn't answer raises an error after a while."""
    from unittest.mock import patch

    import custom_components.intellicenter.entity as entity

    panel.silent = True
    with patch.object(entity, "COMMAND_TIMEOUT", 0.3):
        err = await call_and_catch(
            hass, "light", "turn_on", {"entity_id": "light.test_pool_pool_light"}
        )
    assert err.translation_key == "command_timeout"
    assert err.translation_placeholders == {"name": "Pool Light", "seconds": "0.3"}


async def test_command_without_a_connection_is_reported(
    hass: HomeAssistant, integration, panel
) -> None:
    """A change made while the connection is down says so."""
    component = hass.data["entity_components"]["switch"]
    entity = component.get_entity("switch.test_pool_waterfall")

    panel.silent = True
    for writer in list(panel._writers):
        writer.transport.abort()
    await wait_for(lambda: not integration.runtime_data.controller.connected)

    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError) as err:
        await entity.async_turn_on()
    assert err.value.translation_key == "not_connected"


async def test_errors_are_translated(hass: HomeAssistant, integration, panel) -> None:
    """The error shown to the user is the translated sentence."""
    from homeassistant.helpers.translation import async_get_translations

    translations = await async_get_translations(
        hass, "en", "exceptions", ["intellicenter"]
    )
    message = translations["component.intellicenter.exceptions.command_refused.message"]
    assert message.format(name="Spa", code="406") == (
        "The IntelliCenter refused the change to Spa (error 406)."
    )
