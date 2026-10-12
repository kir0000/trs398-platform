"""What may be typed into the cells: kind, hard limits (the server rejects), typical range (a soft warning only), length, examples.

One table serves the page (HTML attributes read by the script in base.html) and the server (the same limits are checked
again, so a request that does not come from the page is held to them as well).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Field:
    label: str
    kind: str = "num"                 # num, series (numbers separated by spaces), text
    lo: Optional[float] = None        # hard limits of a number
    hi: Optional[float] = None
    tlo: Optional[float] = None       # typical range: outside it a warning is shown, the value is still accepted
    thi: Optional[float] = None
    unit: str = ""
    maxlen: int = 0                   # text
    pattern: str = ""                 # text: allowed form (regular expression, whole value)
    examples: tuple = ()              # text: suggestions (datalist)
    hint: str = ""                    # what to write


F = Field
FIELDS: dict[str, Field] = {
    # ---- linac
    "name": F("Название аппарата", "text", maxlen=60),
    "model": F("Модель", "text", maxlen=60, hint="например, Varian TrueBeam"),
    "serial_no": F("Серийный №", "text", maxlen=40, pattern=r"[\w\-./ ]*", hint="буквы, цифры, дефис, точка, косая черта"),
    "city": F("Город, страна", "text", maxlen=80),
    "site": F("Отделение", "text", maxlen=80),
    # ---- beam (Equipment)
    "dose_rate": F("Мощность дозы", lo=10, hi=10000, tlo=100, thi=2500, unit="MU/мин", hint="обычно 100–2500"),
    "field_size": F("Размер поля / аппликатор", "text", maxlen=20, pattern=r"\s*\d{1,2}([.,]\d)?\s*[x\u0445\u00d7]\s*\d{1,2}([.,]\d)?\s*(\u0441\u043c)?\s*",
                    examples=("10 x 10", "15 x 15", "6 x 6", "20 x 20", "25 x 25"), hint="ширина × длина, см: 10 x 10"),
    "phantom": F("Фантом", "text", maxlen=30, examples=("водный", "RW3", "Solid Water", "ПММА", "полистирол")),
    "ref_depth": F("Референсная глубина", lo=0.5, hi=20, tlo=1, thi=10.5, unit="г/см²", hint="фотоны обычно 10; электроны 0,6·R50 − 0,1"),
    "zmax": F("zmax", lo=0.2, hi=6, tlo=0.5, thi=3.5, unit="г/см²", hint="глубина максимума дозы"),
    "pdd_zref": F("PDD(zref)", lo=30, hi=100, tlo=55, thi=100, unit="%", hint="при SSD 100 см; фотоны на 10 г/см² обычно 60–85 %"),
    "tmr_zref": F("TMR(zref)", lo=0.3, hi=1.2, tlo=0.5, thi=0.95, hint="для поля 10 × 10"),
    "cal_mu": F("MU при калибровке", lo=1, hi=10000, tlo=50, thi=1000, unit="MU"),
    "exp_cgy_mu": F("Ожидаемая доза в опорной точке", lo=0.2, hi=3, tlo=0.4, thi=1.1, unit="сГр/MU",
                    hint="доза на 1 MU в опорной точке по системе планирования, около 0,6–0,7 на глубине 10 см"),
    "exp_zref": F("Глубина опорной точки", lo=0.5, hi=20, tlo=3, thi=10.5, unit="г/см²"),
    "exp_source": F("Источник", "text", maxlen=120, hint="система планирования, версия, условия"),
    "window_material": F("Материал окна", "text", maxlen=30, examples=("ПММА", "полистирол", "акрил", "RW3")),
    "window_thickness": F("Толщина окна", lo=0, hi=5, tlo=0.05, thi=1.5, unit="г/см²"),
    "c_pl": F("cpl", lo=0.5, hi=1.5, tlo=0.9, thi=1.1),
    "h_pl": F("hpl", lo=0.5, hi=1.5, tlo=0.9, thi=1.1),
    # ---- calibration (Equipment)
    "nd_w": F("ND,w", lo=0.005, hi=1.5, unit="Гр/нКл", hint="камеры Farmer около 0,05, плоскопараллельные около 0,5"),
    "k_elec": F("kelec", lo=0.5, hi=1.5, tlo=0.97, thi=1.03),
    "r50_q0": F("R50 калибровочного пучка", lo=0.5, hi=12, unit="г/см²"),
    "cal_depth": F("Калибровочная глубина", lo=0.5, hi=20, tlo=2, thi=10.5, unit="г/см²"),
    "p0": F("P0", lo=80, hi=110, tlo=98, thi=103, unit="кПа", hint="обычно 101,325"),
    "t0": F("T0", lo=10, hi=35, tlo=19, thi=23, unit="°C", hint="20 или 22"),
    "cal_rh": F("Влажность при калибровке", lo=0, hi=100, tlo=20, thi=80, unit="%"),
    "voltage_v": F("V1 при калибровке", lo=-1500, hi=1500, unit="В", hint="например, −300"),
    "lab": F("Лаборатория", "text", maxlen=60),
    "el_model": F("Модель электрометра", "text", maxlen=60),
    "el_sn": F("Серийный № электрометра", "text", maxlen=40, pattern=r"[\w\-./ ]*"),
    "el_range": F("Диапазон электрометра", "text", maxlen=20, examples=("Low", "Medium", "High")),
    "kelec_lab": F("Лаборатория калибровки электрометра", "text", maxlen=60),
    # ---- measurement sheet
    "pressure": F("P", lo=80, hi=110, tlo=95, thi=105, unit="кПа"),
    "temp": F("T", lo=10, hi=35, tlo=18, thi=26, unit="°C"),
    "humidity": F("Влажность", lo=0, hi=100, tlo=20, thi=80, unit="%", hint="по TRS-398 в диапазоне 20–80 % поправки нет"),
    "mu": F("MU", lo=1, hi=100000, unit="MU"),
    "v1": F("V1", lo=-1500, hi=1500, unit="В"),
    "v2": F("V2", lo=-1500, hi=1500, unit="В"),
    "tpr": F("TPR20,10", lo=0.3, hi=0.95, tlo=0.55, thi=0.8),
    "pdd10": F("PDD(10)", lo=30, hi=100, tlo=55, thi=85, unit="%"),
    "pdd20": F("PDD(20)", lo=10, hi=100, tlo=30, thi=60, unit="%"),
    "r50": F("R50", lo=0.5, hi=12, tlo=1.5, thi=9, unit="г/см²"),
    "zref": F("zref", lo=1, hi=20, tlo=2, thi=10.5, unit="г/см²"),
    "m1": F("Показания", "series"), "m2": F("Показания", "series"), "m_plus": F("Показания", "series"),
    "m_minus": F("Показания", "series"), "m1_v1": F("Показания", "series"),
}


def attrs(name: str) -> str:
    """HTML attributes for the cell `name`; the script of base.html reads them (empty for a name without a rule)."""
    f = FIELDS.get(name)
    if not f:
        return ""
    e = html.escape
    out = [f'data-kind="{f.kind}"', f'data-label="{e(f.label)}"']
    if f.kind == "num":
        out += ['inputmode="decimal"', 'autocomplete="off"']
        for key, val in (("lo", f.lo), ("hi", f.hi), ("tlo", f.tlo), ("thi", f.thi)):
            if val is not None:
                out.append(f'data-{key}="{val:g}"')
    elif f.kind == "series":
        out += ['inputmode="decimal"', 'autocomplete="off"']
    else:
        out.append('autocomplete="off"')
        if f.maxlen:
            out.append(f'maxlength="{f.maxlen}"')
        if f.pattern:
            out.append(f'pattern="{e(f.pattern, quote=True)}"')
        if f.examples:
            out.append(f'list="dl-{name}"')
    if f.unit:
        out.append(f'data-unit="{e(f.unit)}"')
    if f.hint:
        out.append(f'title="{e(f.hint)}"')
    return " " + " ".join(out)


def datalists() -> str:
    """The suggestion lists of all text cells with examples."""
    return "".join(f'<datalist id="dl-{n}">' + "".join(f'<option value="{html.escape(x)}">' for x in f.examples) + "</datalist>"
                   for n, f in FIELDS.items() if f.kind == "text" and f.examples)


def check_text(name: str, raw) -> Optional[str]:
    """A text value of the form, trimmed; None when empty. Raises ValueError with a message when it breaks the rule."""
    f = FIELDS[name]
    text = (raw or "").strip()
    if not text:
        return None
    if f.maxlen and len(text) > f.maxlen:
        raise ValueError(f"«{f.label}»: не длиннее {f.maxlen} знаков")
    if f.pattern and not re.fullmatch(f.pattern, text):
        raise ValueError(f"«{f.label}»: недопустимые знаки" + (f" ({f.hint})" if f.hint else ""))
    if any(ord(c) < 32 for c in text):
        raise ValueError(f"«{f.label}»: недопустимые знаки")
    return text


def limits(name: str) -> tuple[Optional[float], Optional[float]]:
    f = FIELDS[name]
    return f.lo, f.hi
