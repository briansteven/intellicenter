# Changelog

Changes in briansteven/intellicenter since dwradcliffe/intellicenter v2.0.0.
Versions 2.x are drop-in replacements for dwradcliffe's (with the water heater
state change in 2.2.0); 3.0.0 makes this an independent version.

## 3.4.1

### Feed totals removed

The "pH feed total" and "ORP feed total" sensors added in 3.2.0 were wrong: on
a real IntelliChem the value they show restarts at every dose (every 20
minutes or so while it doses), so it isn't how much chemical has been fed, and
its unit isn't known for sure either. Home Assistant took each restart for a
new meter, so their statistics add up to nonsense. Both sensors are removed
(the integration deletes them when it starts). Their long-term statistics stay
until you delete them: Developer tools > Statistics lists them as no longer
provided, with a button to delete them.

## 3.4.0

### Egg timers

The IntelliCenter turns a circuit off once it has run for its egg timer after
being turned on by hand (12 hours unless changed; schedules have their own end
time), unless the circuit's "Don't Stop" is on. Both are now settings in Home
Assistant for each body of water (on the body's device: "Spa Egg timer", "Spa
Do not stop"), light, light show, featured circuit and circuit group (on the
IntelliCenter's device). The egg timer is in minutes, from 1 to 1439 (23 hours
59 minutes), as the IntelliCenter offers it. **These settings are disabled by
default**: enable the ones you want (Settings > Entities).

## 3.3.0

### Pump speeds

Each speed the IntelliCenter keeps for a pump (one per circuit the pump runs
for: "Pool", "Spa"...) is a setting on the pump's device, in RPM or GPM as set
at the IntelliCenter, within the pump's limits. The pump runs at the highest
speed of the circuits that are on. **These settings are disabled by default**:
enable the ones you want to change from Home Assistant (Settings > Entities).

### Equipment changes are picked up

Equipment added or removed at the IntelliCenter, a circuit made featured (or
no longer featured), and a heater or chlorinator assigned to other bodies used
to need a reload of the integration to show in Home Assistant. The integration
now notices (from the IntelliCenter's updates, a comparison of its equipment
every 15 minutes, and after reconnecting) and reloads itself a minute later.
Entities of removed equipment stay, unavailable, until you delete them.

A body, pump, heater or chemistry controller renamed at the IntelliCenter
renames its device in Home Assistant (unless you renamed it yourself).

## 3.2.0

### IntelliChem and IntelliChlor

New, on the IntelliChem's device (when the IntelliCenter reports them):

- **Settings**: pH target (7.0 to 7.8), ORP target (400 to 800 mV), and the water
  test values the IntelliChem computes the saturation index from: total
  alkalinity, calcium hardness and cyanuric acid. A value the IntelliChem
  refuses shows an error.
- **Alarms**: pH high, pH low, ORP high and ORP low, as problem sensors (their
  thresholds and delays are set on the IntelliChem).
- **Feed totals**: how much pH and ORP chemical the IntelliChem has fed, as
  running totals (shown in fl. oz. or mL, following Home Assistant's units), so
  statistics can show how much is used per day or week. (Wrong: removed in
  3.4.1.)

And on the IntelliChlor's device: **Superchlorinate duration** (1 to 96 hours).

### Changed

- The IntelliChem's "Water quality" sensor is now named **Saturation index**,
  which is what it is (the Langelier index the IntelliChem shows, balanced
  between -0.5 and +0.5). Its entity ID doesn't change.

## 3.1.0

### Failed commands are reported

Turning something on or off, or changing a setting (water heater, chlorinator
output, light show), used to send the command without checking the
IntelliCenter's answer: a command it refused, or that never reached it, was
silently lost, and the switch just flipped back. Commands now wait for the
answer (up to 10 seconds) and report a failure in Home Assistant: an error in
the interface, a failed step in an automation or script (where
`continue_on_error: true` keeps going), with the reason:

- "The IntelliCenter refused the change to Spa (error 406)."
- "The IntelliCenter didn't answer the change to Spa within 10 seconds. It may
  still be applied."
- "Not connected to the IntelliCenter: Spa wasn't changed."

The IntelliCenter answers an error with a message ID of its own rather than the
request's (seen on firmware 1.064: a change to an unknown object is answered
`404` with a random ID). Requests go out one at a time, so an error is now
matched to the request waiting for it. This also stops the keep-alive check
from waiting on an answer it already got.

