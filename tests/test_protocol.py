"""Tests for the low level protocol (no Home Assistant needed)."""

import json
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "intellicenter"),
)

from pyintellicenter.protocol import ICProtocol  # noqa: E402


class RecordingController:
    """Stand-in for the controller that records the messages it receives."""

    def __init__(self):
        """Initialize."""
        self.messages = []

    def receivedMessage(self, msg_id, command, response, msg):
        """Record a message."""
        self.messages.append(msg)


class RecordingTransport:
    """Stand-in for an asyncio transport that records what is written."""

    def __init__(self, on_write=None):
        """Initialize."""
        self.written = []
        self.on_write = on_write

    def write(self, data):
        """Record a write and run the optional side effect."""
        self.written.append(data)
        if self.on_write:
            self.on_write()


def make_protocol(on_write=None):
    controller = RecordingController()
    protocol = ICProtocol(controller)
    protocol._transport = RecordingTransport(on_write)
    return protocol, controller


def line(obj):
    return (json.dumps(obj, ensure_ascii=False) + "\r\n").encode()


def test_complete_message_is_processed_before_the_next_one_completes():
    """A chunk ending in the middle of a message must not hold back the others."""
    protocol, controller = make_protocol()
    first = line({"command": "NotifyList", "messageID": "1"})
    second = line({"command": "NotifyList", "messageID": "2"})

    protocol.data_received(first + second[:10])
    assert [m["messageID"] for m in controller.messages] == ["1"]

    protocol.data_received(second[10:])
    assert [m["messageID"] for m in controller.messages] == ["1", "2"]


def test_several_messages_in_one_chunk():
    """Every message in a chunk is processed, in order."""
    protocol, controller = make_protocol()
    data = b"".join(line({"messageID": str(i), "command": "x"}) for i in range(5))
    protocol.data_received(data)
    assert [m["messageID"] for m in controller.messages] == ["0", "1", "2", "3", "4"]


def test_character_split_across_chunks_is_decoded():
    """A multi-byte UTF-8 character split across two chunks is kept intact."""
    protocol, controller = make_protocol()
    data = line({"messageID": "1", "command": "x", "SNAME": "Piscine d'été"})
    split_at = data.index("é".encode()) + 1  # in the middle of the character

    protocol.data_received(data[:split_at])
    protocol.data_received(data[split_at:])

    assert controller.messages[0]["SNAME"] == "Piscine d'été"


def test_response_processed_during_the_write_keeps_the_queue_moving():
    """Flow control stays right even if the response comes back mid-write.

    The request must already be counted as pending when its response is
    processed, or the counter sticks and every later request is queued forever.
    """
    protocol = None

    def answer_immediately():
        protocol.responseReceived()

    protocol, _ = make_protocol(on_write=answer_immediately)

    protocol.sendRequest("first")
    assert protocol._out_pending == 0

    protocol.sendRequest("second")
    assert protocol._transport.written == [b"first", b"second"]
