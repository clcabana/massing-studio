"""app.parcels: the Open Data fetch pages at the API's 100-record cap, and a parcel becomes a Lot."""
import math

import pytest

from app import parcels


def _fake_api(total: int):
    """Stand-in for the Explore API: `total` records, and it rejects limit > 100 like the real one."""
    calls = []

    def page(ds, where, limit, offset):
        assert 0 < limit <= parcels.PAGE, f"limit {limit} would be a 400 from the City"
        calls.append((limit, offset))
        return [{"i": i} for i in range(offset, min(offset + limit, total))]

    return page, calls


def test_ods_pages_past_100(monkeypatch):
    page, calls = _fake_api(total=250)
    monkeypatch.setattr(parcels, "_ods_page", page)
    recs = parcels._ods("property-parcel-polygons", -123.158, 49.2627, 220, limit=300)
    assert [r["i"] for r in recs] == list(range(250))
    assert calls == [(100, 0), (100, 100), (100, 200)]


def test_ods_honours_limit(monkeypatch):
    page, calls = _fake_api(total=1000)
    monkeypatch.setattr(parcels, "_ods_page", page)
    recs = parcels._ods("public-streets", -123.158, 49.2627, 220, limit=150)
    assert len(recs) == 150
    assert calls == [(100, 0), (50, 100)]


def test_ods_single_short_page(monkeypatch):
    page, calls = _fake_api(total=7)
    monkeypatch.setattr(parcels, "_ods_page", page)
    assert len(parcels._ods("lanes", -123.158, 49.2627, 60, limit=200)) == 7
    assert calls == [(100, 0)]


def test_nearby_reads_live_shaped_records(monkeypatch):
    """Records shaped like the live API (geom is a GeoJSON Feature, fields as of 2026-09)."""
    ring = [[-123.158, 49.2627], [-123.1578, 49.2627], [-123.1578, 49.2629], [-123.158, 49.2629], [-123.158, 49.2627]]
    by_ds = {
        "property-parcel-polygons": [{"civic_number": "2150", "streetname": "W 11TH AV", "site_id": "S1", "tax_coord": "T1",
                                      "geom": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}}}],
        "zoning-districts-and-labels": [{"zoning_district": "RT-7", "zoning_classification": "Two-Family",
                                         "geom": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}}}],
        "public-streets": [{"hblock": "2100 W 11TH AV", "streetuse": "Residential",
                            "geom": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-123.159, 49.2626], [-123.157, 49.2626]]}}}],
        "lanes": [{"geom": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-123.159, 49.26295], [-123.157, 49.26295]]}}}],
    }
    monkeypatch.setattr(parcels, "FIXTURE", False)
    monkeypatch.setattr(parcels, "_CACHE", {})
    monkeypatch.setattr(parcels, "_ods_page", lambda ds, where, limit, offset: by_ds[ds] if offset == 0 else [])
    out = parcels.nearby(49.2627, -123.158, 120)
    assert out["fixture"] is False
    assert out["parcels"][0]["address"] == "2150 W 11TH AV" and out["parcels"][0]["id"] == "S1"
    assert out["zoning"][0]["district"] == "RT-7"
    assert out["streets"][0]["name"] == "2100 W 11TH AV"
    assert len(out["lanes"]) == 1


def test_fixture_parcel_to_lot():
    data = parcels._fixture(49.2627, -123.158)
    p = next(x for x in data["parcels"] if x["id"] == "fx-0-0")
    res = parcels.parcel_to_lot(p, data["streets"], data["lanes"], data["zoning"])
    lot = res["lot"]
    kinds = [e["kind"] for e in lot["edge_kinds"]]
    assert kinds[0] == "street" and "lane" in kinds and kinds.count("neighbour") == 2
    assert math.isclose(lot["width_m"], 10.06, abs_tol=0.05) and math.isclose(lot["depth_m"], 37.19, abs_tol=0.05)
    assert res["area_m2"] == pytest.approx(10.06 * 37.19, rel=0.01)
    assert lot["zoning"] == "RT-7 (fixture)" and lot["source"].startswith("FIXTURE")


