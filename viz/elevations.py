"""
viz.elevations — each exposing building face as a 2D elevation.

Openings drawn to scale, storey bands as horizontal rules, and on the right of
each band a small bar: actual % unprotected openings against the permitted %
from Table 3.2.3.1.-D. Bar in blue when OK, red when over. Title carries the
limiting distance; the caption carries the wall requirements for the tightest
band. Draws the BandResults from codesheet.spatial, not its own logic.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from codesheet.model import BuildingModel
from codesheet.spatial import BandResult

INK, MUTED, RULE, WALL, GLASS = "#1f2328", "#6b7280", "#d9d8d1", "#ece9e1", "#ffffff"
OK, OVER, PERMIT = "#2a78d6", "#c8352b", "#b9c4d6"


def build_figure(b: BuildingModel, bands: dict[str, list[BandResult]]) -> go.Figure:
    faces = [f for f in b.exterior_faces if bands.get(f.label)]
    n = len(faces)
    cols = 2 if n > 1 else 1
    rows = (n + cols - 1) // cols
    titles = [f"{f.label} — LD {f.limiting_distance_m:g} m" for f in faces]
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles, horizontal_spacing=0.08, vertical_spacing=0.12)

    for k, f in enumerate(faces):
        r, c = k // cols + 1, k % cols + 1
        L = f.length_m(); z0, z1 = f.base_elevation_m, f.top_elevation_m
        gauge_x0 = L * 1.04; gauge_w = L * 0.22
        # wall
        fig.add_shape(type="rect", x0=0, x1=L, y0=z0, y1=z1, fillcolor=WALL, line=dict(color=INK, width=1.5), row=r, col=c)
        # openings
        for o in f.openings:
            if o.offset_m + o.width_m > L + 0.01:
                continue
            fig.add_shape(type="rect", x0=o.offset_m, x1=o.offset_m + o.width_m, y0=z0 + o.sill_m, y1=z0 + o.sill_m + o.height_m,
                          fillcolor=GLASS, line=dict(color=INK, width=0.6), row=r, col=c)
        # bands + gauges
        for br in bands[f.label]:
            fig.add_shape(type="line", x0=0, x1=L, y0=br.z0, y1=br.z0, line=dict(color=MUTED, width=1, dash="dot"), row=r, col=c)
            fig.add_annotation(x=-0.3, y=(br.z0 + br.z1) / 2, text=br.label, showarrow=False, xanchor="right", row=r, col=c,
                               font=dict(size=10, color=MUTED, family="IBM Plex Mono, monospace"))
            gy0, gy1 = br.z0 + 0.25, br.z1 - 0.25
            # permitted (track) and actual (fill), both as fraction of gauge width
            fig.add_shape(type="rect", x0=gauge_x0, x1=gauge_x0 + gauge_w * min(br.permitted_pct, 100) / 100, y0=gy0, y1=gy1,
                          fillcolor=PERMIT, line=dict(width=0), row=r, col=c)
            fig.add_shape(type="rect", x0=gauge_x0, x1=gauge_x0 + gauge_w * min(br.actual_pct, 100) / 100, y0=gy0 + (gy1 - gy0) * 0.3, y1=gy1 - (gy1 - gy0) * 0.3,
                          fillcolor=OK if br.ok else OVER, line=dict(width=0), row=r, col=c)
            fig.add_annotation(x=gauge_x0 + gauge_w + L * 0.02, y=(gy0 + gy1) / 2, xanchor="left", showarrow=False, row=r, col=c,
                               text=f"{br.actual_pct:g}% / {br.permitted_pct:g}%", font=dict(size=10, color=INK, family="IBM Plex Mono, monospace"))
        worst = min(bands[f.label], key=lambda x: x.permitted_pct - x.actual_pct)
        cap = (f"tightest band {worst.label}: {worst.actual_pct:g}% of {worst.permitted_pct:g}% permitted · "
               f"wall: FRR ≥ {worst.frr_min} min, {worst.cladding} cladding") if worst.frr_min else \
              f"100% permitted at this limiting distance — no exposing-face requirement"
        fig.add_annotation(x=0, y=z0 - 0.4, xanchor="left", yanchor="top", showarrow=False, row=r, col=c, text=cap,
                           font=dict(size=10.5, color=INK))
        fig.update_xaxes(range=[-L * 0.08, L * 1.5], visible=False, row=r, col=c)
        fig.update_yaxes(range=[z0 - 2.4, z1 + 0.6], showgrid=False, zeroline=False, tickfont=dict(size=10, family="IBM Plex Mono, monospace"),
                         scaleanchor=None, row=r, col=c)

    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10),
                      font=dict(color=INK, family="IBM Plex Sans, system-ui, sans-serif"), showlegend=False, height=380 * rows)
    for a in fig.layout.annotations[:n]:
        a.font = dict(size=13, color=INK)
    return fig


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    from codesheet.spatial import analyze
    _, bands = analyze(project)
    fig = build_figure(project, bands)
    fig.write_html(root / "out" / "example_elevations.html", include_plotlyjs=True, full_html=True)
    print("wrote")
