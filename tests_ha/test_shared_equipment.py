"""Heaters, the bodies they are assigned to, and bodies that aren't heated."""

import asyncio
import copy

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS


def objects(heater_bodies: str, spa_heat_source: str, **spa):
    """The default system with the given heater assignment and spa settings."""
    result = copy.deepcopy(DEFAULT_OBJECTS)
    result["H0001"]["BODY"] = heater_bodies
    result["B1202"]["HEATER"] = spa_heat_source
    result["B1202"]["HTSRC"] = spa_heat_source
    result["B1202"].update(spa)
    return result


def spa_water_heater(hass):
    return er.async_get(hass).async_get_entity_id(
        "water_heater", "intellicenter", "test-unique-idB1202LOTMP"
    )


def spa_issue(hass, entry):
    return ir.async_get(hass).async_get_issue(
        "intellicenter", f"heater_not_heating_{entry.entry_id}_B1202"
    )


# the spa on, at 79°F for a 99°F target
COLD_SPA = {"STATUS": "ON", "HTMODE": "0", "LSTTMP": "79", "LOTMP": "99"}


@pytest.mark.parametrize("panel_objects", [objects("B1101 B1202", "00000")])
async def test_spa_water_heater_exists_while_its_heat_is_off(
    hass: HomeAssistant, integration
) -> None:
    """A heater assigned to the spa gives it a water heater, heat source or not."""
    assert spa_water_heater(hass)
    assert hass.states.get("water_heater.spa_heater").state == "off"
    assert spa_issue(hass, integration) is None


@pytest.mark.parametrize("not_heating_delay", [0.2])
@pytest.mark.parametrize("panel_objects", [objects("B1101", "H0001", **COLD_SPA)])
async def test_spa_not_heated_by_a_heater_not_assigned_to_it(
    hass: HomeAssistant, integration, panel
) -> None:
    """The spa selects a heater assigned to the pool only, and isn't heated.

    Some IntelliCenters don't heat a body with a heater that isn't assigned to
    it: once the spa has stayed cold long enough, a repair issue says why. It
    clears once the heater is assigned to the spa.
    """
    # the selected heater is offered, assigned or not
    spa = hass.states.get("water_heater.spa_heater")
    assert spa.attributes["operation_list"] == ["off", "Gas Heater"]
    assert spa.state == "Gas Heater"

    await wait_for(lambda: spa_issue(hass, integration) is not None)
    issue = spa_issue(hass, integration)
    assert issue.translation_key == "heater_not_heating"
    assert issue.translation_placeholders == {
        "body": "Spa",
        "heater": "Gas Heater",
        "minutes": "0",
    }

    panel.set_params("H0001", {"BODY": "B1101 B1202"})
    await wait_for(lambda: spa_issue(hass, integration) is None)


@pytest.mark.parametrize("not_heating_delay", [0.2])
@pytest.mark.parametrize("panel_objects", [objects("B1101", "H0001", **COLD_SPA)])
async def test_spa_heated_by_a_heater_not_assigned_to_it(
    hass: HomeAssistant, integration, panel
) -> None:
    """Other IntelliCenters heat the spa anyway: then there is nothing to report."""
    panel.set_params("B1202", {"HTMODE": "1"})
    await wait_for(lambda: hass.states.get("binary_sensor.gas_heater").state == "on")
    await asyncio.sleep(0.4)
    assert spa_issue(hass, integration) is None


@pytest.mark.parametrize("not_heating_delay", [0.2])
@pytest.mark.parametrize("panel_objects", [objects("B1101", "H0001")])
async def test_nothing_reported_while_the_spa_doesnt_need_heat(
    hass: HomeAssistant, integration, panel
) -> None:
    """A spa that is off, or already warm, isn't expected to be heated."""
    await asyncio.sleep(0.4)
    assert spa_issue(hass, integration) is None

    panel.set_params("B1202", {"STATUS": "ON", "LSTTMP": "100", "LOTMP": "99"})
    await asyncio.sleep(0.4)
    assert spa_issue(hass, integration) is None

    # it cools down below its target and stays unheated
    panel.set_params("B1202", {"LSTTMP": "97"})
    await wait_for(lambda: spa_issue(hass, integration) is not None)

    # an issue goes away with the integration
    assert await hass.config_entries.async_unload(integration.entry_id)
    assert spa_issue(hass, integration) is None


@pytest.mark.parametrize("panel_objects", [objects("B1101", "00000")])
async def test_pool_only_heater_with_no_spa_heat_source(
    hass: HomeAssistant, integration, panel
) -> None:
    """A heater for the pool only, and a spa that doesn't select it: no spa heater."""
    assert spa_water_heater(hass) is None
    assert spa_issue(hass, integration) is None


async def test_issues_of_earlier_versions_are_removed(
    hass: HomeAssistant, config_entry, use_panel
) -> None:
    """2.2 raised an issue on the configuration alone: it goes away in 3.0."""
    legacy = f"heater_not_assigned_{config_entry.entry_id}_B1202"
    ir.async_create_issue(
        hass,
        "intellicenter",
        legacy,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="heater_not_assigned",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue("intellicenter", legacy) is None
    assert await hass.config_entries.async_unload(config_entry.entry_id)
