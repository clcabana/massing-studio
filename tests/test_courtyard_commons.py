"""
Golden tests on the synthetic Courtyard Commons project (data/projects/courtyard_commons.py).

Every expected value is worked by hand from the VBBL 2025 text and tables — the
arithmetic is written next to each assertion so a reviewer can check it against the
bylaw, not against the engine.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "data" / "projects")]

from courtyard_commons import project
from codesheet import height_area, occupancy, articles, separations, spatial, targets, sheet

CHOSEN = {"North": "3.2.2.51", "South": "3.2.2.51"}
HD = height_area.analyze(project)
OD = occupancy.analyze(project)
AD = articles.analyze(project, HD, OD, chosen=CHOSEN)
H = {d.key: d for d in HD}
O = {d.key: d for d in OD}
A = {d.key: d for d in AD}
SEP = {d.key: d for d in separations.analyze(project, AD)}
SP_DETS, BANDS = spatial.analyze(project)
SP = {d.key: d for d in SP_DETS}
T_DETS, T = targets.analyze(project, HD)
TD = {d.key: d for d in T_DETS}


# ---- grade, first storey, height, area ------------------------------------------------

def test_first_storey_is_the_uppermost_within_2m_of_grade():
    # Grade 10.00. North/South L1 floors at 10.50 (+0.50 m) → first storey; L2 at 15.00 is not.
    assert H["North.first_storey"].value == "L1" and H["South.first_storey"].value == "L1"
    # Parkade: P2 (4.00) and P1 (7.00) are both below grade + 2 m; the UPPERMOST wins → P1.
    assert H["Parkade.first_storey"].value == "P1"


def test_basements_carry_occupancy_but_not_height():
    assert H["North.basements"].value == "none" and H["South.basements"].value == "none"
    assert H["Parkade.basements"].value == ["P2"]
    assert H["Parkade.building_height_storeys"].value == 1          # P1 only
    assert H["Parkade.height_to_top_floor_m"].value == 0.0


def test_storeys_and_height_to_top_floor():
    # North L1..L5 = 5 storeys; L5 floor 24.0 − L1 floor 10.5 = 13.5 m
    assert H["North.building_height_storeys"].value == 5 and H["North.height_to_top_floor_m"].value == 13.5
    # South L1..L6 = 6 storeys; 27.0 − 10.5 = 16.5 m ≤ 18 m (3.2.2.51.(1)(c))
    assert H["South.building_height_storeys"].value == 6 and H["South.height_to_top_floor_m"].value == 16.5


def test_building_area_is_the_largest_storey_above_grade_per_block():
    assert H["North.building_area_m2"].value == 1000       # 50 × 20
    assert H["South.building_area_m2"].value == 1400       # 50 × 28
    assert H["Parkade.building_area_m2"].value == 2500     # P1 (50 × 50); P2 is a basement and does not count
    assert any("firewall" in f.lower() for f in H["North.building_area_m2"].flags)


# ---- major occupancies (3.1.2.1, 3.2.2.8) ----------------------------------------------

def test_ten_percent_rule_makes_the_offices_a_major_occupancy():
    # North L1 (1,000 m²): A2 = dining 300 + kitchen 100 + auditorium 150 = 550 (55 %); D = offices 150 (15 %) > 10 %.
    v = O["North.major_occupancies"].value
    assert set(["C", "A2"]) <= set(v) and "D" in v
    assert any("D" in f and "10%" in f for f in O["North.major_occupancies"].flags)   # major by area, not declared


def test_declared_occupancy_governs_the_parkade_list():
    # P1 (2,500 m²): F3 parking 1,800 + storage 200 = 2,000 (80 %); A2 room 300 (12 %) — both over 10 %.
    # Declared [A2]: honoured; F3 is listed as subsidiary rather than promoted.
    assert O["Parkade.major_occupancies"].value == ["A2"]
    assert "F3" in O["Parkade.major_occupancies"].because
    assert not any("Unclassified" in f for blk in ("North", "South", "Parkade") for f in O[f"{blk}.major_occupancies"].flags)


# ---- governing article (3.2.2) -----------------------------------------------------------

def test_north_designer_choice_honoured_with_candidates():
    # Group C, 5 storeys, 13.5 m, 1,000 m², sprinklered: 3.2.2.47 (any), .48 (≤12 st, ≤50 m, ≤6,000),
    # .49 (≤6 st, ≤7,200 at 5), .51 (≤6 st, ≤18 m, ≤1,800 at 5) qualify; .52 (≤4 st) and .55 (≤3 st) do not.
    assert set(A["North.article_candidates"].value) == {"3.2.2.47", "3.2.2.48", "3.2.2.49", "3.2.2.51"}
    d = A["North.article"]
    assert d.value == "3.2.2.51" and d.inputs["chosen_by_designer"] is True
    assert any("Group A2" in f and "(5)(a)" in f for f in d.flags)      # admitted below the 3rd storey
    assert any("Group D" in f for f in d.flags)                          # D has no ladder encoded → flagged, never silent


def test_south_qualifies_at_six_storeys_under_the_area_cap():
    # 6 storeys, 16.5 m, 1,400 m² ≤ 1,500 m² (3.2.2.51 at 6 storeys)
    d = A["South.article"]
    assert d.value == "3.2.2.51" and d.inputs["chosen_by_designer"] is True
    assert not any(f.startswith("DESIGNER SELECTED") for f in d.flags)


def test_refused_designer_choice_falls_back_and_says_so():
    # 3.2.2.52 allows 4 storeys; South has 6. The least demanding qualifying rung is .51
    # (1 h floors, combustible permitted) — ahead of .49 (noncombustible) and .48/.47 (2 h floors).
    ad = articles.analyze(project, HD, OD, chosen={"South": "3.2.2.52"})
    d = next(x for x in ad if x.key == "South.article")
    assert d.value == "3.2.2.51" and d.inputs["chosen_by_designer"] is False
    assert d.flags[0].startswith("DESIGNER SELECTED 3.2.2.52") and "≤ 4 storeys" in d.flags[0]


def test_parkade_on_the_a2_ladder_with_a_basement():
    # 1 storey, 2,500 m², sprinklered, 2 streets, basement present:
    #   3.2.2.25 Table: 1 storey facing 2 streets → 2,000 m² < 2,500 ✗
    #   3.2.2.26: ≤ 4,800 m² at 1 storey ✓        3.2.2.27: 1,200 m² (no 2,400 bonus — there is a basement) ✗
    #   3.2.2.28: 500 m² facing 2 streets ✗       .23 and .24 also qualify but are more demanding
    assert A["Parkade.article"].value == "3.2.2.26"
    assert set(A["Parkade.article_candidates"].value) == {"3.2.2.23", "3.2.2.24", "3.2.2.26"}
    assert A["Parkade.req.Construction"].value == "noncombustible (declared)"      # declared over the permission
    assert A["Parkade.req.3.2.1.2 slab"].clauses[0].id == "3.2.1.2"


def test_requirement_lines_follow_the_article():
    assert A["North.req.Construction"].value == "combustible or noncombustible"
    assert A["North.req.Floor assemblies"].value == "fire separations, FRR ≥ 1 h"
    assert A["North.req.Roof assemblies"].value == "FRR ≥ 1 h"


# ---- fire separations (3.1.3) ------------------------------------------------------------

def test_note_3_raises_c_over_a2_to_two_hours_under_3_2_2_51():
    assert SEP["North.sep.L1|L2.A2-C"].value == "2 h"
    assert "Note (3)" in SEP["North.sep.L1|L2.A2-C"].because


def test_same_storey_pair_uses_the_table():
    assert SEP["North.sep.L1.A2-D"].value == "1 h"                     # Table 3.1.3.1: A2 ↔ D = 1 h


def test_ancillary_rooms_inherit_and_create_no_separations():
    assert not any(k.startswith("North.sep.L2") for k in SEP)          # the lounge is Group C like the suites
    assert not any(k.startswith("South.sep.") for k in SEP)


# ---- spatial separation (3.2.3) ----------------------------------------------------------

def test_north_face_bands_on_the_150_row():
    # 50 m face; L1 band 4.5 m → 225 m², L2–L5 bands 3.0 m → 150 m²: all on the "150 or more" row of
    # Table 3.2.3.1-D. LD 4.6 m interpolates between 30 % (4 m) and 40 % (5 m) → 36 %.
    N = {r.label: r for r in BANDS["North (PL)"]}
    assert list(N) == ["L1", "L2", "L3", "L4", "L5"]
    for lvl in N:
        assert N[lvl].permitted_pct == 36.0, lvl
        # Table 3.2.3.7, permitted > 25 to 50 %: 45 min, noncombustible cladding
        assert N[lvl].frr_min == 45 and N[lvl].cladding == "noncombustible"
    # stated actuals: 30, 20, 20, 40, 15 — only L4 exceeds
    assert [N[l].actual_pct for l in N] == [30, 20, 20, 40, 15]
    assert [N[l].ok for l in N] == [True, True, True, False, True]
    assert any("exceed" in f.lower() for f in SP["North.face.North (PL).L4"].flags)
    assert SP["North.face.North (PL).L2"].inputs["actual_source"] == "stated on drawings"


def test_street_faces_unrestricted_but_schematic_windows_flagged():
    for face in ("West (street)", "South (street)"):
        for r in BANDS[face]:
            assert r.permitted_pct == 100 and r.frr_min == 0, face      # LD ≥ 9 m → 100 % on every row
    d = [x for k, x in SP.items() if k.startswith("South.face.South (street).") and not k.endswith("summary")]
    assert d and all(any("synthesized" in f for f in x.flags) for x in d)


# ---- occupant load, egress, washrooms (3.1.17, 3.4, 3.7) --------------------------------------

def test_occupant_load_rows_by_table_3_1_17_1():
    st = {(blk, s["label"]): s for blk, v in T.items() if blk != "_site" for s in v["storeys"]}
    # North L1: dining 300 ÷ 1.2 = 250, −20 % → 240 ÷ 1.2 = 200 · kitchen 100 ÷ 9.3 → 11 · auditorium 120 seats
    #           office 150 ÷ 9.3 → 17 · lobby 50 ÷ 1.85 → 28 gross, 100 % deducted → 0
    assert (st["North", "L1"]["gross"], st["North", "L1"]["net"]) == (250 + 11 + 120 + 17 + 28, 200 + 11 + 120 + 17)
    # North L2: 24 sleeping rooms × 2 = 48; lounge 60 ÷ 1.85 → 33 gross, deducted to 0
    assert (st["North", "L2"]["gross"], st["North", "L2"]["net"]) == (48 + 33, 48)
    rows = {r["zone"]: r for r in st["North", "L2"]["rows"]}
    assert rows["Student suites L2"]["basis"].startswith("24 sleeping rooms × 2")
    # Parkade P1: parking 1,800 ÷ 46 → 40 · room 300 ÷ 1.85 → 163 gross, 240 ÷ 1.85 → 130 net · bikes 200 ÷ 46 → 5
    assert (st["Parkade", "P1"]["gross"], st["Parkade", "P1"]["net"]) == (40 + 163 + 5, 40 + 130 + 5)
    assert st["Parkade", "P2"]["net"] == 55                             # 2,500 ÷ 46 = 54.3 → 55
    # South L1: lobby 40 ÷ 1.85 → 22 gross / 0 net; 10 rooms × 2 = 20
    assert (st["South", "L1"]["gross"], st["South", "L1"]["net"]) == (42, 20)


def test_block_and_site_totals():
    assert T["North"]["total"] == {"gross": 426 + 3 * 81 + 73, "net": 348 + 3 * 48 + 40}       # 742 / 532
    assert T["South"]["total"] == {"gross": 42 + 5 * 32, "net": 20 + 5 * 32}                   # 202 / 180
    assert T["Parkade"]["total"] == {"gross": 55 + 208, "net": 55 + 175}                       # 263 / 230
    assert T["_site"] == {"gross": 742 + 202 + 263, "net": 532 + 180 + 230}                    # 1,207 / 942
    assert TD["site.occupant_load_total"].value == 942


def test_exits_travel_and_widths_north_l1():
    l1 = next(s for s in T["North"]["storeys"] if s["label"] == "L1")
    assert l1["exits"] == 2 and l1["travel_m"] == 45                     # > 2 storeys → 2 exits; sprinklered → 45 m
    # 348 persons × 8 mm = 2,784 mm aggregate stair ÷ 2 = 1,392; doors 348 × 6.1 = 2,122.8 → 2,123 ÷ 2 → 1,062
    assert l1["widths"]["stair_aggregate_mm"] == 2784 and l1["widths"]["stair_each_mm"] == 1392
    assert l1["widths"]["door_each_mm"] == 1062
    assert T["North"]["egress"] == {"exits": 2, "governing_storey": "L1", "governing_load": 348, "stair_each_mm": 1392, "door_each_mm": 1062, "travel_m": 45}


def test_min_stair_width_steps_up_above_two_storeys():
    # South L2 (32 persons × 8 = 256 ÷ 2 = 128 mm) → Table 3.4.3.2-A minimum 900 mm; L4 sits > 2 storeys up → 1,100 mm
    st = {s["label"]: s for s in T["South"]["storeys"]}
    assert st["L2"]["widths"]["stair_each_mm"] == 900 and st["L4"]["widths"]["stair_each_mm"] == 1100


def test_parking_level_travel_distance():
    p2 = next(s for s in T["Parkade"]["storeys"] if s["label"] == "P2")
    assert p2["travel_m"] == 60 and p2["exits"] == 2                    # storage garage (1)(e); 55 persons > 60? no — but 1 storey ≤ 2 … load 55 ≤ 60, area 2,500 > 300 → 2 exits


def test_washrooms_by_group_on_north_l1():
    wash = {w["group"]: w for w in next(s for s in T["North"]["storeys"] if s["label"] == "L1")["washrooms"]}
    # A2 load 200 + 11 + 120 = 331 → 166 of each sex → Table 3.7.2.2-A row 151–175: 4 M, 7 F; lavatories 2 + 4; urinals ⌊4 × ⅔⌋ = 2
    a2 = wash["A2"]
    assert a2["load"] == 331 and (a2["male_wc"], a2["female_wc"]) == (4, 7)
    assert a2["lavatories"] == {"male": 2, "female": 4} and a2["urinals_max"] == 2
    # D load 17 → 9 of each sex → Table -B: 1 + 1; ≤ 25 persons and ≤ 200 m² → both single-room alternatives offered
    d = wash["D"]
    assert (d["male_wc"], d["female_wc"]) == (1, 1)
    assert any("3.7.2.2.(2)" in x for x in d["alternatives"]) and any("(15)" in x for x in d["alternatives"])


def test_dwelling_units_get_one_wc_each():
    l2 = next(s for s in T["North"]["storeys"] if s["label"] == "L2")["washrooms"][0]
    assert l2["wc_total"] == 20 and l2["rule"].startswith("at least one water closet per dwelling unit")


def test_gender_neutral_count_vbbl_3_7_2_9():
    # North non-residential load = L1 only = 348 → 1 + ⌈(348 − 200) ÷ 100⌉ = 3
    assert TD["North.gender_neutral_wc"].value == 3 and TD["North.gender_neutral_wc"].clauses[0].id == "3.7.2.9"
    # Parkade: 55 + 40 + 130 + 5 = 230 → 1 + 1 = 2;  South is all residential → 0
    assert TD["Parkade.gender_neutral_wc"].value == 2 and TD["South.gender_neutral_wc"].value == 0


# ---- the whole sheet -----------------------------------------------------------------------

def test_every_determination_is_cited_with_a_page():
    sd = sheet.run_all(project, chosen=CHOSEN)
    dets = [d for s in sd.sections for d in s.dets]
    assert len(dets) > 100
    for d in dets:
        assert d.clauses, f"{d.key} has no clause citation"
        assert all(c.page for c in d.clauses), f"{d.key} citation missing page"
