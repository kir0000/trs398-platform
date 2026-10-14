"""Export of the comparison of the energies of one linac: the table of the states, the monthly means of every beam, the correlations,
the hints. The same numbers as on the page "Energy comparison", not rounded to the screen."""
from __future__ import annotations

from datetime import date

from core import compare, spc

STATUS_HEAD = ["Тип", "Пучок", "Записей", "Последняя", "Откл., %", "Среднее, %", "σ, %", "Тренд, %/мес", "Прогноз выхода за допуск", "Статус",
               "За 3σ", "Другие правила", "CUSUM", "Вне допуска", "Последний сигнал"]


def status_rows(summaries: list[dict]) -> list[list]:
    """The table "state of every energy"; the type is γ or e⁻ and the beam is the rest of the label, as on the page."""
    rows = [STATUS_HEAD]
    for r in summaries:
        kind, _, beam = r["label"].partition(" ")
        rows.append([kind, beam, r["n"], r["last_date"], r["last"], r["mean"], r["sigma"], r["trend"], r["forecast"], str(r["status"]).split(":")[0],
                     r["n_3sigma"] or "", r["n_rules"] or "", r["n_cusum"] or "", r["out_of_tolerance"] or "", r["last_signal"]])
    return rows


def parameter_rows(linac: str, modality: str, period: str, user: str, today: date) -> list[list]:
    return [["Параметр", "Значение"], ["Аппарат", linac], ["Тип пучков", modality], ["Период", period],
            ["Предел наблюдения, %", spc.OBSERVE_PCT], ["Допуск (действие), %", spc.ACTION_PCT],
            ["Сдвиг пучка в месяце от, %", compare.SHIFT_PCT], ["Общий сдвиг: не менее пучков", compare.MIN_BEAMS],
            ["Общий сдвиг: доля пучков в одну сторону", compare.SHARE], ["Выгружено", today], ["Пользователь", user]]


def month_rows(data: dict) -> list[list]:
    """Months in rows, the beams in columns (the mean deviation of the month), then what the energies did together."""
    labels = list(data["matrix"])
    rows = [["Месяц"] + labels + ["Среднее по энергиям, %", "Разброс, %", "Вверх", "Вниз", "Общий сдвиг"]]
    by_month = {c.month: c for c in data["common"]}
    for i, month in enumerate(data["months"]):
        c = by_month.get(month)
        rows.append([month] + [data["matrix"][label][i] for label in labels]
                    + ([c.mean, c.spread, c.up, c.down, c.direction or ""] if c else [None, None, None, None, ""]))
    return rows


def correlation_rows(data: dict) -> list[list]:
    labels = data["corr_labels"]
    return [["Корреляция"] + labels] + [[labels[i]] + list(row) for i, row in enumerate(data["corr"])]


def hint_rows(data: dict) -> list[list]:
    return [["Подсказки (решение за физиком)"]] + [[h] for h in data["hints"]]
