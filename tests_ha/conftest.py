"""Fixtures for the tests that run the integration inside Home Assistant.

These need Home Assistant and pytest-homeassistant-custom-component:

    pip install -r requirements_test_ha.txt
    python -m pytest tests_ha
"""

import asyncio
import os
import sys
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fake_panel import FakePanel  # noqa: E402

# pytest-homeassistant-custom-component ships its own (empty) custom_components
# package; make Home Assistant's loader look in this repository as well.
import custom_components  # noqa: E402

_OURS = os.path.join(ROOT, "custom_components")
if _OURS not in custom_components.__path__:
    custom_components.__path__.append(_OURS)

DOMAIN = "intellicenter"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components/."""
    yield


@pytest.fixture
def panel_objects():
    """Object model served by the fake panel (None: the default one)."""
    return None


@pytest.fixture
async def panel(socket_enabled, panel_objects):
    """Run a fake IntelliCenter on a random local port."""
    fake = FakePanel(panel_objects)
    await fake.start()
    yield fake
    await fake.close()


async def wait_for(predicate, timeout=5.0):
    """Wait until predicate() is true, letting the event loop run."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


@pytest.fixture
def connection_settings():
    """Keep-alive and reconnect settings used by the integration under test."""
    return {"keepAliveInterval": 60, "keepAliveTimeout": 30}


@pytest.fixture
async def integration(hass, panel, connection_settings):
    """Set up the integration against the fake panel and tear it down after."""
    import custom_components.intellicenter as ic

    real_controller = ic.ModelController

    def controller_factory(host, model, **kwargs):
        kwargs.update(connection_settings)
        return real_controller(host, model, port=panel.port, **kwargs)

    # the fake panel reports Fahrenheit, like most US systems
    await hass.config.async_update(unit_system="us_customary")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Pool",
        data={"host": "127.0.0.1"},
        unique_id="test-unique-id",
    )
    entry.add_to_hass(hass)

    with patch.object(ic, "ModelController", controller_factory):
        assert await hass.config_entries.async_setup(entry.entry_id)
        # entities are created once the connection to the panel is up
        await wait_for(lambda: hass.states.get("switch.test_pool_pool") is not None)
        await hass.async_block_till_done()

        yield entry

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
