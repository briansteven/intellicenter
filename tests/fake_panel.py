"""A fake IntelliCenter that serves a small but realistic object model.

Unlike fake_intellicenter.FakeIntelliCenter (which only answers the SYSTEM
request used to identify the panel), this one implements enough of the local
protocol on port 6681 to load the whole integration:

- GetParamList: by condition (``OBJTYP=...``) or for every object (``INCR``)
- RequestParamList: return the requested attributes and subscribe to them
- SetParamList: apply the changes, answer, then push a NotifyList

Attributes the panel has no value for are echoed back as their own key name,
which is how the real panel says "undefined". Like the real panel (IC 1.064),
an error is answered with a messageID of its own, not the request's: a change
to an unknown object gets a 404, an unknown command an "Error" 404.

Like the real panel on power loss, it can be told to go silent without
closing the connection.

Like IC 3.x, it can raise and clear alerts: objects of type STATUS, created
and deleted with a WriteParamList pushed to every connection.
"""

import asyncio
import copy
import json
import time
import uuid

# Modeled on a real pool + spa system with shared equipment (IC 1.064):
# one gas heater assigned to both bodies. (Like every attribute an object
# doesn't have, a heater's SHARE is echoed back as "SHARE": undefined.)
DEFAULT_OBJECTS = {
    "_5451": {
        "OBJTYP": "SYSTEM",
        "PROPNAME": "Test Pool",
        "VER": "IC: 1.064 , ICWEB:2021-10-19 1.007",
        "MODE": "ENGLISH",
        "SNAME": "test-system-sname",
        "VACFLO": "OFF",
        "SERVICE": "AUTO",
    },
    "B1101": {
        "OBJTYP": "BODY",
        "SUBTYP": "POOL",
        "SNAME": "Pool",
        "PARENT": "M0101",
        "FILTER": "C0006",
        "HEATER": "H0001",
        "HTSRC": "H0001",
        "HTMODE": "0",
        "STATUS": "ON",
        "SHARE": "B1202",
        "LOTMP": "77",
        "LSTTMP": "78",
        "VOL": "15000",
    },
    "B1202": {
        "OBJTYP": "BODY",
        "SUBTYP": "SPA",
        "SNAME": "Spa",
        "PARENT": "M0102",
        "FILTER": "C0001",
        "HEATER": "H0001",
        "HTSRC": "H0001",
        "HTMODE": "0",
        "STATUS": "OFF",
        "SHARE": "B1101",
        "LOTMP": "99",
        "LSTTMP": "79",
        "VOL": "500",
    },
    "H0001": {
        "OBJTYP": "HEATER",
        "SUBTYP": "GENERIC",
        "SNAME": "Gas Heater",
        "PARENT": "M0101",
        "BODY": "B1101 B1202",
        "LISTORD": "1",
    },
    "C0006": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "POOL",
        "SNAME": "Pool",
        "PARENT": "M0101",
        "STATUS": "ON",
        "FEATR": "OFF",
        "USE": "WHITER",
        "TIME": "720",
        "DNTSTP": "OFF",
    },
    "C0001": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "SPA",
        "SNAME": "Spa",
        "PARENT": "M0102",
        "STATUS": "OFF",
        "FEATR": "OFF",
        "USE": "WHITER",
        "TIME": "720",
        "DNTSTP": "OFF",
    },
    "C0002": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "INTELLI",
        "SNAME": "Pool Light",
        "PARENT": "M0101",
        "STATUS": "OFF",
        "FEATR": "OFF",
        "USE": "MAGNTAR",
        "TIME": "720",
        "DNTSTP": "OFF",
    },
    "C0004": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "GENERIC",
        "SNAME": "Waterfall",
        "PARENT": "M0101",
        "STATUS": "OFF",
        "FEATR": "ON",
        "USE": "WHITER",
        "TIME": "720",
        "DNTSTP": "OFF",
    },
    # not featured: no switch, so no egg timer either
    "C0003": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "GENERIC",
        "SNAME": "AUX 3",
        "PARENT": "M0101",
        "STATUS": "OFF",
        "FEATR": "OFF",
        "TIME": "720",
        "DNTSTP": "OFF",
    },
    # a command, not a circuit a user turns on
    "_A111": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "ALL",
        "SNAME": "All Lights On",
        "PARENT": "00000",
        "STATUS": "PERMIT",
        "FEATR": "OFF",
        "TIME": "0",
        "DNTSTP": "OFF",
    },
    "PMP01": {
        "OBJTYP": "PUMP",
        "SUBTYP": "VSF",
        "SNAME": "VSF",
        "STATUS": "10",
        "RPM": "3000",
        "PWR": "1349",
        "GPM": "62",
        "MIN": "450",
        "MAX": "3450",
        "MINF": "20",
        "MAXF": "140",
    },
    # the pump's speed for each circuit it runs for
    "p0101": {
        "OBJTYP": "PMPCIRC",
        "PARENT": "PMP01",
        "CIRCUIT": "C0006",
        "SPEED": "3000",
        "SELECT": "RPM",
    },
    "p0102": {
        "OBJTYP": "PMPCIRC",
        "PARENT": "PMP01",
        "CIRCUIT": "C0001",
        "SPEED": "50",
        "SELECT": "GPM",
    },
    "CHM01": {
        "OBJTYP": "CHEM",
        "SUBTYP": "ICHEM",
        "SNAME": "IntelliChem 1",
        "BODY": "B1101",
        "PHVAL": "7.40",
        "ORPVAL": "620",
        "QUALTY": "-0.1",
        "PHTNK": "7",
        "ORPTNK": "7",
        "PHSET": "7.4",
        "ORPSET": "650",
        "ALK": "100",
        "CALC": "348",
        "CYACID": "58",
        "PHHI": "OFF",
        "PHLO": "OFF",
        "ORPHI": "OFF",
        "ORPLO": "OFF",
        "PHVOL": "4864",
        "ORPVOL": "0",
        "SINDEX": "2.47",
    },
    "CHR01": {
        "OBJTYP": "CHEM",
        "SUBTYP": "ICHLOR",
        "SNAME": "IntelliChlor 1",
        "BODY": "B1101",
        "SALT": "3500",
        "PRIM": "25",
        "SEC": "20",
        "SUPER": "OFF",
        "TIMOUT": "86400",
    },
    "_A135": {
        "OBJTYP": "SENSE",
        "SUBTYP": "AIR",
        "SNAME": "Air Sensor",
        "PARENT": "00000",
        "SOURCE": "82",
    },
    "SSW11": {
        "OBJTYP": "SENSE",
        "SUBTYP": "POOL",
        "SNAME": "Water Sensor 1",
        "PARENT": "00000",
        "SOURCE": "78",
    },
    # every day from sunrise to sunset (TIME, TIMOUT: today's), heating left as
    # it is ("HOLD", written as "00001")
    "SCH01": {
        "OBJTYP": "SCHED",
        "SNAME": "Pool",
        "ACT": "ON",
        "STATUS": "ON",
        "CIRCUIT": "C0006",
        "DAY": "MTWRFAU",
        "START": "SRIS",
        "STOP": "SSET",
        "TIME": "06,49,00",
        "TIMOUT": "18,35,00",
        "HEATER": "HOLD",
        "LOTMP": "78",
        "VACFLO": "OFF",
        "SINGLE": "OFF",
    },
    # a cover object as IC 1.064 defines one, installed or not: no position
    "CVR01": {
        "OBJTYP": "EXTINSTR",
        "SUBTYP": "COVER",
        "SNAME": "Cover 1",
        "BODY": "B1101",
        "STATUS": "OFF",
        "NORMAL": "ON",
    },
}


