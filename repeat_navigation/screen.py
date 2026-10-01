"""Read-only VT observer. Never transforms or records terminal output."""
import codecs
import re


class Screen:
    def __init__(self, rows, columns):
        self.resize(rows, columns)
        self.pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.generation = 0
        self.ready = False
        self.style = "0"
        self.scene = None

    def resize(self, rows, columns):
        self.cells = [[" "] * min(1000, max(1, columns)) for _ in range(min(300, max(1, rows)))]
        self.styles = [["0"] * len(self.cells[0]) for _ in self.cells]
        self.row = self.column = 0

    def feed(self, data):
        self.generation += 1
        self.ready |= b"\x1b[?2026h" in data or b"\x1b[?1049h" in data
        self.pending += self.decoder.decode(data)
        while self.pending:
            text = self.pending
            if text[0] == "\x1b":
                if len(text) < 2:
                    return
                if text[1] == "[":
                    match = re.match(r"\x1b\[([0-?]*)([ -/]*)([@-~])", text)
                    if not match:
                        if len(text) > 65536:
                            self.pending = ""
                        return
                    self.pending = text[match.end():]
                    params, _, command = match.groups()
                    if params.startswith(("?", ">", "<")):
                        if params in ("?2026", "?1049") and command == "h":
                            self.ready = True
                        if params == "?2026" and command == "l":
                            # Commit only complete native paints. Ignore the
                            # PREFIX footer; selected workspace/tab styling and
                            # the pane cursor reveal actual focus completion.
                            chrome = [(tuple(self.cells[0]), tuple(self.styles[0]))]
                            chrome += [(tuple(c[:26]), tuple(s[:26])) for c, s in zip(self.cells[:-1], self.styles[:-1])]
                            self.scene = hash((tuple(chrome), self.row, self.column))
                        continue
                    values = [int(p or "0") for p in params.split(";") if p.isdigit() or not p]
                    n = values[0] if values else 0
                    if command == "m":
                        self.style = params if n == 0 else (self.style + "|" + params)[-4096:]
                    elif command in ("H", "f"):
                        self.row = min(len(self.cells)-1, max(0, (n or 1)-1))
                        self.column = min(len(self.cells[0])-1, max(0, (values[1] if len(values)>1 else 1)-1))
                    elif command == "G":
                        self.column = min(len(self.cells[0])-1, max(0, (n or 1)-1))
                    elif command in ("A", "B"):
                        self.row = min(len(self.cells)-1, max(0, self.row + (n or 1)*(1 if command == "B" else -1)))
                    elif command in ("C", "D"):
                        self.column = min(len(self.cells[0])-1, max(0, self.column + (n or 1)*(1 if command == "C" else -1)))
                    elif command == "J":
                        if n in (2, 3):
                            self.cells = [[" "] * len(self.cells[0]) for _ in self.cells]
                        elif n == 0:
                            self.cells[self.row][self.column:] = [" "] * (len(self.cells[0])-self.column)
                            for row in range(self.row+1, len(self.cells)):
                                self.cells[row] = [" "] * len(self.cells[0])
                    elif command == "K":
                        start, end = (0, len(self.cells[0])) if n == 2 else ((0, self.column+1) if n == 1 else (self.column, len(self.cells[0])))
                        self.cells[self.row][start:end] = [" "] * (end-start)
                    continue
                if text[1] == "]":
                    match = re.search(r"\x07|\x1b\\", text)
                    if not match:
                        if len(text) > 65536:
                            self.pending = ""
                        return
                    self.pending = text[match.end():]
                    continue
                self.pending = text[2:]
                continue
            self.pending = text[1:]
            char = text[0]
            if char == "\r":
                self.column = 0
            elif char == "\n":
                self.row = min(len(self.cells)-1, self.row+1)
            elif char == "\b":
                self.column = max(0, self.column-1)
            elif ord(char) >= 32 and char != "\x7f":
                self.cells[self.row][self.column] = char
                self.styles[self.row][self.column] = self.style
                self.column = min(len(self.cells[0])-1, self.column+1)

    @property
    def prefix_visible(self):
        footer = "".join(self.cells[-1])
        return bool(re.search(r"\bPREFIX\s", footer))
