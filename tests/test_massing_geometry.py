"""Per-storey footprints, courtyards, rooftop enclosures and imaginary-line limiting distances."""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from codesheet.massing import MassingSpec, analyze_massing, to_building_model
from test_engine_js import SPECS


def test_podium_tower_areas_and_faces():
    r = analyze_massing(MassingSpec(**SPECS["podium_tower_court"]))
    s = r["summary"]["T"]
    assert s["area"] == 40 * 36 - 16 * 12                 # podium governs; courtyard subtracted
    assert s["storeys"] == 6                              # 5 + occupied rooftop enclosure counts (3.2.1.1)
    faces = r["faces"]
    assert any("L1–L2" in k for k in faces) and any("L3–L4" in k for k in faces) and any("L5" in k for k in faces)
    b = to_building_model(MassingSpec(**SPECS["podium_tower_court"]))
    assert any("COUNTS as a storey" in n for n in b.notes) and any("courtyard edge" in n for n in b.notes)
    # tower west face at x=4 → 4 m to the west PL; podium west face at x=0 → 0 m
    west = {k: v["ld"] for k, v in faces.items() if "west" in k}
    assert west["T · west (property line) L1–L2"] == 0 and west["T · west (property line) L3–L4"] == 4 and west["T · west (property line) L5"] == 8


def test_service_enclosure_is_not_a_storey():
    spec = dict(SPECS["podium_tower_court"]); spec = MassingSpec(**spec)
    spec.blocks[0].roof.enclosure.use = "elevator machine room and stair"
    r = analyze_massing(spec)
    assert r["summary"]["T"]["storeys"] == 5
    assert any("not a storey" in n for n in r["building"]["notes"])


def test_imaginary_line_between_blocks():
    r = analyze_massing(MassingSpec(**SPECS["two_blocks_a2"]))
    f = r["faces"]["North · imaginary line to South (same lot)"]
    assert f["ld"] == 5.0 and f["exposure"] == "same_lot"   # 10 m apart → line halfway


def test_stepped_back_party_walls_keep_zero_glazing():
    r = analyze_massing(MassingSpec(**SPECS["stepback_party"]))
    f = r["faces"]
    assert f["A · east (property line) L3–L5"]["bands"][0]["actual"] == 0 and f["A · west (property line) L3–L5"]["bands"][0]["actual"] == 0
    assert f["A · south (street) L3–L5"]["bands"][0]["actual"] == 30 and f["A · south (street) L3–L5"]["ld"] == 13   # stepped face: block default, LD grows by the stepback
    assert r["summary"]["A"]["storeys"] == 5                      # service penthouse is not a storey
