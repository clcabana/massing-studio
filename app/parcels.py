"""
app.parcels — "pick a site": City of Vancouver Open Data → a Lot for the massing layer.

Datasets (Open Data portal, Explore API v2.1):
    property-parcel-polygons      parcel outlines
    zoning-districts-and-labels   zoning district polygons
    public-streets                street centrelines (hblock carries the name: "2200 W 10TH AV")
    lanes                         lane centrelines
    building-footprints-2015      neighbouring building outlines (2015 orthophotos; no heights)
    building-footprints-2009      2009 LiDAR footprints with heights (hgt_agl) — matched to the 2015 outlines
    public-trees                  street trees: height_m, diameter_cm, species
    block-outlines                the land between rights-of-way, one polygon per block (lanes are inside it)
    right-of-way-widths           a point per ROW segment with its width (feet as '66', sometimes metres as '11.237m')
    sidewalk-condition-rating     one line per block face that has a sidewalk ('2600 ARBUTUS ST E'); the geometry is
                                  schematic — a constant ~5 m off the centreline whatever the ROW — so it says which
                                  side of which block has a sidewalk, not where its edges are
The dataset ids and the attribute names we look for live in DATASETS below so
they can be corrected without touching the logic if the City renames them.

The public realm in 3D (`ground` in the response): block outlines as drawn by the
City; the street right-of-way is whatever is outside them. Lanes are cut back out
of their block as a strip along the lane centreline, as wide as the nearest
right-of-way-widths point says (20 ft when none). Sidewalks are drawn as a strip of
nominal width along the block's property line on every face the inventory lists —
the position within the ROW (against the property line) and the width are
assumptions and are labelled as such in `source`.

Flow: /api/parcels?lat=&lon=&radius= returns everything near a point in lon/lat.
The client shows it on a map; when the user clicks a parcel, /api/parcels/lot
turns that parcel + the nearby centrelines into a Lot: local metres, CCW,
rotated so the principal street edge is at the bottom, and one edge kind per
segment: street or lane when a centreline of that type lies just outside the
edge (ROW width ≈ 2 × distance to the centreline), else neighbour. The same
response carries the site context in that lot frame — site_context(): the
neighbouring buildings (named by their parcel's address, heights from the 2009
LiDAR where a footprint matches, else estimated), the public trees and the
street names — for the 3D view, the plan and the Rhino file.

FIXTURE mode (CODESHEET_FIXTURE=1 or --fixture) serves a synthetic block of
33-ft lots so the picker can be developed and demonstrated offline. Fixture
parcels are flagged as such in the response.
"""
from __future__ import annotations

import json, math, os, re, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from codesheet.massing import Lot, LotEdge

BASE = "https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/{ds}/records"
DATASETS = {
    "parcels": {"id": "property-parcel-polygons", "addr_fields": ["civic_number", "streetname", "std_street", "site_id", "tax_coord"]},
    "zoning": {"id": "zoning-districts-and-labels", "fields": ["zoning_district", "zoning_classification"]},
    "streets": {"id": "public-streets", "fields": ["hblock", "streetuse", "std_street"]},
    "lanes": {"id": "lanes", "fields": []},
    "footprints": {"id": "building-footprints-2015"},
    "footprints_2009": {"id": "building-footprints-2009", "height_fields": ["hgt_agl", "maxht_m", "avght_m"]},
    "trees": {"id": "public-trees", "name_fields": ["common_name", "genus_name"]},
    "blocks": {"id": "block-outlines"},
    "row_widths": {"id": "right-of-way-widths", "field": "width"},
    "sidewalks": {"id": "sidewalk-condition-rating", "name_field": "hundred_block"},
}
STREET_MAX_M, LANE_MAX_M = 28.0, 9.0      # a centreline farther than this is not "this edge's" street/lane
CONTEXT_RADIUS_M = 90.0                    # neighbours, trees and street names this far from the lot centre
EST_HOUSE_M, EST_GARAGE_M = 8.5, 3.0       # heights when no 2009 LiDAR footprint matches (built after 2009)
SIDEWALK_W_M = 1.8                         # nominal walk width; the City's inventory gives the side, not the width
LANE_W_M = 6.1                             # 20 ft, the standard Vancouver lane, when no right-of-way-widths point is on the lane
SIDEWALK_MATCH_M = 25.0                    # a sidewalk line farther than this from every block outline is not drawn
FIXTURE = os.environ.get("CODESHEET_FIXTURE") == "1"
PAGE = 100                                 # Explore API v2.1 /records rejects limit > 100; page with offset instead


