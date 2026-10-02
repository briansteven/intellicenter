"""Readings the IntelliCenter reports with a placeholder, a fault or not at all."""

import asyncio
import copy

import pytest

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from conftest import wait_for
from fake_panel import DEFAULT_OBJECTS

FIRMWARE_3 = "IC: 3.014 , ICWEB:2026-04-22 3.014"

PH = "sensor.intellichem_1_ph"
ORP = "sensor.intellichem_1_orp"
QUALITY = "sensor.intellichem_1_saturation_index"
SALT = "sensor.intellichlor_1_salt"
SOLAR = "sensor.test_pool_solar_sensor_1"


def objects(firmware=None, **changes):
    """Return the default objects, with this firmware and changed attributes."""
    result = copy.deepcopy(DEFAULT_OBJECTS)
    if firmware:
        result["_5451"]["VER"] = firmware
    for objnam, params in changes.items():
        result.setdefault(objnam, {}).update(params)
    return result


def quality_requests(panel):
    return [
        request
        for request in panel.requests
        if request.get("command") == "GetParamList"
        and request["objectList"][0]["objnam"] == "CHM01"
        and request["objectList"][0]["keys"] == ["QUALTY"]
    ]


@pytest.fixture
def quick_refresh(monkeypatch):
    """Read the saturation index again right away (instead of after 10 s)."""
    import custom_components.intellicenter.pyintellicenter.controller as controller

    monkeypatch.setattr(controller, "QUALITY_REFRESH_DELAY", 0.05)


# --- placeholders after the IntelliCenter restarted ---------------------------


@pytest.mark.parametrize(
    "panel_objects",
    [
        objects(
            CHM01={"PHVAL": "0.00", "ORPVAL": "0", "QUALTY": "1.27"},
            CHR01={"SALT": "0"},
        )
    ],
)
async def test_placeholders_are_unknown(hass: HomeAssistant, integration, panel) -> None:
    """pH 0.00, ORP 0, saturation index 1.27 and salt 0 aren't readings."""
    for entity_id in (PH, ORP, QUALITY, SALT):
        assert hass.states.get(entity_id).state == STATE_UNKNOWN, entity_id

    # the IntelliChlor reports first (a couple of minutes after a restart)
    panel.set_params("CHR01", {"SALT": "3450"})
    await wait_for(lambda: hass.states.get(SALT).state == "3450")

    # then the IntelliChem: pH and ORP together (IC 1.064 sends its saturation
    # index with them)
    panel.set_params("CHM01", {"PHVAL": "7.40", "ORPVAL": "650", "QUALTY": "-0.1"})
    await wait_for(lambda: hass.states.get(PH).state == "7.4")
    assert hass.states.get(ORP).state == "650"
    assert hass.states.get(QUALITY).state == "-0.1"


@pytest.mark.parametrize(
    "panel_objects", [objects(CHM01={"PHVAL": "0.00", "QUALTY": "1.27"})]
)
async def test_values_count_once_the_ph_does(
    hass: HomeAssistant, integration, panel
) -> None:
    """ORP and the saturation index are judged by the pH, which comes with them.

    The saturation index left from before the pH (the placeholder) stays
    unknown until a value comes with or after the pH.
    """
    assert hass.states.get(ORP).state == STATE_UNKNOWN  # 620, but no pH yet
    assert hass.states.get(QUALITY).state == STATE_UNKNOWN
    panel.set_params("CHM01", {"PHVAL": "7.40"})
    await wait_for(lambda: hass.states.get(ORP).state == "620")
    assert hass.states.get(QUALITY).state == STATE_UNKNOWN
    panel.set_params("CHM01", {"QUALTY": "-0.1"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "-0.1")


async def test_real_readings_are_shown(hass: HomeAssistant, integration, panel) -> None:
    """Readings, including an ORP of 0 once the pH is real, are shown as they are."""
    assert hass.states.get(PH).state == "7.4"
    assert hass.states.get(ORP).state == "620"
    assert hass.states.get(QUALITY).state == "-0.1"
    assert hass.states.get(SALT).state == "3500"
    panel.set_params("CHM01", {"ORPVAL": "0"})
    await wait_for(lambda: hass.states.get(ORP).state == "0")


# --- the saturation index on firmware 3.x -------------------------------------


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_3)])
async def test_saturation_index_is_read_again_on_firmware_3(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """IC 3.x doesn't push the saturation index: it is read after a change."""
    assert hass.states.get(QUALITY).state == "-0.1"

    # the IntelliCenter computes it again, without telling
    panel.objects["CHM01"]["QUALTY"] = "0.05"
    panel.set_params("CHM01", {"PHVAL": "7.50"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "0.05")

    # several changes in a row are one read
    reads = len(quality_requests(panel))
    panel.set_params("CHM01", {"ORPVAL": "630"})
    panel.set_params("CHM01", {"ORPVAL": "640"})
    await wait_for(lambda: len(quality_requests(panel)) > reads)
    await asyncio.sleep(0.2)
    assert len(quality_requests(panel)) == reads + 1


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_3)])
async def test_pushed_saturation_index_is_not_read_again(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """When the IntelliCenter does push the saturation index, it isn't read.

    (It is read once after connecting: what was read then may predate the pH.)
    """
    await wait_for(lambda: len(quality_requests(panel)) == 1)
    await asyncio.sleep(0.1)
    panel.set_params("CHM01", {"PHVAL": "7.50", "QUALTY": "0.02"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "0.02")
    await asyncio.sleep(0.2)
    assert len(quality_requests(panel)) == 1


async def test_saturation_index_is_pushed_by_older_firmware(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """IC 1.064 pushes it: nothing is read again."""
    panel.set_params("CHM01", {"PHVAL": "7.50"})
    await wait_for(lambda: hass.states.get(PH).state == "7.5")
    await asyncio.sleep(0.2)
    assert quality_requests(panel) == []


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_3)])
async def test_pending_read_is_cancelled_on_unload(
    hass: HomeAssistant, integration, panel
) -> None:
    """Unloading doesn't leave a read of the saturation index behind."""
    controller = integration.runtime_data.controller
    panel.set_params("CHM01", {"PHVAL": "7.50"})
    await wait_for(lambda: hass.states.get(PH).state == "7.5")
    assert "CHM01" in controller._qualityRefreshes  # waiting 10 s
    task = controller._qualityRefreshes["CHM01"]

    assert await hass.config_entries.async_unload(integration.entry_id)
    await hass.async_block_till_done()
    assert controller._qualityRefreshes == {}
    await asyncio.sleep(0)
    assert task.cancelled()


