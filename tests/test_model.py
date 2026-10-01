"""Tests for how updates from the system are applied to the model."""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "intellicenter"),
)

from pyintellicenter import ModelController, PoolModel  # noqa: E402
from pyintellicenter.controller import SystemInfo  # noqa: E402


def make_controller():
    model = PoolModel({"SCHED": {"SNAME", "ACT", "VACFLO"}, "SYSTEM": {"MODE"}})
    model.addObjects(
        [
            {"objnam": "_5451", "params": {"OBJTYP": "SYSTEM", "SNAME": "x"}},
            {"objnam": "SCH01", "params": {"OBJTYP": "SCHED", "SNAME": "Pool"}},
        ]
    )
    controller = ModelController("127.0.0.1", model)
    controller._systemInfo = SystemInfo(
        "_5451",
        {"PROPNAME": "Test", "VER": "1.064", "MODE": "ENGLISH", "SNAME": "x"},
    )
    return controller, model


def test_undefined_attributes_are_not_stored():
    """An attribute echoed back as its own name has no value."""
    controller, model = make_controller()

    controller._applyUpdates(
        [{"objnam": "SCH01", "params": {"ACT": "ACT", "VACFLO": "OFF"}}]
    )

    assert model["SCH01"]["ACT"] is None
    assert "ACT" not in model["SCH01"].attributes
    assert model["SCH01"]["VACFLO"] == "OFF"


def test_defined_attributes_are_applied_and_reported():
    """Real values still update the model and are reported as changes."""
    controller, model = make_controller()
    reported = []
    controller._updatedCallback = lambda ctrl, updates: reported.append(updates)

    controller._applyUpdates([{"objnam": "SCH01", "params": {"ACT": "ON"}}])

    assert model["SCH01"]["ACT"] == "ON"
    assert reported == [{"SCH01": {"ACT": "ON"}}]
