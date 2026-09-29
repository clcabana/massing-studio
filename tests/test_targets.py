"""
Occupant load, egress and washroom rules — hand-worked code arithmetic on the
functions themselves. Whole-project totals are in test_courtyard_commons.py.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from codesheet import targets
from codesheet.model import OccupancyGroup as O, Zone


def test_rounding_is_ceiling():
    assert targets.ceil(2500 / 46) == 55 and targets.ceil(150 / 1.85) == 82 and targets.ceil(9 / 9.3) == 1
    assert targets.ceil(100 / 1.0) == 100                                # exact quotients do not round up


def test_zone_load_rules():
    r = targets.zone_load(Zone(name="Dining", description="dining hall", area_m2=300, net_deduction_pct=20), O.A2, 1)
    assert (r["gross"], r["net_load"]) == (250, 200)                      # 300 ÷ 1.2; 240 ÷ 1.2
    r = targets.zone_load(Zone(name="Suites", description="apartment suites", area_m2=800, sleeping_rooms=24), O.C, 2)
    assert (r["gross"], r["net_load"], r["dwelling"]) == (48, 48, True)   # 24 × 2
    r = targets.zone_load(Zone(name="Suites", description="apartment suites", area_m2=700), O.C, 2)
    assert r["gross"] == 40 and any("estimated" in f for f in r["flags"])  # 700 ÷ 35 = 20 rooms × 2
    r = targets.zone_load(Zone(name="Shop", description="retail CRU", area_m2=370), O.E, 1)
    assert r["gross"] == 100 and r["factor"] == 3.70                     # first storey mercantile
    assert targets.zone_load(Zone(name="Shop", description="retail CRU", area_m2=560), O.E, 3)["gross"] == 100   # upper storey 5.60
    r = targets.zone_load(Zone(name="Hall", description="auditorium", area_m2=150, occupant_load=120), O.A2, 1)
    assert r["gross"] == r["net_load"] == 120                            # fixed seats


def test_one_exit_rule():
    assert targets.exits_required(O.C, 140, 40, 2, True)[0] == 1
    assert targets.exits_required(O.C, 160, 40, 2, True)[0] == 2        # > 150 m² Table -B
    assert targets.exits_required(O.D, 250, 30, 2, False)[0] == 2       # > 200 m² Table -A
    assert targets.exits_required(O.D, 150, 61, 2, True)[0] == 2        # load > 60
    assert targets.exits_required(O.D, 150, 30, 3, True)[0] == 2        # 3 storeys


def test_travel_distance():
    assert targets.travel_distance_limit({O.D}, False, "office") == (40, "(1)(b) business and personal services")
    assert targets.travel_distance_limit({O.C}, False, "suites")[0] == 30
    assert targets.travel_distance_limit({O.C, O.A2}, True, "x")[0] == 45
    assert targets.travel_distance_limit({O.F3}, True, "parking")[0] == 60


def test_exit_widths():
    w = targets.exit_widths(348, 2, 0)
    assert (w["stair_aggregate_mm"], w["stair_each_mm"], w["door_each_mm"]) == (2784, 1392, 1062)   # 8 and 6.1 mm/person
    assert targets.exit_widths(32, 2, 1)["stair_each_mm"] == 900         # Table 3.4.3.2-A minimum, ≤ 2 storeys up
    assert targets.exit_widths(32, 2, 3)["stair_each_mm"] == 1100        # above the 2nd storey
    assert targets.exit_widths(10, 2, 0)["door_each_mm"] == 850


def test_washrooms_assembly_table_a():
    w = targets.washrooms_for(O.A2, 284, 400, "dining hall", None, False)   # 142 of each sex → row 126–150
    assert (w["male_wc"], w["female_wc"]) == (3, 6) and w["lavatories"] == {"male": 2, "female": 3} and w["urinals_max"] == 2
    w = targets.washrooms_for(O.A2, 1000, 900, "hall", None, False)         # 500 each sex → over 400
    assert (w["male_wc"], w["female_wc"]) == (7 + 1, 13 + 1)


def test_washrooms_other_groups():
    assert targets.wc_business(51) == 4 and targets.wc_business(150) == 5
    assert targets.wc_industrial(101) == 7
    w = targets.washrooms_for(O.E, 400, 800, "retail", None, False)         # 200 each: 1 M, 2 F
    assert (w["male_wc"], w["female_wc"]) == (1, 2)
    w = targets.washrooms_for(O.C, 60, 900, "suites", 26, True)
    assert w["wc_total"] == 26 and w["rule"].startswith("at least one water closet per dwelling unit")
    w = targets.washrooms_for(O.D, 20, 150, "office", None, False)
    assert any("3.7.2.2.(2)" in a for a in w["alternatives"]) and any("(15)" in a for a in w["alternatives"])


def test_gender_neutral_vbbl():
    assert targets.gender_neutral(200)[0] == 0
    assert targets.gender_neutral(284)[0] == 2 and targets.gender_neutral(401)[0] == 4
