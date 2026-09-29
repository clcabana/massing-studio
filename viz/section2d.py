"""
viz.section2d — the height-and-grade determination as a drawing.

One panel per block, a schematic section: storeys as bars stacked on their real
elevations (width ∝ footprint area so podiums and setbacks read), the grade
line, the shaded 2 m first-storey test band, the first storey outlined, and a
running count on the storeys that make up building height. Basements are
hatched grey so it is obvious they exist but don't count.

This draws the DETERMINATIONS from codesheet.height_area, not its own logic.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from codesheet.model import BuildingModel
from codesheet.determinations import Determination
from codesheet.height_area import analyze

INK, MUTED, RULE = "#1f2328", "#6b7280", "#d9d8d1"
COUNTED, BASEMENT, ROOF = "#2a78d6", "#9aa0a6", "#d9dde3"
GRADE_C, BAND_C = "#5b7a3a", "rgba(91,122,58,0.12)"
FIRST_C = "#c8352b"


def build_figure(b: BuildingModel, dets: list[Determination] | None = None) -> go.Figure:
    dets = dets or analyze(b)
    D = {d.key: d for d in dets}
    blocks = b.blocks()
    fig = make_subplots(rows=1, cols=len(blocks), shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=[f"{blk} Block" for blk in blocks])
    g = b.site.grade_elevation_m
    ymin = min(s.elevation_m for s in b.storeys) - 1.5
    ymax = max(s.elevation_m + s.height_m for s in b.storeys) + 2.5

    for col, blk in enumerate(blocks, start=1):
        fs = D[f"{blk}.first_storey"].value
        counted = D[f"{blk}.building_height_storeys"].inputs["counted"]
        maxA = max((s.footprint.area() if s.footprint else b.footprint.area()) for s in b.storeys_sorted(blk))
        n = 0
        for s in b.storeys_sorted(blk):
            A = s.footprint.area() if s.footprint else b.footprint.area()
            w = 0.25 + 0.75 * (A / maxA)          # bar half-width, normalised
            x0, x1 = -w, w
            if s.is_part_of:                        # detached piece drawn to the side
                x0, x1 = 1.1, 1.1 + 0.6 * (A / maxA)
            z0, z1 = s.elevation_m, s.elevation_m + s.height_m
            if s.is_roof:
                colour, txt = ROOF, ""
            elif s.label in counted and not s.is_part_of:
                n += 1; colour, txt = COUNTED, f"{s.label}  ·  storey {n}"
            elif s.is_part_of:
                colour, txt = COUNTED, ""          # detached piece: no label, hover would be noise
            else:
                colour, txt = BASEMENT, f"{s.label}  ·  basement"
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=z0, y1=z1 - 0.06, row=1, col=col,
                          fillcolor=colour, opacity=0.9 if colour != BASEMENT else 0.55,
                          line=dict(color=FIRST_C if s.label == fs and not s.is_part_of else INK,
                                    width=3 if s.label == fs and not s.is_part_of else 1))
            if txt:
                fig.add_annotation(x=(x0 + x1) / 2, y=(z0 + z1) / 2, text=txt, showarrow=False, row=1, col=col,
                                   font=dict(size=11, color="#ffffff" if colour == COUNTED else INK))
            fig.add_annotation(x=-1.02, y=z0, text=f"{z0:.2f}", showarrow=False, xanchor="right", row=1, col=col,
                               font=dict(size=10, color=MUTED, family="IBM Plex Mono, monospace"))
        # grade line + 2 m band
        fig.add_shape(type="rect", x0=-1.05, x1=1.8, y0=g, y1=g + 2.0, row=1, col=col, fillcolor=BAND_C, line=dict(width=0), layer="below")
        fig.add_shape(type="line", x0=-1.05, x1=1.8, y0=g, y1=g, row=1, col=col, line=dict(color=GRADE_C, width=2.5))
        fig.add_annotation(x=1.78, y=g, text=f"grade {g:.2f} m", showarrow=False, xanchor="right", yanchor="top",
                           row=1, col=col, font=dict(size=11, color=GRADE_C))
        fig.add_annotation(x=1.78, y=g + 2.0, text="+2.0 m — first-storey test", showarrow=False, xanchor="right", yanchor="bottom",
                           row=1, col=col, font=dict(size=10, color=GRADE_C))
        # verdict
        hs = D[f"{blk}.building_height_storeys"]; ba = D[f"{blk}.building_area_m2"]; hm = D[f"{blk}.height_to_top_floor_m"]
        fig.add_annotation(x=0.35, y=ymax - 0.3, xanchor="center", yanchor="top", row=1, col=col, showarrow=False, align="left",
                           text=(f"<b>{hs.value} storeys</b> in building height · first storey <b>{fs}</b><br>"
                                 f"building area <b>{ba.value:,.0f} m²</b> · {hm.value} m to top floor"),
                           font=dict(size=12, color=INK), bgcolor="rgba(255,255,255,0.85)", bordercolor=RULE, borderwidth=1, borderpad=6)

    fig.update_xaxes(visible=False, range=[-1.35, 1.85])
    fig.update_yaxes(title_text="elevation (m)", range=[ymin, ymax], gridcolor=RULE, zeroline=False, col=1,
                     tickfont=dict(family="IBM Plex Mono, monospace", size=11))
    fig.update_yaxes(range=[ymin, ymax], gridcolor=RULE, zeroline=False)
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10),
                      font=dict(color=INK, family="IBM Plex Sans, system-ui, sans-serif"), showlegend=False, height=620)
    return fig


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    fig = build_figure(project)
    out = root / "out" / "example_section.html"
    fig.write_html(out, include_plotlyjs=True, full_html=True)
    print("wrote", out)
