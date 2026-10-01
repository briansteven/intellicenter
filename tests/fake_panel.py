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
"""

import asyncio
import copy
import json
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
    },
    "C0001": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "SPA",
        "SNAME": "Spa",
        "PARENT": "M0102",
        "STATUS": "OFF",
        "FEATR": "OFF",
        "USE": "WHITER",
    },
    "C0002": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "INTELLI",
        "SNAME": "Pool Light",
        "PARENT": "M0101",
        "STATUS": "OFF",
        "FEATR": "OFF",
        "USE": "MAGNTAR",
    },
    "C0004": {
        "OBJTYP": "CIRCUIT",
        "SUBTYP": "GENERIC",
        "SNAME": "Waterfall",
        "PARENT": "M0101",
        "STATUS": "OFF",
        "FEATR": "ON",
        "USE": "WHITER",
    },
    "PMP01": {
        "OBJTYP": "PUMP",
        "SUBTYP": "VSF",
        "SNAME": "VSF",
        "STATUS": "10",
        "RPM": "3000",
        "PWR": "1349",
        "GPM": "62",
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
    "SCH01": {
        "OBJTYP": "SCHED",
        "SNAME": "Pool",
        "ACT": "ON",
        "VACFLO": "OFF",
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
            notify = []
            for item in request["objectList"]:
                self.objects[item["objnam"]].update(item["params"])
                notify.append({"objnam": item["objnam"], "params": item["params"]})
            return [
                {"command": "SetParamList", "messageID": msg_id, "response": "200"},
                {
                    "command": "NotifyList",
                    "messageID": str(uuid.uuid4()),
                    "objectList": notify,
                },
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
