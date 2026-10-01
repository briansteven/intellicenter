# Changelog

Changes in this fork (briansteven/intellicenter) since dwradcliffe/intellicenter
v2.0.0. Upgrading from any of these versions is a drop-in replacement: no
configuration changes, and entities keep their IDs.

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

- **Shared heaters report heating for either body.** The heater binary sensor
  only looked at the bodies in the heater's BODY attribute, so it stayed off
  while a shared heater heated the spa.
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

- **Water heaters for both bodies on shared pool/spa equipment.** IntelliCenter
  can list only one body on a shared heater (BODY="B1101", SHARE="SHARE"), which
  made the spa's water heater disappear after a restart.

## 2.0.1

- The salt sensor uses `UnitOfRatio.PARTS_PER_MILLION`; the old constant is
  removed in Home Assistant 2027.8 (dwradcliffe/intellicenter#49).
- Includes upstream's fix of the Fahrenheit water heater minimum temperature
  (40°F, not 4°F).
