"""Timed-repeat state machine. Prefix acknowledgement prevents modal hijacking."""
from collections import deque
from dataclasses import dataclass
from .keys import CTRL, navigation


@dataclass
class Pending:
    raw: bytes
    target: bytes
    mapping: dict
    expires: float
    generation: int
    repeated: bool


class Engine:
    def __init__(self, timeout=0.5, acknowledge=0.12):
        self.timeout = timeout
        self.acknowledge = acknowledge
        self.prefix = False
        self.mapping = {}
        self.deadline = 0.0
        self.pending = None
        self.queue = deque()
        self.literal = b""
        self.waiting = None

    def feed(self, tokens):
        if len(self.queue) + len(tokens) > 128:
            # Do not turn paste-like bursts into a long backlog of focus hops.
            self.literal += ((self.pending.raw if self.pending else b"") +
                             b"".join(t.raw for t in self.queue) + b"".join(t.raw for t in tokens))
            self.pending = None
            self.queue.clear()
            self.prefix = False
            self.stop()
        else:
            self.queue.extend(tokens)

    def stop(self):
        self.mapping = {}
        self.deadline = 0.0

    def drain(self, now, generation, prefix_visible, ready=True, scene=None):
        output = bytearray(self.literal)
        self.literal = b""
        if now >= self.deadline:
            self.stop()
        if self.pending:
            pending = self.pending
            if generation > pending.generation and prefix_visible:
                output.extend(pending.target)
                self.mapping = pending.mapping
                self.deadline = now + self.timeout
                self.pending = None
                self.waiting = (scene, now) if scene is not None else None
            elif now >= pending.expires:
                # A popup/auth prompt did not enter native prefix mode. Keep
                # input literal rather than treating its text as navigation.
                output.extend(pending.raw)
                self.stop()
                self.pending = None
            else:
                return bytes(output)
        if self.waiting:
            before, started = self.waiting
            if now-started < .25 and (prefix_visible or scene == before):
                return bytes(output)
            self.waiting = None
        while self.queue:
            token = self.queue.popleft()
            if token.kind == "reply" or not token.press:
                output.extend(token.raw)
                continue
            if token.key == "b" and token.mods == CTRL and token.kind == "key":
                output.extend(token.raw)
                self.stop()
                self.prefix = not self.prefix
                continue
            initial = navigation(token) if self.prefix and ready else None
            if initial:
                self.pending = Pending(token.raw, token.raw, initial,
                                       now+self.acknowledge, generation, False)
                self.prefix = False
                break
            if self.prefix:
                self.prefix = False
                self.stop()
                output.extend(token.raw)
                continue
            if self.mapping and token.kind == "key":
                target = self.mapping.get(token.key) if token.mods == 0 else None
                if token.mods and navigation(token):
                    target = token.raw
                if target:
                    # Native navigation is one-shot. Ask for a new prefix,
                    # then wait for its visible acknowledgement before replay.
                    output.extend(b"\x02")
                    mapping = navigation(token) if token.mods else self.mapping
                    self.pending = Pending(token.raw, target, mapping,
                                           now+self.acknowledge, generation, True)
                    break
                if token.key == "esc":
                    self.stop()  # Optional cancel; never required to resume typing.
                    continue
            self.stop()
            output.extend(token.raw)
        return bytes(output)
