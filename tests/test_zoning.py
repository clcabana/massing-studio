"""
codesheet.zoning: the district table, the geometry of yards, FSR / coverage / height arithmetic and the
outright / conditional / exceeds tiers. Expected values are worked by hand from the spec geometry and the
figures in data/zoning/vancouver/districts.json.
"""
import copy, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import pytest

from codesheet import zoning
from codesheet.massing import MassingSpec, Lot, analyze_massing
from test_engine_js import SPECS


def _spec(name, **lot_overrides):
    s = copy.deepcopy(SPECS[name]); s["lot"] = {**s["lot"], **lot_overrides}
    return MassingSpec(**s)


def _z(name, **lot):
    return analyze_massing(_spec(name, **lot))


def test_code_normalisation_and_aliases():
    assert zoning.normalize_code("CD-1 (123)") == "CD-1"
    assert zoning.normalize_code(" rt-7 (fixture) ") == "RT-7"
    assert zoning.normalize_code("") is None
    r, notes = zoning.district_rules("RS-1")                       # replaced by R1-1 in 2023
    assert r.district == "RS-1" and r.height_m == 11.5 and r.fsr == 0.7 and any("R1-1" in n for n in notes)
    r, notes = zoning.district_rules("RM-4N")
    assert r.fsr_conditional == 1.45 and r.front_m == 6.1
    r, notes = zoning.district_rules("FM-1")
    assert r is None and "not in the district table" in notes[0]


def test_lane_lot_as_c2_hand_calc():
    # 15.24 × 37.19 lot = 566.8 m²; 4 storeys × (15.24 × 30 = 457.2) = 1,828.8 m² → FSR 3.23 > 3.0
    r = _z("lane_mixed", zoning="C-2")
    z = r["zoning"]
    assert z["district"] == "C-2" and z["site_area_m2"] == 566.8 and z["floor_area_m2"] == 1828.8
    items = {i["what"]: i for i in z["items"]}
    assert items["floor space ratio"]["value"] == 3.23 and items["floor space ratio"]["status"] == "exceeds" and items["floor space ratio"]["headroom"] == -0.23
    # grade 10, first floor +0.1, 4.2 + 3 + 3 + 3 = 13.2 → roof at 13.3 m ≤ 13.8 outright; parapet 0.6 m rises past it
    assert items["height"]["value"] == 13.3 and items["height"]["status"] == "outright" and items["height"]["headroom"] == 0.5
    assert items["storeys"]["value"] == 4 and items["storeys"]["outright"] == 4 and items["storeys"]["conditional"] == 6 and items["storeys"]["status"] == "outright"
    assert "site coverage" not in items                              # C-2 has no coverage figure encoded
    yards = {y["edge"]: y for y in z["yards"]}
    assert yards["south"]["role"] == "front" and yards["south"]["measured_m"] == 0.0 and yards["south"]["ok"] is True
    assert yards["north"]["role"] == "rear" and yards["north"]["kind"] == "lane" and yards["north"]["measured_m"] == 7.19 and yards["north"]["ok"] is None
    assert yards["east"]["role"] == "side" and yards["west"]["role"] == "side"
    assert z["uses"][0]["ok"] and "Group E → retail: outright" in z["uses"][0]["text"] and "Group C → dwelling: conditional" in z["uses"][0]["text"]
    assert z["status"] == "exceeds"
    D = {d["key"]: d for d in r["determinations"]}
    assert D["site.zoning.height"]["value"] == 13.3 and D["site.zoning.storeys"]["value"] == 4
    assert any("parapet" in f for f in D["site.zoning.height"]["flags"])
    assert any("counted twice" in f for f in D["site.zoning.fsr"]["flags"])          # L1 is 4.2 m floor-to-floor
    assert any("conditional approval use" in f for f in D["site.zoning.uses.A"]["flags"])


