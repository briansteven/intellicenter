"""Heaters and the bodies they are assigned to."""

import copy

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS


def objects(heater_bodies: str, spa_heat_source: str):
    """The default system with the given heater assignment and spa heat source."""
    result = copy.deepcopy(DEFAULT_OBJECTS)
    result["H0001"]["BODY"] = heater_bodies
    result["B1202"]["HEATER"] = spa_heat_source
    result["B1202"]["HTSRC"] = spa_heat_source
    return result


def spa_water_heater(hass, entry):
    return er.async_get(hass).async_get_entity_id(
        "water_heater", "intellicenter", f"{entry.entry_id}B1202LOTMP"
    )


def spa_issue(hass, entry):
    return ir.async_get(hass).async_get_issue(
        "intellicenter", f"heater_not_assigned_{entry.entry_id}_B1202"
    )


@pytest.mark.parametrize("panel_objects", [objects("B1101 B1202", "00000")])
async def test_spa_water_heater_exists_while_its_heat_is_off(
    hass: HomeAssistant, integration
) -> None:
    """A heater assigned to the spa gives it a water heater, heat source or not."""
    assert spa_water_heater(hass, integration)
    assert hass.states.get("water_heater.test_pool_spa").state == "off"
    assert spa_issue(hass, integration) is None


@pytest.mark.parametrize("panel_objects", [objects("B1101", "H0001")])
async def test_heater_not_assigned_to_the_selected_body(
    hass: HomeAssistant, integration, panel
) -> None:
    """The spa selects a heater that is assigned to the pool only.

    The IntelliCenter doesn't heat the spa then, so there is no spa water
    heater and a repair issue says why. It clears once the heater is assigned
    to the spa.
    """
    assert spa_water_heater(hass, integration) is None
    issue = spa_issue(hass, integration)
    assert issue is not None
    assert issue.translation_placeholders == {"body": "Spa", "heater": "Gas Heater"}

    panel.set_params("H0001", {"BODY": "B1101 B1202"})
    await wait_for(lambda: spa_issue(hass, integration) is None)


@pytest.mark.parametrize("panel_objects", [objects("B1101", "00000")])
async def test_pool_only_heater_with_no_spa_heat_source(
    hass: HomeAssistant, integration, panel
) -> None:
    """A heater for the pool only, and a spa that doesn't select it: all fine."""
    assert spa_water_heater(hass, integration) is None
    assert spa_issue(hass, integration) is None

    # selecting it for the spa anyway raises the issue
    panel.set_params("B1202", {"HEATER": "H0001"})
    await wait_for(lambda: spa_issue(hass, integration) is not None)
