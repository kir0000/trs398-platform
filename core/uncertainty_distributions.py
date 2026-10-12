"""Probability distributions of the Type B components and the formulas that turn the source data into a standard uncertainty.

Sources: JCGM 100 (GUM) 4.3; IAEA TRS-398 Rev.1 Tables 17, 24, 25; McDermott PN, J Appl Clin Med Phys 25 (2024) e14339,
doi:10.1002/acm2.14339 (Monte Carlo propagation: uniform inputs sigma = (x+ - x-) / (2 sqrt(3)), normal inputs the 1 sigma
value of the cited source or half of a k = 2 value).

The standard components of the budget (by their code) get a distribution and a "how it is determined" text; user-added lines
carry their own. The texts hold for every energy: sensitivities are given as a rule (derivative of the dose with respect to the
quantity), not as numbers of 6 MV / 6 MeV only.
"""
from __future__ import annotations

from math import sqrt

# key -> (name, formula of the standard uncertainty u from the half-width a, sigma or expanded U)
DISTRIBUTIONS: dict[str, tuple[str, str]] = {
    "normal": ("нормальное", "u = σ;  u = U / k  (k = 2 для 95 %)"),
    "uniform": ("прямоугольное", "u = a / √3"),
    "triangular": ("треугольное", "u = a / √6"),
    "ushaped": ("U-образное", "u = a / √2"),
}

# how the value of a quantity is turned into u: used in the reference card of the page
FORMULAS: list[tuple[str, str, str]] = [
    ("Нормальное", "в свидетельстве указана расширенная неопределённость U с коэффициентом охвата k; известно СКО",
     "u = U / k  (k = 2: u = U / 2);  u = σ"),
    ("Прямоугольное", "известны только границы ±a (допуск, класс точности прибора, цена деления), значения внутри равновероятны",
     "u = a / √3"),
    ("Треугольное", "значения вблизи середины интервала ±a вероятнее, чем у краёв",
     "u = a / √6"),
    ("U-образное", "значение чаще у границ ±a (периодические колебания)", "u = a / √2"),
    ("Тип A: повторные измерения", "n показаний одной серии", "u = s / √n,  s = √(Σ(xᵢ − x̄)² / (n − 1))"),
    ("Тип A: журнал выхода", "ряд отклонений выхода, индивидуальная карта (I-MR)", "σ = MR̄ / 1,128  (MR̄ — средний размах двух соседних значений)"),
    ("Чувствительность", "влияние величины x на дозу D: относительная неопределённость дозы",
     "uᵢ = cᵢ · u(x),  cᵢ = (∂D/∂x) · x / D  или  cᵢ = d ln D / dx  (в %/ед. x)"),
    ("Суммирование", "независимые составляющие", "u_c = √(Σ uᵢ²),  U = k · u_c  (k = 2)"),
]

SENSITIVITY_RULES = {
    "depth": "чувствительность к глубине: фотоны — c = d ln PDD/dz = −(μ_eff + 2/(SSD + z)), для вашего пучка из PDD(z) на двух соседних глубинах "
             "c ≈ ln[PDD(z)/PDD(z+1 см)] (%/см), убывает с ростом энергии; электроны — c зависит от энергии и положения на спаде дозы (≈0,8 % на 1 мм при 6 МэВ, примерно вдвое меньше при 18 МэВ, McDermott 2024)",
    "ssd": "чувствительность к SSD: c = 2 / (SSD + z) (≈1,8 %/см при SSD 100 см, z = 10 см, от энергии почти не зависит)",
    "fieldsize": "чувствительность к размеру поля: c = d ln D/ds по выходному фактору (мало вблизи 10×10 см)",
}


def standard_uncertainty(dist: str, value: float, k: float = 2.0) -> float:
    """u of one input: `value` is the half-width a (uniform, triangular, U-shaped), the sigma (normal, k = 1)
    or the expanded uncertainty U (normal, with the coverage factor k > 1)."""
    if dist == "uniform":
        return value / sqrt(3)
    if dist == "triangular":
        return value / sqrt(6)
    if dist == "ushaped":
        return value / sqrt(2)
    if dist == "normal":
        return value / k if k and k > 0 else value
    raise ValueError(f"unknown distribution {dist!r}")