def test_corner_polygon_as_rm4_roles_and_yards():
    # lot (0,0)(30,0)(30,30)(0,12) = 630 m²; footprint (2,2)(26,2)(26,26)(2,14) = 432 m² × 2 storeys → FSR 1.37
    r = _z("corner_poly_unsprinklered", zoning="RM-4")
    z = r["zoning"]
    assert z["site_area_m2"] == 630.0 and z["floor_area_m2"] == 864.0
    items = {i["what"]: i for i in z["items"]}
    assert items["floor space ratio"]["value"] == 1.37 and items["floor space ratio"]["status"] == "conditional"    # 0.75 outright, 1.45 conditional
    assert items["height"]["value"] == 6.2 and items["height"]["status"] == "outright"                              # grade 5, floor 5.2, 2 × 3.0
    roles = {y["edge"]: y["role"] for y in z["yards"]}
    assert roles == {"edge 0": "front", "edge 1": "flank", "edge 2": "rear", "edge 3": "side"}                     # lane is the rear, 2nd street flanks
    y = {v["edge"]: v for v in z["yards"]}
    assert y["edge 0"]["measured_m"] == 2.0 and y["edge 0"]["required_m"] == 6.1 and y["edge 0"]["ok"] is False
    assert y["edge 1"]["measured_m"] == 4.0 and y["edge 1"]["required_m"] == 2.1 and y["edge 1"]["ok"] is True
    assert y["edge 3"]["measured_m"] == 2.0 and y["edge 3"]["required_m"] == 2.1 and y["edge 3"]["ok"] is False
    assert y["edge 2"]["measured_m"] == -0.69 and y["edge 2"]["ok"] is False          # the footprint corner (2,14) pokes past the diagonal lot line
    assert z["site"]["ok"] and z["site"]["area_m2"] == 630.0                            # ≥ 550 m² minimum
    assert z["status"] == "exceeds"
    flags = [f for b, f in r["flags"]]
    assert any("rear (m) figure is transcribed but not verified" in f for f in flags)   # RM-4 rear yard is listed as unverified
    assert any("Corner lot" in f for f in flags)


def test_unknown_and_missing_district():
    z = _z("lane_mixed", zoning=None)["zoning"]
    assert z["status"] == "unknown" and z["district"] is None
    z = _z("lane_mixed", zoning="FM-1")["zoning"]
    assert z["status"] == "unknown" and z["district"] == "FM-1" and any("not in the district table" in n for n in z["notes"])


def test_use_not_permitted_in_r1_1():
    r = _z("small_two_storey_office", zoning="R1-1")       # retail + dental clinic on a residential lot
    z = r["zoning"]
    assert not z["uses"][0]["ok"] and z["status"] == "exceeds"
    flags = [f for b, f in r["flags"]]
    assert any("Group D" in f and "not a listed use in R1-1" in f for f in flags)
    assert any("Group E" in f and "neighbourhood grocery" in f for f in flags) or any("retail: conditional" in u["text"] for u in z["uses"])
    items = {i["what"]: i for i in z["items"]}
    assert items["site coverage"]["value"] == pytest.approx(100 * 12 * 18 / 600, abs=0.05)      # 216 of 600 m² = 36 %


def test_designer_override_and_toa():
    rules = {"district": "CD-1", "height_m": 20.0, "fsr": 2.0, "front_m": 3.0, "uses": {"dwelling": "outright", "assembly": "outright"}, "designer_edited": True}
    r = _z("two_blocks_a2", zoning="CD-1 (512)", zoning_rules=rules)
    z = r["zoning"]
    assert z["district"] == "CD-1" and z["designer_edited"]
    items = {i["what"]: i for i in z["items"]}
    assert items["height"]["outright"] == 20.0 and items["floor space ratio"]["outright"] == 2.0
    assert "storeys" not in items                                   # no storey cap given, no TOA
    assert all(u["ok"] for u in z["uses"])
    # TOA tier on the C-2 lane lot: 12 storeys / FSR 4.0 may not be refused → the 3.23 FSR becomes 'toa'
    r = _z("lane_mixed", zoning="C-2", zoning_rules={"toa": "station_400"})
    items = {i["what"]: i for i in r["zoning"]["items"]}
    assert items["floor space ratio"]["toa"] == 4.0 and items["floor space ratio"]["status"] == "toa" and items["floor space ratio"]["cap"] == 4.0
    assert items["storeys"]["cap"] == 12
    assert r["zoning"]["status"] == "toa"


def test_sheet_and_workbook_carry_a_zoning_section(tmp_path):
    from codesheet import sheet, xlsx_sheet, height_area
    from codesheet.massing import to_building_model
    m = _spec("lane_mixed", zoning="C-2")
    b = to_building_model(m)
    zd, _ = zoning.analyze(m, b, height_area.analyze(b))
    sd = sheet.run_all(b, zoning=zd)
    assert sd.sections[0].number == "0" and sd.sections[0].dets and sd.sections[0].dets[0].key == "site.zoning.district"
    html = sheet.render_html(sd)
    assert "Zoning — district schedule limits" in html and "C-2 District Schedule" in html
    p = xlsx_sheet.to_xlsx(sd, tmp_path / "z.xlsx")
    assert p.exists()
    assert "0" not in [s.number for s in sheet.run_all(b).sections]           # without zoning dets the section is left out