def test_street_label_from_hundred_block():
    assert parcels.street_label("2200 W 10TH AV") == "W 10th Ave"
    assert parcels.street_label("KING EDWARD AV") == "King Edward Ave"
    assert parcels.street_label("ARBUTUS ST") == "Arbutus St"
    assert parcels.street_label("W 11th Ave") == "W 11th Ave"
    assert parcels.street_label("") == "street"


def test_fixture_site_context_in_the_lot_frame():
    """Neighbours, trees and street names land in the picked lot's rotated frame; the lot's own house is dropped."""
    data = parcels._fixture(49.2627, -123.158)
    p = next(x for x in data["parcels"] if x["id"] == "fx-0-3")          # a row-0 lot: fronts north, so the frame is rotated 180°
    res = parcels.parcel_to_lot(p, data["streets"], data["lanes"], data["zoning"])
    ctx = parcels.site_context(res["frame"], res["lot"]["polygon"], data["parcels"], data["streets"], fixture_origin=p["origin"])
    poly = res["lot"]["polygon"]
    assert p["address"].startswith("2124 W 12th")                          # row 0 fronts W 12th, and is addressed on it
    assert ctx["context"], "no neighbours"
    for c in ctx["context"]:
        cx = sum(q[0] for q in c["footprint"]) / len(c["footprint"]); cy = sum(q[1] for q in c["footprint"]) / len(c["footprint"])
        assert not parcels._point_in_ring((cx, cy), poly), "the site's own building must not be a neighbour"
        assert c["height_m"] in (8.5, 3.0) and c["source"].startswith("FIXTURE")
    names = {c["name"] for c in ctx["context"]}
    assert any(n.startswith("21") and "Ave" in n for n in names), names         # named by the parcel's address
    assert any(n.endswith("garage") for n in names)
    # the two immediate neighbours' houses sit beside the lot (x just outside 0..W), at the same depth band
    W = res["lot"]["width_m"]
    def xr(c): return min(q[0] for q in c["footprint"]), max(q[0] for q in c["footprint"])
    beside = [c for c in ctx["context"] if c["height_m"] == 8.5 and (-W - 1 < xr(c)[1] < 0.5 or W - 0.5 < xr(c)[0] < 2 * W + 1)
              and min(q[1] for q in c["footprint"]) < res["lot"]["depth_m"]]          # same side of the lane
    assert len(beside) >= 2, [(c["name"], xr(c)) for c in ctx["context"]]
    assert {c["name"] for c in beside} >= {"2116 W 12th Ave", "2132 W 12th Ave"}      # the two next-door houses, named by their parcels
    assert all(0 < min(q[1] for q in c["footprint"]) < 8 for c in beside), "next-door houses line up with the lot's front yard"
    assert not any(c["name"] == "neighbour" for c in ctx["context"]), "every fixture building stands on a fixture parcel"
    assert ctx["trees"] and all(t["height_m"] > 0 and 2 <= t["crown_m"] <= 14 for t in ctx["trees"])
    assert {s["name"] for s in ctx["streets"]} >= {"W 12th Ave", "W 11th Ave"}
    # street in front: the lot fronts W 12th, which the frame puts below the lot (y < 0)
    front = [s for s in ctx["streets"] if s["name"] == "W 12th Ave"][0]
    assert all(q[1] < 0 for q in front["line"])


