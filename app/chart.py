"""Server-side SVG control chart (no JavaScript, works offline and prints cleanly)."""
from __future__ import annotations

from html import escape

from core.spc import SpcSummary

W, H = 900, 340
ML, MR_, MT, MB = 56, 16, 14, 34


def control_chart(s: SpcSummary) -> str:
    pts = s.points
    if not pts:
        return ""
    xs = [p.on.toordinal() for p in pts]
    ys = [p.deviation_pct for p in pts]
    lines = []
    if s.cl is not None and s.sigma:
        lines = [("CL", s.cl, "#555", ""), ("+2σ", s.cl + 2 * s.sigma, "#b07000", "4 3"),
                 ("−2σ", s.cl - 2 * s.sigma, "#b07000", "4 3"), ("+3σ", s.cl + 3 * s.sigma, "#b00020", "6 3"),
                 ("−3σ", s.cl - 3 * s.sigma, "#b00020", "6 3")]
    lo = min(ys + [v for _, v, _, _ in lines])
    hi = max(ys + [v for _, v, _, _ in lines])
    pad = (hi - lo) * 0.08 or 0.1
    lo, hi = lo - pad, hi + pad
    x0, x1 = min(xs), max(xs)
    span = (x1 - x0) or 1

    def X(v):
        return ML + (v - x0) / span * (W - ML - MR_)

    def Y(v):
        return MT + (hi - v) / (hi - lo) * (H - MT - MB)

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Контрольная карта отклонения выхода">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        out.append(f'<line x1="{ML}" x2="{W - MR_}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#ddd"/>'
                   f'<text x="{ML - 6}" y="{Y(v) + 4:.1f}" font-size="11" text-anchor="end" fill="#555">{v:.2f}</text>')
    for name, v, color, dash in lines:
        out.append(f'<line x1="{ML}" x2="{W - MR_}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{color}" '
                   f'stroke-dasharray="{dash}"/><text x="{W - MR_ - 2}" y="{Y(v) - 3:.1f}" font-size="10" '
                   f'text-anchor="end" fill="{color}">{name}</text>')
    path = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(xs, ys))
    out.append(f'<polyline points="{path}" fill="none" stroke="#2a5db0" stroke-width="1.4"/>')
    for p, a, b in zip(pts, xs, ys):
        color = "#b00020" if p.signal == "за 3σ" else "#b07000" if p.signal else "#2a5db0"
        r = 4.5 if p.signal else 2.8
        tip = f"{p.on:%d.%m.%Y}: {b:+.3f} %" + (f" ({p.signal})" if p.signal else "")
        out.append(f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="{r}" fill="{color}"><title>{escape(tip)}</title></circle>')
    for k in range(5):
        d = x0 + span * k / 4
        from datetime import date
        out.append(f'<text x="{X(d):.1f}" y="{H - 10}" font-size="11" text-anchor="middle" fill="#555">'
                   f'{date.fromordinal(int(d)):%m.%Y}</text>')
    out.append(f'<text x="14" y="{(H - MB) / 2:.0f}" font-size="11" fill="#555" '
               f'transform="rotate(-90 14 {(H - MB) / 2:.0f})" text-anchor="middle">отклонение, %</text></svg>')
    return "".join(out)
