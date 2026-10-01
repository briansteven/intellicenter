"""Tests for commands sent from Home Assistant to the panel."""

import threading

import pytest

from homeassistant.core import HomeAssistant

from conftest import wait_for


@pytest.mark.parametrize(
    ("domain", "service", "data", "objnam", "expected"),
    [
        ("switch", "turn_on", {"entity_id": "switch.test_pool_spa"}, "B1202", {"STATUS": "ON"}),
        ("switch", "turn_off", {"entity_id": "switch.test_pool_waterfall"}, "C0004", {"STATUS": "OFF"}),
        ("light", "turn_on", {"entity_id": "light.test_pool_pool_light"}, "C0002", {"STATUS": "ON"}),
        (
            "number",
            "set_value",
            {"entity_id": "number.test_pool_intellichlor_1_output_pool", "value": 30},
            "CHR01",
            {"PRIM": "30"},
        ),
        (
            "water_heater",
            "set_temperature",
            {"entity_id": "water_heater.test_pool_spa", "temperature": 101},
            "B1202",
            {"LOTMP": "101"},
        ),
        (
            "water_heater",
            "set_operation_mode",
            {"entity_id": "water_heater.test_pool_spa", "operation_mode": "off"},
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
    entity_id = "water_heater.test_pool_spa"
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
