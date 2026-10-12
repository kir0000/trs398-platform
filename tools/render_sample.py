"""Render sample photon and electron protocols (PDF, and PNG when pypdfium2 is installed) for a visual check.

Runs inside the app container (WeasyPrint and the templates live there), data is synthetic:
    docker exec -i trs398_app python - < tools/render_sample.py
    (PowerShell has no '<': Get-Content tools/render_sample.py -Raw | docker exec -i trs398_app python -)
    docker cp trs398_app:/tmp/sample_photon.pdf .
"""
import datetime as dt
import math
from dataclasses import asdict
from decimal import Decimal as D

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app import protocol
from app.notation import sym, sym_plain
from core import electron as el
from core import photon as ph

# synthetic output history: 30 monthly points around nominal with a small drift
HISTORY = [(dt.date(2024, 1, 15) + dt.timedelta(days=30 * i), round(0.15 * math.sin(i) + 0.012 * i - 0.1, 3))
           for i in range(30)]
COMMON = dict(id=7, measured_on=dt.date(2026, 9, 19), geometry="SSD", humidity_pct=D(50), tmr_zref=None, note="образец",
              cal_k_elec=D(1), cal_lab="Лаборатория", calibrated_on=dt.date(2026, 2, 1), creator="Иванов И. И.",
              approver="Петров П. П.", approved_at=dt.datetime(2026, 9, 20, 10, 0), status="approved", linac="Аппарат 1",
              cal_q0="Co-60")


def photon():
    r = ph.calculate(ph.PhotonInput(chamber_id=26, nd_w=0.05138, mu=200, pressure_kpa=100.63, temp_c=23, v1=-300,
                                    v2=-100, m1=[24.36] * 3, m2=[24.21] * 3, tpr=0.62763, fff=True, pdd_zref=63.3,
                                    m_plus=[24.35] * 3, m_minus=[24.36] * 3))
    s = dict(COMMON, modality="photon", mu=D(200), pressure_kpa=D("100.63"), temp_c=D(23), v1=D(-300), v2=D(-100),
             m1_readings=[D("24.36")] * 3, m2_readings=[D("24.21")] * 3, m_plus_readings=[D("24.35")] * 3,
             m_minus_readings=[D("24.36")] * 3, beam_quality=D("0.62763"), pdd_zref=D("63.3"), nominal_energy=D(6),
             fff=True, chamber="Sun Nuclear SNC600c Farmer", serial_no="0001", nd_w=D("0.05138"), cal_voltage=D(-300),
             extra={"form": {"field_size": "10", "zmax": "1,2", "dose_rate": "600", "city": "Город, Страна", "cal_depth": "5",
                             "p0": "101,325", "t0": "22", "cal_rh": "50", "polarity_cal": "+−", "cal_pol_corrected": "1",
                             "polarity_user": "−", "electrometer_range": "Medium", "electrometer_model": "PTW UNIDOS E",
                             "electrometer_sn": "1234", "kelec_separate": "1", "kelec_lab": "ВНИИФТРИ", "kelec_date": "2026-02-10",
                             "m1_v1": "24,36 24,36 24,36", "m_user": "24,36 24,36 24,36"}})
    return s, asdict(r)


def electron():
    r = el.calculate(el.ElectronInput(chamber_id=1, nd_w=0.5791, mu=100, pressure_kpa=102.91, temp_c=21.9, v1=300,
                                      v2=100, m1=[1.883] * 4, m2=[1.887] * 4, m_plus=[1.883] * 4, m_minus=[1.888] * 4,
                                      r50_measured=3.755, pdd_zref=99.95))
    res = asdict(r)
    res["k_vol"] = 1.0                                   # stored as 1 for electrons
    s = dict(COMMON, modality="electron", mu=D(100), pressure_kpa=D("102.91"), temp_c=D("21.9"), v1=D(300), v2=D(100),
             m1_readings=[D("1.883")] * 4, m2_readings=[D("1.887")] * 4, m_plus_readings=[D("1.883")] * 4,
             m_minus_readings=[D("1.888")] * 4, beam_quality=D("3.755"), pdd_zref=D("99.95"), nominal_energy=D(15),
             fff=False, chamber="PTW 34001 Roos", serial_no="0002", nd_w=D("0.5791"), cal_voltage=D(300),
             extra={"r50w": r.r50w, "zref": r.zref, "form": {"q0_is_co60": "1", "field_size": "15х15"}})
    return s, res


env = Environment(loader=FileSystemLoader("/srv/app/templates"), autoescape=select_autoescape())
env.filters.update(sym=sym, sym_plain=sym_plain)
for name, make in (("photon", photon), ("electron", electron)):
    s, res = make()
    v = protocol.build(s, res, HISTORY)
    html = env.get_template("protocol.html").render(s=s, res=res, v=v, screen=False, status_labels={"approved": "утверждено"})
    path = f"/tmp/sample_{name}.pdf"
    HTML(string=html).write_pdf(path)
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        for i in range(len(pdf)):
            pdf[i].render(scale=1.4).to_pil().save(f"/tmp/sample_{name}_{i + 1}.png")
        print(name, "pages:", len(pdf))
    except ImportError:
        print(name, "written (install pypdfium2 and pillow for PNG)")