class FakePanel:
    """Minimal model-driven stand-in for the IntelliCenter local API."""

    def __init__(self, objects=None):
        """Initialize the fake panel with a (deep copied) object model."""
        self.objects = copy.deepcopy(objects or DEFAULT_OBJECTS)
        self.silent = False  # when True, requests are read but never answered
        self.response_delay = 0  # seconds to wait before answering each request
        self.refuse_changes = {}  # objnam: error code to answer its changes with
        self.refuse_conditions = set()  # conditions GetParamList answers with an error
        # when True, the NotifyList following a change is held until released
        # (the real panel can report a change after answering the next request)
        self.hold_notify = False
        self._held = []
        self.requests = []  # every request received, in order
        self.connections = 0
        self._server = None
        self._writers = []

    @property
    def port(self) -> int:
        """Return the port the fake panel listens on."""
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> int:
        """Start listening on a random local port and return it."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.port

    async def close(self):
        """Stop the server and drop every connection."""
        for writer in self._writers:
            writer.transport.abort()
        self._server.close()
        await self._server.wait_closed()

    def set_params(self, objnam: str, params: dict):
        """Change attributes on the panel side and notify connected clients."""
        self.objects[objnam].update(params)
        self._broadcast(
            {
                "command": "NotifyList",
                "messageID": str(uuid.uuid4()),
                "objectList": [{"objnam": objnam, "params": params}],
            }
        )

    def raise_alert(
        self, objnam: str, message: str, parent: str, raised: int = 1790963580
    ):
        """Raise an alert like IC 3.x: create a STATUS object and push it."""
        params = {
            "COUNT": "1",
            "MODE": "0",
            "OBJNAM": objnam,
            "OBJTYP": "STATUS",
            "PARENT": parent,
            "PARTY": str(raised),
            "SHOMNU": "ON",
            "SINDEX": "37234",
            "SNAME": message,
            "STATIC": "OFF",
            "TIME": str(raised),
        }
        self.objects[objnam] = params
        self.push_write_param_list(
            {"created": [{"objnam": objnam, "params": dict(params)}]}
        )

    def clear_alert(self, objnam: str):
        """Clear an alert like IC 3.x: delete its object and push that."""
        del self.objects[objnam]
        self.push_write_param_list({"deleted": [objnam]})

    def release_notify(self):
        """Send the notifications held back (see hold_notify)."""
        held, self._held = self._held, []
        for message in held:
            self._broadcast(message)

    def push_write_param_list(self, *items: dict):
        """Push a WriteParamList with the given items (changes, created, deleted)."""
        now = str(int(time.time()))
        self._broadcast(
            {
                "command": "WriteParamList",
                "messageID": str(uuid.uuid4()),
                "timeSince": now,
                "timeNow": now,
                "response": "200",
                "objectList": list(items),
            }
        )

    def changes(self, objnam: str = None) -> list:
        """Return the SetParamList requests received, optionally for one object."""
        found = []
        for request in self.requests:
            if request.get("command", "").upper() != "SETPARAMLIST":
                continue
            for item in request.get("objectList", []):
                if objnam is None or item["objnam"] == objnam:
                    found.append(item["params"])
        return found

    # -------------------------------------------------------------------------

    def _values(self, objnam: str, keys: list) -> dict:
        obj = self.objects.get(objnam, {})
        return {key: obj.get(key, key) for key in keys}

    def _answer(self, request: dict):
        command = request.get("command", "")
        msg_id = request["messageID"]

        if command == "GetParamList":
            condition = request.get("condition", "")
            if condition in self.refuse_conditions:
                return [
                    {
                        "command": "SendParamList",
                        "messageID": str(uuid.uuid4()),
                        "response": "400",
                    }
                ]
            keys = request["objectList"][0]["keys"]
            if condition.startswith("OBJTYP="):
                objtype = condition.split("=", 1)[1]
                names = [n for n, o in self.objects.items() if o["OBJTYP"] == objtype]
            else:
                names = list(self.objects)
            return [
                {
                    "command": "SendParamList",
                    "messageID": msg_id,
                    "response": "200",
                    "objectList": [
                        {"objnam": n, "params": self._values(n, keys)} for n in names
                    ],
                }
            ]

        if command == "RequestParamList":
            return [
                {
                    "command": "SendParamList",
                    "messageID": msg_id,
                    "response": "200",
                    "objectList": [
                        {
                            "objnam": item["objnam"],
                            "params": self._values(item["objnam"], item["keys"]),
                        }
                        for item in request["objectList"]
                    ],
                }
            ]

        if command.upper() == "SETPARAMLIST":
            for item in request["objectList"]:
                objnam = item["objnam"]
                if objnam not in self.objects or objnam in self.refuse_changes:
                    code = self.refuse_changes.get(objnam, "404")
                    return [
                        {
                            "command": "SetParamList",
                            "messageID": str(uuid.uuid4()),
                            "response": code,
                        }
                    ]
            for item in request["objectList"]:
                obj = self.objects[item["objnam"]]
                if obj.get("OBJTYP") == "SCHED" and item["params"].get("HEATER") == "HOLD":
                    # IC 3.014: "don't change" reads HOLD but is written 00001
                    return [
                        {"command": "SetParamList", "messageID": msg_id, "response": "400"}
                    ]
            notify = []
            for item in request["objectList"]:
                params = dict(item["params"])
                obj = self.objects[item["objnam"]]
                if obj.get("OBJTYP") == "SCHED" and params.get("HEATER") == "00001":
                    params["HEATER"] = "HOLD"
                obj.update(params)
                notify.append({"objnam": item["objnam"], "params": params})
            pushed = {
                "command": "NotifyList",
                "messageID": str(uuid.uuid4()),
                "objectList": notify,
            }
            if self.hold_notify:
                self._held.append(pushed)
                return [{"command": "SetParamList", "messageID": msg_id, "response": "200"}]
            return [
                {"command": "SetParamList", "messageID": msg_id, "response": "200"},
                pushed,
            ]

        return [
            {
                "command": "Error",
                "messageID": str(uuid.uuid4()),
                "response": "404",
                "description": f"'{command}' Unknown command!",
            }
        ]

    def _broadcast(self, message: dict):
        data = (json.dumps(message) + "\r\n").encode()
        for writer in self._writers:
            if not writer.is_closing():
                writer.write(data)

    async def _handle(self, reader, writer):
        self.connections += 1
        self._writers.append(writer)
        decoder = json.JSONDecoder()
        buffer = ""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    return
                buffer += data.decode()
                while buffer:
                    buffer = buffer.lstrip()
                    try:
                        request, end = decoder.raw_decode(buffer)
                    except ValueError:
                        break  # wait for the rest of the request
                    buffer = buffer[end:]
                    self.requests.append(request)
                    if self.silent:
                        continue
                    if self.response_delay:
                        await asyncio.sleep(self.response_delay)
                    for reply in self._answer(request):
                        writer.write((json.dumps(reply) + "\r\n").encode())
                    await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            return
        finally:
            if writer in self._writers:
                self._writers.remove(writer)