# --- a faulty temperature sensor ----------------------------------------------


@pytest.mark.parametrize(
    "panel_objects",
    [
        objects(
            FIRMWARE_3,
            SSS11={
                "OBJTYP": "SENSE",
                "SUBTYP": "SOLAR",
                "SNAME": "Solar Sensor 1",
                "PARENT": "00000",
                "SOURCE": "156",
                "PROBE": "ERR",
            },
        )
    ],
)
async def test_faulty_temperature_sensor_is_unavailable(
    hass: HomeAssistant, integration, panel
) -> None:
    """IC 3.x flags a faulty (or missing) sensor with PROBE "ERR"."""
    assert hass.states.get(SOLAR).state == STATE_UNAVAILABLE
    # the other sensors don't report PROBE here: they stay available
    assert hass.states.get("sensor.test_pool_air_sensor").state == "82"

    panel.set_params("SSS11", {"PROBE": "80", "SOURCE": "80"})
    await wait_for(lambda: hass.states.get(SOLAR).state == "80")

    panel.set_params("SSS11", {"PROBE": "ERR", "SOURCE": "156"})
    await wait_for(lambda: hass.states.get(SOLAR).state == STATE_UNAVAILABLE)


# --- the saturation index after a restart, on firmware 3.x --------------------


def record_states(hass, entity_id):
    """Return the list of states the entity goes through from now on."""
    from homeassistant.helpers.event import async_track_state_change_event

    states = []

    def changed(event):
        new = event.data["new_state"]
        states.append(new.state if new else None)

    async_track_state_change_event(hass, [entity_id], changed)
    return states


