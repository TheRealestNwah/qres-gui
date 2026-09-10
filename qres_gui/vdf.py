"""Reader/writer for Valve's text KeyValues format (.vdf / .acf).

Key order and duplicate keys are preserved, so a file written back differs
from Steam's own output only where a value was changed.
"""

from __future__ import annotations

from typing import Iterator, Union

Value = Union[str, "KV"]

# Steam only escapes backslashes and quotes; tabs and newlines are written raw.
_UNESCAPE = {"\\": "\\", '"': '"'}


class KV:
    """An ordered block of key/value pairs. Lookups ignore case, as Steam's do."""

    __slots__ = ("pairs",)

    def __init__(self, pairs: list[list] | None = None):
        self.pairs: list[list] = pairs if pairs is not None else []

    def _find(self, key: str) -> int:
        low = key.lower()
        for i, pair in enumerate(self.pairs):
            if pair[0].lower() == low:
                return i
        return -1

    def get(self, key: str, default=None):
        i = self._find(key)
        return self.pairs[i][1] if i >= 0 else default

    def __contains__(self, key: str) -> bool:
        return self._find(key) >= 0

    def __getitem__(self, key: str) -> Value:
        i = self._find(key)
        if i < 0:
            raise KeyError(key)
        return self.pairs[i][1]

    def __setitem__(self, key: str, value: Value) -> None:
        i = self._find(key)
        if i >= 0:
            self.pairs[i][1] = value
        else:
            self.pairs.append([key, value])

    def items(self) -> Iterator[tuple[str, Value]]:
        for key, value in self.pairs:
            yield key, value

    def block(self, *path: str, create: bool = False) -> "KV | None":
        """Walk nested blocks by key, optionally creating missing ones."""
        node = self
        for key in path:
            child = node.get(key)
            if not isinstance(child, KV):
                if not create:
                    return None
                child = KV()
                node[key] = child
            node = child
        return node


def _tokens(text: str) -> Iterator[tuple[str, bool]]:
    """Yield (token, was_quoted). Braces are yielded unquoted."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif c in "{}":
            yield c, False
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n and text[i + 1] in _UNESCAPE:
                    buf.append(_UNESCAPE[text[i + 1]])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            yield "".join(buf), True
            i += 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            token = text[start:i]
            if not token.startswith("["):  # skip platform conditionals like [$WIN32]
                yield token, False


def loads(text: str) -> KV:
    root = KV()
    stack = [root]
    key: str | None = None
    for token, quoted in _tokens(text):
        if not quoted and token == "{":
            if key is None:
                raise ValueError("VDF: '{' without a key")
            child = KV()
            stack[-1].pairs.append([key, child])
            stack.append(child)
            key = None
        elif not quoted and token == "}":
            if len(stack) == 1 or key is not None:
                raise ValueError("VDF: unexpected '}'")
            stack.pop()
        elif key is None:
            key = token
        else:
            stack[-1].pairs.append([key, token])
            key = None
    if len(stack) != 1 or key is not None:
        raise ValueError("VDF: unexpected end of input")
    return root


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def dumps(kv: KV) -> str:
    out: list[str] = []

    def walk(node: KV, depth: int) -> None:
        indent = "\t" * depth
        for key, value in node.pairs:
            if isinstance(value, KV):
                out.append(f'{indent}"{_escape(key)}"\n{indent}{{\n')
                walk(value, depth + 1)
                out.append(f"{indent}}}\n")
            else:
                out.append(f'{indent}"{_escape(key)}"\t\t"{_escape(value)}"\n')

    walk(kv, 0)
    return "".join(out)
