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
The dataset ids and the attribute names we look for live in DATASETS below so
they can be corrected without touching the logic if the City renames them.

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

import json, math, os, urllib.parse, urllib.request
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
}
STREET_MAX_M, LANE_MAX_M = 28.0, 9.0      # a centreline farther than this is not "this edge's" street/lane
CONTEXT_RADIUS_M = 90.0                    # neighbours, trees and street names this far from the lot centre
EST_HOUSE_M, EST_GARAGE_M = 8.5, 3.0       # heights when no 2009 LiDAR footprint matches (built after 2009)
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
                 radius_m: float = CONTEXT_RADIUS_M, fixture_origin: Optional[list] = None) -> dict:
    """Neighbouring buildings, public trees and street names around the lot, in the lot's frame.

    Buildings: 2015 outlines; height from the 2009 LiDAR footprint whose centroid falls inside the outline
    (or that contains the outline's centroid), else estimated by size. The lot's own building is dropped.
    Each neighbour is named by the address of the parcel it stands on when that parcel is in `parcels`.
    `fixture_origin` ([lon, lat] carried by fixture parcels) switches to the synthetic block instead of Open Data."""
    T = _to_frame(frame)
    lon0, lat0 = frame["lon0"], frame["lat0"]
    fixture = fixture_origin is not None
    if fixture:
        fps, trees_ll = _fixture_context(fixture_origin[1], fixture_origin[0])
        lidar = []
    else:
        fps = [{"ring": r, "height_m": None, "source": "CoV footprint 2015"} for rec in _ods(DATASETS["footprints"]["id"], lon0, lat0, radius_m, 300) for r in _rings(_geom(rec))]
        hf = DATASETS["footprints_2009"]["height_fields"]
        lidar = [{"ring": r, "height_m": _first(rec, hf)} for rec in _ods(DATASETS["footprints_2009"]["id"], lon0, lat0, radius_m + 10, 300) for r in _rings(_geom(rec))]
        trees_ll = []
        for rec in _ods(DATASETS["trees"]["id"], lon0, lat0, radius_m, 300):
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
        h = float(t.get("height_m") or 0) or 8.0
        trees.append({"x": x, "y": y, "height_m": round(max(2.0, h), 1), "crown_m": _crown_m(float(t.get("diameter_cm") or 20)),
                      "name": str(t.get("name") or "tree").title()})
    # street names: the centrelines the map already fetched, renamed from the hundred-block label
    out_streets = []
    for s in streets:
        line = [T(q) for q in s.get("line", [])]
        if len(line) >= 2 and min(math.hypot(p[0] - lc[0], p[1] - lc[1]) for p in line) <= radius_m + 60:
            out_streets.append({"name": street_label(s.get("name") or "street"), "line": line})
    src = ("FIXTURE (synthetic block)" if fixture else
           "City of Vancouver Open Data: building-footprints-2015 (outlines), building-footprints-2009 (LiDAR heights), public-trees, public-streets")
    return {"context": context, "trees": trees, "streets": out_streets, "context_source": src}


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