**What to check:** automations and scripts that should keep going when an
IntelliCenter command fails need `continue_on_error: true` on that step.

## 3.0.0

This version no longer aims to stay interchangeable with dwradcliffe's: it
adopts Home Assistant's current conventions for devices and names, and fixes
values that were off. Updating keeps every entity ID, its history, area and
customizations; read "What changes when you update" below.

### What changes when you update

- **Bodies, pumps, heaters and chemistry controllers are devices.** Each body of
  water (pool, spa), pump, heater, IntelliChlor and IntelliChem is now a device
  connected through the IntelliCenter's device, with its entities. Everything
  else (circuits, lights, sensors, schedules...) stays on the IntelliCenter's
  device. The new devices start in the IntelliCenter's area, so entities stay in
  the area they were in.
- **Entity names follow Home Assistant's conventions**: an entity's name is its
  device's name plus what it is. Entity IDs don't change; the names shown where
  you haven't renamed an entity do, for example:

  | Entity | Before | After |
  | --- | --- | --- |
  | pool temperature | Pool last temp | Pool Temperature |
  | pool target temperature | Pool desired temp | Pool Target temperature |
  | pool water heater | Pool | Pool Heater |
  | pump speed / flow | VSF rpm / VSF gpm | VSF Speed / VSF Flow |
  | IntelliChem pH | IntelliChem 1 (pH) | IntelliChem 1 pH |
  | IntelliChlor output | IntelliChlor 1 Output % (Pool) | IntelliChlor 1 Pool output |
  | a circuit, light or sensor | Waterfall | *IntelliCenter's name* Waterfall |

  Dashboard cards that set their own names are unaffected. New entities get IDs
  from these names (for example `water_heater.pool_heater` on a new
  installation).
- **IntelliChem tank levels are 1 lower.** The IntelliCenter reports tank levels
  1 to 7 for what the IntelliChem shows as 0 to 6 (found by joyfulhouse's
  version and nodejs-poolController); the sensors now show 0 to 6. **Check
  automations that compare a tank level with a number**: to alert at the same
  point as before, lower the number by 1.
- **Pump flow is a flow rate** (`gal/min`, which the entity's settings can show
  in L/min) instead of a plain number in `gpm`. Home Assistant may ask, in
  Developer tools > Statistics, what to do about the unit of the existing
  statistics: the values are the same, so keep them.
- **Unique IDs come from the IntelliCenter** instead of the config entry, like
  dwradcliffe/intellicenter#46: after removing and adding the system again, Home
  Assistant restores entity customizations (within 30 days). Existing entities
  are migrated in place at startup, from this version's 2.x, dwradcliffe's,
  jlvaillant's and joyfulhouse's formats. **Going back to a version before 3.0
  creates a second set of entities: restore a backup instead.**
- Freeze protection is shown as "Cold"/"Normal" (a cold sensor), the heater's
  sensor as "Running"/"Not running", and settings (vacation mode, chlorinator
  output) are listed as configuration on their device.
- Requires Home Assistant 2025.1 or later.

### Setup and connection

- **Setup waits for the IntelliCenter.** It used to succeed at once and create
  the entities whenever the IntelliCenter answered, so an unreachable system
  looked set up but had no entities. Now an IntelliCenter that doesn't answer
  within 30 seconds puts the integration in "retrying setup" with the reason,
  and Home Assistant tries again later.
- **Reconfigure** changes the IntelliCenter's address without removing it (it
  checks that the same IntelliCenter answers there). Adding an already
  configured IntelliCenter at a new address also updates it.
- Adding the integration no longer hangs on an IntelliCenter that accepts the
  connection but doesn't answer: it reports "Failed to connect" after 15
  seconds.
- Debug logging works for the whole integration (the connection code forced its
  log level to INFO), connection problems are logged once rather than at every
  retry, and losing the connection is a warning.

### Heating