def _ods_page(ds: str, where: str, limit: int, offset: int) -> list[dict]:
    q = {"where": where, "limit": limit, "offset": offset}
    url = BASE.format(ds=ds) + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "massing-studio/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["results"]


# ---------------------------------------------------------------------------- fetch

def _ods(ds: str, lon: float, lat: float, radius_m: float, limit: int = 100) -> list[dict]:
    """Up to `limit` records within radius_m of the point, fetched in pages of PAGE (the API's maximum)."""
    where = f"within_distance(geom, geom'POINT({lon} {lat})', {int(radius_m)}m)"
    out: list[dict] = []
    while len(out) < limit:
        page = _ods_page(ds, where, min(PAGE, limit - len(out)), len(out))
        out.extend(page)
        if len(page) < PAGE:
            break
    return out


def _geom(rec: dict):
    g = rec.get("geom") or rec.get("geo_shape") or {}
    return g.get("geometry", g) if isinstance(g, dict) else None


def _first(rec: dict, keys: list[str]):
    for k in keys:
        if rec.get(k) not in (None, ""):
            return rec[k]
    return None


_CACHE: dict = {}                               # (dataset, rounded lon, lat, radius, limit) → (time, records)
CACHE_TTL_S = 600


def _ods_cached(ds: str, lon: float, lat: float, radius_m: float, limit: int) -> list[dict]:
    """_ods with a short memory: panning back over the same block does not ask the City again."""
    key = (ds, round(lon, 4), round(lat, 4), int(radius_m), limit)        # 1e-4° ≈ 8 m
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    recs = _ods(ds, lon, lat, radius_m, limit)
    if len(_CACHE) > 400:
        _CACHE.clear()
    _CACHE[key] = (time.time(), recs)
    return recs


def _parallel(jobs: dict) -> dict:
    """Run {name: callable} concurrently (the Open Data calls are independent and ~0.5 s each)."""
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {name: ex.submit(fn) for name, fn in jobs.items()}
        return {name: f.result() for name, f in futs.items()}


def nearby(lat: float, lon: float, radius_m: float = 250) -> dict:
    if FIXTURE:
        return _fixture(lat, lon)
    parcels, zoning, streets, lanes = [], [], [], []

    def lanes_or_none():
        try:
            return _ods_cached(DATASETS["lanes"]["id"], lon, lat, radius_m + 60, 200)
        except Exception:
            return []                            # lanes dataset optional
    R = _parallel({"parcels": lambda: _ods_cached(DATASETS["parcels"]["id"], lon, lat, radius_m, 200),
                   "zoning": lambda: _ods_cached(DATASETS["zoning"]["id"], lon, lat, radius_m + 200, 50),
                   "streets": lambda: _ods_cached(DATASETS["streets"]["id"], lon, lat, radius_m + 60, 200),
                   "lanes": lanes_or_none})
    for rec in R["parcels"]:
        g = _geom(rec)
        if g and g.get("type") in ("Polygon", "MultiPolygon"):
            ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
            addr = " ".join(str(rec[k]) for k in ("civic_number", "streetname") if rec.get(k)) or _first(rec, DATASETS["parcels"]["addr_fields"])
            parcels.append({"id": str(rec.get("site_id") or rec.get("tax_coord") or len(parcels)), "address": addr, "ring": ring})
    for rec in R["zoning"]:
        g = _geom(rec)
        if g and g.get("type") in ("Polygon", "MultiPolygon"):
            rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
            zoning.append({"district": _first(rec, DATASETS["zoning"]["fields"]), "rings": rings})
    for rec in R["streets"]:
        g = _geom(rec)
        if g and g.get("type") in ("LineString", "MultiLineString"):
            lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for ln in lines:
                streets.append({"name": _first(rec, DATASETS["streets"]["fields"]) or "street", "line": ln})
    for rec in R["lanes"]:
        g = _geom(rec)
        if g and g.get("type") in ("LineString", "MultiLineString"):
            for ln in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                lanes.append({"line": ln})
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
    frame = {"lon0": cx, "lat0": cy, "ang_deg": math.degrees(ang), "dx": minx, "dy": miny}     # lon/lat → this lot's metres
    return {"lot": json.loads(lot.model_dump_json()), "rotation_deg": round(math.degrees(ang), 1),
            "edge_distances_m": [None if d is None else round(d, 1) for d in dists], "area_m2": round(_area(poly), 1), "frame": frame}