# standard components of the budget (by code): (distribution key, how it is determined)
STANDARD: dict[str, tuple[str, str]] = {
    "s1_cal_secondary": ("normal", "u = U / k по свидетельству лаборатории (k = 2): U = 2,5 % → u = 1,25 %. Эта строка уже включает неопределённость самого свидетельства."),
    "s1_stab_secondary": ("uniform", "u = a / √3, a — наибольшее изменение коэффициента вторичного эталона между поверками по свидетельствам. 0, если в U свидетельства это уже учтено."),
    "s1_cal_user": ("normal", "u = U / k по свидетельству (k = 2) для дозиметра пользователя. 0, если U свидетельства относится к коэффициенту камеры целиком."),
    "s1_cal_user_psdl": ("normal", "u = U / k по свидетельству ДЛПЭ (k = 2)."),
    "s2_stab_user": ("normal", "Тип A: u = s, СКО отношения показаний камеры к контрольному источнику (или по журналу). Либо a / √3 по наибольшему дрейфу за межповерочный интервал. McDermott 2024: 0,4 % (фотоны), 0,3 % (электроны), нормальное."),
    "s2_conditions": ("uniform", "u = √Σ(cᵢ · aᵢ / √3)²: глубина камеры (±1 мм), SSD (±2 мм), размер поля (±2 мм); cᵢ — чувствительность дозы к параметру (правила ниже). McDermott 2024 для 6 MV / 6 МэВ: глубина 0,30 / 0,47 %, SSD 0,21 / 0,23 %, поле 0,10 %."),
    "s2_reading": ("normal", "Тип A: u = s / √n, СКО среднего серии показаний M, включая повторяемость выхода; McDermott 2024: 0,075 %. Нестабильность монитора ускорителя входит сюда же."),
    "s2_influence": ("uniform", "u = √(u²_kTP + u²_kpol + u²_ks + u²_kelec): давление ±8 мбар → 0,46 % (a / √3), температура ±0,4 °C → 0,23 °C, влажность ±0,15 % → 0,087 % (прямоугольные); kpol, ks — нормальные (повторяемость серий); kelec — U / k по свидетельству электрометра."),
    "s2_kq": ("normal", "Расчётное kQ (TRS-398): u из таблицы, k = 1. Фотоны: внутренняя неопределённость расчётного kQ ≈ 0,4 % (0,45 % при 18 MV) плюс аппроксимация kQ(TPR20,10) 0,07 %; McDermott 2024."),
    "s2_applic": ("uniform", "u = a / √3, a — допуск на различие конкретной камеры и камер, по которым рассчитан kQ."),
}

# electrons use another text of kQ (R50 / I50 chain)
STANDARD_ELECTRON_KQ = ("normal", "Табл. 24/25: u (k = 1) по типу камеры и R50. Цепочка McDermott 2024: k_ecal 0,5 % (нормальное), k′R50 ±0,2 % (прямоугольное → 0,12 %), "
                                  "R50 по I50: I50 ±0,15 см (прямоугольное → 0,087 см), формула R50 ±0,04 см (прямоугольное → 0,023 см).")

TYPE_A = ("normal", "σ = MR̄ / 1,128 по журналу выхода (I-MR); число записей n. Для малого n расширенную неопределённость считают с k по t-распределению, а не 2.")


def decorate(budget, electron: bool = False):
    """Attach distribution and formula to the standard components of a budget."""
    for c in budget.stage1 + budget.stage2:
        if c.code in STANDARD:
            c.dist, c.how = STANDARD[c.code]
    if electron:
        for c in budget.stage2:
            if c.code == "s2_kq":
                c.dist, c.how = STANDARD_ELECTRON_KQ
    return budget
