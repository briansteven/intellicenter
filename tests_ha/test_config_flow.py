"""Adding an IntelliCenter, and changing its address."""

from hashlib import blake2b
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "intellicenter"


def panel_unique_id(sname="test-system-sname"):
    """The unique ID the integration derives from the panel's system object."""
    h = blake2b(digest_size=8)
    h.update(sname.encode())
    return h.hexdigest()


@pytest.fixture
def flow_uses_panel(panel):
    """Make the config flow connect to the fake panel."""
    import custom_components.intellicenter.config_flow as config_flow

    real_controller = config_flow.BaseController

    def controller_factory(host, **kwargs):
        return real_controller(host, port=panel.port, **kwargs)

    with patch.object(config_flow, "BaseController", controller_factory):
        yield


@pytest.fixture
def config_entry(hass):
    """A configured system, with the unique ID the fake panel gives."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Pool",
        data={"host": "127.0.0.1"},
        unique_id=panel_unique_id(),
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_adds_a_system(hass: HomeAssistant, flow_uses_panel, use_panel) -> None:
    """The user gives the address: the system is added under its own name."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Pool"
    assert result["data"] == {"host": "127.0.0.1"}
    assert result["result"].unique_id == panel_unique_id()
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_flow_with_a_silent_panel(
    hass: HomeAssistant, flow_uses_panel, panel
) -> None:
    """A panel that doesn't answer: an error instead of a flow that hangs."""
    import custom_components.intellicenter.config_flow as config_flow

    panel.silent = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch.object(config_flow, "FLOW_TIMEOUT", 0.3):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "127.0.0.1"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_adds_a_known_system_at_a_new_address(
    hass: HomeAssistant, flow_uses_panel, config_entry
) -> None:
    """Adding a configured system again updates its address instead."""
    hass.config_entries.async_update_entry(config_entry, data={"host": "10.0.0.9"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data == {"host": "127.0.0.1"}


async def test_reconfigure_changes_the_address(
    hass: HomeAssistant, flow_uses_panel, integration, config_entry
) -> None:
    """Reconfigure: the system's new address, then a reload."""
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert hass.states.get("switch.pool").state == "on"


async def test_reconfigure_refuses_another_system(
    hass: HomeAssistant, flow_uses_panel, config_entry
) -> None:
    """An address where another IntelliCenter answers is refused."""
    hass.config_entries.async_update_entry(config_entry, unique_id="another-system")
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data == {"host": "127.0.0.1"}


async def test_reconfigure_with_an_unreachable_address(
    hass: HomeAssistant, flow_uses_panel, config_entry, panel
) -> None:
    """An address where nothing answers: the form again, with an error."""
    import custom_components.intellicenter.config_flow as config_flow

    panel.silent = True
    result = await config_entry.start_reconfigure_flow(hass)
    with patch.object(config_flow, "FLOW_TIMEOUT", 0.3):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "127.0.0.1"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