def test_site_context_reads_live_shaped_records_and_lidar_heights(monkeypatch):
    """2015 outline + a 2009 LiDAR footprint under it → that height; no match → estimated; trees and names flow through."""
    lon0, lat0 = -123.158, 49.2627
    kx = 111320.0 * math.cos(math.radians(lat0)); ky = 110540.0
    ll = lambda x, y: [lon0 + x / kx, lat0 + y / ky]                    # metres east/north of the frame origin
    frame = {"lon0": lon0, "lat0": lat0, "ang_deg": 0.0, "dx": -20.0, "dy": -20.0}   # lot metres = proj metres + 20
    lot_poly = [[20, 20], [30, 20], [30, 57], [20, 57]]
    feat = lambda typ, coords: {"type": "Feature", "geometry": {"type": typ, "coordinates": coords}}
    ring = lambda x0, y0, x1, y1: [ll(x0, y0), ll(x1, y0), ll(x1, y1), ll(x0, y1), ll(x0, y0)]
    by_ds = {
        "building-footprints-2015": [
            {"object_id": 1, "geom": feat("Polygon", [ring(12, 2, 22, 17)])},         # east neighbour → lot x 32..42
            {"object_id": 2, "geom": feat("Polygon", [ring(2, 2, 8, 17)])},           # the site's own house (inside the lot) → dropped
            {"object_id": 3, "geom": feat("MultiPolygon", [[ring(-12, 2, -2, 17)]])},  # west neighbour, no LiDAR → estimated
            {"object_id": 4, "geom": feat("Polygon", [ring(14, 25, 16, 27)])},        # a 4 m² shed → dropped
        ],
        "building-footprints-2009": [{"hgt_agl": 7.4, "maxht_m": 8.1, "geom": feat("Polygon", [ring(12.5, 2.5, 21.5, 16.5)])}],
        "public-trees": [{"common_name": "CRIMEAN LINDEN", "height_m": 9.1, "diameter_cm": 30, "geom": feat("Point", ll(5, -4))},
                         {"common_name": "RED MAPLE", "height_m": None, "diameter_cm": None, "geo_point_2d": {"lon": ll(15, -4)[0], "lat": ll(15, -4)[1]}}],
        "property-parcel-polygons": [{"civic_number": "2168", "streetname": "W 11TH AV", "site_id": "P-west",       # names the west neighbour
                                      "geom": feat("Polygon", [ring(-14, 0, 0, 37)])}],
    }
    monkeypatch.setattr(parcels, "_CACHE", {})
    monkeypatch.setattr(parcels, "_ods_page", lambda ds, where, limit, offset: by_ds[ds] if offset == 0 else [])
    parcels_near = [{"id": "P-east", "address": "2158 W 11TH AV", "ring": ring(10, 0, 24, 37)}]
    streets = [{"name": "2100 W 11TH AV", "line": [ll(-40, -10), ll(60, -10)]}, {"name": "far away", "line": [ll(500, 500), ll(600, 500)]}]
    ctx = parcels.site_context(frame, lot_poly, parcels_near, streets)
    assert [c["name"] for c in ctx["context"]] == ["2158 W 11TH AV", "2168 W 11TH AV"]   # east named by the map's parcel, west by the one fetched around the lot
    east, west = ctx["context"]
    assert east["height_m"] == 7.4 and "2009 LiDAR" in east["source"]
    assert east["footprint"][0] == [32.0, 22.0] or [32.0, 22.0] in east["footprint"]
    assert west["height_m"] == parcels.EST_HOUSE_M and "estimated" in west["source"]
    assert [t["name"] for t in ctx["trees"]] == ["Crimean Linden", "Red Maple"]
    assert ctx["trees"][0]["height_m"] == 9.1 and ctx["trees"][0]["crown_m"] == pytest.approx(1.5 + 0.17 * 30, abs=0.1)
    assert ctx["trees"][1]["height_m"] == 8.0 and ctx["trees"][0]["x"] == pytest.approx(25.0, abs=0.05)
    assert [s["name"] for s in ctx["streets"]] == ["W 11th Ave"] and ctx["streets"][0]["line"][0][1] == pytest.approx(10.0, abs=0.05)
    assert "building-footprints-2015" in ctx["context_source"]
