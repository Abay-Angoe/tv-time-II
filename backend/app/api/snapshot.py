"""Render a universe as a self-contained, shareable HTML page (inline SVG star-map).

No external requests (posters live on TMDB and can't be embedded offline), so this is
a stylised dot-map: nodes coloured by phase, sized by rewatches, cluster labels at
their centroids, plus the strongest connections as faint lines. Fully self-contained —
the user can save it or send the file to anyone.
"""

from __future__ import annotations

import html
import sqlite3

from ..db import loads

# Okabe-Ito palette (matches the frontend colors.ts).
_PALETTE = ["#56B4E9", "#E69F00", "#009E73", "#F0E442", "#0072B2", "#D55E00",
            "#CC79A7", "#94D4C0", "#B7A0D0", "#E4A0A0", "#8FB339", "#7FBEEB"]
_W = 1100
_M = 60


def _color(cid) -> str:
    if cid is None:
        return "#6b7280"
    return _PALETTE[cid % len(_PALETTE)]


def build_snapshot_html(conn: sqlite3.Connection, media_type: str) -> str:
    nodes = conn.execute(
        """SELECT id, title, projection_x, projection_y, cluster_id, rewatch_count
           FROM films WHERE media_type = ? AND projection_x IS NOT NULL""",
        (media_type,),
    ).fetchall()
    if not nodes:
        return "<h1>Nothing to show yet — run the pipeline first.</h1>"

    def px(x: float) -> float: return _M + (x / 100.0) * (_W - 2 * _M)

    # strongest edges for a light constellation
    edges = conn.execute(
        """SELECT e.film_a, e.film_b, e.weight FROM edges e
           JOIN films f ON f.id = e.film_a WHERE f.media_type = ? AND e.weight >= 0.5""",
        (media_type,),
    ).fetchall()
    pos = {n["id"]: (px(n["projection_x"]), px(n["projection_y"])) for n in nodes}

    parts: list[str] = []
    for e in edges:
        if e["film_a"] in pos and e["film_b"] in pos:
            x1, y1 = pos[e["film_a"]]; x2, y2 = pos[e["film_b"]]
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'stroke="#ffffff" stroke-opacity="0.06" stroke-width="0.8"/>')
    for n in nodes:
        x, y = pos[n["id"]]
        r = 3 + min(n["rewatch_count"] or 0, 6) * 1.2
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                     f'fill="{_color(n["cluster_id"])}" fill-opacity="0.9"/>')

    # cluster island labels at centroids
    clusters = conn.execute(
        """SELECT c.id, c.label, c.user_label,
                  AVG(f.projection_x) x, AVG(f.projection_y) y, COUNT(*) n
           FROM clusters c JOIN films f ON f.cluster_id = c.id
           WHERE c.media_type = ? GROUP BY c.id""",
        (media_type,),
    ).fetchall()
    for c in clusters:
        label = c["user_label"] or c["label"]
        if not label or c["n"] < 4:
            continue
        parts.append(
            f'<text x="{px(c["x"]):.1f}" y="{px(c["y"]):.1f}" fill="#ffffff" '
            f'fill-opacity="0.55" font-size="13" font-weight="600" text-anchor="middle">'
            f'{html.escape(label.upper())}</text>')

    total = len(nodes)
    phases = sum(1 for c in clusters if (c["user_label"] or c["label"]))
    title = "My TV Universe" if media_type == "tv" else "My Cinema Universe"
    noun = "shows" if media_type == "tv" else "films"
    svg = (f'<svg viewBox="0 0 {_W} {_W}" width="100%" xmlns="http://www.w3.org/2000/svg">'
           + "".join(parts) + "</svg>")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin:0; background:#0b0d12; color:#e6e7ec;
         font-family:Inter,system-ui,-apple-system,sans-serif; text-align:center; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:28px 16px 48px; }}
  h1 {{ margin:0 0 4px; font-size:1.6rem; letter-spacing:0.5px; }}
  .sub {{ color:#9aa1ad; font-size:0.9rem; margin-bottom:14px; }}
  svg {{ background:radial-gradient(circle at 50% 40%, #111725, #0b0d12 70%); border-radius:16px; }}
  .foot {{ color:#6b7280; font-size:0.78rem; margin-top:16px; }}
</style></head>
<body><div class="wrap">
  <h1>◎ {title}</h1>
  <div class="sub">{total} {noun} · {phases} phases · screen distance = thematic similarity</div>
  {svg}
  <div class="foot">Personal Cinema Universe Explorer · dot size = rewatches</div>
</div></body></html>"""