def _area(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def _centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _to_frame(frame: dict):
    """The lon/lat → lot-metres transform parcel_to_lot used, so context lands in the same frame."""
    P = _proj(frame["lon0"], frame["lat0"]); ang = math.radians(frame["ang_deg"]); ca, sa = math.cos(ang), math.sin(ang)

    def T(p):
        x, y = P(p)
        return [round(x * ca - y * sa - frame["dx"], 2), round(x * sa + y * ca - frame["dy"], 2)]
    return T


def _rings(g) -> list[list]:
    if not g:
        return []
    if g.get("type") == "Polygon":
        return [g["coordinates"][0]]
    if g.get("type") == "MultiPolygon":
        return [p[0] for p in g["coordinates"]]
    return []


def _open(ring: list) -> list:
    return ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring


# ---------------------------------------------------------------------------- public realm: blocks, lanes, sidewalks

def _row_width_m(raw) -> Optional[float]:
    """right-of-way-widths.width: feet as a bare number ('66', '20'), occasionally metres ('11.237m', '18(m)')."""
    s = str(raw or "").strip().lower()
    num = re.findall(r"\d+(?:\.\d+)?", s)
    if not num:
        return None
    v = float(num[0])
    return round(v if "m" in s else v * 0.3048, 2)


def _ccw_ring(pts: list) -> list:
    s = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    return pts if s > 0 else pts[::-1]


def _offset_polyline(pts: list, d: float) -> list:
    """Each vertex moved by d along the average of its two edge normals (right-hand normal of the travel direction).
    For a CCW ring the right-hand normal points outward."""
    n = len(pts)
    out = []
    for i in range(n):
        nx = ny = 0.0
        for a, b in ((pts[i - 1], pts[i]) if i > 0 else (None, None), (pts[i], pts[i + 1]) if i < n - 1 else (None, None)):
            if a is None:
                continue
            ux, uy = b[0] - a[0], b[1] - a[1]; L = math.hypot(ux, uy) or 1.0
            nx += uy / L; ny += -ux / L
        L = math.hypot(nx, ny) or 1.0
        out.append([round(pts[i][0] + d * nx / L, 2), round(pts[i][1] + d * ny / L, 2)])
    return out


def _strip(pts: list, d0: float, d1: float) -> list:
    """The polygon between two parallel offsets of an open polyline (d measured along the right-hand normal)."""
    return _offset_polyline(pts, d0) + _offset_polyline(pts, d1)[::-1]


def _ring_project(p, ring: list) -> tuple[float, float]:
    """(distance, arc position) of the point on the ring boundary nearest p."""
    best = (1e18, 0.0); s = 0.0
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy or 1e-9; L = math.sqrt(L2)
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        d = math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
        if d < best[0]:
            best = (d, s + t * L)
        s += L
    return best


def _ring_slice(ring: list, s0: float, s1: float) -> list:
    """The boundary of the ring between arc positions s0 and s1, the shorter way round, in the ring's own direction."""
    n = len(ring)
    cum = [0.0]
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    per = cum[-1] or 1e-9
    fwd = (s1 - s0) % per
    if fwd > per / 2:
        s0, s1 = s1, s0; fwd = per - fwd

    def at(s):
        s %= per
        for i in range(n):
            if cum[i] <= s <= cum[i + 1] + 1e-9:
                a, b = ring[i], ring[(i + 1) % n]; L = cum[i + 1] - cum[i]
                t = (s - cum[i]) / L if L else 0.0
                return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
        return list(ring[0])
    start = s0 % per; end = start + fwd
    inner = sorted((v, k % n) for k in range(1, n + 1) for v in (cum[k], cum[k] + per) if start + 1e-6 < v < end - 1e-6)
    out = [at(start)] + [list(ring[k]) for _, k in inner] + [at(end)]
    clean = [out[0]]
    for q in out[1:]:
        if math.hypot(q[0] - clean[-1][0], q[1] - clean[-1][1]) > 0.05:
            clean.append(q)
    return clean


def _polyline_len(pts: list) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def ground_patches(T, lot_centre, radius_m: float, blocks_ll: list, lanes_ll: list, roww_ll: list, walks_ll: list, src: str) -> list[dict]:
    """Block outlines, lane strips and sidewalk strips in the lot frame.
    blocks_ll: rings in lon/lat; lanes_ll: centreline polylines; roww_ll: (lonlat, width_m); walks_ll: (name, polyline)."""
    lc = lot_centre
    near = lambda pts, r: any(math.hypot(p[0] - lc[0], p[1] - lc[1]) <= r for p in pts)
    out: list[dict] = []
    blocks = []
    for ring in blocks_ll:
        pts = _simplify([T(p) for p in _open(ring)], 0.25)
        if len(pts) < 3 or not (near(pts, radius_m + 120) or _point_in_ring(lc, pts)):
            continue
        pts = _ccw_ring(pts)
        blocks.append(pts)
        out.append({"kind": "block", "footprint": pts, "name": "block", "width_m": None, "source": f"{src} block-outlines"})
    roww = [(T(p), w) for p, w in roww_ll if w]
    for line in lanes_ll:
        pts = [T(p) for p in line]
        pts = [p for i, p in enumerate(pts) if i == 0 or math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) > 0.05]
        if len(pts) < 2 or not near(pts, radius_m + 40):
            continue
        mid = pts[len(pts) // 2]
        w = min(((math.hypot(q[0] - mid[0], q[1] - mid[1]), ww) for q, ww in roww), default=(1e9, None))
        width = w[1] if w[0] <= 12 else LANE_W_M
        out.append({"kind": "lane", "footprint": _strip(pts, width / 2, -width / 2), "name": "lane", "width_m": round(width, 2),
                    "source": f"{src} lanes · width " + ("right-of-way-widths" if w[0] <= 12 else f"{LANE_W_M} m assumed (no right-of-way-widths point on this lane)")})
    for name, line in walks_ll:
        pts = [T(p) for p in line]
        if len(pts) < 2 or not near(pts, radius_m + 40) or not blocks:
            continue
        mid = pts[len(pts) // 2]
        d, ring = min(((_ring_project(mid, r)[0], r) for r in blocks), key=lambda x: x[0])
        if d > SIDEWALK_MATCH_M:
            continue
        s0 = _ring_project(pts[0], ring)[1]; s1 = _ring_project(pts[-1], ring)[1]
        edge = _ring_slice(ring, s0, s1)
        if len(edge) < 2 or _polyline_len(edge) < 2.0:
            continue
        out.append({"kind": "sidewalk", "footprint": _strip(edge, 0.0, SIDEWALK_W_M), "name": f"{street_label(name)} sidewalk".strip(),
                    "width_m": SIDEWALK_W_M,
                    "source": f"{src} sidewalk-condition-rating (which block faces have a sidewalk) · drawn {SIDEWALK_W_M} m wide against the property line: position and width assumed"})
    return out


# ---------------------------------------------------------------------------- site context

_STREET_ABBR = {"AV": "Ave", "AVE": "Ave", "AVENUE": "Ave", "ST": "St", "STREET": "St", "DR": "Dr", "DRIVE": "Dr", "RD": "Rd", "ROAD": "Rd",
                "BLVD": "Blvd", "BOULEVARD": "Blvd", "CR": "Cres", "CRES": "Cres", "CRESCENT": "Cres", "PL": "Pl", "PLACE": "Pl", "CT": "Ct",
                "COURT": "Ct", "HWY": "Hwy", "HIGHWAY": "Hwy", "MEWS": "Mews", "WAY": "Way", "LANE": "Lane", "DIVERSION": "Diversion",
                "N": "N", "S": "S", "E": "E", "W": "W", "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW"}


def street_label(hblock: str) -> str:
    """'2200 W 10TH AV' → 'W 10th Ave'; 'KING EDWARD AV' → 'King Edward Ave'."""
    words = [w for w in str(hblock or "").strip().split() if w]
    if words and words[0].isdigit():
        words = words[1:]                                  # the hundred-block number
    out = []
    for w in words:
        u = w.upper()
        if u in _STREET_ABBR:
            out.append(_STREET_ABBR[u])
        elif u[:-2].isdigit() and u[-2:] in ("ST", "ND", "RD", "TH"):
            out.append(u[:-2] + u[-2:].lower())            # 10TH → 10th
        else:
            out.append(w.capitalize())
    return " ".join(out) or "street"


def _crown_m(diameter_cm: float) -> float:
    """Crown diameter from trunk diameter — a rough street-tree allometry: DBH 20 cm ≈ 5 m crown, 50 cm ≈ 10 m."""
    return round(max(2.0, min(14.0, 1.5 + 0.17 * diameter_cm)), 1)


def site_context(frame: dict, lot_polygon: list, parcels: list[dict] = (), streets: list[dict] = (),
                 radius_m: float = CONTEXT_RADIUS_M, fixture_origin: Optional[list] = None, lanes: list[dict] = ()) -> dict:
    """Neighbouring buildings, public trees, street names and the public realm (block outlines, lanes,
    sidewalks) around the lot, in the lot's frame.

    Buildings: 2015 outlines; height from the 2009 LiDAR footprint whose centroid falls inside the outline
    (or that contains the outline's centroid), else estimated by size. The lot's own building is dropped.
    Each neighbour is named by the address of the parcel it stands on when that parcel is in `parcels`.
    `lanes` are the map's lane centrelines (lon/lat), cut out of the block outlines as strips.
    `fixture_origin` ([lon, lat] carried by fixture parcels) switches to the synthetic block instead of Open Data."""
    T = _to_frame(frame)
    lon0, lat0 = frame["lon0"], frame["lat0"]
    fixture = fixture_origin is not None
    ground_note = ""
    if fixture:
        fps, trees_ll = _fixture_context(fixture_origin[1], fixture_origin[0])
        lidar = []
        blocks_ll, roww_ll, walks_ll = _fixture_ground(fixture_origin[1], fixture_origin[0])
    else:
        def optional(ds, r, n):
            def go():
                try:
                    return _ods_cached(ds, lon0, lat0, r, n)
                except Exception as e:                   # the public realm is decoration: never lose the neighbours over it
                    return {"error": f"{ds}: {str(e)[:80]}"}
            return go
        R = _parallel({"fp": lambda: _ods_cached(DATASETS["footprints"]["id"], lon0, lat0, radius_m, 300),
                       "lidar": lambda: _ods_cached(DATASETS["footprints_2009"]["id"], lon0, lat0, radius_m + 10, 300),
                       "trees": lambda: _ods_cached(DATASETS["trees"]["id"], lon0, lat0, radius_m, 300),
                       "parcels": lambda: _ods_cached(DATASETS["parcels"]["id"], lon0, lat0, radius_m + 10, 300),
                       "blocks": optional(DATASETS["blocks"]["id"], radius_m + 80, 40),
                       "roww": optional(DATASETS["row_widths"]["id"], radius_m + 60, 100),
                       "walks": optional(DATASETS["sidewalks"]["id"], radius_m + 40, 100)})
        errs = [R[k]["error"] for k in ("blocks", "roww", "walks") if isinstance(R[k], dict)]
        ground_note = (" · public realm incomplete: " + "; ".join(errs)) if errs else ""
        blocks_ll = [r for rec in (R["blocks"] if not isinstance(R["blocks"], dict) else []) for r in _rings(_geom(rec))]
        roww_ll = []
        for rec in (R["roww"] if not isinstance(R["roww"], dict) else []):
            g = _geom(rec); pt = g.get("coordinates") if g and g.get("type") == "Point" else None
            if pt is None and rec.get("geo_point_2d"):
                pt = [rec["geo_point_2d"]["lon"], rec["geo_point_2d"]["lat"]]
            if pt:
                roww_ll.append((pt, _row_width_m(rec.get(DATASETS["row_widths"]["field"]))))
        walks_ll = []
        for rec in (R["walks"] if not isinstance(R["walks"], dict) else []):
            g = _geom(rec)
            if g and g.get("type") in ("LineString", "MultiLineString"):
                for ln in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                    walks_ll.append((rec.get(DATASETS["sidewalks"]["name_field"]) or "", ln))
        # parcels around the lot itself, so every neighbour can be named (the map's parcels centre on the map, not the lot)
        extra = []
        for rec in R["parcels"]:
            g = _geom(rec)
            for r in _rings(g):
                extra.append({"id": str(rec.get("site_id") or rec.get("tax_coord") or ""), "ring": r,
                              "address": " ".join(str(rec[k]) for k in ("civic_number", "streetname") if rec.get(k)) or None})
        parcels = list(parcels) + [p for p in extra if p["address"]]
        fps = [{"ring": r, "height_m": None, "source": "CoV footprint 2015"} for rec in R["fp"] for r in _rings(_geom(rec))]
        hf = DATASETS["footprints_2009"]["height_fields"]
        lidar = [{"ring": r, "height_m": _first(rec, hf)} for rec in R["lidar"] for r in _rings(_geom(rec))]
        trees_ll = []
        for rec in R["trees"]:
            g = _geom(rec); pt = g.get("coordinates") if g and g.get("type") == "Point" else None
            if pt is None and rec.get("geo_point_2d"):
                pt = [rec["geo_point_2d"]["lon"], rec["geo_point_2d"]["lat"]]
            if pt:
                trees_ll.append({"lonlat": pt, "height_m": rec.get("height_m"), "diameter_cm": rec.get("diameter_cm"), "name": _first(rec, DATASETS["trees"]["name_fields"])})
    lc = _centroid(lot_polygon)
    # buildings → lot metres, drop the site's own and the sheds
    bld = []
    for fp in fps:
        pts = _simplify([T(p) for p in _open(fp["ring"])], 0.3)
        if len(pts) < 3 or _area(pts) < 8:
            continue
        c = _centroid(pts)
        if _point_in_ring(c, lot_polygon) or math.hypot(c[0] - lc[0], c[1] - lc[1]) > radius_m:
            continue
        bld.append({"pts": pts, "c": c, "area": _area(pts), "h": fp.get("height_m"), "src": fp.get("source", "")})
    # heights from the 2009 LiDAR footprints
    L = []
    for r in lidar:
        if not r["height_m"]:
            continue
        pts = [T(p) for p in _open(r["ring"])]
        if len(pts) >= 3:
            L.append({"pts": pts, "c": _centroid(pts), "area": _area(pts), "h": float(r["height_m"])})
    for b in bld:
        if b["h"] is not None:
            continue
        hits = [l for l in L if _point_in_ring(l["c"], b["pts"])] or [l for l in L if _point_in_ring(b["c"], l["pts"])]
        if hits:
            b["h"] = round(max(hits, key=lambda l: l["area"])["h"], 1); b["src"] += " · height 2009 LiDAR"
        else:
            b["h"] = EST_HOUSE_M if b["area"] > 70 else EST_GARAGE_M; b["src"] += " · height estimated (no 2009 LiDAR match)"
    # names from the parcels they stand on
    prings = [(p.get("address") or str(p.get("id")), [T(q) for q in _open(p["ring"])]) for p in parcels if p.get("ring")]
    context = []
    for b in sorted(bld, key=lambda b: math.hypot(b["c"][0] - lc[0], b["c"][1] - lc[1])):
        addr = next((a for a, r in prings if len(r) >= 3 and _point_in_ring(b["c"], r)), None)
        small = b["area"] <= 70 and b["h"] <= 4.5
        context.append({"name": (f"{addr} garage" if small else addr) if addr else ("garage" if small else "neighbour"),
                        "footprint": b["pts"], "height_m": max(2.0, float(b["h"])), "source": b["src"]})
    # trees
    trees = []
    for t in trees_ll:
        x, y = T(t["lonlat"])
        if math.hypot(x - lc[0], y - lc[1]) > radius_m:
            continue
        h = max(2.0, float(t.get("height_m") or 0) or 8.0)
        crown = min(_crown_m(float(t.get("diameter_cm") or 20)), round(0.9 * h, 1))     # a crown is never taller than the tree
        trees.append({"x": x, "y": y, "height_m": round(h, 1), "crown_m": max(1.5, crown), "name": str(t.get("name") or "tree").title()})
    # street names: the centrelines the map already fetched, renamed from the hundred-block label
    out_streets = []
    for s in streets:
        line = [T(q) for q in s.get("line", [])]
        if len(line) >= 2 and min(math.hypot(p[0] - lc[0], p[1] - lc[1]) for p in line) <= radius_m + 60:
            out_streets.append({"name": street_label(s.get("name") or "street"), "line": line})
    # public realm: block outlines, lanes cut out of them, sidewalk strips along the property lines
    ground = ground_patches(T, lc, radius_m, blocks_ll, [l.get("line", []) for l in lanes], roww_ll, walks_ll,
                            "FIXTURE" if fixture else "CoV")
    src = ("FIXTURE (synthetic block)" if fixture else
           "City of Vancouver Open Data: building-footprints-2015 (outlines), building-footprints-2009 (LiDAR heights), public-trees, public-streets, "
           "block-outlines, lanes + right-of-way-widths, sidewalk-condition-rating" + ground_note)
    return {"context": context, "trees": trees, "streets": out_streets, "ground": ground, "context_source": src}


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
            # row 0 fronts W 12th (the north street), row 1 fronts W 11th; `origin` lets site_context rebuild the same block
            parcels.append({"id": f"fx-{row}-{i}", "address": f"{2100 + i * 8} W {'12th' if row == 0 else '11th'} Ave", "ring": ring, "fixture": True, "origin": [lon, lat]})
        # wide corner lot at the east end
        x0 = -40 + 8 * W
        yA, yB = (y0, y0 + D) if sign == 1 else (y0 - D - lane_w, y0 - lane_w)
        ring = [ll(x0, yA), ll(x0 + 2 * W, yA), ll(x0 + 2 * W, yB), ll(x0, yB), ll(x0, yA)]
        parcels.append({"id": f"fx-{row}-c", "address": f"{2100 + 64} W {'12th' if row == 0 else '11th'} Ave (corner)", "ring": ring, "fixture": True, "origin": [lon, lat]})
    streets.append({"name": "W 11th Ave", "line": [ll(-80, y0 - lane_w - D - street_w / 2), ll(80, y0 - lane_w - D - street_w / 2)]})
    streets.append({"name": "W 12th Ave", "line": [ll(-80, y0 + D + street_w / 2), ll(80, y0 + D + street_w / 2)]})
    streets.append({"name": "Yew St", "line": [ll(-40 + 10 * W + street_w / 2, -120), ll(-40 + 10 * W + street_w / 2, 120)]})
    lanes.append({"line": [ll(-80, y0 - lane_w / 2), ll(80, y0 - lane_w / 2)]})
    zoning = [{"district": "RT-7 (fixture)", "rings": [[ll(-200, -200), ll(200, -200), ll(200, 200), ll(-200, 200)]]}]
    return {"center": [lon, lat], "parcels": parcels, "zoning": zoning, "streets": streets, "lanes": lanes, "fixture": True}


def _fixture_ground(lat: float, lon: float):
    """The fixture block's public realm in the City's shapes: one block outline around both rows of lots and the
    lane between them, a right-of-way-widths point on the lane (20 ft), and sidewalk lines drawn the way the
    City draws them — a schematic ~5 m off each street centreline, named by hundred block and side."""
    kx = 111320.0 * math.cos(math.radians(lat)); ky = 110540.0
    ll = lambda x, y: [lon + x / kx, lat + y / ky]
    W, D, lane_w, street_w = 10.06, 37.19, 6.0, 20.0
    y0 = 0.0
    x0, x1 = -40.0, -40.0 + 10 * W
    yS, yN = y0 - lane_w - D, y0 + D                                       # the block's south and north property lines
    block = [ll(x0, yS), ll(x1, yS), ll(x1, yN), ll(x0, yN), ll(x0, yS)]
    roww = [(ll((x0 + x1) / 2, y0 - lane_w / 2), 20 * 0.3048)]
    walks = [("2100 W 12TH AV S", [ll(x0 + 2, yN + street_w / 2 - 5), ll(x1 - 2, yN + street_w / 2 - 5)]),
             ("2100 W 11TH AV N", [ll(x0 + 2, yS - street_w / 2 + 5), ll(x1 - 2, yS - street_w / 2 + 5)]),
             ("2600 YEW ST W", [ll(x1 + street_w / 2 - 5, yS + 2), ll(x1 + street_w / 2 - 5, yN - 2)])]
    return [block], roww, walks


def _fixture_context(lat: float, lon: float):
    """Synthetic neighbours for the fixture block: a house (8.5 m) and a lane garage (3 m) on every lot,
    boulevard trees every 9 m along both streets. Same geometry as _fixture(), so the frame lines up."""
    kx = 111320.0 * math.cos(math.radians(lat)); ky = 110540.0
    ll = lambda x, y: [lon + x / kx, lat + y / ky]
    W, D, lane_w, street_w = 10.06, 37.19, 6.0, 20.0
    y0 = 0.0
    fps, trees = [], []
    rect = lambda x0, y0_, x1, y1: [ll(x0, y0_), ll(x1, y0_), ll(x1, y1), ll(x0, y1)]
    for row, sign in ((0, 1), (1, -1)):
        lots = [(-40 + i * W, W) for i in range(8)] + [(-40 + 8 * W, 2 * W)]
        for x0, w in lots:
            yA, yB = (y0, y0 + D) if sign == 1 else (y0 - D - lane_w, y0 - lane_w)
            if sign == 1:      # fronts the north street, lane to the south
                fps.append({"ring": rect(x0 + 1.2, yB - 18, x0 + w - 1.2, yB - 6), "height_m": 8.5, "source": "FIXTURE house"})
                fps.append({"ring": rect(x0 + 1, yA + 1, x0 + 7, yA + 7), "height_m": 3.0, "source": "FIXTURE garage"})
            else:
                fps.append({"ring": rect(x0 + 1.2, yA + 6, x0 + w - 1.2, yA + 18), "height_m": 8.5, "source": "FIXTURE house"})
                fps.append({"ring": rect(x0 + 1, yB - 7, x0 + 7, yB - 1), "height_m": 3.0, "source": "FIXTURE garage"})
    for x in range(-36, -40 + 10 * int(W) + 1, 9):
        trees.append({"lonlat": ll(x, y0 + D + 2.5), "height_m": 9.0, "diameter_cm": 30, "name": "Crimean linden"})
        trees.append({"lonlat": ll(x, y0 - lane_w - D - 2.5), "height_m": 7.5, "diameter_cm": 22, "name": "Red maple"})
    return fps, trees
