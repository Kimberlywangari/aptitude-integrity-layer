"""The HTML Cytonn's questions arrive in, turned into the plain text the candidate screen shows.

Their text is a small, fixed set of tags (paragraphs, bold, underline, superscripts, a few lists and
pictures), so a candidate's browser is never given markup to render: whatever is not text is either
dropped or turned into something plain. Pictures leave a marker in the text, `[[image 1]]`, at the
place they appeared, and their addresses are returned separately in the same order.
"""

import posixpath
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPT = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ol", "ul", "table", "tr", "blockquote"}
_SKIPPED = {"script", "style", "head", "title"}
_ORDINALS = {"st", "nd", "rd", "th"}
_LETTERED = re.compile(r"^([A-H])[.)]\s+(.+)$", re.DOTALL)


def marker(number: int) -> str:
    return f"[[image {number}]]"


def clean_image_url(src: str | None) -> str | None:
    """The address of a picture with the `/../` Cytonn's links carry resolved, or None if it is
    not an ordinary web address."""
    if not src:
        return None
    parts = urlsplit(src.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    path = posixpath.normpath(parts.path) if parts.path else "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _raised(text: str, sign: str, table: dict[int, int]) -> str:
    """Digits and a few signs become real superscripts (10³); anything else is written as ^(...)."""
    if text and all(ord(c) in table for c in text):
        return text.translate(table)
    if not text or text in _ORDINALS:  # 1st, 2nd, 3rd, 4th: nothing to raise
        return text
    return f"{sign}{text}" if len(text) == 1 else f"{sign}({text})"


def _lowered(text: str) -> str:
    return _raised(text, "_", _SUBSCRIPT)


class _Plain(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[str | None] = []
        self._skip = 0
        self._sup = 0
        self._sub = 0
        self._lists: list[list[int] | None] = []  # a counter for an <ol>, None for a <ul>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n\n")
            if tag == "ol":
                self._lists.append([0])
            elif tag == "ul":
                self._lists.append(None)
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            counter = self._lists[-1] if self._lists else None
            if counter is not None:
                counter[0] += 1
                self.parts.append(f"\n{counter[0]}. ")
            else:
                self.parts.append("\n- ")
        elif tag == "sup":
            self._sup += 1
        elif tag == "sub":
            self._sub += 1
        elif tag == "img":
            self.images.append(clean_image_url(dict(attrs).get("src")))
            self.parts.append(f"\n{marker(len(self.images))}\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)  # <br/> and <img ... /> are starts with no end

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n\n")
            if tag in ("ol", "ul") and self._lists:
                self._lists.pop()
        elif tag == "sup":
            self._sup = max(0, self._sup - 1)
        elif tag == "sub":
            self._sub = max(0, self._sub - 1)

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._sup or self._sub:
            data = _raised(data.strip(), "^", _SUPERSCRIPT) if self._sup else _lowered(data.strip())
        self.parts.append(data)


def to_plain(html: str) -> tuple[str, list[str | None]]:
    """(plain text, picture addresses in order). An address is None when a picture's `src` is not a
    usable web address; the marker for it is still in the text, so the caller can refuse the
    question rather than show a gap."""
    parser = _Plain()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ").replace("​", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip(), parser.images


def strip_option_letters(options: list[str]) -> list[str]:
    """Some of Cytonn's answers begin with their own letter ("A. When the AI..."), and the screen
    puts its own in front. The letters come off only when every answer has one and they run A, B,
    C... in order, so a real answer that happens to start like a letter is left alone."""
    matches = [_LETTERED.match(option) for option in options]
    if len(options) >= 2 and all(matches):
        if [m.group(1) for m in matches if m] == list("ABCDEFGH"[: len(options)]):
            return [m.group(2).strip() for m in matches if m]
    return options
