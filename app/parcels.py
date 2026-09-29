"""
app.parcels — "pick a site": City of Vancouver Open Data → a Lot for the massing layer.

Datasets (Open Data portal, Explore API v2.1):
    property-parcel-polygons      parcel outlines
    zoning-districts-and-labels   zoning district polygons
    public-streets                street centrelines
    lanes                         lane centrelines
The dataset ids and the attribute names we look for live in DATASETS below so
they can be corrected without touching the logic if the City renames them.

Flow: /api/parcels?lat=&lon=&radius= returns everything near a point in lon/lat.
The client shows it on a map; when the user clicks a parcel, /api/parcels/lot
turns that parcel + the nearby centrelines into a Lot: local metres, CCW,
rotated so the principal street edge is at the bottom, and one edge kind per
segment: street or lane when a centreline of that type lies just outside the
edge (ROW width ≈ 2 × distance to the centreline), else neighbour.

FIXTURE mode (CODESHEET_FIXTURE=1 or --fixture) serves a synthetic block of
33-ft lots so the picker can be developed and demonstrated offline. Fixture
parcels are flagged as such in the response.
"""
from __future__ import annotations

import json, math, os, urllib.parse, urllib.request
from typing import Optional

from codesheet.massing import Lot, LotEdge

BASE = "https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/{ds}/records"
DATASETS = {
    "parcels": {"id": "property-parcel-polygons", "addr_fields": ["civic_number", "streetname", "std_street", "site_id", "tax_coord"]},
    "zoning": {"id": "zoning-districts-and-labels", "fields": ["zoning_district", "zoning_classification"]},
    "streets": {"id": "public-streets", "fields": ["hblock", "streetuse", "std_street"]},
    "lanes": {"id": "lanes", "fields": []},
}
STREET_MAX_M, LANE_MAX_M = 28.0, 9.0      # a centreline farther than this is not "this edge's" street/lane
FIXTURE = os.environ.get("CODESHEET_FIXTURE") == "1"


# ---------------------------------------------------------------------------- fetch

def _ods(ds: str, lon: float, lat: float, radius_m: float, limit: int = 100) -> list[dict]:
    q = {"where": f"within_distance(geom, geom'POINT({lon} {lat})', {int(radius_m)}m)", "limit": limit}
    url = BASE.format(ds=ds) + "?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())["results"]


def _geom(rec: dict):
    g = rec.get("geom") or rec.get("geo_shape") or {}
    return g.get("geometry", g) if isinstance(g, dict) else None


def _first(rec: dict, keys: list[str]):
    for k in keys:
        if rec.get(k) not in (None, ""):
            return rec[k]
    return None


def nearby(lat: float, lon: float, radius_m: float = 250) -> dict:
    if FIXTURE:
        return _fixture(lat, lon)
    parcels, zoning, streets, lanes = [], [], [], []
    for rec in _ods(DATASETS["parcels"]["id"], lon, lat, radius_m, 200):
        g = _geom(rec)
        if g and g.get("type") in ("Polygon", "MultiPolygon"):
            ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
            addr = " ".join(str(rec[k]) for k in ("civic_number", "streetname") if rec.get(k)) or _first(rec, DATASETS["parcels"]["addr_fields"])
            parcels.append({"id": str(rec.get("site_id") or rec.get("tax_coord") or len(parcels)), "address": addr, "ring": ring})
    for rec in _ods(DATASETS["zoning"]["id"], lon, lat, radius_m + 200, 50):
        g = _geom(rec)
        if g and g.get("type") in ("Polygon", "MultiPolygon"):
            rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
            zoning.append({"district": _first(rec, DATASETS["zoning"]["fields"]), "rings": rings})
    for rec in _ods(DATASETS["streets"]["id"], lon, lat, radius_m + 60, 200):
        g = _geom(rec)
        if g and g.get("type") in ("LineString", "MultiLineString"):
            lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for ln in lines:
                streets.append({"name": _first(rec, DATASETS["streets"]["fields"]) or "street", "line": ln})
    try:
        for rec in _ods(DATASETS["lanes"]["id"], lon, lat, radius_m + 60, 200):
            g = _geom(rec)
            if g and g.get("type") in ("LineString", "MultiLineString"):
                for ln in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                    lanes.append({"line": ln})
    except Exception:
        pass                                     # lanes dataset optional
    return {"center": [lon, lat], "parcels": parcels, "zoning": zoning, "streets": streets, "lanes": lanes, "fixture": False}


