"""
codesheet.rhino_io — the Rhino round trip.

    export_3dm(spec, path)   MassingSpec → site.3dm
    import_3dm(path)         site.3dm    → (MassingSpec, warnings)

Conventions in the file (metres; z = 0 is GRADE):

    Site::Property line      closed polyline of the lot (user text kind=property_line)
    Site::Lot edges          one line per lot edge (kind=street|lane|neighbour, row_width_m)
    Site::ROW centrelines    dashed lines at half the right-of-way width outside street/lane edges
    Site::Setbacks           the setback polygon, when the lot carries setbacks
    Site::Grade              a flat surface at z = 0 covering the lot
    Context::Neighbours      one extrusion per neighbouring building (name, height_m)
    Massing::<Block>::L<n>   ONE EXTRUSION PER STOREY, bottom at the floor level, height = floor-to-floor.
                             User text: occupancy, use, f2f, beds, units, ded, glazing.
                             Courtyards: a closed curve on the same layer with kind=hole.
    Massing::<Block>::Roof   optional extrusion = rooftop enclosure (use, occupancy)

Editing in Rhino: move, scale or redraw a storey extrusion (or draw a new box on the
block's layer) and Save. The importer reads whatever solids sit under Massing::<Block>,
sorts them by base elevation and rebuilds the storey stack: footprint from the bottom
face, floor-to-floor from the height, attributes from user text (falling back to the
spec that was exported, stored as document user text "codesheet.spec").
"""
from __future__ import annotations

import json, math, pathlib
from typing import Optional

import rhino3dm as rh

from codesheet.massing import (MassingSpec, BlockSpec, StoreySpec, Lot, LotEdge, ContextBuilding, ContextTree, RoofSpec, EnclosureSpec, _ccw)

DOC_KEY = "codesheet.spec"
FILE_VERSION = 9
COLORS = {"Site": (30, 33, 38, 255), "Property line": (200, 53, 43, 255), "Lot edges": (120, 120, 120, 255), "ROW centrelines": (200, 53, 43, 255),
          "Setbacks": (178, 107, 0, 255), "Grade": (223, 227, 211, 255), "Context": (150, 150, 150, 255), "Neighbours": (170, 170, 170, 255),
          "Trees": (95, 158, 90, 255), "Street names": (120, 120, 120, 255), "Massing": (29, 79, 156, 255)}
OCC_COLORS = {"C": (42, 120, 214, 255), "A2": (235, 104, 52, 255), "E": (232, 123, 164, 255), "D": (237, 161, 0, 255), "F3": (27, 175, 122, 255), "A1": (198, 82, 31, 255), "B2": (74, 58, 167, 255), "F2": (0, 131, 0, 255)}


# --- helpers -------------------------------------------------------------------------

def _P(x, y, z=0.0):
    return rh.Point3d(float(x), float(y), float(z))


def _polyline(pts, z=0.0) -> rh.PolylineCurve:
    ring = [_P(x, y, z) for x, y in pts] + [_P(pts[0][0], pts[0][1], z)]
    return rh.Polyline(ring).ToPolylineCurve()


class _Layers:
    def __init__(self, model: rh.File3dm):
        self.m = model
        self.ids: dict[str, rh.Layer] = {}

    def get(self, path: str, color=None) -> int:
        """'Massing::North::L1' → layer index, creating parents as needed."""
        if path in self.ids:
            return self.ids[path].Index
        parts = path.split("::")
        parent = self.get("::".join(parts[:-1])) if len(parts) > 1 else None
        L = rh.Layer(); L.Name = parts[-1]
        if parent is not None:
            L.ParentLayerId = self.ids["::".join(parts[:-1])].Id
        c = color or COLORS.get(parts[-1]) or COLORS.get(parts[0])
        if c:
            L.Color = c
        idx = self.m.Layers.Add(L)
        self.ids[path] = self.m.Layers[idx]
        return idx


def _attrs(layer: int, name: str = "", **user) -> rh.ObjectAttributes:
    a = rh.ObjectAttributes(); a.LayerIndex = layer
    if name:
        a.Name = name
    for k, v in user.items():
        if v is not None:
            a.SetUserString(k, str(v))
    return a


