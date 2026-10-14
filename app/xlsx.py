"""A small writer of .xlsx files (no dependencies): several sheets, text, numbers, dates, a bold header row, widths of the columns.

    data = write([("Данные", [["Дата", "Значение"], [date(2026, 1, 15), 0.12]]), ("Сводка", [[...]])])

Excel and LibreOffice open the result; the cells are plain values (no formulas).
"""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
EPOCH = dt.date(1899, 12, 30)

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{sheets}</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""
# cell formats: 0 normal, 1 bold header, 2 date dd.mm.yyyy, 3 number 0.000, 4 bold header with wrapping
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="2"><numFmt numFmtId="164" formatCode="dd\\.mm\\.yyyy"/><numFmt numFmtId="165" formatCode="0.000"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF7"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>"""


def column(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_name(name: str, used: set[str]) -> str:
    clean = _BAD_SHEET.sub(" ", str(name)).strip("' ")[:31] or "Лист"
    base, i = clean, 2
    while clean.lower() in used:
        clean = f"{base[:28]} {i}"
        i += 1
    used.add(clean.lower())
    return clean


def cell(ref: str, value, header: bool = False) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, dt.datetime):
        serial = (value.replace(tzinfo=None) - dt.datetime(1899, 12, 30)).total_seconds() / 86400
        return f'<c r="{ref}" s="2"><v>{serial:.8f}</v></c>'
    if isinstance(value, dt.date):
        return f'<c r="{ref}" s="2"><v>{(value - EPOCH).days}</v></c>'
    if isinstance(value, (int, float, Decimal)) and not header:
        v = float(value)
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return f'<c r="{ref}"><v>{repr(v) if isinstance(value, float) else value}</v></c>'
    text = _ILLEGAL.sub("", str(value))
    style = ' s="1"' if header else ""
    return f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def sheet_xml(rows: list[list], header_rows: int = 1) -> str:
    widths: dict[int, int] = {}
    body = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row):
            cells.append(cell(f"{column(c)}{r}", value, header=r <= header_rows))
            size = len(str(value)) if value is not None and not isinstance(value, (dt.date, dt.datetime)) else 10
            widths[c] = max(widths.get(c, 0), min(size, 60))
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{max(8, w + 2)}" customWidth="1"/>' for c, w in sorted(widths.items()))
    pane = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="%d" topLeftCell="A%d" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            % (header_rows, header_rows + 1)) if header_rows and len(rows) > header_rows else ""
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    if not widths:
        return head + "<sheetData/></worksheet>"
    return f"{head}{pane}<cols>{cols}</cols><sheetData>{''.join(body)}</sheetData></worksheet>"


def write(sheets: list[tuple[str, list[list]]]) -> bytes:
    """The bytes of a workbook; `sheets` is [(name, rows)], the first row of every sheet is the header."""
    used: set[str] = set()
    names = [sheet_name(n, used) for n, _ in sheets]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES.format(sheets="".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1))))
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", STYLES)
        for i, (_, rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows))
    return out.getvalue()
