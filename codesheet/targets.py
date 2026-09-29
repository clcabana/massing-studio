"""
codesheet.targets — occupant load, egress targets and washroom counts.

Three questions a designer asks of every storey once the massing holds:

  1. How many people?           Table 3.1.17.1 (area per person by use),
                                 fixed seats (3.1.17.1.(1)(a)) or 2 per
                                 sleeping room in a dwelling unit (1)(b).
                                 Gross (floor area / factor) and DESIGNED (net,
                                 after the circulation / duplicate-use /
                                 fixed-furnishing deductions the code
                                 consultant applies) are both reported.
  2. How do they get out?       Number of exits (3.4.2.1), travel distance
                                 limit (3.4.2.5), aggregate exit width
                                 (3.4.3.2.(1)) and the minimum widths of
                                 Table 3.4.3.2.-A.
  3. Where do they go?          Water closets per sex (3.7.2.2 by Group),
                                 lavatories (3.7.2.3), the urinal
                                 substitution (3.7.2.2.(3)), single-WC and
                                 unisex alternatives ((2), (15), (16)) and the
                                 Vancouver-only gender-neutral washroom
                                 (3.7.2.9).

These are TARGETS, not checks: massing cannot know where the stairs are. They
tell the designer what the plan will have to provide.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Optional

from codesheet.model import BuildingModel, Zone, Storey, OccupancyGroup as O
from codesheet.determinations import Determination, Bylaw, Clause
from codesheet import occupancy

# --- Table 3.1.17.1 -----------------------------------------------------------
# (pattern, area per person m², row label) — first match wins; matched against
# name + description, lower-cased. None = count-based (fixed seats).
OL_RULES: list[tuple[str, Optional[float], str]] = [
    (r"fixed seat|auditorium",                                   None,  "space with fixed seats — number of seats"),
    (r"\bstanding\b",                                            0.40,  "standing space"),
    (r"stadi|grandstand",                                        0.60,  "stadia and grandstands"),
    (r"\bstage\b",                                               0.75,  "stages for theatrical performances"),
    (r"seats and tables|banquet",                                0.95,  "space with non-fixed seats and tables"),
    (r"dining|beverage|cafeteria|restaurant|caf[eé]\b|\bbar\b|\bpub\b|community hall|dining hall",
                                                                 1.20,  "dining, beverage and cafeteria space"),
    (r"classroom|lecture",                                       1.85,  "classrooms"),
    (r"laborator",                                               4.60,  "laboratories in schools"),
    (r"library stack",                                           9.30,  "library stack areas"),
    (r"school shop|vocational",                                  9.30,  "school shops and vocational rooms"),
    (r"bowling|billiard|pool room",                              9.30,  "bowling alleys, pool and billiard rooms"),
    (r"yoga|dance|exercise room without",                        1.40,  "exercise rooms without equipment"),
    (r"\bgym\b|fitness|exercise|weight room",                    4.60,  "exercise rooms with equipment"),
    (r"kitchen",                                                 9.30,  "kitchens"),
    (r"reading|writing|lounge|study|multi-?purpose|communal|amenity|prayer|institute|board room|meeting|games? room|movie|music room|lobby|entry hall|entrance",
                                                                 1.85,  "reading or writing rooms or lounges"),
    (r"detention|cell",                                          11.60, "detention quarters"),
    (r"\bcare\b|treatment|sleeping room|patient",                10.00, "care, treatment and sleeping room areas"),
    (r"dormitor",                                                4.60,  "dormitories"),
    (r"personal service|salon|barber|\bspa\b",                   4.60,  "personal services shops"),
    (r"office|business|clinic|bank",                             9.30,  "offices"),
    (r"retail|shop|store|grocery|market|mercantile|\bcru\b",     None,  "mercantile — by storey (3.70 basements/first storey, 5.60 other storeys)"),
    (r"manufactur|process|workshop|fabricat",                    4.60,  "manufacturing or process rooms"),
    (r"parking|parkade|garage|hangar",                           46.00, "storage garages"),
    (r"warehouse",                                               28.00, "storage spaces (warehouse)"),
    (r"cleaning|repair",                                         4.60,  "cleaning and repair goods"),
    (r"laundry",                                                 9.30,  "laundry — not listed; office factor 9.30 applied by analogy"),
    (r"storage|bike|bicycle|service|mechanical|electrical|fire alarm|\bfa room\b|garbage|recycling|elevator|janitor",
                                                                 46.00, "storage"),
    (r"corridor",                                                3.70,  "public corridors intended for occupancies in addition to pedestrian travel"),
]
DWELLING_RE = re.compile(r"dwelling|\bsuites?\b|apartment|townhome|bedroom|\bunits?\b")   # strong words only; lobbies/amenity rooms are NOT dwelling units

GROUP_DEFAULT: dict[O, tuple[float, str]] = {
    O.A1: (0.75, "space with non-fixed seats"), O.A2: (1.20, "dining, beverage and cafeteria space"),
    O.B2: (10.0, "care, treatment and sleeping room areas"), O.D: (9.30, "offices"),
    O.F2: (4.60, "manufacturing or process rooms"), O.F3: (28.0, "storage spaces (warehouse)"),
}
MERCANTILE_LOW, MERCANTILE_UPPER = 3.70, 5.60
PERSONS_PER_SLEEPING_ROOM = 2
DEFAULT_M2_PER_SLEEPING_ROOM = 35.0      # massing assumption when bedrooms are not counted yet

# --- 3.4.2.1.(2) one-exit criteria ---------------------------------------------
ONE_EXIT_A = {"A": (150, 15), "B": (75, 10), "C": (100, 15), "D": (200, 25), "E": (150, 15), "F2": (150, 10), "F3": (200, 15)}
ONE_EXIT_B = {"A": 200, "B": 100, "C": 150, "D": 300, "E": 200, "F2": 200, "F3": 300}
ONE_EXIT_MAX_OL = 60

# --- 3.4.3.2 widths ---------------------------------------------------------------
MM_PER_PERSON = {"door": 6.1, "stair": 8.0, "steep_stair": 9.2}          # (1)(a), (b), (c)
MIN_WIDTH = {"corridor": 1100, "ramp": 1100, "stair_low": 900, "stair_high": 1100, "door": 850}   # Table 3.4.3.2.-A

# --- 3.7.2.2 water closets ----------------------------------------------------------
TABLE_A = [(25, 1, 1), (50, 1, 2), (75, 2, 3), (100, 2, 4), (125, 3, 5), (150, 3, 6), (175, 4, 7), (200, 4, 8),
           (250, 5, 9), (300, 5, 10), (350, 6, 11), (400, 6, 12)]          # (max persons of each sex, male WC, female WC)


def ceil(x: float) -> int:
    return int(math.ceil(x - 1e-9))


def ol_factor(z: Zone, group: Optional[O], storey_index_above_grade: Optional[int]) -> tuple[Optional[float], str, list[str]]:
    """(area per person or None for count-based, table row, flags)."""
    flags = []
    if z.ol_factor_m2:
        return z.ol_factor_m2, f"designer factor {z.ol_factor_m2:g} m²/person", flags
    text = f"{z.name} {z.description}".lower()
    if group == O.C and DWELLING_RE.search(text) and "dormitor" not in text:
        return None, "dwelling units — 2 persons per sleeping room", flags
    for pat, f, label in OL_RULES:
        if re.search(pat, text):
            if f is None and "mercantile" in label:
                low = storey_index_above_grade is None or storey_index_above_grade <= 1
                if storey_index_above_grade == 2:
                    flags.append(f"{z.name}: second storey — 3.70 applies only with a principal entrance from a pedestrian thoroughfare or parking area, else 5.60")
                return (MERCANTILE_LOW if low else MERCANTILE_UPPER), ("mercantile — basements and first storeys" if low else "mercantile — other storeys"), flags
            if "not listed" in label:
                flags.append(f"{z.name}: {label}")
            return f, label, flags
    if group in GROUP_DEFAULT:
        f, label = GROUP_DEFAULT[group]
        flags.append(f"{z.name}: no Table 3.1.17.1 row matched the description — Group {group.value} default '{label}' ({f:g} m²/person) applied")
        return f, label, flags
    if group == O.E:
        return MERCANTILE_LOW, "mercantile — basements and first storeys", flags
    if group == O.C:
        return None, "dwelling units — 2 persons per sleeping room", flags
    flags.append(f"{z.name}: occupant load factor could not be determined")
    return None, "unknown", flags


def zone_load(z: Zone, group: Optional[O], storey_index_above_grade: Optional[int]) -> dict:
    """One row of the occupant-load table."""
    f, label, flags = ol_factor(z, group, storey_index_above_grade)
    net = round(z.area_m2 * (1 - z.net_deduction_pct / 100.0), 1)
    row = {"zone": z.name, "group": group.value if group else None, "area": z.area_m2, "deduction_pct": z.net_deduction_pct,
           "net_area": net, "factor": f, "row": label, "flags": flags, "dwelling": False}
    if z.occupant_load is not None:                      # designer count (fixed seats, posted load)
        row.update(gross=z.occupant_load, net_load=z.occupant_load, basis="designer count / fixed seats (3.1.17.1.(1)(a),(c))")
        return row
    if f is None and label.startswith("dwelling"):
        row["dwelling"] = True
        if z.sleeping_rooms is not None:
            n = z.sleeping_rooms * PERSONS_PER_SLEEPING_ROOM
            row.update(gross=n, net_load=n, basis=f"{z.sleeping_rooms} sleeping rooms × 2 (3.1.17.1.(1)(b))")
        else:
            rooms = ceil(net / DEFAULT_M2_PER_SLEEPING_ROOM)
            n = rooms * PERSONS_PER_SLEEPING_ROOM
            row.update(gross=n, net_load=n, basis=f"≈{rooms} sleeping rooms assumed at {DEFAULT_M2_PER_SLEEPING_ROOM:g} m² each × 2 (3.1.17.1.(1)(b))")
            row["flags"].append(f"{z.name}: sleeping rooms estimated from area — count bedrooms when the plan exists")
        return row
    if f is None:
        row.update(gross=0, net_load=0, basis="not determined")
        return row
    row.update(gross=ceil(z.area_m2 / f), net_load=ceil(net / f), basis=f"area ÷ {f:g} m²/person")
    return row


# --- egress ------------------------------------------------------------------------

def exits_required(group: Optional[O], floor_area_m2: float, ol: int, building_storeys: int, sprinklered: bool) -> tuple[int, list[str]]:
    """3.4.2.1: 2 exits unless the one-exit criteria of Sentence (2) are met."""
    why = []
    if building_storeys > 2:
        return 2, ["building height > 2 storeys — Sentence (2) not available"]
    if ol > ONE_EXIT_MAX_OL:
        return 2, [f"occupant load {ol} > 60"]
    g = "A" if group in (O.A1, O.A2) else ("B" if group == O.B2 else (group.value if group else "C"))
    if sprinklered:
        cap = ONE_EXIT_B.get(g)
        if cap and floor_area_m2 <= cap:
            return 1, [f"one exit permitted: ≤ 2 storeys, load {ol} ≤ 60, floor area {floor_area_m2:g} ≤ {cap} m² (Table 3.4.2.1.-B), travel ≤ 25 m"]
        return 2, [f"floor area {floor_area_m2:g} m² > {cap} m² (Table 3.4.2.1.-B)"]
    cap = ONE_EXIT_A.get(g)
    if cap and floor_area_m2 <= cap[0]:
        return 1, [f"one exit permitted: ≤ 2 storeys, load {ol} ≤ 60, floor area {floor_area_m2:g} ≤ {cap[0]} m², travel ≤ {cap[1]} m (Table 3.4.2.1.-A)"]
    return 2, [f"floor area {floor_area_m2:g} m² > {cap[0] if cap else '—'} m² (Table 3.4.2.1.-A)"]


def travel_distance_limit(groups: set[O], sprinklered: bool, text: str) -> tuple[int, str]:
    """3.4.2.5.(1) — the limit that applies to the floor area."""
    if sprinklered:
        if O.F3 in groups and re.search(r"parking|parkade|garage", text):
            return 60, "(1)(e) storage garage conforming to 3.2.2.92 (else 45 m sprinklered)"
        return 45, "(1)(c) sprinklered throughout"
    if groups == {O.D}:
        return 40, "(1)(b) business and personal services"
    return 30, "(1)(f) any other floor area, not sprinklered"


def exit_widths(ol: int, n_exits: int, storeys_above_lowest_exit: int) -> dict:
    """3.4.3.2.(1), (7) and Table 3.4.3.2.-A."""
    door_agg = ol * MM_PER_PERSON["door"]
    stair_agg = ol * MM_PER_PERSON["stair"]
    per = max(n_exits, 1)
    stair_min = MIN_WIDTH["stair_high"] if storeys_above_lowest_exit > 2 else MIN_WIDTH["stair_low"]
    return {"door_aggregate_mm": ceil(door_agg), "stair_aggregate_mm": ceil(stair_agg),
            "door_each_mm": max(MIN_WIDTH["door"], ceil(door_agg / per)),
            "stair_each_mm": max(stair_min, ceil(stair_agg / per)),
            "corridor_min_mm": MIN_WIDTH["corridor"], "stair_min_mm": stair_min,
            "note": "stair rise ≤ 180 / run ≥ 280 assumed (8 mm/person); 9.2 mm/person otherwise"}


# --- washrooms --------------------------------------------------------------------------

def wc_assembly(n_each_sex: int) -> tuple[int, int]:
    for cap, m, f in TABLE_A:
        if n_each_sex <= cap:
            return m, f
    return 7 + ceil((n_each_sex - 400) / 200), 13 + ceil((n_each_sex - 400) / 100)


def wc_business(n: int) -> int:
    if n <= 25: return 1
    if n <= 50: return 2
    return 3 + ceil((n - 50) / 50)


def wc_industrial(n: int) -> int:
    for cap, v in ((10, 1), (25, 2), (50, 3), (75, 4), (100, 5)):
        if n <= cap: return v
    return 6 + ceil((n - 100) / 30)


def washrooms_for(group: O, ol: int, area_m2: float, text: str, dwelling_units: Optional[int], is_dwelling: bool) -> dict:
    """
    Water closets per 3.7.2.2 for one Group on one storey, with lavatories
    (3.7.2.3) and the alternatives the article allows. Persons of each sex =
    load equally divided ((1)).
    """
    n = ceil(ol / 2)
    out = {"group": group.value, "load": ol, "each_sex": n, "male_wc": None, "female_wc": None, "rule": "", "sentence": None,
           "alternatives": [], "lavatories": None, "urinals_max": None}
    if ol == 0:
        out["rule"] = "no occupant load"; return out
    if group == O.C:
        if is_dwelling:
            out.update(rule="at least one water closet per dwelling unit", sentence=9,
                       dwelling_units=dwelling_units, wc_total=dwelling_units)
            return out
        m = f = ceil(n / 10); out.update(male_wc=m, female_wc=f, rule="residential (not dwelling units): 1 per 10 persons of each sex", sentence=8)
    elif group == O.B2:
        m = f = ceil(n / 10); out.update(male_wc=m, female_wc=f, rule="care occupancy: 1 per 10 persons of each sex", sentence=8)
    elif group in (O.A1, O.A2):
        if re.search(r"worship|church|mosque|temple|synagogue|chapel|undertak|funeral", text):
            m = f = ceil(n / 150); out.update(male_wc=m, female_wc=f, rule="place of worship / undertaking premises: 1 per 150 of each sex", sentence=6)
        elif re.search(r"daycare|day care|primary school|elementary", text):
            out.update(male_wc=ceil(n / 30), female_wc=ceil(n / 25), rule="primary school / daycare: 1 per 30 males, 1 per 25 females", sentence=5)
        else:
            m, f = wc_assembly(n); out.update(male_wc=m, female_wc=f, rule="assembly — Table 3.7.2.2.-A", sentence=4)
        if 60 < ol <= 100:
            out["alternatives"].append("3 unisex toilet rooms (1 WC + 1 lavatory each, one accessible) may serve 61–100 persons (3.7.2.2.(16))")
    elif group == O.D:
        m = f = wc_business(n); out.update(male_wc=m, female_wc=f, rule="business and personal services — Table 3.7.2.2.-B", sentence=10)
    elif group == O.E:
        out.update(male_wc=ceil(n / 300), female_wc=ceil(n / 150), rule="mercantile: 1 per 300 males, 1 per 150 females", sentence=11)
        if area_m2 <= 500:
            out["alternatives"].append("suite ≤ 500 m²: may be based on staff only, Table 3.7.2.2.-B (3.7.2.2.(14))")
    else:   # F
        m = f = wc_industrial(n); out.update(male_wc=m, female_wc=f, rule="industrial — Table 3.7.2.2.-C", sentence=12)
        if re.search(r"parking|parkade|garage", text):
            out["alternatives"].append("storage garage: load may be based on staff only (3.7.2.1.(2))")
    if group != O.C and ol <= 25:
        out["alternatives"].append("load ≤ 25: one water closet may serve both sexes (3.7.2.2.(2))")
    if group != O.C and group != O.B2 and area_m2 <= 200 and ol <= 60:
        out["alternatives"].append("suite ≤ 200 m² and ≤ 60 persons: 2 unisex toilet rooms (1 WC + 1 lavatory each, one accessible) (3.7.2.2.(15))")
    if out["male_wc"] is not None:
        mwc = out["male_wc"]
        out["urinals_max"] = 1 if mwc == 2 else int(math.floor(mwc * 2 / 3))
        out["lavatories"] = {"male": ceil(mwc / 2), "female": ceil(out["female_wc"] / 2)}     # 3.7.2.3.(1)
        out["wc_total"] = mwc + out["female_wc"]
    return out


def gender_neutral(ol_non_residential: int) -> tuple[int, str]:
    """3.7.2.9.(1) — Vancouver: building/suite load > 200 → 1 accessible WC + 1 per additional 100."""
    if ol_non_residential <= 200:
        return 0, f"non-residential load {ol_non_residential} ≤ 200 — not triggered"
    n = 1 + ceil((ol_non_residential - 200) / 100)
    return n, f"1 + ({ol_non_residential} − 200) ÷ 100 → {n} water closets in gender-neutral facilities, at least one accessible"


# --- analysis ---------------------------------------------------------------------------

def analyze(b: BuildingModel, hd: list[Determination], law: Optional[Bylaw] = None) -> tuple[list[Determination], dict]:
    """
    Returns (determinations, targets) where `targets` is the JSON-friendly
    structure the live panel renders:
      {blk: {"storeys": [{...}], "total": {"gross", "net"}, "egress": {...}, "gender_neutral": {...}}, "_site": {...}}
    """
    law = law or Bylaw()
    H = {d.key: d for d in hd}
    out: list[Determination] = []
    targets: dict = {}
    site_gross = site_net = 0
    c_3_1_17 = law.article("3.1.17.1")
    for blk in b.blocks():
        storeys = [s for s in b.storeys_sorted(blk) if not s.is_roof]
        first = H.get(f"{blk}.first_storey"); first_label = first.value if first else None
        bh = H.get(f"{blk}.building_height_storeys"); building_storeys = bh.value if bh else len(storeys)
        # index above grade: first storey = 1, basements ≤ 0
        labels = [s.label for s in storeys if not s.is_part_of]
        fi = labels.index(first_label) if first_label in labels else 0
        idx = {lbl: i - fi + 1 for i, lbl in enumerate(labels)}
        blk_gross = blk_net = 0
        rows_by_storey = []
        parts = defaultdict(list)          # main storey → detached parts (is_part_of)
        for s in storeys:
            if s.is_part_of:
                parts[s.is_part_of].append(s)
        for s in storeys:
            if s.is_part_of:
                continue
            group_rows = occupancy.classify_storey(s)
            for p in parts.get(s.label, []):
                group_rows += occupancy.classify_storey(p, s)
            zrows, flags = [], []
            loads_by_group: dict[O, int] = defaultdict(int)
            area_by_group: dict[O, float] = defaultdict(float)
            text_by_group: dict[O, str] = defaultdict(str)
            dwelling_units = 0; dwelling_any = False; dwelling_known = True
            for z, g, conf, note in group_rows:
                r = zone_load(z, g, idx.get(s.label))
                zrows.append(r); flags += r.pop("flags")
                if g is not None:
                    loads_by_group[g] += r["net_load"]; area_by_group[g] += z.area_m2
                    text_by_group[g] += f" {z.name} {z.description}".lower()
                    if r["dwelling"]:
                        dwelling_any = True
                        if z.dwelling_units is not None: dwelling_units += z.dwelling_units
                        else: dwelling_known = False
            gross = sum(r["gross"] for r in zrows); net = sum(r["net_load"] for r in zrows)
            blk_gross += gross; blk_net += net
            floor_area = s.floor_area_m2 or (s.plan_area_m2() + sum(p.plan_area_m2() for p in parts.get(s.label, [])))
            groups = {g for g in loads_by_group}
            dom = max(loads_by_group, key=lambda g: area_by_group[g]) if loads_by_group else None
            alltext = " ".join(text_by_group.values())
            n_exits, why = exits_required(dom, round(floor_area, 1), net, building_storeys, b.is_sprinklered)
            td, td_why = travel_distance_limit(groups, b.is_sprinklered, alltext)
            above = max(0, idx.get(s.label, 1) - 1)
            widths = exit_widths(net, n_exits, above)
            wash = []
            for g in sorted((g for g in loads_by_group if loads_by_group[g] > 0), key=lambda g: g.value):
                wash.append(washrooms_for(g, loads_by_group[g], area_by_group[g], text_by_group[g],
                                          dwelling_units if (dwelling_known and dwelling_units) else None, dwelling_any and g == O.C))
            st = {"label": s.label, "index_above_grade": idx.get(s.label), "floor_area": round(floor_area, 1), "gross": gross, "net": net,
                  "rows": zrows, "exits": n_exits, "exits_why": why, "travel_m": td, "travel_why": td_why, "widths": widths,
                  "washrooms": wash, "groups": sorted(g.value for g in groups), "flags": flags}
            rows_by_storey.append(st)
            out.append(Determination(
                key=f"{blk}.{s.label}.occupant_load", label=f"Occupant load — {s.label}", value=net, unit="persons", block=blk,
                clauses=[c_3_1_17], inputs={"gross": gross, "net": net, "rows": zrows},
                because=(f"{len(zrows)} area(s): " + "; ".join(f"{r['zone']} {r['net_area']:g} m² ÷ {r['factor']:g} = {r['net_load']}" if r["factor"] else f"{r['zone']} {r['net_load']} ({r['basis']})" for r in zrows)
                         + (f". Gross (no deductions) {gross}." if gross != net else "")),
                flags=flags))
            out.append(Determination(
                key=f"{blk}.{s.label}.egress", label=f"Egress — {s.label}",
                value=f"{n_exits} exit{'s' if n_exits > 1 else ''} · travel ≤ {td} m · stair {widths['stair_each_mm']} mm · door {widths['door_each_mm']} mm", block=blk,
                clauses=[law.article("3.4.2.1", 1 if n_exits == 2 else 2), law.article("3.4.2.5", 1), law.article("3.4.3.2", 1), law.article("3.4.3.2", 8)],
                inputs={"floor_area": round(floor_area, 1), "load": net, "building_storeys": building_storeys, "exits": n_exits, "travel_m": td, **widths},
                because=(f"Exits: {'; '.join(why)}. Travel distance: {td_why}. Width: {net} persons × 8 mm = {widths['stair_aggregate_mm']} mm "
                         f"aggregate stair ÷ {n_exits}, min {widths['stair_min_mm']} mm (Table 3.4.3.2.-A); doors {net} × 6.1 mm = {widths['door_aggregate_mm']} mm "
                         f"aggregate, min 850 mm each; corridors ≥ 1 100 mm."),
                flags=([] if n_exits == 2 else ["single exit: travel distance also limited by 3.4.2.1.(2) (25 m sprinklered / Table -A)"])))
            if wash:
                bits = []
                for w in wash:
                    if w.get("male_wc") is not None:
                        bits.append(f"Group {w['group']} ({w['load']} p.): {w['male_wc']} M + {w['female_wc']} F water closets, "
                                    f"{w['lavatories']['male']}+{w['lavatories']['female']} lavatories")
                    elif w["group"] == "C" and w.get("rule", "").startswith("at least one"):
                        bits.append(f"Group C: ≥ 1 water closet per dwelling unit" + (f" ({w['dwelling_units']} units)" if w.get("dwelling_units") else ""))
                out.append(Determination(
                    key=f"{blk}.{s.label}.washrooms", label=f"Washrooms — {s.label}", value="; ".join(bits) or "—", block=blk,
                    clauses=[law.article("3.7.2.2", w["sentence"]) for w in wash if w.get("sentence")] + [law.article("3.7.2.3", 1)],
                    inputs={"by_group": wash},
                    because=("Each dwelling unit has its own water closet (3.7.2.2.(9)); no common washrooms required by 3.7.2." if all(w.get("male_wc") is None for w in wash) else
                             "Persons of each sex = load ÷ 2 (3.7.2.2.(1)); lavatories 1 per 2 water closets (3.7.2.3.(1)); "
                             "urinals may replace up to ⅔ of male water closets (3.7.2.2.(3))."),
                    flags=[a for w in wash for a in w["alternatives"]]))
        # block roll-up
        site_gross += blk_gross; site_net += blk_net
        out.append(Determination(key=f"{blk}.occupant_load_total", label="Occupant load — building", value=blk_net, unit="persons", block=blk,
                                 clauses=[c_3_1_17], inputs={"gross": blk_gross, "net": blk_net},
                                 because=f"Sum of storeys. Gross {blk_gross}, designed (net) {blk_net}."))
        gov = max(rows_by_storey, key=lambda r: r["net"]) if rows_by_storey else None
        n_exits_blk = max((r["exits"] for r in rows_by_storey), default=2)
        egress = None
        if gov:
            widths = exit_widths(gov["net"], n_exits_blk, max(0, max(r["index_above_grade"] or 1 for r in rows_by_storey) - 1))
            egress = {"exits": n_exits_blk, "governing_storey": gov["label"], "governing_load": gov["net"],
                      "stair_each_mm": widths["stair_each_mm"], "door_each_mm": widths["door_each_mm"],
                      "travel_m": min(r["travel_m"] for r in rows_by_storey)}
            out.append(Determination(key=f"{blk}.egress", label="Exit stairs — building", value=n_exits_blk, unit="exit stairs", block=blk,
                                     clauses=[law.article("3.4.2.1", 1), law.article("3.4.3.2", 4)], inputs=egress,
                                     because=f"Exit width need not be cumulative between storeys (3.4.3.2.(4)): size each stair for the busiest storey, "
                                             f"{gov['label']} at {gov['net']} persons → {widths['stair_each_mm']} mm clear per stair."))
        non_res = sum(sum(r["net_load"] for r in st["rows"] if r["group"] not in (None, "C")) for st in rows_by_storey)
        gn, gn_why = gender_neutral(non_res)
        out.append(Determination(key=f"{blk}.gender_neutral_wc", label="Gender-neutral washroom (VBBL)", value=gn, unit="water closets", block=blk,
                                 clauses=[law.article("3.7.2.9", 1)], inputs={"non_residential_load": non_res},
                                 because=gn_why, flags=["Vancouver-specific provision — not in BCBC 2024"] if gn else []))
        targets[blk] = {"storeys": rows_by_storey, "total": {"gross": blk_gross, "net": blk_net}, "egress": egress,
                        "gender_neutral": {"wc": gn, "non_residential_load": non_res}}
    out.append(Determination(key="site.occupant_load_total", label="Occupant load — project", value=site_net, unit="persons",
                             clauses=[c_3_1_17], inputs={"gross": site_gross, "net": site_net},
                             because=f"All buildings. Gross {site_gross}, designed (net) {site_net}."))
    targets["_site"] = {"gross": site_gross, "net": site_net}
    return out, targets
