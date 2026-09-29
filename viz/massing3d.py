"""
viz.massing3d — draw a BuildingModel as an interactive 3D massing.

What you should see, and why each thing is there:
  * One slab per storey, extruded from the footprint. Colour = the storey's
    dominant occupancy group. This is the first "does the model look like the
    building?" check, and it previews the occupancy classifier's job.
  * The grade plane, drawn as a translucent sheet at Site.grade_elevation_m.
    Storeys below it are basements; counting the ones above it is 'building
    height in storeys'. Seeing P1/P2 sit under the sheet makes that concrete.
  * Each exterior face as a wire outline with its openings as filled patches,
    plus a dashed line at the limiting distance. This is the raw material of
    the spatial separation calc (3.2.3): face area, opening area, distance.

No bylaw logic here either — only drawing. Hover any slab for zone breakdown.
"""

from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go

from codesheet.model import BuildingModel, Storey, ExteriorFace, Point

# Categorical palette (validated default, light mode). Fixed order, never cycled.
OCC_COLOUR = {
    "C":  "#2a78d6",   # residential            slot 1 blue
    "A2": "#eb6834",   # assembly               slot 2 orange
    "F3": "#1baf7a",   # parking / low-hazard   slot 3 aqua
    "D":  "#eda100",   # business               slot 4 yellow
    "E":  "#e87ba4",   # mercantile             slot 5 magenta
    "F2": "#008300",
    "B2": "#4a3aa7",
    None: "#9aa0a6",   # unclassified — grey, deliberately not a series hue
}
INK = "#1f2328"
MUTED = "#6b7280"


def first_storey_floor(b: BuildingModel) -> float:
    """
    Floor elevation of the 'first storey': the uppermost storey whose floor is
    not more than 2 m above grade (Div. A definition). Everything below it is
    a basement. Used here only to label the drawing; piece 5 (height & grade)
    will own this rule properly, with the clause reference.
    """
    g = b.site.grade_elevation_m
    cands = [s.elevation_m for s in b.storeys if not s.is_roof and s.elevation_m <= g + 2.0]
    return max(cands) if cands else g


def _dominant_occupancy(storey: Storey):
    by = defaultdict(float)
    for z in storey.zones:
        by[z.occupancy.value if z.occupancy else None] += z.area_m2
    if not by:
        return None
    return max(by, key=by.get)


def _box_mesh(poly: list[Point], z0: float, z1: float, colour: str, name: str, hover: str):
    """Extrude a plan polygon between z0 and z1 as a Mesh3d with flat shading."""
    n = len(poly)
    xs = [p.x for p in poly] * 2
    ys = [p.y for p in poly] * 2
    zs = [z0] * n + [z1] * n
    i, j, k = [], [], []
    # top & bottom fans
    for t in range(1, n - 1):
        i += [0, n]; j += [t, n + t]; k += [t + 1, n + t + 1]
    # sides
    for a in range(n):
        b = (a + 1) % n
        i += [a, a]; j += [b, n + b]; k += [n + b, n + a]
    return go.Mesh3d(
        x=xs, y=ys, z=zs, i=i, j=j, k=k,
        color=colour, opacity=0.92, flatshading=True, name=name,
        hovertemplate=hover + "<extra></extra>", showlegend=False,
        lighting=dict(ambient=0.6, diffuse=0.6, specular=0.05),
    )


def _outline(poly: list[Point], z: float, colour=INK, width=2):
    pts = poly + [poly[0]]
    return go.Scatter3d(x=[p.x for p in pts], y=[p.y for p in pts], z=[z] * len(pts),
                        mode="lines", line=dict(color=colour, width=width),
                        hoverinfo="skip", showlegend=False)


def _face_traces(face: ExteriorFace):
    """Wire outline of the face, its openings as patches, and the limiting-distance line."""
    traces = []
    sx, sy, ex, ey = face.start.x, face.start.y, face.end.x, face.end.y
    L = face.length_m()
    ux, uy = (ex - sx) / L, (ey - sy) / L          # unit vector along the face
    nx, ny = uy, -ux                               # outward normal (CCW footprint)
    z0, z1 = face.base_elevation_m, face.top_elevation_m

    traces.append(go.Scatter3d(
        x=[sx, ex, ex, sx, sx], y=[sy, ey, ey, sy, sy], z=[z0, z0, z1, z1, z0],
        mode="lines", line=dict(color=INK, width=3), showlegend=False,
        hovertemplate=(f"<b>{face.label}</b><br>face {L:.1f} m × {face.height_m():.1f} m = "
                       f"{face.area_m2():.0f} m²<br>unprotected openings {face.unprotected_opening_area_m2():.0f} m² "
                       f"({100*face.unprotected_opening_area_m2()/face.area_m2():.0f} %)<br>"
                       f"limiting distance {face.limiting_distance_m} m ({face.exposure.value})<extra></extra>"),
    ))
    # openings, pushed 0.05 m out so they render in front of the slab
    for o in face.openings:
        if o.offset_m + o.width_m > L + 0.01:
            continue
        ax, ay = sx + ux * o.offset_m + nx * 0.05, sy + uy * o.offset_m + ny * 0.05
        bx, by = ax + ux * o.width_m, ay + uy * o.width_m
        zb, zt = z0 + o.sill_m, z0 + o.sill_m + o.height_m
        traces.append(go.Mesh3d(
            x=[ax, bx, bx, ax], y=[ay, by, by, ay], z=[zb, zb, zt, zt],
            i=[0, 0], j=[1, 2], k=[2, 3], color="#ffffff", opacity=0.95,
            hovertemplate=f"{o.label} {o.width_m}×{o.height_m} m = {o.area_m2():.1f} m²<extra></extra>",
            showlegend=False,
        ))
    # limiting-distance line on the ground, dashed
    d = face.limiting_distance_m
    traces.append(go.Scatter3d(
        x=[sx + nx * d, ex + nx * d], y=[sy + ny * d, ey + ny * d], z=[z0, z0],
        mode="lines", line=dict(color=MUTED, width=4, dash="dash"), showlegend=False,
        hovertemplate=f"{face.label}: limiting distance {d} m<extra></extra>",
    ))
    # tie lines from face corners to the LD line
    for px, py in ((sx, sy), (ex, ey)):
        traces.append(go.Scatter3d(x=[px, px + nx * d], y=[py, py + ny * d], z=[z0, z0],
                                   mode="lines", line=dict(color=MUTED, width=2, dash="dot"),
                                   hoverinfo="skip", showlegend=False))
    return traces


