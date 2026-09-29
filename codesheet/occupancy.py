"""
codesheet.occupancy — piece 4: classify zones and roll up major occupancies.

Two jobs:

1. Zone → Group/Division (Table 3.1.2.1). Deterministic keyword rules, in
   priority order, each carrying a confidence and a note. An explicit
   `occupancy` on the Zone always wins. Anything the rules can't place is
   returned as None with a flag, never guessed. (Later the AI layer can
   propose a classification; it still lands here as an override the human
   accepts.)

2. Per block: which Groups are MAJOR occupancies. 3.1.2.1.(2) says a building
   is classified by ALL its major occupancies, and 3.2.2.8.(1) lets a Group be
   ignored where its aggregate area on a storey is ≤ 10% of that storey's
   floor area (not for F1/F2). We apply that storey by storey, and a Group
   is major for the block if it is major on any storey.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from codesheet.model import BuildingModel, Zone, Storey, OccupancyGroup as O
from codesheet.determinations import Determination, Bylaw

# (pattern, group, confidence, note) — first match wins. Patterns are matched
# against name + description, lower-cased.
RULES: list[tuple[str, Optional[O], float, str]] = [
    (r"\b(parking|parkade|garage)\b",                         O.F3, 0.95, "storage garage — low-hazard industrial"),
    (r"\b(dwelling|suite|suites|apartment|residential|rental|student housing|bedroom|townhome)\b",
                                                              O.C,  0.95, "residential occupancy"),
    (r"\b(theatre|theater|performing arts|cinema)\b",         O.A1, 0.85, "production/viewing of performing arts"),
    (r"\b(auditorium|lecture)\b",                             O.A2, 0.70, "assembly; reclassify A1 if used for performing arts"),
    (r"\b(dining|community hall|restaurant|caf[eé]|kitchen|prayer|chapel|reading room|movie|games room|music room|daycare|classroom|multi-?purpose)\b",
                                                              O.A2, 0.85, "assembly not elsewhere classified"),
    (r"\b(office|institute|clinic|salon|bank|studio)\b",      O.D,  0.85, "business and personal services"),
    (r"\b(retail|shop|store|grocery|market|mercantile)\b",    O.E,  0.9,  "mercantile"),
    (r"\b(lobby|entry hall|entrance|corridor|vestibule)\b",   None, 0.6,  "circulation — takes the occupancy it serves"),
    (r"\b(lounge|amenity|communal|study|laundry|reading nook|shared)\b",
                                                              None, 0.6,  "ancillary to the residential occupancy it serves"),
    (r"\b(storage|bike|bicycle|service|mechanical|electrical|fire alarm|fa room|garbage|recycling|elevator)\b",
                                                              O.F3, 0.7,  "service/storage — low-hazard; often treated as part of the building's major occupancy"),
]

# The table row text, quoted so the sheet can show it.
TABLE_3121 = {
    O.A1: "Assembly occupancies intended for the production and viewing of the performing arts",
    O.A2: "Assembly occupancies not elsewhere classified in Group A",
    O.B2: "Treatment occupancies",
    O.C:  "Residential occupancies",
    O.D:  "Business and personal services occupancies",
    O.E:  "Mercantile occupancies",
    O.F2: "Medium-hazard industrial occupancies",
    O.F3: "Low-hazard industrial occupancies",
}

SUBSIDIARY_FRACTION = 0.10   # 3.2.2.8.(1)


def classify_zone(z: Zone, storey_dominant: Optional[O] = None) -> tuple[Optional[O], float, str]:
    """Return (group, confidence, note). Explicit override wins."""
    if z.occupancy is not None:
        return z.occupancy, 1.0, "set explicitly in the model"
    text = f"{z.name} {z.description}".lower()
    for pat, grp, conf, note in RULES:
        if re.search(pat, text):
            if grp is None:           # circulation/ancillary → inherit
                if storey_dominant is not None:
                    return storey_dominant, conf, f"{note} → inherits {storey_dominant.value}"
                return None, conf, note + " (no dominant occupancy on this storey to inherit)"
            return grp, conf, note
    return None, 0.0, "no rule matched — needs a human classification"


def dominant_group(zones: list[Zone]) -> Optional[O]:
    by = defaultdict(float)
    for z in zones:
        g, conf, _ = classify_zone(z)
        if g is not None and conf >= 0.7:
            by[g] += z.area_m2
    return max(by, key=by.get) if by else None


def classify_storey(s: Storey, parent: Optional[Storey] = None) -> list[tuple[Zone, Optional[O], float, str]]:
    """Two passes: first the zones with their own identity, then the
    ancillary ones inherit the storey's dominant classified group — or the
    parent storey's, for a detached piece (is_part_of)."""
    dom = dominant_group(s.zones)
    if dom is None and parent is not None:
        dom = dominant_group(parent.zones)
    return [(z, *classify_zone(z, dom)) for z in s.zones]


