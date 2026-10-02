"""
codesheet.massing — the designer-facing model, and the bridge to the engine.

A designer at massing stage thinks in: a lot with edges (street / lane /
neighbour), blocks with a footprint polygon, a stack of storeys each with an
occupancy, a floor-to-floor, and a rough glazing ratio per face. That is the
MassingSpec. `to_building_model()` turns it into the full BuildingModel the
rule modules consume, deriving:

  * one Zone per storey (area = polygon area, occupancy = the storey's pick)
  * one ExteriorFace per polygon edge, with the limiting distance measured
    from the edge to the nearest lot edge, plus half the right-of-way width
    when that lot edge is a street or lane (3.2.3.1: LD to the centreline)
  * stated_upo_pct on every band = the face's glazing ratio

`headroom()` then asks the article selector how far each governing condition
is from flipping — the number a designer actually wants while dragging.
"""
from __future__ import annotations

import math
import re
from typing import Optional, Literal

from pydantic import BaseModel, Field

from codesheet.model import (BuildingModel, Site, Footprint, Point, Storey, Zone, ExteriorFace,
                             OccupancyGroup as O, ExposureType as X)
from codesheet.determinations import Determination, Bylaw
from codesheet import height_area, occupancy, articles, spatial, separations, targets, zoning
from codesheet.zoning import ZoningRules

EdgeKind = Literal["street", "lane", "neighbour"]


class LotEdge(BaseModel):
    kind: EdgeKind = "neighbour"
    row_width_m: float = Field(20.0, description="Right-of-way width for street/lane; LD is measured to its centreline.")


class Lot(BaseModel):
    """
    A lot is a polygon in local metres (x east, y north). For the common rectangular
    case give width/depth and the four named edges; for a parcel picked from the map
    give `polygon` and one `edge_kinds` entry per polygon segment (segment i runs from
    vertex i to i+1). width_m/depth_m then describe the bounding box.
    """
    width_m: float = Field(..., gt=0)
    depth_m: float = Field(..., gt=0)
    edges: dict[str, LotEdge] = Field(default_factory=lambda: {
        "south": LotEdge(kind="street", row_width_m=20.0), "north": LotEdge(kind="lane", row_width_m=6.0),
        "east": LotEdge(), "west": LotEdge()})
    polygon: Optional[list[list[float]]] = Field(None, description="[[x,y],...] CCW, metres; None = rectangle from width/depth")
    edge_kinds: Optional[list[LotEdge]] = Field(None, description="one per polygon segment")
    grade_m: float = 10.0
    setbacks: Optional[dict[str, float]] = Field(None, description="{'front','side','rear'} metres — drawn as the setback envelope in the plan and the Rhino file")
    address: Optional[str] = None
    zoning: Optional[str] = Field(None, description="District code, e.g. 'RM-4', 'C-2', 'CD-1 (123)'; looked up in data/zoning/vancouver/districts.json")
    zoning_rules: Optional[ZoningRules] = Field(None, description="Overrides for the district's limits (a CD-1 by-law, an area plan, a figure the designer checked)")
    source: Optional[str] = Field(None, description="e.g. 'CoV Open Data parcel 012-345-678' or 'described'")

    def boundary(self) -> list[tuple[tuple[float, float], tuple[float, float], LotEdge, str]]:
        """Segments (a, b, kind, label) of the lot boundary, CCW."""
        if self.polygon:
            pts = [tuple(p) for p in self.polygon]
            kinds = self.edge_kinds or [LotEdge() for _ in pts]
            return [(pts[i], pts[(i + 1) % len(pts)], kinds[i] if i < len(kinds) else LotEdge(), f"edge {i}") for i in range(len(pts))]
        W, D = self.width_m, self.depth_m
        E = self.edges
        return [((0, 0), (W, 0), E.get("south", LotEdge()), "south"), ((W, 0), (W, D), E.get("east", LotEdge()), "east"),
                ((W, D), (0, D), E.get("north", LotEdge()), "north"), ((0, D), (0, 0), E.get("west", LotEdge()), "west")]