def build_figure(b: BuildingModel) -> go.Figure:
    fig = go.Figure()
    fp = b.footprint.vertices
    grade = b.site.grade_elevation_m
    seen_groups = set()

    first_floor = first_storey_floor(b)
    for s in b.storeys_sorted():
        poly = s.footprint.vertices if s.footprint else fp
        occ = _dominant_occupancy(s)
        seen_groups.add(occ)
        z0, z1 = s.elevation_m, s.elevation_m + s.height_m
        zones = "<br>".join(f"&nbsp;&nbsp;{z.name}: {z.area_m2:.0f} m² [{z.occupancy.value if z.occupancy else '?'}]"
                            for z in s.zones) or "&nbsp;&nbsp;(no zones)"
        rel = "above grade" if s.elevation_m >= first_floor - 0.01 else "below grade"
        hover = (f"<b>{s.block} Block · {s.label}</b> — FFL {s.elevation_m:.2f} m ({rel})<br>"
                 f"gross {s.gross_area_m2():.0f} m², dominant {occ or 'unclassified'}<br>{zones}")
        colour = "#d9dde3" if s.is_roof else OCC_COLOUR[occ]
        fig.add_trace(_box_mesh(poly, z0, z1 - 0.08, colour, s.label, hover))
        fig.add_trace(_outline(poly, z1 - 0.08))

    # grade plane
    xs = [p.x for p in fp]; ys = [p.y for p in fp]
    m = 8.0
    gx = [min(xs) - m, max(xs) + m, max(xs) + m, min(xs) - m]
    gy = [min(ys) - m, min(ys) - m, max(ys) + m, max(ys) + m]
    fig.add_trace(go.Mesh3d(x=gx, y=gy, z=[grade] * 4, i=[0, 0], j=[1, 2], k=[2, 3],
                            color="#b7c4a1", opacity=0.35, showlegend=False,
                            hovertemplate=f"grade {grade:.2f} m (Div. A 1.4.1.2)<extra></extra>"))

    for f in b.exterior_faces:
        for t in _face_traces(f):
            fig.add_trace(t)

    # block name floating above each block's top storey
    for blk in b.blocks():
        tops = [s for s in b.storeys_sorted(blk) if s.footprint]
        if not tops:
            continue
        top = tops[-1]
        v = top.footprint.vertices
        cx = sum(p.x for p in v) / len(v); cy = sum(p.y for p in v) / len(v)
        fig.add_trace(go.Scatter3d(x=[cx], y=[cy], z=[top.elevation_m + top.height_m + 2.5], mode="text",
                                   text=[f"{blk} Block"], textfont=dict(size=14, color=INK),
                                   hoverinfo="skip", showlegend=False))

    # legend as dummy traces — identity is also in hover text, so not colour-alone
    for g in sorted(seen_groups, key=lambda x: (x is None, str(x))):
        fig.add_trace(go.Scatter3d(x=[None], y=[None], z=[None], mode="markers",
                                   marker=dict(size=10, color=OCC_COLOUR[g], symbol="square"),
                                   name=f"Group {g}" if g else "Unclassified"))

    fig.update_layout(
        title=dict(text=f"{b.project_name} — massing by dominant occupancy<br>"
                        f"<sup>{b.site.address} · {'sprinklered' if b.is_sprinklered else 'unsprinklered'} · "
                        f"building area {b.building_area_m2():.0f} m² · grade {grade:.1f} m</sup>",
                   font=dict(color=INK, size=16)),
        scene=dict(aspectmode="data",
                   xaxis=dict(title="x (m)", showbackground=False, gridcolor="#e5e7eb"),
                   yaxis=dict(title="y (m)", showbackground=False, gridcolor="#e5e7eb"),
                   zaxis=dict(title="elev (m)", showbackground=False, gridcolor="#e5e7eb"),
                   camera=dict(eye=dict(x=-1.25, y=-1.7, z=0.75))),
        legend=dict(title="Dominant occupancy", x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
        paper_bgcolor="#ffffff", margin=dict(l=0, r=0, t=70, b=0), font=dict(color=INK),
    )
    return fig


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    fig = build_figure(project)
    out = root / "out" / "example_massing.html"
    fig.write_html(out, include_plotlyjs=True, full_html=True)
    print("wrote", out)