# ---------------------------------------------------------------------------- geometry

def _proj(lon0: float, lat0: float):
    kx = 111320.0 * math.cos(math.radians(lat0)); ky = 110540.0
    return (lambda p: ((p[0] - lon0) * kx, (p[1] - lat0) * ky))


def _simplify(pts: list, tol: float = 0.35) -> list:
    """Drop near-duplicate and near-collinear vertices (parcel outlines carry many)."""
    out = []
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < tol:
            continue
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        base = math.hypot(c[0] - a[0], c[1] - a[1]) or 1.0
        if abs(cross) / base < tol:
            continue
        out.append(b)
    return out if len(out) >= 3 else pts


def _seg_dist(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy or 1e-9
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _nearest_line(pt, normal, lines: list[list], max_d: float) -> Optional[float]:
    """Distance to the nearest polyline that lies on the outward side of the edge."""
    best = None
    for ln in lines:
        for a, b in zip(ln, ln[1:]):
            d = _seg_dist(pt, a, b)
            if d > max_d:
                continue
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if (mid[0] - pt[0]) * normal[0] + (mid[1] - pt[1]) * normal[1] <= 0:
                continue                         # behind the edge — that's the neighbour's street
            best = d if best is None else min(best, d)
    return best


def _point_in_ring(p, ring) -> bool:
    x, y = p; inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i][0], ring[i][1]; x2, y2 = ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def parcel_to_lot(parcel: dict, streets: list[dict], lanes: list[dict], zoning: list[dict], grade_m: float = 10.0) -> dict:
    ring = parcel["ring"]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    cx = sum(p[0] for p in ring) / len(ring); cy = sum(p[1] for p in ring) / len(ring)
    P = _proj(cx, cy)
    pts = _simplify([P(p) for p in ring])
    # CCW
    if sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) < 0:
        pts = pts[::-1]
    st_lines = [[P(q) for q in s["line"]] for s in streets]
    ln_lines = [[P(q) for q in l["line"]] for l in lanes]
    kinds, dists = [], []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ux, uy = b[0] - a[0], b[1] - a[1]; L = math.hypot(ux, uy) or 1.0
        nrm = (uy / L, -ux / L)
        ds = _nearest_line(m, nrm, st_lines, STREET_MAX_M)
        dl = _nearest_line(m, nrm, ln_lines, LANE_MAX_M)
        if ds is not None and (dl is None or ds <= dl * 1.5):
            kinds.append(LotEdge(kind="street", row_width_m=round(2 * ds, 1))); dists.append(ds)
        elif dl is not None:
            kinds.append(LotEdge(kind="lane", row_width_m=round(2 * dl, 1))); dists.append(dl)
        else:
            kinds.append(LotEdge(kind="neighbour", row_width_m=0.0)); dists.append(None)
    # rotate so the longest street edge is horizontal at the bottom
    street_edges = [i for i, k in enumerate(kinds) if k.kind == "street"] or list(range(len(pts)))
    i0 = max(street_edges, key=lambda i: math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0], pts[(i + 1) % len(pts)][1] - pts[i][1]))
    a, b = pts[i0], pts[(i0 + 1) % len(pts)]
    ang = -math.atan2(b[1] - a[1], b[0] - a[0])
    ca, sa = math.cos(ang), math.sin(ang)
    # re-index so the principal street edge is edge 0, then rotate
    pts = pts[i0:] + pts[:i0]; kinds = kinds[i0:] + kinds[:i0]; dists = dists[i0:] + dists[:i0]
    rot = [(x * ca - y * sa, x * sa + y * ca) for x, y in pts]
    minx = min(p[0] for p in rot); miny = min(p[1] for p in rot)
    poly = [[round(x - minx, 2), round(y - miny, 2)] for x, y in rot]
    W = max(p[0] for p in poly); D = max(p[1] for p in poly)
    zone = next((z["district"] for z in zoning for r in z["rings"] if _point_in_ring((cx, cy), r)), None)
    lot = Lot(width_m=round(W, 2), depth_m=round(D, 2), polygon=poly, edge_kinds=kinds, grade_m=grade_m,
              address=parcel.get("address"), zoning=zone,
              source=("FIXTURE parcel " if parcel.get("fixture") else "CoV Open Data parcel ") + str(parcel.get("id")))
    return {"lot": json.loads(lot.model_dump_json()), "rotation_deg": round(math.degrees(ang), 1),
            "edge_distances_m": [None if d is None else round(d, 1) for d in dists], "area_m2": round(_area(poly), 1)}