@pytest.mark.parametrize(
    "panel_objects",
    [objects(FIRMWARE_3, CHM01={"PHVAL": "0.00", "ORPVAL": "0", "QUALTY": "1.27"})],
)
async def test_placeholder_saturation_index_is_never_shown(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """IC 3.x sends pH and ORP without the saturation index: the placeholder
    isn't shown in the meantime, and it stays unknown until recomputed."""
    states = record_states(hass, QUALITY)
    assert hass.states.get(QUALITY).state == STATE_UNKNOWN

    # what the panel did at 11:07:49 on 2026-10-02 (not recomputed yet)
    panel.set_params("CHM01", {"PHVAL": "7.40", "ORPVAL": "640"})
    await wait_for(lambda: hass.states.get(PH).state == "7.4")
    await wait_for(lambda: len(quality_requests(panel)) == 1)
    await asyncio.sleep(0.2)
    assert hass.states.get(QUALITY).state == STATE_UNKNOWN

    # recomputed, noticed at the next change
    panel.objects["CHM01"]["QUALTY"] = "-0.1"
    panel.set_params("CHM01", {"ORPVAL": "645"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "-0.1")
    assert "1.27" not in states


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_3)])
async def test_saturation_index_is_read_after_a_change_is_written(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """A change answered with a WriteParamList (alkalinity set...) reads it too."""
    panel.objects["CHM01"]["QUALTY"] = "-0.3"
    panel.push_write_param_list(
        {"changes": [{"objnam": "CHM01", "params": {"ALK": "80"}}]}
    )
    await wait_for(lambda: hass.states.get(QUALITY).state == "-0.3")


@pytest.mark.parametrize("panel_objects", [objects(FIRMWARE_3)])
@pytest.mark.parametrize(
    "connection_settings", [{"keepAliveInterval": 0.2, "keepAliveTimeout": 0.2}]
)
async def test_saturation_index_read_across_a_reconnection(
    hass: HomeAssistant, integration, panel, monkeypatch
) -> None:
    """A read pending when the connection drops is dropped; later ones work."""
    import custom_components.intellicenter.pyintellicenter.controller as module

    monkeypatch.setattr(module, "QUALITY_REFRESH_DELAY", 0.5)
    handler = integration.runtime_data
    handler._timeBetweenReconnects = 0.2
    controller = handler.controller

    panel.set_params("CHM01", {"PHVAL": "7.50"})
    await wait_for(lambda: "CHM01" in controller._qualityRefreshes)
    panel.silent = True
    await wait_for(lambda: hass.states.get(PH).state == STATE_UNAVAILABLE)
    assert controller._qualityRefreshes == {}

    panel.silent = False
    await wait_for(lambda: hass.states.get(PH).state == "7.5", timeout=10)
    panel.objects["CHM01"]["QUALTY"] = "0.1"
    panel.set_params("CHM01", {"ORPVAL": "650"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "0.1", timeout=5)


@pytest.mark.parametrize("panel_objects", [objects(), objects(FIRMWARE_3)])
async def test_saturation_index_after_a_ph_dropout(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """The pH drops to 0 and comes back, the saturation index stays: it is
    the last real value, shown again with the pH."""
    assert hass.states.get(QUALITY).state == "-0.1"
    panel.set_params("CHM01", {"PHVAL": "0.00"})
    await wait_for(lambda: hass.states.get(QUALITY).state == STATE_UNKNOWN)
    panel.set_params("CHM01", {"PHVAL": "7.40"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "-0.1")


@pytest.mark.parametrize(
    "panel_objects",
    [objects(FIRMWARE_3, CHM01={"PHVAL": "0.00", "ORPVAL": "0", "QUALTY": "1.27"})],
)
async def test_placeholder_read_again_stays_unknown(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """Read twice while the panel still has the placeholder: still unknown."""
    states = record_states(hass, QUALITY)
    reads = len(quality_requests(panel))
    panel.set_params("CHM01", {"PHVAL": "7.40", "ORPVAL": "640"})
    await wait_for(lambda: len(quality_requests(panel)) == reads + 1)
    await asyncio.sleep(0.2)
    panel.set_params("CHM01", {"PHVOL": "512"})  # dosing
    await wait_for(lambda: len(quality_requests(panel)) == reads + 2)
    await asyncio.sleep(0.2)
    assert hass.states.get(QUALITY).state == STATE_UNKNOWN
    assert "1.27" not in states


@pytest.mark.parametrize(
    "panel_objects",
    [objects(CHM01={"PHVAL": "0.00", "ORPVAL": "0", "QUALTY": "1.27"})],
)
async def test_saturation_index_pushed_before_the_ph(
    hass: HomeAssistant, integration, panel
) -> None:
    """IC 1.064 sending the saturation index just before the pH: shown with it."""
    panel.set_params("CHM01", {"QUALTY": "-0.1"})
    await asyncio.sleep(0.1)
    assert hass.states.get(QUALITY).state == STATE_UNKNOWN
    panel.set_params("CHM01", {"PHVAL": "7.40", "ORPVAL": "650"})
    await wait_for(lambda: hass.states.get(QUALITY).state == "-0.1")


@pytest.mark.parametrize(
    "panel_objects",
    [objects(FIRMWARE_3, CHM01={"PHVAL": "0.00", "ORPVAL": "0", "QUALTY": "1.27"})],
)
async def test_saturation_index_after_a_reload_is_read_again(
    hass: HomeAssistant, quick_refresh, integration, panel
) -> None:
    """Reloaded just after the pH came (the panel hadn't recomputed the
    saturation index yet): the placeholder isn't shown, and it is read again
    shortly after connecting."""
    panel.set_params("CHM01", {"PHVAL": "7.40", "ORPVAL": "640"})
    await wait_for(lambda: hass.states.get(PH).state == "7.4")

    states = record_states(hass, QUALITY)
    assert await hass.config_entries.async_reload(integration.entry_id)
    await hass.async_block_till_done()
    panel.objects["CHM01"]["QUALTY"] = "-0.1"  # recomputed, not pushed
    await wait_for(lambda: hass.states.get(QUALITY).state == "-0.1")
    assert "1.27" not in states
