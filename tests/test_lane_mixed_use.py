"""
Second project: synthetic Lane Mixed-Use. Every expected value below is computed by
hand from the VBBL 2025 text/tables, independently of the code.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "data" / "projects")]
from lane_mixed_use import project
from codesheet import sheet, spatial, height_area, occupancy

SD = sheet.run_all(project, chosen={"A": "3.2.2.52"})
D = {d.key: d for s in SD.sections for d in s.dets}


def test_height_and_area():
    # L1 floor 10.10 is 0.10 m above grade → first storey; L1–L4 → 4 storeys; 15.24 × 30 = 457.2 m²
    assert D["A.first_storey"].value == "L1"
    assert D["A.building_height_storeys"].value == 4
    assert abs(D["A.building_area_m2"].value - 457) < 1
    assert D["A.height_to_top_floor_m"].value == 9.5


def test_superimposed_occupancies():
    assert set(D["A.major_occupancies"].value) == {"C", "E"}
    assert D["A.article"].value == "3.2.2.52"                    # C, ≤4 storeys sprinklered, 457 ≤ 1800
    # E portion per 3.2.2.7: E ladder at 4 storeys, 457 m², sprinklered → 3.2.2.67 (≤4 st, ≤1800) is least demanding
    assert D["A.article.E"].value == "3.2.2.67"
    # Table 3.1.3.1: C ↔ E = 2 h; floor article says 1 h; greater governs
    assert D["A.sep.L1|L2.E-C"].value == "2 h"


def test_side_walls_on_property_line():
    for face in ("East (PL)", "West (PL)"):
        for d in (x for k, x in D.items() if k.startswith(f"A.face.{face}.") and not k.endswith("summary")):
            assert d.inputs["permitted_pct"] == 0            # LD 0 → 0% in every row of Table -D
            assert d.inputs["frr_min"] == 60 and d.inputs["construction"] == "noncombustible"   # Table 3.2.3.7, 0–10%


def test_lane_face_hand_calc():
    # Residential band: 15.24 m × 3.0 m = 45.7 m² at LD 4 m. Table -D rows 40 (64%) and 50 (56%) → ≈59.4%.
    r = D["A.face.North (lane).L2"]
    assert abs(r.inputs["permitted_pct"] - 59.4) < 0.6
    # actual: 3 windows × 1.5 × 1.5 = 6.75 m² / 45.7 = 14.8%
    assert abs(r.inputs["actual_pct"] - 14.8) < 0.2
    # Table 3.2.3.7 for permitted >50–100: 45 min, cladding combustible or noncombustible
    assert r.inputs["frr_min"] == 45 and r.inputs["cladding"] == "combustible or noncombustible"


def test_street_face_unrestricted_but_wall_still_listed():
    r = D["A.face.South (street).L2"]
    assert r.inputs["permitted_pct"] == 100 and r.inputs["frr_min"] == 0