Polygon = list[list[float]]


class StoreySpec(BaseModel):
    occupancy: O = O.C
    use: str = Field("", description="Plain description, e.g. 'retail CRU'. Helps the sheet read well.")
    floor_to_floor_m: float = Field(3.0, gt=0)
    footprint: Optional[Polygon] = Field(None, description="This storey's own outline (podium / stepback); None = the block footprint")
    holes: Optional[list[Polygon]] = Field(None, description="This storey's courtyards; None = the block's holes")
    # occupant-load inputs (Table 3.1.17.1); all optional at massing stage
    net_deduction_pct: float = Field(0.0, ge=0, le=100, description="circulation / duplicate-use deduction for the designed load")
    ol_factor_m2: Optional[float] = Field(None, gt=0, description="override area per person")
    sleeping_rooms: Optional[int] = Field(None, ge=0, description="Group C: bedrooms on this storey (2 persons each)")
    dwelling_units: Optional[int] = Field(None, ge=0, description="Group C: suites on this storey (1 WC each)")


class EnclosureSpec(BaseModel):
    """A rooftop enclosure (3.2.1.1.(1)): not a storey when it houses only elevator machinery, stairs or service rooms."""
    footprint: Polygon
    height_m: float = Field(3.0, gt=0)
    use: str = "elevator machine room, stair"
    occupancy: O = O.C


class BalconySpec(BaseModel):
    edge: int = Field(..., ge=0, description="footprint edge index the balconies project from")
    depth_m: float = Field(1.5, gt=0)
    storeys: Optional[list[int]] = Field(None, description="1-based storey numbers; None = every storey above the first")


class RoofSpec(BaseModel):
    parapet_m: float = Field(0.6, ge=0)
    enclosure: Optional[EnclosureSpec] = None
    balconies: list[BalconySpec] = Field(default_factory=list)


class BlockSpec(BaseModel):
    name: str = "A"
    footprint: Polygon = Field(..., min_length=3, description="[[x,y],...] metres, lot coordinates")
    holes: list[Polygon] = Field(default_factory=list, description="courtyards through every storey (a storey may override)")
    roof: RoofSpec = Field(default_factory=RoofSpec)
    storeys: list[StoreySpec] = Field(..., min_length=1)
    first_floor_above_grade_m: float = 0.1
    glazing_pct_by_edge: dict[int, float] = Field(default_factory=dict, description="edge index → % unprotected openings, default 30")
    default_glazing_pct: float = 30.0
    firewall_separated: bool = Field(True, description="Blocks are separate buildings (firewall). False = one building spread over several volumes (not yet supported).")


class ContextBuilding(BaseModel):
    """A neighbouring building, for the 3D view and the Rhino file. Not part of the code analysis
    (limiting distance is to the property line, not to the neighbour)."""
    name: str = "neighbour"
    footprint: Polygon
    height_m: float = Field(10.0, gt=0)
    source: str = Field("", description="where it came from, e.g. 'CoV footprint 2015 · height 2009 LiDAR'; empty = drawn by hand")


class ContextTree(BaseModel):
    """A tree near the site (City of Vancouver public-trees), for the 3D view and the Rhino file only."""
    x: float
    y: float
    height_m: float = Field(8.0, gt=0)
    crown_m: float = Field(5.0, gt=0, description="crown diameter")
    name: str = ""


class StreetName(BaseModel):
    """A named street centreline in lot coordinates; drawn as a label in the plan and the 3D view."""
    name: str
    line: list[list[float]] = Field(..., min_length=2)


class GroundPatch(BaseModel):
    """A piece of the public realm around the lot, in lot coordinates, for the 3D view, the plan and the Rhino file only.
    `block`: a City block outline (the land between rights-of-way; everything outside the blocks is street).
    `lane`: a lane right-of-way cut back out of its block. `sidewalk`: a sidewalk strip along the property line."""
    kind: Literal["block", "lane", "sidewalk"]
    footprint: Polygon
    name: str = ""
    width_m: Optional[float] = Field(None, description="lane: right-of-way width; sidewalk: nominal walk width")
    source: str = ""


