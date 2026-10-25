"""Reading the written content out of an uploaded document, whatever it is saved as.

An admin can hand the invite list or the question bank over as a PDF, a Word or Excel file, an
OpenDocument file, a slide deck, RTF, HTML, or plain text. The kind is decided from the bytes, never
from the file name. Only the standard library reads the zip-and-XML formats (DOCX, XLSX, PPTX, ODT,
ODS, ODP), HTML, RTF and text; PDF is the one thing that needs a library (pypdf).

Everything uploaded is untrusted:

* the upload is capped (MAX_BYTES) and so is the text that comes out (MAX_TEXT_CHARS);
* a zip is read member by member, never unpacked, with caps on the member count and each member's
  size, so a zip bomb has nothing to expand into;
* an XML part that declares a DOCTYPE or an ENTITY is refused, so there are no entity tricks;
* nothing is executed, and no macro, link or embedded file is followed.

Not readable, and said so plainly: the old binary Office formats (.doc, .xls, .ppt), a scanned PDF
that is only pictures (there is no OCR), a password-protected file, an archive that is not a
document, and anything that is not written content at all.

`want="table"` is for the question-bank import, which needs rows and columns: a spreadsheet gives
its first sheet, a Word file its first table, a text file itself when it looks like CSV or TSV.
Anything else says "no table found" instead of guessing.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from xml.etree import ElementTree

from app.errors import ApiError

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_ZIP_MEMBERS = 2000
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_ROWS = 100_000
MAX_COLUMNS = 1024

Want = Literal["text", "table"]

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # .doc, .xls, .ppt from before Office 2007
UTF16_MARKS = (b"\xff\xfe", b"\xfe\xff")
FORMATS = (
    "PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), OpenDocument (.odt, .ods, .odp), "
    "RTF, HTML, and plain text (.txt, .md, .csv, .tsv)"
)


@dataclass(frozen=True)
class Extracted:
    text: str
    kind: str  # pdf | docx | xlsx | pptx | odt | ods | odp | rtf | html | text
    tabular: bool = False  # rows and columns, written as CSV (or tab-separated text)


def refuse(code: str, status: int = 422, **extra: object) -> ApiError:
    return ApiError(status, code, formats=FORMATS, **extra)


# ---------------------------------------------------------------------------------- the front door


def extract(data: bytes, want: Want = "text") -> Extracted:
    """The written content of `data`: plain text, or for `want="table"` CSV rows."""
    if not data.strip():
        raise refuse("empty_file")
    if len(data) > MAX_BYTES:
        raise refuse("file_too_large", 413, max_mb=MAX_BYTES // (1024 * 1024))

    if data.startswith(OLE_MAGIC):
        raise refuse("legacy_office_format", 415)
    try:
        if data.startswith(PDF_MAGIC):
            result = _pdf(data)
        elif data.startswith(ZIP_MAGIC):
            result = _zip_document(data, want)
        elif data.lstrip().startswith(b"{\\rtf"):
            result = Extracted(_rtf(data.decode("latin-1")), "rtf")
        else:
            result = _plain(data)
    except RecursionError:
        raise refuse("unreadable_file") from None  # nested so deeply that no reader can follow it

    if not result.text.strip():
        raise refuse("no_text_found")
    if len(result.text) > MAX_TEXT_CHARS:
        raise refuse("too_much_text", 413)
    if want == "table" and not result.tabular:
        raise refuse("no_table_found")
    return result


# ------------------------------------------------------------------------------------ plain text


def _plain(data: bytes) -> Extracted:
    utf16 = data.startswith(UTF16_MARKS)
    if not utf16 and b"\x00" in data[:4096]:
        raise refuse("unsupported_type", 415)  # a binary file, not written content
    text = None
    for encoding in ("utf-16",) if utf16 else ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise refuse("unsupported_type", 415)
    control = sum(1 for ch in text[:4096] if ord(ch) < 32 and ch not in "\t\n\r\f")
    if control > 0.05 * max(1, min(len(text), 4096)):
        raise refuse("unsupported_type", 415)
    head = text[:2048].lower()
    if "<html" in head or head.lstrip().startswith("<!doctype html"):
        return Extracted(_html(text), "html")
    lines = [line for line in text.splitlines() if line.strip()][:3]
    tabular = bool(lines) and all(any(d in line for d in (",", "\t", ";")) for line in lines)
    return Extracted(text, "text", tabular)


class _TextOfHtml(HTMLParser):
    BLOCKS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    SKIP = {"script", "style", "head", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.hidden += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.hidden:
            self.hidden -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _html(text: str) -> str:
    parser = _TextOfHtml()
    parser.feed(text)
    lines = "".join(parser.parts).splitlines()
    return "\n".join(line.strip(" \t") for line in lines if line.strip())


# ------------------------------------------------------------------------------------------- RTF

# Groups that hold fonts, colours, styles and pictures, not words.
_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "footnote"}
_RTF_TOKEN = re.compile(
    r"\\([a-z]+)(-?\d+)? ?|\\'([0-9a-f]{2})|\\(.)|([{}])|([^\\{}]+)", re.IGNORECASE | re.DOTALL
)


def _rtf(source: str) -> str:
    out: list[str] = []
    depth = 0
    skip_from: int | None = None  # the depth of a group whose words are left out
    drop_next = False  # the stand-in character that follows a \uN escape
    for match in _RTF_TOKEN.finditer(source):
        word, number, hexa, symbol, brace, text = match.groups()
        if brace == "{":
            depth += 1
        elif brace == "}":
            if skip_from is not None and depth <= skip_from:
                skip_from = None
            depth -= 1
        elif skip_from is not None:
            continue
        elif word:
            lowered = word.lower()
            if lowered in _RTF_SKIP and depth > 0:
                skip_from = depth
            elif lowered in ("par", "line", "sect", "row"):
                out.append("\n")
            elif lowered in ("tab", "cell"):
                out.append("\t")
            elif lowered == "u" and number:
                out.append(chr(int(number) % 65536))
                drop_next = True
        elif hexa:
            out.append(bytes([int(hexa, 16)]).decode("cp1252", "replace"))
        elif symbol:
            if symbol == "*" and depth > 0:
                skip_from = depth  # a destination this reader does not know: leave it out
            elif symbol in "\\{}":
                out.append(symbol)
        elif text:
            plain = text.replace("\r", "").replace("\n", "")
            if drop_next:
                plain, drop_next = plain[1:], False
            out.append(plain)
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


# ------------------------------------------------------------------------------------------- PDF


def _pdf(data: bytes) -> Extracted:
    # shortcut: no time limit around pypdf. Only an admin can upload, so a PDF built to stall it is
    # not a threat today; run it in a worker with a timeout if uploads ever come from elsewhere.
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):  # many "protected" files open like this
            raise refuse("password_protected")
        text = "\n\n".join(
            (page.extract_text() or "").strip() for page in reader.pages[:MAX_PDF_PAGES]
        )
    except ApiError:
        raise
    except Exception:  # noqa: BLE001  (a damaged PDF can fail in many ways, all of them "unreadable")
        raise refuse("unreadable_file") from None
    if not text.strip():
        raise refuse("scanned_pdf")  # pictures of pages: there is no OCR
    return Extracted(text, "pdf")


# ------------------------------------------------------------------- zip documents (OOXML, ODF)


def _xml(zf: zipfile.ZipFile, name: str) -> ElementTree.Element:
    if zf.getinfo(name).file_size > MAX_MEMBER_BYTES:
        raise refuse("file_too_large", 413, max_mb=MAX_BYTES // (1024 * 1024))
    raw = zf.read(name)
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise refuse("unreadable_file")  # no entity tricks
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise refuse("unreadable_file") from None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _csv_text(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def _zip_document(data: bytes, want: Want) -> Extracted:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise refuse("unreadable_file") from None
    with zf:
        names = zf.namelist()
        if len(names) > MAX_ZIP_MEMBERS:
            raise refuse("unreadable_file")
        if "word/document.xml" in names:
            return _docx(zf, want)
        if "xl/workbook.xml" in names:
            return Extracted(_xlsx(zf, names), "xlsx", tabular=True)
        if any(re.fullmatch(r"ppt/slides/slide\d+\.xml", n) for n in names):
            return Extracted(_pptx(zf, names), "pptx")
        if "content.xml" in names and "mimetype" in names:
            mimetype = zf.read("mimetype")[:100].decode("ascii", "ignore")
            for word, kind in (("spreadsheet", "ods"), ("presentation", "odp"), ("text", "odt")):
                if word in mimetype:
                    text = _ods(zf) if kind == "ods" else _odf_text(zf)
                    return Extracted(text, kind, tabular=kind == "ods")
    raise refuse("unsupported_type", 415)  # a zip, but not a document


# ---- Word


def _docx(zf: zipfile.ZipFile, want: Want) -> Extracted:
    root = _xml(zf, "word/document.xml")
    body = next((e for e in root if _local(e.tag) == "body"), root)

    def words(node: ElementTree.Element) -> str:
        parts: list[str] = []
        for e in node.iter():
            name = _local(e.tag)
            if name == "t" and e.text:
                parts.append(e.text)
            elif name == "tab":
                parts.append("\t")
            elif name in ("br", "cr"):
                parts.append("\n")
        return "".join(parts)

    tables: list[list[list[str]]] = []
    lines: list[str] = []
    for child in body:
        name = _local(child.tag)
        if name == "p":
            lines.append(words(child))
        elif name == "tbl":
            rows = [
                [words(cell).strip() for cell in row if _local(cell.tag) == "tc"]
                for row in child
                if _local(row.tag) == "tr"
            ]
            tables.append(rows)
            lines.extend("\t".join(r) for r in rows)
    if want == "table":
        if not tables:
            raise refuse("no_table_found")
        return Extracted(_csv_text(tables[0]), "docx", tabular=True)
    return Extracted("\n".join(lines), "docx")


# ---- Excel


def _column(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref.upper())
    index = 0
    for ch in letters.group(0) if letters else "A":
        index = index * 26 + ord(ch) - 64
    return index - 1


def _xlsx(zf: zipfile.ZipFile, names: list[str]) -> str:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in _xml(zf, "xl/sharedStrings.xml"):
            shared.append("".join(t.text or "" for t in item.iter() if _local(t.tag) == "t"))
    sheet = "xl/worksheets/sheet1.xml"
    if "xl/_rels/workbook.xml.rels" in names:  # the workbook's first sheet, whatever it is called
        rels = {r.get("Id"): r.get("Target") for r in _xml(zf, "xl/_rels/workbook.xml.rels")}
        listed = (s for s in _xml(zf, "xl/workbook.xml").iter() if _local(s.tag) == "sheet")
        first = next(listed, None)
        if first is not None:
            rid = next((v for k, v in first.attrib.items() if _local(k) == "id"), None)
            target = rels.get(rid)
            if target:
                sheet = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    if sheet not in names:
        raise refuse("unreadable_file")
    rows: list[list[str]] = []
    for row in _xml(zf, sheet).iter():
        if _local(row.tag) != "row":
            continue
        cells: list[str] = []
        for cell in row:
            if _local(cell.tag) != "c":
                continue
            at = min(_column(cell.get("r", "A")), MAX_COLUMNS)
            cells.extend([""] * (at - len(cells)))
            kind = cell.get("t")
            value = next((v.text or "" for v in cell if _local(v.tag) == "v"), "")
            if kind == "s" and value.isdigit() and int(value) < len(shared):
                value = shared[int(value)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter() if _local(t.tag) == "t")
            elif kind == "b":
                value = "TRUE" if value == "1" else "FALSE"
            cells.append(value)
        rows.append(cells)
        if len(rows) > MAX_ROWS:
            raise refuse("too_much_text", 413)
    return _csv_text(rows)


# ---- PowerPoint


def _pptx(zf: zipfile.ZipFile, names: list[str]) -> str:
    slides = sorted(
        (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)),
    )
    out: list[str] = []
    for name in slides:
        for para in _xml(zf, name).iter():
            if _local(para.tag) == "p":
                line = "".join(t.text or "" for t in para.iter() if _local(t.tag) == "t")
                if line.strip():
                    out.append(line)
    return "\n".join(out)


# ---- OpenDocument (text and presentation read as lines, a spreadsheet as rows)


def _odf_paragraph(node: ElementTree.Element) -> str:
    parts: list[str] = []

    def walk(element: ElementTree.Element) -> None:
        if element.text:
            parts.append(element.text)
        for child in element:
            name = _local(child.tag)
            if name == "tab":
                parts.append("\t")
            elif name == "line-break":
                parts.append("\n")
            elif name == "s":
                count = next((v for k, v in child.attrib.items() if k.endswith("}c")), "1")
                parts.append(" " * (int(count) if count.isdigit() else 1))
            else:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(node)
    return "".join(parts)


def _odf_cell(cell: ElementTree.Element) -> str:
    return "\n".join(_odf_paragraph(p) for p in cell if _local(p.tag) == "p")


def _odf_text(zf: zipfile.ZipFile) -> str:
    out: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        for child in node:
            name = _local(child.tag)
            if name in ("p", "h"):
                line = _odf_paragraph(child)
                if line.strip():
                    out.append(line)
            elif name == "table":  # a table is read row by row, cells with tabs between them
                for row in child.iter():
                    if _local(row.tag) == "table-row":
                        cells = [_odf_cell(c) for c in row if _local(c.tag) == "table-cell"]
                        if any(cells):
                            out.append("\t".join(cells))
            else:
                walk(child)

    walk(_xml(zf, "content.xml"))
    return "\n".join(out)


def _ods(zf: zipfile.ZipFile) -> str:
    sheet = next(
        (t for t in _xml(zf, "content.xml").iter() if _local(t.tag) == "table"), None
    )  # the first sheet
    rows: list[list[str]] = []
    for row in sheet.iter() if sheet is not None else []:
        if _local(row.tag) != "table-row":
            continue
        cells: list[str] = []
        for cell in row:
            if _local(cell.tag) != "table-cell":
                continue
            repeat = next(
                (int(v) for k, v in cell.attrib.items() if k.endswith("columns-repeated")), 1
            )
            cells.extend([_odf_cell(cell)] * min(repeat, MAX_COLUMNS))
            del cells[MAX_COLUMNS:]
        while cells and cells[-1] == "":
            cells.pop()  # the long run of empty cells a spreadsheet keeps at the end of a row
        if cells:
            rows.append(cells)
        if len(rows) > MAX_ROWS:
            raise refuse("too_much_text", 413)
    return _csv_text(rows)