def analyze(b: BuildingModel, law: Optional[Bylaw] = None) -> list[Determination]:
    law = law or Bylaw()
    out: list[Determination] = []
    for blk in b.blocks():
        major_any: dict[O, list[str]] = defaultdict(list)     # group → storeys where it's major
        present: dict[O, float] = defaultdict(float)
        unclassified: list[str] = []
        over: list[str] = []
        for s in b.storeys_sorted(blk):
            if s.is_roof:
                continue
            parent = next((p for p in b.storeys_sorted(blk) if p.label == s.is_part_of), None) if s.is_part_of else None
            rows = classify_storey(s, parent)
            floor_area = s.plan_area_m2(b.footprint)
            if floor_area and s.gross_area_m2() > floor_area * 1.02:
                over.append(f"{s.label} (zones {s.gross_area_m2():,.0f} m² > floor {floor_area:,.0f} m²)")
            per_group: dict[O, float] = defaultdict(float)
            for z, g, conf, note in rows:
                if g is None:
                    unclassified.append(f"{s.label}: {z.name}")
                    continue
                per_group[g] += z.area_m2
                present[g] += z.area_m2
            # per-zone determinations (the sheet's occupancy rows)
            for z, g, conf, note in rows:
                out.append(Determination(
                    key=f"{blk}.{s.label}.{z.name}.occupancy", label=f"{s.label} — {z.name}",
                    value=g.value if g else "?", block=blk,
                    clauses=[law.article("3.1.2.1", 1)],
                    because=(f"{z.description}. {note}." + (f" Table 3.1.2.1: “{TABLE_3121[g]}”." if g else "")),
                    inputs={"area_m2": z.area_m2, "confidence": conf},
                    flags=[] if g else ["Unclassified — assign an occupancy."] if conf == 0 else ["Low-confidence classification — confirm."] if conf < 0.75 else [],
                ))
            for g, a in per_group.items():
                frac = a / floor_area if floor_area else 1.0
                if frac > SUBSIDIARY_FRACTION or g in (O.F2,):
                    major_any[g].append(f"{s.label} ({a:,.0f} m², {frac:.0%} of storey)")
        computed = sorted(major_any, key=lambda g: -present[g])
        declared = b.declared_major_occupancies.get(blk)
        if declared:
            # designer's declaration governs the list; disagreements are surfaced below
            majors = list(declared) + [g for g in computed if g not in declared and g not in (O.F3,)]
        else:
            majors = computed
        minors = [g for g in present if g not in majors]
        d = Determination(
            key=f"{blk}.major_occupancies", label="Major occupancies", value=[g.value for g in majors], block=blk,
            clauses=[law.article("3.1.2.1", 2), law.article("3.2.2.8", 1)],
            because=("Classified by all major occupancies (3.1.2.1.(2)). A Group whose aggregate area on a storey is "
                     "≤ 10% of that storey's floor area need not be treated as major there (3.2.2.8.(1)). "
                     + " ".join(f"{g.value}: major on {'; '.join(v)}." for g, v in major_any.items())
                     + (" Subsidiary only: " + ", ".join(f"{g.value} ({present[g]:,.0f} m² total)" for g in minors) + "." if minors else "")),
            inputs={"areas_m2": {g.value: round(a) for g, a in present.items()}},
        )
        if declared:
            only_declared = [g.value for g in declared if g not in major_any]
            only_computed = [g.value for g in computed if g not in declared]
            note = " Declared by the designer: " + ", ".join(g.value for g in declared) + "."
            if only_declared:
                note += f" Declared but below the 10% area test: {', '.join(only_declared)} (conservative declaration honoured)."
            if only_computed:
                note += f" Major by area but not declared: {', '.join(only_computed)}."
            d.because += note
            if only_computed:
                d.flags.append(f"By area, {', '.join(only_computed)} exceed(s) 10% of a storey but is not declared major — confirm the classification.")
        if unclassified:
            d.flags.append("Unclassified zones: " + ", ".join(unclassified))
        if over:
            d.flags.append("Zone areas exceed the storey's floor area — check the zone schedule: " + "; ".join(over))
        if len(majors) > 1:
            d.flags.append("Multiple major occupancies — 3.2.2.6 (most restrictive governs) or 3.2.2.7 (superimposed) applies; occupancy separations per 3.1.3.1.")
        out.append(d)
    return out


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    for d in analyze(project):
        if d.key.endswith("major_occupancies"):
            print(f"\n[{d.block}] {d.label}: {d.value}\n   {d.because}")
            for f in d.flags: print("   ⚠", f)
        else:
            print(f"  {d.block:5} {d.label:45} {str(d.value):3}  conf={d.inputs['confidence']:.2f}  {d.flags[0] if d.flags else ''}")
