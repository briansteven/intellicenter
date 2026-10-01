# Pentair Intellicenter for Home Assistant

[![hacs][hacsbadge]][hacs]
[![GitHub Release][releases-shield]][releases]
[![Tests][tests-shield]][tests]

## About this fork

This is a maintained fork of [dwradcliffe/intellicenter](https://github.com/dwradcliffe/intellicenter)
(itself a fork of [jlvaillant/intellicenter](https://github.com/jlvaillant/intellicenter)).
It is a drop-in replacement: same integration, same entities and entity IDs, no
configuration changes. (One deliberate exception since 2.2.0: a water heater's
state is now its operation mode, see the [changelog](CHANGELOG.md#220).) It
focuses on reliability:

- **Notices when the IntelliCenter goes away.** When the panel loses power or
  drops off the network it never closes the connection, so Home Assistant used to
  stay "connected" to nothing, with every value frozen, until the integration was
  reloaded. A keep-alive now detects this within about 90 seconds, marks the
  entities unavailable, and reconnects as soon as the panel is back.
- **Commands no longer stop working.** Commands were written to the connection
  from a background thread, which could wedge the request queue so that switches,
  lights and heater settings silently stopped reaching the panel.
- **Shared pool/spa equipment.** A heater shared by the pool and the spa now gets
  a water heater entity for both bodies, and its binary sensor reports heating for
  either one.
- Messages split across network packets are processed right away, reconnection
  survives drops during the initial handshake, values the panel reports as
  undefined are no longer shown as if they were real, sensors report numbers
  (so temperatures convert between °F and °C), pH and ORP have units, water
  heaters support turn on/off, pumps show as running from their actual speed or
  power, an error that stopped systems on IntelliCenter firmware 3.x from loading
  is fixed, and Home Assistant 2027.8 won't break the salt sensor.

See [CHANGELOG.md](CHANGELOG.md) for the details and credits: several of these
fixes come from pull requests and forks by other members of the community.

Please report problems in this repository's
[issues](https://github.com/briansteven/intellicenter/issues).

## Installation

### From HACS

1. Install HACS if you haven't already (see [installation guide](https://hacs.xyz/docs/use/)).
2. Add custom repository `https://github.com/briansteven/intellicenter` as "Integration" in HACS.
3. Find and download the "Pentair IntelliCenter" integration in HACS.
4. Restart your Home Assistant.
5. 'Pentair Intellicenter' should appear thru discovery in your Home Assistant Integration's page

### Switching from dwradcliffe/intellicenter or jlvaillant/intellicenter

Your existing setup is reused as is: don't delete the integration from Home
Assistant.

1. In HACS, remove the old "Pentair IntelliCenter" repository (this only deletes
   its files).
2. Add `https://github.com/briansteven/intellicenter` as a custom repository
   ("Integration") and download it.
3. Restart Home Assistant. Your config entry, entities, entity IDs, areas and
   customizations are kept.
4. If an automation or template checks a water heater for `on` or `idle`, switch
   it to the heater's binary sensor (see the [2.2.0 changelog](CHANGELOG.md#220)).

### Features

- Connect to a Pentair Intellicenter thru the local (network) interface
- supports Zeroconf discovery
- reconnects itself gracefully in the Intellicenter reboots and/or gets disconnected
- "Local push" makes system very responsive
- The integration works independently of the security setting on the Intellicenter

### Entities created

- for each body of water (like Pool and Spa) it creates:
    - a switch to turn the body on and off
    - a sensor for the last temperature
    - a sensor for the desired temperature
    - a water heater entity (if applicable):
        - choose a heater from the list to enable it, set to OFF otherwise
        - its state is the selected heater's name, or 'off' when no heater is
          selected (whether the heater is running right now is the heater's
          binary sensor, below)
        Note that the water heater supports turn_on and turn_off operations.
        for turn_on, it will reuse the last heater chosen.
      A heater shared by the pool and the spa (shared equipment) appears in
      the water heater of both bodies.
- for each heater, a binary sensor will indicate is the heater is running
  independently of which body is heating
- creates a switch for all circuits marked as "Featured" on the IntelliCenter
  (for example "Cleaner" or "Spa Blower)
- for each light (and light show) it creates a Light entity
  Note that color effects are only supported for IntelliBrite or MagicStream lights
- for each schedule, a binary_sensor will indicate if the schedule is currently running
  Note that these entities are disabled by default
- if the pool has a IntelliChem unit, sensors will be created for
  ph level, ORP level (mV), ph tank level and ORP tank level
- a switch controls "Vacation mode". It's disabled by default
- for each pump, a binary_sensor shows whether it is running (from its speed,
  power or flow when it reports them, from its status otherwise)
  if the pump supports these features, sensors will reflect power consumption, RPM and GPM
  Note that the power usage is rounded to the nearest 25W to reduced the amount of changes in HA
  Also note that depending on the setting of the pump, RPM or GPM can fluctuate constantly.
- a binary_sensor will indicate if the system is in Freeze prevention mode
- sensors will be created for each sensor in the system (like Water and Air)
  Note that a Solar sensor might also be present even if (like in my case) its value
  is not relevant

### Examples

<img src="device_info.png" width="400"/>

<img src="entities.png" width="400"/>

### Connection

The integration keeps a single connection to the IntelliCenter (port 6681) and
receives changes as they happen. Every minute it also checks that the panel still
answers; if it doesn't within 30 seconds the connection is dropped, the entities
become unavailable, and reconnection is retried (after 30 seconds, then backing
off up to every 5 minutes) until the panel is back.

### Caveats

- while I tried to make the code as robust as possible I could only test using
  my own pool configuration. In particular, I do not have covers, chemistry, cascades,
  multiple heaters, etc... These may work out of the box or not...
- while the choice is metric/english on the Intellicenter is handled, changing it
  while the integration is running can lead to some values being off.
- In general it is recommended to reload the integration where significant changes are done to the pool configuration
- Pool covers are not supported yet.

## Development

The protocol tests need only pytest; the end-to-end tests run the integration
inside Home Assistant against a fake IntelliCenter
(`tests/fake_panel.py`):

```
pip install -r requirements_test.txt
python -m pytest tests

pip install -r requirements_test_ha.txt
python -m pytest tests_ha
```

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange
[releases-shield]: https://img.shields.io/github/v/release/briansteven/intellicenter
[releases]: https://github.com/briansteven/intellicenter/releases
[tests-shield]: https://github.com/briansteven/intellicenter/actions/workflows/tests.yaml/badge.svg
[tests]: https://github.com/briansteven/intellicenter/actions/workflows/tests.yaml
