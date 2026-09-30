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
