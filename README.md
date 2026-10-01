# Pentair IntelliCenter for Home Assistant

[![hacs][hacsbadge]][hacs]
[![GitHub Release][releases-shield]][releases]
[![Tests][tests-shield]][tests]

Control and monitor a Pentair IntelliCenter pool system from Home Assistant,
over its local network interface: bodies of water, heaters, pumps, lights,
featured circuits, IntelliChlor and IntelliChem, sensors and schedules.

## About this version

This started as a fork of [dwradcliffe/intellicenter](https://github.com/dwradcliffe/intellicenter)
(itself a fork of [jlvaillant/intellicenter](https://github.com/jlvaillant/intellicenter))
and is now maintained independently. It takes fixes from the other versions
when they apply (see [CHANGELOG.md](CHANGELOG.md) for the details and credits)
and focuses on reliability:

- **Notices when the IntelliCenter goes away.** When the panel loses power or
  drops off the network it never closes the connection, so Home Assistant used
  to stay "connected" to nothing, with every value frozen. A keep-alive detects
  this within about 90 seconds, marks the entities unavailable, and reconnects as
  soon as the panel is back.
- **Commands don't fail silently.** Commands wait for the IntelliCenter's answer:
  one it refuses or doesn't answer shows an error (and fails the automation step
  that sent it) instead of being lost. They are sent from Home Assistant's
  event loop, so the request queue can't wedge.
- **Says why a body isn't heated.** If the pool or spa stays cold while a heater
  that isn't assigned to it is selected, a repair explains how to fix the heater
  settings.
- **Setup that tells the truth.** An IntelliCenter that can't be reached shows
  as such (and setup is retried), its address can be changed without removing
  it, and its diagnostics can be downloaded for a bug report.
- **Stable entities.** Unique IDs come from the IntelliCenter itself, so
  removing and adding it again brings back entity customizations.

Please report problems in this repository's
[issues](https://github.com/briansteven/intellicenter/issues), with the
integration's diagnostics if you can (Settings > Devices & services > Pentair
IntelliCenter > ⋮ > Download diagnostics: addresses and identifiers are
removed).

## Installation

Requires Home Assistant 2025.1 or later.

1. Install [HACS](https://hacs.xyz/docs/use/) if you haven't already.
2. In HACS, add the custom repository `https://github.com/briansteven/intellicenter`
   with the type "Integration".
3. Download "Pentair IntelliCenter" and restart Home Assistant.
4. The IntelliCenter is usually discovered (Settings > Devices & services). If it
   isn't, add the "Pentair IntelliCenter" integration and enter its IP address.
   Giving the IntelliCenter a fixed (reserved) address in your router helps; if
   the address changes, use **Reconfigure** on the integration to enter the new
   one.

### Switching from another version

Keep your existing setup: don't delete the integration from Home Assistant.

1. In HACS, remove the other "Pentair IntelliCenter" repository (this only
   deletes its files) and download this one as above.
2. Restart Home Assistant.

Entities keep their entity IDs, history, areas and customizations, from
dwradcliffe's, jlvaillant's and joyfulhouse's versions alike. What changes:

- From a 2.x version (this one's or dwradcliffe's), see [3.0.0 in the
  changelog](CHANGELOG.md#300): bodies, pumps, heaters and chemistry controllers
  become devices, entity names follow Home Assistant's current conventions, and
  a few values are corrected.
- From joyfulhouse's version, entities this version doesn't have (such as its
  climate and select entities) stay behind, unavailable: delete them from
  Settings > Entities once you have checked nothing uses them.
- Going back to a version before 3.0 is not supported: it would create a second
  set of entities. Restore a backup instead.

## What you get

The IntelliCenter is a device; each body of water, pump, heater and chemistry
controller is a device connected through it, in the IntelliCenter's area unless
you move it.

- **Each body of water** (pool, spa):
    - a switch to turn it on and off
    - its temperature and target temperature
    - a water heater (if a heater can heat it): pick a heater as its operation
      mode or `off`, set the target temperature, turn it on (with the heater used
      last) or off. Its state is the selected heater's name or `off`; whether
      the heater is running right now is the heater's own sensor. A heater
      assigned to both the pool and the spa appears in both.
- **Each heater**: a sensor that is on while it heats (or, for a heat pump,
  cools) any body.
- **Each pump**: a sensor that is on while it runs (from its speed, power or flow
  when it reports them, from its status otherwise), and its power (rounded to
  25 W), speed and flow when it reports them.
- **IntelliChlor**: salt level, superchlorinate switch and duration, and the
  output setting for each body it serves.
- **IntelliChem**: pH, ORP, saturation index, the levels of both tanks (0 to 6,
  as the IntelliChem shows them), how much chemical it has fed, its pH and ORP
  alarms, and its settings: pH and ORP targets, and the alkalinity, calcium
  hardness and cyanuric acid values the saturation index is computed from.
- **Lights and light shows**: on/off, with color effects for IntelliBrite,
  MagicStream and GloBrite lights.
- **Featured circuits and circuit groups** (for example "Cleaner" or "Spa
  Blower"): switches.
- **Air, water and solar sensors.**
- **Pool and spa covers**, when the IntelliCenter reports their position
  (read-only; older firmware such as 1.064 doesn't report it).
- **Freeze protection**, **service mode** (on while the IntelliCenter is in
  service or timeout mode), **vacation mode** (a switch, disabled by default)
  and **schedules** (on while running, disabled by default).

### Connection

The integration keeps a single connection to the IntelliCenter (port 6681) and
receives changes as they happen. Every minute it also checks that the panel still
answers; if it doesn't within 30 seconds the connection is dropped, the entities
become unavailable, and reconnection is retried (after 30 seconds, then backing
off up to every 5 minutes) until the panel is back.

## Troubleshooting

- **The pool or spa doesn't heat.** Check Settings > Repairs. In the
  IntelliCenter's heater settings (Pentair app or panel), a heater must be
  assigned to every body it should heat; a heater shared by the pool and the
  spa is assigned to both. Some IntelliCenters don't heat a body with a heater
  that isn't assigned to it, and Home Assistant says so after the body has
  stayed cold for 10 minutes.
- **Setup keeps retrying.** Home Assistant can't reach the IntelliCenter at the
  address it has: check the address (Reconfigure changes it) and that nothing
  blocks port 6681.
- **Changes to the pool's configuration** (new equipment, renamed bodies) are
  picked up when the integration is reloaded. Circuits renamed at the
  IntelliCenter are renamed in Home Assistant right away.
- Changing the IntelliCenter between metric and English units while the
  integration runs can leave some values off until it is reloaded.

## Development

The protocol tests need only pytest; the end-to-end tests run the integration
inside Home Assistant against a fake IntelliCenter (`tests/fake_panel.py`):

```
pip install -r requirements_test.txt
python -m pytest tests

pip install -r requirements_test_ha.txt
python -m pytest tests_ha
```

A weekly GitHub Actions job (`.github/workflows/fork-watch.yaml`) reports what
changed in the other IntelliCenter versions and runs the tests against the
latest Home Assistant; the report is on the `fork-watch` branch.

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange
[releases-shield]: https://img.shields.io/github/v/release/briansteven/intellicenter
[releases]: https://github.com/briansteven/intellicenter/releases
[tests-shield]: https://github.com/briansteven/intellicenter/actions/workflows/tests.yaml/badge.svg
[tests]: https://github.com/briansteven/intellicenter/actions/workflows/tests.yaml