def _area(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


# ---------------------------------------------------------------------------- fixture

def _fixture(lat: float, lon: float) -> dict:
    """A synthetic Vancouver-style block: an E–W street, a lane behind, 33-ft lots 122 ft deep, one corner lot."""
    kx = 111320.0 * math.cos(math.radians(lat)); ky = 110540.0
    ll = lambda x, y: [lon + x / kx, lat + y / ky]
    W, D, lane_w, street_w = 10.06, 37.19, 6.0, 20.0
    parcels, streets, lanes = [], [], []
    y0 = 0.0
    for row, sign in ((0, 1), (1, -1)):                      # two rows of lots facing two streets
        for i in range(8):
            x0 = -40 + i * W
            yA, yB = (y0, y0 + D) if sign == 1 else (y0 - D - lane_w, y0 - lane_w)
            ring = [ll(x0, yA), ll(x0 + W, yA), ll(x0 + W, yB), ll(x0, yB), ll(x0, yA)]
            parcels.append({"id": f"fx-{row}-{i}", "address": f"{2100 + i * 8} W {'11th' if row == 0 else '12th'} Ave", "ring": ring, "fixture": True})
        # wide corner lot at the east end
        x0 = -40 + 8 * W
        yA, yB = (y0, y0 + D) if sign == 1 else (y0 - D - lane_w, y0 - lane_w)
        ring = [ll(x0, yA), ll(x0 + 2 * W, yA), ll(x0 + 2 * W, yB), ll(x0, yB), ll(x0, yA)]
        parcels.append({"id": f"fx-{row}-c", "address": f"{2100 + 64} W {'11th' if row == 0 else '12th'} Ave (corner)", "ring": ring, "fixture": True})
    streets.append({"name": "W 11th Ave", "line": [ll(-80, y0 - lane_w - D - street_w / 2), ll(80, y0 - lane_w - D - street_w / 2)]})
    streets.append({"name": "W 12th Ave", "line": [ll(-80, y0 + D + street_w / 2), ll(80, y0 + D + street_w / 2)]})
    streets.append({"name": "Yew St", "line": [ll(-40 + 10 * W + street_w / 2, -120), ll(-40 + 10 * W + street_w / 2, 120)]})
    lanes.append({"line": [ll(-80, y0 - lane_w / 2), ll(80, y0 - lane_w / 2)]})
    zoning = [{"district": "RT-7 (fixture)", "rings": [[ll(-200, -200), ll(200, -200), ll(200, 200), ll(-200, 200)]]}]
    return {"center": [lon, lat], "parcels": parcels, "zoning": zoning, "streets": streets, "lanes": lanes, "fixture": True}