- **A body selecting a heater that isn't assigned to it.** IntelliCenters
  differ: some don't heat a body with a heater that isn't assigned to it (the
  pump runs and the water stays cold), others heat it anyway (reported to
  joyfulhouse's version). So:
  - such a body gets a water heater with that heater as an option, and
  - the repair issue (which 2.2.1 raised on the settings alone) is raised only
    when it matters: the body is on, below its target temperature, and hasn't
    been heated for 10 minutes. It clears once the body is heated or the heater
    is assigned to it.
- A water heater shows a heater selected at the IntelliCenter after Home
  Assistant started, even if it wasn't one of its options.

### New

- **Service mode**: a sensor that is on while the IntelliCenter is in service or
  timeout mode (when it suspends its normal operation, such as schedules).
- **Pool and spa covers** now appear, for IntelliCenters that report the cover's
  position (they never did: cover objects weren't loaded). They are read-only.
  Older firmware such as 1.064 doesn't report a position, so they don't appear.
- **"SAm" light show** for color lights.
- **Diagnostics** include the integration version, firmware, connection state
  and time since the IntelliCenter last answered; addresses and identifiers are
  removed.
- Devices of equipment the IntelliCenter no longer has can be deleted.
- A weekly job reports what changed in the other IntelliCenter versions and
  runs the tests against the latest Home Assistant.

### Fixed

- A chlorinator serving more than two bodies no longer creates two output
  settings with the same ID.
- Entities set up while the connection drops show as unavailable, not with
  their last values.
- A body's switch shows a hot tub icon for the spa.
- Compatible with Home Assistant 2026.9's device registry changes (which
  deprecate how devices were linked and looked up).

## 2.2.2

### Connection

- **An answer the panel mislabels no longer drops the connection.** The panel
  sometimes answers a request with an error carrying another request's ID. When
  that happened to the keep-alive check, the integration didn't recognize the
  answer and dropped a working connection after 30 seconds. Any answer from the
  panel now counts. (Updates the panel pushes still don't: if requests go
  unanswered, reconnecting is what gets commands working again.)
- **A slow panel can finish connecting.** Connecting loads every object in
  several requests, and the 60-second limit applied to all of them together, so
  a large or slow panel that kept answering could be cut off and retried
  forever. The attempt now fails only when the panel has answered nothing for 60
  seconds.

Both found by GitHub Copilot's review of dwradcliffe/intellicenter#53.

## 2.2.1

### Fixed: heaters belong to the bodies they're assigned to

Since 2.0.2, a body also got a water heater for a heater that isn't assigned to
it, when the body still had that heater selected or the heater looked "shared".
That was a mistake: `SHARE="SHARE"` is only how the IntelliCenter reports an
attribute an object doesn't have, and the IntelliCenter doesn't heat a body with
a heater that isn't assigned to it. The water heater looked usable while the
pump ran and the water stayed cold. A heater now serves exactly the bodies its
settings assign it to (its `BODY`), as in dwradcliffe/intellicenter.

- **New repair issue** when a body has a heater selected that isn't assigned to
  it: it explains that the IntelliCenter won't heat that body and how to fix it
  in the heater settings (Pentair app or panel), and clears itself once the
  heater is assigned.

If your spa or pool water heater disappears after updating, this is why: see
Settings > Repairs.

## 2.2.0

### Breaking change: a water heater's state is its operation mode

A water heater's state is now its operation mode: the name of the selected
heater (for example `Gas Heater`), or `off` when no heater is selected. It used
to be `on`, `idle` or `off`, which Home Assistant doesn't expect for a water
heater: its controls read the state as the selected mode, so the selected heater
was never shown as selected in the water heater dialog or a tile card's
operation mode control (dwradcliffe/intellicenter#40 by @hacctarr).

Whether a heater is heating right now is the heater's binary sensor (for example
`binary_sensor.gas_heater`), which reports heating for any body it serves,
including the spa on shared equipment. The water heater's `HTMODE` attribute is
also still there (`0` when not heating).

**What to check:** automations, scripts, templates and dashboards that compare a
water heater's state with `on` or `idle`:

| Before | After |
| --- | --- |
| water heater is `on` | the heater's binary sensor is `on` |
| water heater is `idle` | the body is on, a heater is selected (water heater is not `off`) and the heater's binary sensor is `off` |
| water heater is `off` | water heater is `off` (no heater selected); a body that is switched off with a heater selected now shows the heater's name |

For example, a notification template that said
`{{ states('water_heater.spa') }}` can say
`{{ 'heating' if is_state('binary_sensor.gas_heater', 'on') else ('off' if is_state('water_heater.spa', 'off') else 'idle') }}`.

## 2.1.0

### Connection and commands

- **Commands are sent from the event loop.** Switch, light, number and water
  heater commands ran in a worker thread and wrote to the connection from there.
  asyncio transports are not thread safe: if the panel's answer was processed at
  the wrong moment, the one-request-at-a-time counter stuck and every later
  command was queued forever, while updates kept arriving. A request made from
  any other thread is now handed over to the event loop.
- **Messages are processed as soon as they are complete.** A network packet
  ending in the middle of a message held back the complete messages in front of
  it. Text is also decoded incrementally, so an accented name split across two
  packets no longer drops the connection. (Same fix as NTillmann/intellicenter
  and josehumbertoco/intellicenter.)
- **Reconnection survives a drop during the initial handshake.** It could stop
  for good until Home Assistant was restarted. A failing callback can no longer
  break the reconnection loop, and two loops never run at once.
- **Unloading cleans up properly**: it returns the real result, doesn't try to
  unload platforms that were never set up, and no longer leaves a Home Assistant
  stop listener behind on every reload (based on dwradcliffe/intellicenter#44 by
  @gmisner).

### Entities

- The heater binary sensor reports heating for any body that uses the heater.
  (This entry used to say it stayed off while a shared heater heated the spa;
  that was the misreading corrected in 2.2.1.)
- **Sensors report numbers** instead of text, so temperatures are converted
  between °F and °C and display precision can be set; numbers and water heaters
  cope with missing values (dwradcliffe/intellicenter#45 by @gmisner).
- **pH and ORP sensors have units** (pH, mV) (dwradcliffe/intellicenter#36 by
  @loopj). Home Assistant will ask once, under Repairs, to confirm the unit
  change for their long-term statistics.
- **Pumps show as running from their speed, power or flow** rather than their
  status, which can stay on while the pump is stopped; the binary sensor now has
  the "running" device class (dwradcliffe/intellicenter#39 by @hacctarr).
- **Water heaters support turn on/off** (the README already said so): turning on
  uses the heater used last. A restored or unnamed heater no longer causes bad
  values (feature idea from dwradcliffe/intellicenter#32 by @anderjoshai).
- **Values the panel reports as undefined are ignored.** IntelliCenter echoes an
  attribute's name when it has no value; those were stored as the value, so a
  schedule sensor could stay off and entities were created for attributes a
  device doesn't have. Such binary sensors now report unknown.
- Light effects are guarded when a light doesn't support them
  (dwradcliffe/intellicenter#43 by @gmisner), and a light show whose member
  circuit is missing, or a chlorinator that doesn't say which bodies it serves,
  no longer breaks setup.

### Compatibility

- Systems on IntelliCenter firmware 3.x, which report some objects without a
  type, no longer fail to load (dwradcliffe/intellicenter#41 by @bmrowe).
- Relative imports in the binary sensor platform
  (dwradcliffe/intellicenter#47 by @gmisner).

### Tests and tooling

- End-to-end tests run the integration inside Home Assistant against a fake
  IntelliCenter (`tests/fake_panel.py`, `tests_ha/`), alongside the protocol
  tests in `tests/`. Both run on every push, with flake8, hassfest and the HACS
  validation.

## 2.0.3

- **Keep-alive.** The original `ping` heartbeat was removed upstream because
  firmware 1.064 doesn't answer it, which left no way to notice a dead
  connection: when the panel lost power or dropped off the network, Home
  Assistant stayed "connected" with every value frozen until the integration was
  reloaded. The integration now checks every 60 seconds that the panel answers
  and drops the connection if it doesn't within 30 seconds, so entities become
  unavailable and reconnection starts. Connection attempts time out after 60
  seconds and the retry delay is capped at 5 minutes
  (dwradcliffe/intellicenter#50).

## 2.0.2

- Water heaters for bodies listed with a "shared" heater. **This was wrong and
  is reverted in 2.2.1**: the spa's water heater had disappeared because its
  heater was no longer assigned to the spa in the IntelliCenter settings, so the
  IntelliCenter wasn't going to heat it.

## 2.0.1

- The salt sensor uses `UnitOfRatio.PARTS_PER_MILLION`; the old constant is
  removed in Home Assistant 2027.8 (dwradcliffe/intellicenter#49).
- Includes upstream's fix of the Fahrenheit water heater minimum temperature
  (40°F, not 4°F).
