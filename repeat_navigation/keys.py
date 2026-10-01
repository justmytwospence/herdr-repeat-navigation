"""Bounded input tokenization. Paste and terminal replies are never hotkeys."""
import re
from dataclasses import dataclass

CTRL, ALT, SHIFT = 4, 2, 1


@dataclass
class Token:
    raw: bytes
    key: str = ""
    mods: int = 0
    kind: str = "key"
    press: bool = True


class Decoder:
    def __init__(self):
        self.buffer = b""
        self.paste = False

    def feed(self, data, flush=False):
        self.buffer += data
        tokens = []
        while self.buffer:
            b = self.buffer
            if self.paste:
                end = b.find(b"\x1b[201~")
                if end < 0:
                    keep = min(5, len(b))
                    if len(b) > keep:
                        tokens.append(Token(b[:-keep], kind="paste"))
                        self.buffer = b[-keep:]
                    break
                tokens.append(Token(b[:end+6], kind="paste"))
                self.buffer = b[end+6:]
                self.paste = False
                continue
            if b.startswith(b"\x1b[200~"):
                tokens.append(Token(b[:6], kind="paste"))
                self.buffer = b[6:]
                self.paste = True
                continue
            if b.startswith(b"\x1b["):
                match = re.match(rb"\x1b\[[0-?]*[ -/]*[@-~]", b)
                if not match:
                    if not flush and len(b) < 8192:
                        break
                    tokens.append(Token(b, kind="unknown"))
                    self.buffer = b""
                    continue
                raw = match.group()
                self.buffer = b[len(raw):]
                kitty = re.fullmatch(rb"\x1b\[(\d+)(?::[0-9:]*)?(?:;(\d+)(?::(\d+))?)?(?:;[0-9:]*)?u", raw)
                if kitty:
                    code, mods, event = kitty.groups()
                    code = int(code)
                    key = chr(code) if code < 128 else ""
                    key = {"\r": "enter", "\t": "tab", "\x1b": "esc"}.get(key, key)
                    tokens.append(Token(raw, key, int(mods or b"1")-1, press=event != b"3"))
                else:
                    kind = "mouse" if raw.startswith(b"\x1b[<") else ("key" if raw[-1:] in b"ABCDHF~" else "reply")
                    tokens.append(Token(raw, kind=kind))
                continue
            if b[0] == 27:
                if len(b) < 2 and not flush:
                    break
                if len(b) > 1 and 32 <= b[1] < 127:
                    tokens.append(Token(b[:2], chr(b[1]), ALT))
                    self.buffer = b[2:]
                else:
                    tokens.append(Token(b[:1], "esc"))
                    self.buffer = b[1:]
                continue
            value = b[0]
            self.buffer = b[1:]
            if value in (10, 13):
                tokens.append(Token(b[:1], "enter"))
            elif value == 9:
                tokens.append(Token(b[:1], "tab"))
            elif value == 8 or value == 127:
                tokens.append(Token(b[:1], "backspace"))
            elif 1 <= value <= 26:
                tokens.append(Token(b[:1], chr(value+96), CTRL))
            elif 32 <= value < 127:
                tokens.append(Token(b[:1], chr(value)))
            else:
                tokens.append(Token(b[:1], kind="unknown"))
        return tokens


def chord(key, mods=0):
    if mods == 0:
        return key.encode()
    # CSI-u distinguishes Ctrl-h/j from Backspace/Enter.
    return ("\x1b[%d;%du" % (ord(key), mods+1)).encode()


def navigation(token):
    """Initial chords and the unmodified pair they allow within repeat time."""
    if token.kind != "key" or not token.press or not token.key:
        return None
    key, mods = token.key, token.mods
    if mods == CTRL and key in "jk":
        return {k: chord(k, CTRL) for k in "jk"}
    if mods == CTRL and key in "hl":
        return {k: chord(k, CTRL) for k in "hl"}
    if mods == CTRL and key in "np":
        return {k: chord(k, CTRL) for k in "np"}
    if mods == ALT and key in "hl":
        return {k: chord(k, ALT) for k in "hl"}
    if mods == 0 and key in "hjkl":
        return {k: chord(k) for k in "hjkl"}
    if mods == 0 and key in "np":
        return {k: chord(k) for k in "np"}
    return None