# --- export ------------------------------------------------------------------------------

def export_3dm(spec: MassingSpec, path: str | pathlib.Path) -> pathlib.Path:
    m = rh.File3dm()
    m.Settings.ModelUnitSystem = rh.UnitSystem.Meters
    m.Strings[DOC_KEY] = spec.model_dump_json()
    m.Strings["codesheet.units"] = "metres; z=0 is grade; edit Massing::<Block> extrusions and Save"
    lay = _Layers(m)
    lot = spec.lot
    lotpts = [tuple(p) for p in (lot.polygon or [[0, 0], [lot.width_m, 0], [lot.width_m, lot.depth_m], [0, lot.depth_m]])]

    # property line + edges + ROW centrelines
    m.Objects.AddCurve(_polyline(lotpts), _attrs(lay.get("Site::Property line"), "property line", kind="property_line", grade_m=lot.grade_m, address=lot.address or "", zoning=lot.zoning or ""))
    for i, (a, b, e, label) in enumerate(lot.boundary()):
        m.Objects.AddLine(_P(*a), _P(*b), _attrs(lay.get("Site::Lot edges"), f"{label} · {e.kind}", kind=e.kind, edge=i, label=label, row_width_m=e.row_width_m))
        if e.kind in ("street", "lane") and e.row_width_m > 0:
            ux, uy = b[0] - a[0], b[1] - a[1]; L = math.hypot(ux, uy) or 1.0
            nx, ny = uy / L, -ux / L                 # outward for a CCW lot
            off = e.row_width_m / 2
            ext = e.row_width_m                      # draw the centreline a little longer than the edge
            ax, ay = a[0] + nx * off - ux / L * ext, a[1] + ny * off - uy / L * ext
            bx, by = b[0] + nx * off + ux / L * ext, b[1] + ny * off + uy / L * ext
            m.Objects.AddLine(_P(ax, ay), _P(bx, by), _attrs(lay.get("Site::ROW centrelines"), f"{label} centreline ({e.kind} {e.row_width_m:g} m)", kind="row_centreline", edge=i, row_width_m=e.row_width_m))
            # the far ROW line, for context
            m.Objects.AddLine(_P(ax + nx * off, ay + ny * off), _P(bx + nx * off, by + ny * off), _attrs(lay.get("Site::Lot edges"), f"{label} far side of {e.kind}", kind="row_far_edge", edge=i))
    # setbacks
    sb = getattr(lot, "setbacks", None)
    if sb and not lot.polygon:
        W, D = lot.width_m, lot.depth_m
        f, s, r = sb.get("front", 0), sb.get("side", 0), sb.get("rear", 0)
        m.Objects.AddCurve(_polyline([(s, f), (W - s, f), (W - s, D - r), (s, D - r)]), _attrs(lay.get("Site::Setbacks"), "setback envelope", kind="setback", front_m=f, side_m=s, rear_m=r))
    # grade plane
    xs = [p[0] for p in lotpts]; ys = [p[1] for p in lotpts]
    pad = 6.0
    plane_pts = [(min(xs) - pad, min(ys) - pad), (max(xs) + pad, min(ys) - pad), (max(xs) + pad, max(ys) + pad), (min(xs) - pad, max(ys) + pad)]
    grade = rh.Extrusion.Create(_polyline(plane_pts, -0.05), 0.05, True)
    m.Objects.AddExtrusion(grade, _attrs(lay.get("Site::Grade"), "grade (z = 0)", kind="grade", grade_m=lot.grade_m))
    # context
    for c in spec.context:
        ex = rh.Extrusion.Create(_polyline(_ccw([tuple(p) for p in c.footprint])), c.height_m, True)
        m.Objects.AddExtrusion(ex, _attrs(lay.get("Context::Neighbours"), c.name, kind="context", height_m=c.height_m, source=c.source or None))
    # trees: an octagonal trunk up to the crown centre, a sphere for the crown; the trunk carries the record
    for t in spec.trees:
        cr = t.crown_m / 2; cz = max(cr, t.height_m - cr)
        trunk = rh.Extrusion.Create(_polyline([(t.x + 0.18 * math.cos(k * math.pi / 4), t.y + 0.18 * math.sin(k * math.pi / 4)) for k in range(8)]), cz, True)
        m.Objects.AddExtrusion(trunk, _attrs(lay.get("Context::Trees"), t.name or "tree", kind="tree", x=t.x, y=t.y, height_m=t.height_m, crown_m=t.crown_m))
        m.Objects.AddBrep(rh.Brep.CreateFromSphere(rh.Sphere(_P(t.x, t.y, cz), cr)), _attrs(lay.get("Context::Trees"), t.name or "tree", kind="tree_crown"))
    # public realm: block outlines, lane and sidewalk strips as closed curves at z = 0 (City of Vancouver Open Data)
    for g in spec.ground:
        m.Objects.AddCurve(_polyline([tuple(p) for p in g.footprint], 0.0), _attrs(lay.get(f"Context::Ground::{g.kind.capitalize()}s"), g.name or g.kind, kind=f"ground_{g.kind}", width_m=g.width_m, source=g.source or None))
    # street names: a text dot at the middle of each centreline
    for s in spec.streets:
        a, b = s.line[(len(s.line) - 1) // 2], s.line[len(s.line) // 2]
        m.Objects.AddTextDot(s.name, _P((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 0.1), _attrs(lay.get("Context::Street names"), s.name, kind="street_name"))
    # massing
    for blk in spec.blocks:
        bl = lay.get(f"Massing::{blk.name}")
        m.Layers[bl].SetUserString("block", json.dumps({"name": blk.name, "default_glazing_pct": blk.default_glazing_pct, "glazing_pct_by_edge": blk.glazing_pct_by_edge, "firewall_separated": blk.firewall_separated}))
        z = blk.first_floor_above_grade_m
        for i, st in enumerate(blk.storeys, start=1):
            pts = _ccw([tuple(p) for p in (st.footprint or blk.footprint)])
            holes = st.holes if st.holes is not None else blk.holes
            li = lay.get(f"Massing::{blk.name}::L{i}", OCC_COLORS.get(st.occupancy.value))
            ex = rh.Extrusion.Create(_polyline(pts, z), st.floor_to_floor_m, True)
            m.Objects.AddExtrusion(ex, _attrs(li, f"{blk.name} L{i}", kind="storey", block=blk.name, storey=i, occupancy=st.occupancy.value, use=st.use,
                                               f2f=st.floor_to_floor_m, beds=st.sleeping_rooms, units=st.dwelling_units, ded=st.net_deduction_pct or None, glazing=blk.default_glazing_pct))
            for h in holes:
                m.Objects.AddCurve(_polyline(_ccw([tuple(p) for p in h]), z), _attrs(li, f"{blk.name} L{i} courtyard", kind="hole", block=blk.name, storey=i))
            z += st.floor_to_floor_m
        enc = blk.roof.enclosure
        if enc is not None:
            li = lay.get(f"Massing::{blk.name}::Roof")
            ex = rh.Extrusion.Create(_polyline(_ccw([tuple(p) for p in enc.footprint]), z), enc.height_m, True)
            m.Objects.AddExtrusion(ex, _attrs(li, f"{blk.name} rooftop enclosure", kind="enclosure", block=blk.name, use=enc.use, occupancy=enc.occupancy.value, height_m=enc.height_m))
        if blk.roof.parapet_m:
            li = lay.get(f"Massing::{blk.name}::Roof")
            top_pts = _ccw([tuple(p) for p in (blk.storeys[-1].footprint or blk.footprint)])
            m.Objects.AddCurve(_polyline(top_pts, z + blk.roof.parapet_m), _attrs(li, f"{blk.name} parapet", kind="parapet", block=blk.name, parapet_m=blk.roof.parapet_m))
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    m.Write(str(path), FILE_VERSION)
    return path


# --- import ------------------------------------------------------------------------------

def _curve_points(c: rh.Curve, n: int = 48) -> list[tuple[float, float, float]]:
    pl = None
    try:
        pl = c.TryGetPolyline()
    except Exception:
        pl = None
    pts = []
    if pl is not None and pl.Count >= 3:
        pts = [(pl[i].X, pl[i].Y, pl[i].Z) for i in range(pl.Count)]
    else:
        d = c.Domain
        pts = [(p.X, p.Y, p.Z) for p in (c.PointAt(d.T0 + (d.T1 - d.T0) * k / n) for k in range(n))]
    # drop the closing duplicate and near-duplicates
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-4:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-4:
        out.pop()
    return out


def _simplify(pts, tol=0.02):
    """Remove collinear points (Rhino often stores boxes with midpoints)."""
    if len(pts) <= 3:
        return pts
    out = []
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > tol:
            out.append(b)
    return out if len(out) >= 3 else pts


def _footprint_of(geom) -> Optional[tuple[list[list[float]], float, float]]:
    """(footprint [[x,y]...], z0, height) for an Extrusion or a Brep solid; None if not a volume."""
    if isinstance(geom, rh.Extrusion):
        c = geom.Profile3d(0, 0.0)
        pts = _curve_points(c)
        bb = geom.GetBoundingBox()
        z0, z1 = bb.Min.Z, bb.Max.Z
        fp = _simplify([[round(p[0], 3), round(p[1], 3)] for p in pts])
        return fp, round(z0, 3), round(z1 - z0, 3)
    if isinstance(geom, rh.Brep):
        vs = [(v.Location.X, v.Location.Y, v.Location.Z) for v in geom.Vertices]
        if len(vs) < 6:
            return None
        zmin = min(v[2] for v in vs); zmax = max(v[2] for v in vs)
        bottom = [v for v in vs if abs(v[2] - zmin) < 1e-3]
        if len(bottom) < 3:
            bb = geom.GetBoundingBox()
            fp = [[bb.Min.X, bb.Min.Y], [bb.Max.X, bb.Min.Y], [bb.Max.X, bb.Max.Y], [bb.Min.X, bb.Max.Y]]
        else:
            # order the bottom vertices around their centroid (fine for convex/near-convex outlines)
            cx = sum(v[0] for v in bottom) / len(bottom); cy = sum(v[1] for v in bottom) / len(bottom)
            bottom.sort(key=lambda v: math.atan2(v[1] - cy, v[0] - cx))
            fp = _simplify([[round(v[0], 3), round(v[1], 3)] for v in bottom])
        return fp, round(zmin, 3), round(zmax - zmin, 3)
    return None


def _layer_path(model: rh.File3dm, idx: int) -> str:
    L = model.Layers[idx]
    return L.FullPath if hasattr(L, "FullPath") and L.FullPath else L.Name


def _num(s, default=None):
    try:
        return float(s) if s not in (None, "", "None") else default
    except ValueError:
        return default


def _same_ring(a, b, tol: float = 0.01) -> bool:
    """Same closed outline, whatever the start vertex or winding (Rhino may re-order a polyline on save)."""
    if not a or not b or len(a) != len(b):
        return False
    n = len(a)
    for seq in (list(b), list(b)[::-1]):
        for k in range(n):
            rolled = seq[k:] + seq[:k]
            if all(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for p, q in zip(a, rolled)):
                return True
    return False


def import_3dm(path: str | pathlib.Path) -> tuple[MassingSpec, list[str]]:
    m = rh.File3dm.Read(str(path))
    if m is None:                                # rhino3dm returns None for a file it cannot parse: mid-save, or not a .3dm
        raise ValueError("not a readable .3dm file (Rhino may still be writing it)")
    warnings: list[str] = []
    base = None
    try:
        base = MassingSpec(**json.loads(m.Strings[DOC_KEY]))
    except Exception:
        warnings.append("No exported spec stored in the file — lot edges, sprinklering and occupant-load inputs default.")
    layer_of = {}
    for i in range(len(m.Layers)):
        layer_of[i] = _layer_path(m, i)

    lot_pts = None; edges_info = {}; context = []; trees = []; blocks: dict[str, dict] = {}
    for obj in m.Objects:
        g = obj.Geometry; a = obj.Attributes; lp = layer_of.get(a.LayerIndex, "")
        kind = a.GetUserString("kind") or ""
        parts = lp.split("::")
        if parts[0] == "Site":
            if kind == "property_line" or parts[-1] == "Property line":
                if isinstance(g, rh.Curve):
                    lot_pts = [[round(p[0], 3), round(p[1], 3)] for p in _curve_points(g)]
            elif kind in ("street", "lane", "neighbour"):
                edges_info[_num(a.GetUserString("edge"), -1)] = (kind, _num(a.GetUserString("row_width_m"), 0.0), a.GetUserString("label"))
        elif parts[0] == "Context":
            if kind == "tree":                       # the trunk carries the record; the crown and the street-name dots are decoration
                trees.append(ContextTree(x=_num(a.GetUserString("x"), 0.0), y=_num(a.GetUserString("y"), 0.0), height_m=_num(a.GetUserString("height_m"), 8.0),
                                         crown_m=_num(a.GetUserString("crown_m"), 5.0), name=a.Name or ""))
                continue
            if kind in ("tree_crown", "street_name"):
                continue
            fz = _footprint_of(g)
            if fz:
                context.append(ContextBuilding(name=a.Name or "neighbour", footprint=fz[0], height_m=max(0.5, fz[2]), source=a.GetUserString("source") or ""))
        elif parts[0] == "Massing" and len(parts) >= 2:
            blk = parts[1]
            B = blocks.setdefault(blk, {"volumes": [], "holes": [], "enclosure": None, "parapet": None})
            if kind == "hole" and isinstance(g, rh.Curve):
                pts = _curve_points(g); B["holes"].append(([[round(p[0], 3), round(p[1], 3)] for p in pts], round(pts[0][2], 3)))
                continue
            if kind == "parapet":
                bb = g.GetBoundingBox(); B["parapet"] = bb.Min.Z; continue
            fz = _footprint_of(g)
            if not fz:
                continue
            if kind == "enclosure" or parts[-1] == "Roof":
                B["enclosure"] = (fz, a)
            else:
                B["volumes"].append((fz, a))

    # lot
    if base is not None:
        lot = base.lot.model_copy(deep=True)
    else:
        lot = Lot(width_m=1, depth_m=1)
    if lot_pts:
        same_rect = (not lot.polygon) and len(lot_pts) == 4 and all(abs(p[0] - q[0]) < 0.01 and abs(p[1] - q[1]) < 0.01 for p, q in zip(lot_pts, [[0, 0], [lot.width_m, 0], [lot.width_m, lot.depth_m], [0, lot.depth_m]]))
        same_poly = bool(lot.polygon) and _same_ring(lot_pts, lot.polygon)     # a parcel-picked lot, untouched in Rhino
        if not (same_rect or same_poly):
            xs = [p[0] for p in lot_pts]; ys = [p[1] for p in lot_pts]
            if len(lot_pts) == 4 and all(abs(p[0] - q[0]) < 0.01 and abs(p[1] - q[1]) < 0.01 for p, q in zip(lot_pts, [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)]])) and abs(min(xs)) < 0.01 and abs(min(ys)) < 0.01:
                lot.width_m, lot.depth_m = round(max(xs), 3), round(max(ys), 3); lot.polygon = None
                warnings.append(f"Lot resized to {lot.width_m} × {lot.depth_m} m from the property line in the file.")
            else:
                pts = _ccw([tuple(p) for p in lot_pts])
                lot.polygon = [list(p) for p in pts]; lot.width_m = round(max(xs) - min(xs), 3); lot.depth_m = round(max(ys) - min(ys), 3)
                kinds = [LotEdge(kind=edges_info[i][0], row_width_m=edges_info[i][1]) if i in edges_info else LotEdge() for i in range(len(pts))]
                lot.edge_kinds = kinds
                warnings.append("Property line redrawn as a polygon; edge kinds taken from the Lot edges layer where the edge count matched, else 'neighbour'.")
        lot.source = f"Rhino: {pathlib.Path(path).name}"

    # blocks
    out_blocks = []
    base_blocks = {b.name: b for b in (base.blocks if base else [])}
    for name, B in blocks.items():
        vols = sorted(B["volumes"], key=lambda v: v[0][1])
        if not vols:
            continue
        bb = base_blocks.get(name)
        storeys = []
        for k, (fz, a) in enumerate(vols):
            fp, z0, h = fz
            proto = bb.storeys[k] if bb and k < len(bb.storeys) else (bb.storeys[-1] if bb and bb.storeys else None)
            occ = a.GetUserString("occupancy") or (proto.occupancy.value if proto else "C")
            st = StoreySpec(occupancy=occ, use=a.GetUserString("use") or (proto.use if proto else ""), floor_to_floor_m=max(2.2, h),
                            net_deduction_pct=_num(a.GetUserString("ded"), proto.net_deduction_pct if proto else 0.0) or 0.0,
                            sleeping_rooms=int(_num(a.GetUserString("beds"), -1)) if _num(a.GetUserString("beds")) is not None else (proto.sleeping_rooms if proto else None),
                            dwelling_units=int(_num(a.GetUserString("units"), -1)) if _num(a.GetUserString("units")) is not None else (proto.dwelling_units if proto else None),
                            ol_factor_m2=proto.ol_factor_m2 if proto else None)
            holes = [hp for hp, hz in B["holes"] if abs(hz - z0) < 0.05 or (z0 - 0.01 <= hz < z0 + h - 0.01)]
            st.footprint = fp; st.holes = holes
            storeys.append((st, z0))
        # gaps between storeys? warn if a storey bottom isn't at the previous top
        for (s1, z1), (s2, z2) in zip(storeys, storeys[1:]):
            if abs(z1 + s1.floor_to_floor_m - z2) > 0.05:
                warnings.append(f"{name}: storey at z={z2} m does not sit on the one below (top at {round(z1 + s1.floor_to_floor_m, 2)} m); floor-to-floor kept from each volume's own height.")
        first_fp = storeys[0][0].footprint
        for st, _ in storeys:                 # storeys identical to the block footprint don't need their own
            if st.footprint == first_fp:
                st.footprint = None
            if not st.holes:
                st.holes = None
        blk = BlockSpec(name=name, footprint=first_fp, storeys=[s for s, _ in storeys], first_floor_above_grade_m=round(storeys[0][1], 3),
                        default_glazing_pct=bb.default_glazing_pct if bb else 30.0,
                        glazing_pct_by_edge=(bb.glazing_pct_by_edge if bb and bb.footprint == first_fp else {}),
                        holes=[hp for hp, hz in B["holes"] if abs(hz - storeys[0][1]) < 0.05] if all(s.holes is None for s, _ in storeys) else [],
                        roof=RoofSpec(parapet_m=bb.roof.parapet_m if bb else 0.6))
        if bb and bb.footprint != first_fp and bb.glazing_pct_by_edge:
            warnings.append(f"{name}: footprint changed in Rhino — per-edge glazing reset to the block default {blk.default_glazing_pct:g}%.")
        if B["enclosure"]:
            fz, a = B["enclosure"]
            blk.roof.enclosure = EnclosureSpec(footprint=fz[0], height_m=max(0.5, fz[2]), use=a.GetUserString("use") or "elevator machine room, stair", occupancy=a.GetUserString("occupancy") or "C")
        out_blocks.append(blk)
    if not out_blocks:
        warnings.append("No storey volumes found under a Massing::<Block> layer — nothing to analyse.")
    spec = MassingSpec(project_name=base.project_name if base else pathlib.Path(path).stem, lot=lot, blocks=out_blocks or (base.blocks if base else []),
                       sprinklered=base.sprinklered if base else True, streets_faced=base.streets_faced if base else None,
                       chosen_articles={k: v for k, v in (base.chosen_articles if base else {}).items() if k in {b.name for b in out_blocks}},
                       context=context or (base.context if base else []), trees=trees or (base.trees if base else []),
                       streets=base.streets if base else [], ground=base.ground if base else [])
    return spec, warnings