class MassingSpec(BaseModel):
    project_name: str = "Untitled massing"
    lot: Lot
    blocks: list[BlockSpec]
    context: list[ContextBuilding] = Field(default_factory=list)
    trees: list[ContextTree] = Field(default_factory=list)
    streets: list[StreetName] = Field(default_factory=list)
    ground: list[GroundPatch] = Field(default_factory=list, description="block outlines, lanes and sidewalks (City of Vancouver Open Data)")
    sprinklered: bool = True
    streets_faced: Optional[int] = Field(None, description="Override; else counted from lot edges of kind street/lane")
    chosen_articles: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------

def _poly_area(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def _ccw(pts):
    s = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    return pts if s > 0 else pts[::-1]


def _ray_hit(px, py, nx, ny, a, b):
    """Distance along the ray (p + t·n, t ≥ 0) to segment ab, or None."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = nx * ey - ny * ex
    if abs(den) < 1e-9:
        return None
    t = ((a[0] - px) * ey - (a[1] - py) * ex) / den
    u = ((a[0] - px) * ny - (a[1] - py) * nx) / den
    # tolerate an edge that sits a few centimetres outside the lot (snapping): it is ON the line
    return max(t, 0.0) if t >= -0.15 and -1e-6 <= u <= 1 + 1e-6 else None


def _edge_exposure(lot: Lot, a, b, others: Optional[list[tuple[str, list]]] = None) -> tuple[X, float, str]:
    """
    Cast a ray from the footprint edge's midpoint along its outward normal to the
    lot boundary. The segment it hits says what the face looks at (street / lane /
    neighbour) and how far away the lot line is. LD to a street or lane is measured
    to the right-of-way centreline (3.2.3.1), so half the ROW width is added.
    """
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    ux, uy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ux, uy) or 1.0
    nx, ny = uy / L, -ux / L                       # outward normal for a CCW polygon
    best = None
    for sa, sb, kind, label in lot.boundary():
        t = _ray_hit(mx, my, nx, ny, sa, sb)
        if t is not None and (best is None or t < best[0]):
            best = (t, kind, label)
    if best is None:
        return X.PROPERTY_LINE, 0.0, "interior"
    # another building on the same lot in the way → imaginary line halfway (Div. A "Limiting distance")
    for name, poly in (others or []):
        for i in range(len(poly)):
            t = _ray_hit(mx, my, nx, ny, poly[i], poly[(i + 1) % len(poly)])
            if t is not None and t > 0.05 and t < best[0]:
                best = (t, LotEdge(kind="neighbour"), f"imaginary line to {name}")
    if best[2].startswith("imaginary line"):
        return X.SAME_LOT, round(best[0] / 2, 2), best[2]
    dist, e, side = max(0.0, best[0]), best[1], best[2]
    if e.kind == "street":
        return X.STREET, round(dist + e.row_width_m / 2, 2), side
    if e.kind == "lane":
        return X.LANE, round(dist + e.row_width_m / 2, 2), side
    return X.PROPERTY_LINE, round(dist, 2), side


def _edge_glazing(blk: "BlockSpec", a, b, block_edge_index: Optional[int]) -> float:
    """
    Glazing for a face edge. On the block outline it is the per-edge value; on a storey's own
    outline it inherits the value of a block edge that lies on the same line with the same
    outward direction (a stepped-back wall still on the party line keeps its 0 %), else the default.
    """
    if block_edge_index is not None:
        return blk.glazing_pct_by_edge.get(block_edge_index, blk.default_glazing_pct)
    if not blk.glazing_pct_by_edge:
        return blk.default_glazing_pct
    pts = _ccw([tuple(p) for p in blk.footprint])
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    ux, uy = b[0] - a[0], b[1] - a[1]
    for i in range(len(pts)):
        p, q = pts[i], pts[(i + 1) % len(pts)]
        vx, vy = q[0] - p[0], q[1] - p[1]
        if abs(ux * vy - uy * vx) > 1e-6 * max(1.0, abs(ux * vx + uy * vy)) or ux * vx + uy * vy <= 0:
            continue                                   # not parallel, or opposite direction
        L = math.hypot(vx, vy) or 1.0
        dist = abs((mx - p[0]) * vy - (my - p[1]) * vx) / L
        if dist < 0.02:
            return blk.glazing_pct_by_edge.get(i, blk.default_glazing_pct)
    return blk.default_glazing_pct


SERVICE_RE = re.compile(r"elevator|machine|stair|mechanical|service|hvac|electrical|penthouse")


def _fp(pts, holes):
    return Footprint(vertices=[Point(x=x, y=y) for x, y in pts], holes=[[Point(x=x, y=y) for x, y in _ccw([tuple(q) for q in h])] for h in (holes or [])])


def to_building_model(m: MassingSpec) -> BuildingModel:
    lot = m.lot
    streets = m.streets_faced if m.streets_faced is not None else len({lbl for _, _, e, lbl in lot.boundary() if e.kind in ("street", "lane")})
    storeys, faces, notes = [], [], []
    # every other block's outlines, for the imaginary-line test
    outlines = {blk.name: [_ccw([tuple(p) for p in (st.footprint or blk.footprint)]) for st in blk.storeys] for blk in m.blocks}
    for blk in m.blocks:
        others = [(n, poly) for n, polys in outlines.items() if n != blk.name for poly in {tuple(p) for p in polys}]
        others = [(n, list(poly)) for n, poly in others]
        blk_pts = _ccw([tuple(p) for p in blk.footprint])
        z = lot.grade_m + blk.first_floor_above_grade_m
        top = z
        runs = []          # (pts, holes, first_label, last_label, z0, z1)
        for i, st in enumerate(blk.storeys, start=1):
            label = f"L{i}"
            pts = _ccw([tuple(p) for p in (st.footprint or blk.footprint)])
            holes = st.holes if st.holes is not None else blk.holes
            fp = _fp(pts, holes)
            area = fp.area()
            storeys.append(Storey(label=label, block=blk.name, elevation_m=round(z, 3), height_m=st.floor_to_floor_m, footprint=fp,
                                  zones=[Zone(name=f"{label} {st.use or st.occupancy.value}", description=st.use or f"Group {st.occupancy.value}",
                                              area_m2=round(area * 0.92, 1), occupancy=st.occupancy,
                                              net_deduction_pct=st.net_deduction_pct, ol_factor_m2=st.ol_factor_m2,
                                              sleeping_rooms=st.sleeping_rooms, dwelling_units=st.dwelling_units)]))
            z1 = z + st.floor_to_floor_m
            if runs and runs[-1][0] == pts and runs[-1][1] == (holes or []):
                r = runs[-1]; runs[-1] = (r[0], r[1], r[2], label, r[4], z1)
            else:
                runs.append((pts, holes or [], label, label, z, z1))
            z = z1
            top = z
        # rooftop enclosure (3.2.1.1.(1))
        enc = blk.roof.enclosure
        roof_z = top
        if enc is not None:
            if SERVICE_RE.search(enc.use.lower()):
                notes.append(f"{blk.name}: rooftop enclosure '{enc.use}' ({_poly_area(enc.footprint):.0f} m², {enc.height_m:g} m) is not a storey — 3.2.1.1.(1), provided it serves only elevator machinery, stairs or service rooms.")
            else:
                label = f"L{len(blk.storeys) + 1}"
                pts = _ccw([tuple(p) for p in enc.footprint]); fp = _fp(pts, [])
                storeys.append(Storey(label=label, block=blk.name, elevation_m=round(top, 3), height_m=enc.height_m, footprint=fp,
                                      zones=[Zone(name=f"{label} {enc.use}", description=enc.use, area_m2=round(fp.area() * 0.92, 1), occupancy=enc.occupancy)]))
                runs.append((pts, [], label, label, top, top + enc.height_m))
                roof_z = top + enc.height_m
                notes.append(f"{blk.name}: rooftop enclosure '{enc.use}' is occupied space, so it COUNTS as a storey (3.2.1.1.(1) exempts only elevator machinery, stairs and service rooms).")
        storeys.append(Storey(label="Roof", block=blk.name, elevation_m=round(roof_z, 3), height_m=max(0.4, blk.roof.parapet_m), footprint=_fp(runs[-1][0], runs[-1][1]), is_roof=True))
        # faces: one per outer edge per run of identical footprints
        labels = {}
        hole_edges = 0
        for pts, holes, l0, l1, z0, z1 in runs:
            hole_edges += sum(len(h) for h in holes)
            band = l0 if l0 == l1 else f"{l0}–{l1}"
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                expo, ld, side = _edge_exposure(lot, a, b, others)
                if side == "interior":
                    continue
                key = (side, band)
                n = labels.get(key, 0) + 1; labels[key] = n
                glaz = _edge_glazing(blk, a, b, i if pts == blk_pts else None)
                st_labels = [s.label for s in storeys if s.block == blk.name and not s.is_roof and z0 - 0.01 <= s.elevation_m < z1 - 0.01]
                faces.append(ExteriorFace(
                    label=f"{blk.name} · {side}{'' if n == 1 else ' ' + str(n)} ({expo.value.replace('_', ' ')})" + (f" {band}" if len(runs) > 1 else ""), block=blk.name,
                    start=Point(x=a[0], y=a[1]), end=Point(x=b[0], y=b[1]),
                    base_elevation_m=round(z0, 3) if z0 > lot.grade_m else lot.grade_m, top_elevation_m=round(z1, 3), exposure=expo, limiting_distance_m=ld,
                    stated_upo_pct={k: glaz for k in st_labels},
                    source_note=f"massing: glazing ratio {glaz:g}% assumed; LD from edge {i} of {band} to the {side}" + (" — half the distance to the facing building (imaginary line, Div. A 'Limiting distance')" if expo == X.SAME_LOT else "")))
        if hole_edges:
            notes.append(f"{blk.name}: {hole_edges} courtyard edge(s) face the same building and are not exposing building faces under 3.2.3 (no separate building or fire compartment across the court). Confirm no firewall divides the court.")
    site = Site(address=lot.address or m.project_name, zoning_district=lot.zoning, grade_elevation_m=lot.grade_m, streets_faced=max(0, min(3, streets)))
    lotpts = lot.polygon or [[0, 0], [lot.width_m, 0], [lot.width_m, lot.depth_m], [0, lot.depth_m]]
    lotfp = Footprint(vertices=[Point(x=p[0], y=p[1]) for p in lotpts])
    return BuildingModel(project_name=m.project_name, site=site, footprint=lotfp, storeys=storeys, exterior_faces=faces,
                         is_sprinklered=m.sprinklered,
                         notes=["Generated from a massing spec: one zone per storey, glazing ratios assumed, LD measured from footprint edges to lot lines."] + notes)


# ---------------------------------------------------------------------------

def headroom(b: BuildingModel, hd: list[Determination], od: list[Determination], ad: list[Determination]) -> dict[str, dict]:
    """
    Per block: for the governing article, how far each condition is from failing,
    and which rung the building would drop to if it did.
    """
    H = {d.key: d for d in hd}; A = {d.key: d for d in ad}
    lad = articles.ladder(b, hd, od)
    out = {}
    for blk, evals in lad.items():
        gov = A.get(f"{blk}.article"); gov_id = gov.value if gov else None
        e = next((x for x in evals if x.rule.id == gov_id), None)
        if not e:
            continue
        r = e.rule
        storeys = H[f"{blk}.building_height_storeys"].value
        height = H[f"{blk}.height_to_top_floor_m"].value
        area = H[f"{blk}.building_area_m2"].value
        items = []
        if r.max_storeys is not None:
            items.append({"what": "storeys", "value": storeys, "cap": r.max_storeys, "headroom": r.max_storeys - storeys, "unit": "storeys"})
        if r.max_height_m is not None:
            items.append({"what": "height to top floor", "value": height, "cap": r.max_height_m, "headroom": round(r.max_height_m - height, 2), "unit": "m"})
        cap = None
        if r.max_area_by_storeys_streets:
            cap = r.max_area_by_storeys_streets.get(storeys, {}).get(b.site.streets_faced)
        elif r.max_area_by_storeys:
            cap = r.max_area_by_storeys.get(storeys)
        if cap:
            items.append({"what": "building area", "value": area, "cap": cap, "headroom": round(cap - area), "unit": "m²"})
        # what happens one storey up?
        nxt = None
        if r.max_storeys is not None:
            up = [evaluate for evaluate in evals]  # reuse
            more = sorted([x for x in (articles.evaluate(rr, storeys + 1, height + 3.0, area, b.is_sprinklered, b.site.streets_faced,
                                                            H[f"{blk}.basements"].value != "none") for rr in [x.rule for x in evals]) if x.qualifies],
                          key=lambda x: x.rule.strictness())
            nxt = more[0].rule.id if more else None
        # least-demanding rung if area grows past cap
        out[blk] = {"article": gov_id, "title": r.title, "items": items,
                    "if_one_more_storey": nxt,
                    "qualifying": [x.rule.id for x in evals if x.qualifies],
                    "excluded": {x.rule.id: [c for c, p, d in x.checks if not p] for x in evals if not x.qualifies}}
    return out


def analyze_massing(m: MassingSpec) -> dict:
    """Everything the live panel needs, JSON-serialisable."""
    b = to_building_model(m)
    law = Bylaw("vbbl-2025")
    hd = height_area.analyze(b, law)
    od = occupancy.analyze(b, law)
    ad = articles.analyze(b, hd, od, law, chosen=m.chosen_articles or None)
    groups = {d.block: (d.value[0] if d.value else "C") for d in od if d.key.endswith("major_occupancies")}
    sp, bands = spatial.analyze(b, law, groups)
    sd = separations.analyze(b, ad, law)
    td, tg = targets.analyze(b, hd, law)
    zd, zs = zoning.analyze(m, b, hd)

    def ser(d: Determination):
        return {"key": d.key, "label": d.label, "block": d.block, "value": d.value if not isinstance(d.value, list) else list(d.value),
                "unit": d.unit, "because": d.because, "flags": d.flags,
                "clauses": [{"id": c.id + (f".({c.sentence})" if c.sentence else ""), "page": c.page, "edition": c.edition} for c in d.clauses]}

    faces = {}
    for name, rs in bands.items():
        faces[name] = {"block": rs[0].face.block, "ld": rs[0].face.limiting_distance_m, "exposure": rs[0].face.exposure.value,
                       "bands": [{"label": r.label, "permitted": r.permitted_pct, "actual": r.actual_pct, "ok": r.ok, "z0": round(r.z0, 3), "z1": round(r.z1, 3),
                                  "frr_min": r.frr_min, "cladding": r.cladding, "construction": r.construction} for r in rs]}
    all_dets = hd + od + ad + sp + sd + td + zd
    return {
        "targets": tg,
        "zoning": zs,
        "building": b.model_dump(mode="json"),
        "determinations": [ser(d) for d in all_dets],
        "headroom": headroom(b, hd, od, ad),
        "faces": faces,
        "flags": sorted({(d.block or "site", f) for d in all_dets for f in d.flags}),
        "summary": {blk: {
            "storeys": next(d.value for d in hd if d.key == f"{blk}.building_height_storeys"),
            "area": next(d.value for d in hd if d.key == f"{blk}.building_area_m2"),
            "height": next(d.value for d in hd if d.key == f"{blk}.height_to_top_floor_m"),
            "majors": next(d.value for d in od if d.key == f"{blk}.major_occupancies"),
            "article": next((d.value for d in ad if d.key == f"{blk}.article"), None),
            "construction": next((d.value for d in ad if d.key == f"{blk}.req.Construction"), None),
            "floors": next((d.value for d in ad if d.key == f"{blk}.req.Floor assemblies"), None),
        } for blk in b.blocks()},
    }
