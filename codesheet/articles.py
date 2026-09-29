"""
codesheet.articles — piece 6: which 3.2.2 article governs, and what it demands.

How Subsection 3.2.2 works, in one paragraph: for each major occupancy Group
there is a ladder of articles. The top rung ("Any Height, Any Area") is the
default and the most demanding — noncombustible, 2 h floors. Each rung below
it is a *permission*: "a building classified as Group C is permitted to
conform to Sentence (2) provided …" a list of conditions on sprinklering,
storeys, height and building area. If the conditions are met, the building
may use that rung's (usually lighter) requirements instead. Several rungs can
be satisfied at once; the designer picks one, and the code sheet has to say
which and show the conditions were met.

So the selector returns ALL qualifying articles with their requirements, marks
the least demanding as the default choice, and shows why the others were
excluded. The rules below are transcribed from the VBBL 2025 text extracted
in data/bylaw/vbbl-2025/articles.json (page numbers come from there).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from codesheet.model import BuildingModel, OccupancyGroup as O
from codesheet.determinations import Determination, Bylaw


@dataclass
class ArticleRule:
    id: str
    group: O
    title: str
    requires_sprinklered: bool
    max_storeys: Optional[int]                 # None = any
    max_height_m: Optional[float]              # first-storey floor → uppermost floor
    max_area_by_storeys: Optional[dict[int, Optional[float]]]  # None = any area; per-storey-count cap (None inside = unlimited)

    construction: str                          # "noncombustible" | "combustible or noncombustible" | "EMTC or noncombustible"
    floor_frr_h: float
    roof_frr_h: Optional[float]
    mezzanine_frr_h: Optional[float]
    notes: list[str] = field(default_factory=list)
    # Other occupancies this article tolerates inside the building (sentence ref, rules)
    admits: dict[str, str] = field(default_factory=dict)
    max_area_by_storeys_streets: Optional[dict[int, dict[int, float]]] = None   # {storeys: {streets_faced: cap}}
    no_basement_area_bonus: Optional[dict[int, float]] = None                 # {storeys: cap if no basement}

    def strictness(self) -> tuple:
        """Sort key: lower = less demanding. Noncombustible-only and 2 h floors are 'more'."""
        return (self.floor_frr_h, 1 if self.construction == "noncombustible" else 0, -(self.max_storeys or 99))


# ---- Group C ladder, VBBL 2025 (BCBC 2024) numbering ---------------------------
GROUP_C: list[ArticleRule] = [
    ArticleRule("3.2.2.47", O.C, "Group C, Any Height, Any Area, Sprinklered",
                requires_sprinklered=True, max_storeys=None, max_height_m=None, max_area_by_storeys=None,
                construction="noncombustible", floor_frr_h=2.0, roof_frr_h=None, mezzanine_frr_h=1.0,
                notes=["Default rung; applies unless 3.2.2.48–.55 or .93 permits otherwise."]),
    ArticleRule("3.2.2.48", O.C, "Group C, up to 12 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=12, max_height_m=50.0,
                max_area_by_storeys={n: 6000.0 for n in range(1, 13)},
                construction="EMTC or noncombustible", floor_frr_h=2.0, roof_frr_h=None, mezzanine_frr_h=1.0,
                notes=["Encapsulated mass timber construction permitted (3.1.6)."],
                admits={"A2": "(4)(a) below the 4th storey", "E": "(4)(b) below the 3rd storey", "F3": "(4)(c) storage garage below the 5th storey"}),
    ArticleRule("3.2.2.49", O.C, "Group C, up to 6 Storeys, Sprinklered, Noncombustible Construction",
                requires_sprinklered=True, max_storeys=6, max_height_m=None,
                max_area_by_storeys={1: None, 2: None, 3: 12000.0, 4: 9000.0, 5: 7200.0, 6: 6000.0},
                construction="noncombustible", floor_frr_h=1.0, roof_frr_h=None, mezzanine_frr_h=1.0),
    ArticleRule("3.2.2.51", O.C, "Group C, up to 6 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=6, max_height_m=18.0,
                max_area_by_storeys={1: 9000.0, 2: 4500.0, 3: 3000.0, 4: 2250.0, 5: 1800.0, 6: 1500.0},
                construction="combustible or noncombustible", floor_frr_h=1.0, roof_frr_h=1.0, mezzanine_frr_h=1.0,
                notes=["Roof noncombustible or FRTW if roof assembly > 25 m above first-storey floor ((2)(c))."],
                admits={"A2": "(5)(a) below the 3rd storey", "E": "(5)(a) below the 3rd storey", "F3": "(5)(b) storage garage below the 4th storey"}),
    ArticleRule("3.2.2.52", O.C, "Group C, up to 4 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=4, max_height_m=None,
                max_area_by_storeys={1: 7200.0, 2: 3600.0, 3: 2400.0, 4: 1800.0},
                construction="combustible or noncombustible", floor_frr_h=1.0, roof_frr_h=None, mezzanine_frr_h=1.0),
    ArticleRule("3.2.2.55", O.C, "Group C, up to 3 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=3, max_height_m=None,
                max_area_by_storeys={1: 5400.0, 2: 2700.0, 3: 1800.0},
                construction="combustible or noncombustible", floor_frr_h=0.75, roof_frr_h=None, mezzanine_frr_h=0.75),
]

# ---- Group A, Division 2 ladder ---------------------------------------------------
GROUP_A2: list[ArticleRule] = [
    ArticleRule("3.2.2.23", O.A2, "Group A, Division 2, Any Height, Any Area, Sprinklered",
                requires_sprinklered=True, max_storeys=None, max_height_m=None, max_area_by_storeys=None,
                construction="noncombustible", floor_frr_h=2.0, roof_frr_h=None, mezzanine_frr_h=1.0,
                notes=["Default rung; applies unless 3.2.2.24–.28 or .93 permits otherwise."]),
    ArticleRule("3.2.2.24", O.A2, "Group A, Division 2, up to 6 Storeys, Any Area, Sprinklered",
                requires_sprinklered=True, max_storeys=6, max_height_m=None, max_area_by_storeys=None,
                construction="noncombustible", floor_frr_h=1.0, roof_frr_h=None, mezzanine_frr_h=1.0),
    ArticleRule("3.2.2.25", O.A2, "Group A, Division 2, up to 2 Storeys",
                requires_sprinklered=False, max_storeys=2, max_height_m=None, max_area_by_storeys=None,
                construction="combustible or noncombustible", floor_frr_h=0.75, roof_frr_h=0.75, mezzanine_frr_h=0.75,
                max_area_by_storeys_streets={1: {1: 1600, 2: 2000, 3: 2400}, 2: {1: 800, 2: 1000, 3: 1200}},
                notes=["Table 3.2.2.25: area by storeys and streets faced. Unsprinklered — VBBL 3.2.2.18.(3) requires sprinklers in all new buildings."]),
    ArticleRule("3.2.2.26", O.A2, "Group A, Division 2, up to 2 Storeys, Increased Area, Sprinklered",
                requires_sprinklered=True, max_storeys=2, max_height_m=None, max_area_by_storeys={1: 4800.0, 2: 2400.0},
                construction="combustible or noncombustible", floor_frr_h=0.75, roof_frr_h=None, mezzanine_frr_h=0.75),
    ArticleRule("3.2.2.27", O.A2, "Group A, Division 2, up to 2 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=2, max_height_m=None, max_area_by_storeys={1: 1200.0, 2: 600.0},
                construction="combustible or noncombustible", floor_frr_h=0.0, roof_frr_h=None, mezzanine_frr_h=None,
                no_basement_area_bonus={1: 2400.0},
                notes=["No FRR stated for floors in this article; Section 3.3 and 3.1.3 separations still apply."]),
    ArticleRule("3.2.2.28", O.A2, "Group A, Division 2, One Storey",
                requires_sprinklered=False, max_storeys=1, max_height_m=None, max_area_by_storeys=None,
                construction="combustible or noncombustible", floor_frr_h=0.0, roof_frr_h=None, mezzanine_frr_h=None,
                max_area_by_storeys_streets={1: {1: 400, 2: 500, 3: 600}},
                notes=["Limits may be doubled without a basement if compartmented by 1 h fire separations ((2))."]),
]

# ---- Group E ladder ------------------------------------------------------------------
GROUP_E: list[ArticleRule] = [
    ArticleRule("3.2.2.66", O.E, "Group E, Any Height, Any Area, Sprinklered",
                requires_sprinklered=True, max_storeys=None, max_height_m=None, max_area_by_storeys=None,
                construction="noncombustible", floor_frr_h=2.0, roof_frr_h=None, mezzanine_frr_h=1.0,
                notes=["Default rung; applies unless 3.2.2.67–.71 or .93 permits otherwise."]),
    ArticleRule("3.2.2.67", O.E, "Group E, up to 4 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=4, max_height_m=None, max_area_by_storeys={n: 1800.0 for n in range(1, 5)},
                construction="combustible or noncombustible", floor_frr_h=1.0, roof_frr_h=None, mezzanine_frr_h=1.0),
    ArticleRule("3.2.2.69", O.E, "Group E, up to 3 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=3, max_height_m=None, max_area_by_storeys={1: 7200.0, 2: 3600.0, 3: 2400.0},
                construction="combustible or noncombustible", floor_frr_h=0.75, roof_frr_h=None, mezzanine_frr_h=0.75),
    ArticleRule("3.2.2.70", O.E, "Group E, up to 2 Storeys",
                requires_sprinklered=False, max_storeys=2, max_height_m=None, max_area_by_storeys=None,
                construction="combustible or noncombustible", floor_frr_h=0.75, roof_frr_h=None, mezzanine_frr_h=None,
                max_area_by_storeys_streets={1: {1: 1000, 2: 1250, 3: 1500}, 2: {1: 600, 2: 750, 3: 900}},
                notes=["Table 3.2.2.70. Unsprinklered — VBBL 3.2.2.18.(3) requires sprinklers in all new buildings."]),
    ArticleRule("3.2.2.71", O.E, "Group E, up to 2 Storeys, Sprinklered",
                requires_sprinklered=True, max_storeys=2, max_height_m=None, max_area_by_storeys={1: 3000.0, 2: 1800.0},
                construction="combustible or noncombustible", floor_frr_h=0.75, roof_frr_h=None, mezzanine_frr_h=None),
]
# 3.2.2.68 (Group E, up to 3 Storeys, unsprinklered) did not extract cleanly — add when needed.

LADDERS = {O.C: GROUP_C, O.A2: GROUP_A2, O.E: GROUP_E}


@dataclass
class Evaluation:
    rule: ArticleRule
    qualifies: bool
    checks: list[tuple[str, bool, str]]     # (condition, passed, detail)


def evaluate(rule: ArticleRule, storeys: int, height_m: float, area_m2: float, sprinklered: bool,
             streets_faced: int = 1, has_basement: bool = True) -> Evaluation:
    checks = []
    if rule.requires_sprinklered:
        checks.append(("sprinklered throughout", sprinklered, "yes" if sprinklered else "no"))
    if rule.max_storeys is not None:
        checks.append((f"≤ {rule.max_storeys} storeys", storeys <= rule.max_storeys, f"{storeys} storeys"))
    if rule.max_height_m is not None:
        checks.append((f"≤ {rule.max_height_m:g} m to uppermost floor", height_m <= rule.max_height_m, f"{height_m:.2f} m"))
    within = rule.max_storeys is None or storeys <= rule.max_storeys
    if rule.max_area_by_storeys_streets is not None and within:
        row = rule.max_area_by_storeys_streets.get(storeys, {})
        cap = row.get(min(max(streets_faced, 1), 3))
        if cap is not None:
            checks.append((f"building area ≤ {cap:,.0f} m² at {storeys} storeys facing {streets_faced} street(s)", area_m2 <= cap, f"{area_m2:,.0f} m²"))
    elif rule.max_area_by_storeys is not None and within:
        cap = rule.max_area_by_storeys.get(storeys)
        if rule.no_basement_area_bonus and not has_basement and storeys in rule.no_basement_area_bonus:
            cap = rule.no_basement_area_bonus[storeys]
            checks.append((f"building area ≤ {cap:,.0f} m² at {storeys} storeys, no basement", area_m2 <= cap, f"{area_m2:,.0f} m²"))
        elif cap is None:
            checks.append(("building area", True, f"{area_m2:,.0f} m² — not limited at {storeys} storeys"))
        else:
            checks.append((f"building area ≤ {cap:,.0f} m² at {storeys} storeys", area_m2 <= cap, f"{area_m2:,.0f} m²"))
    return Evaluation(rule, all(p for _, p, _ in checks), checks)


def ladder(b: BuildingModel, height_dets: list[Determination], occ_dets: list[Determination]) -> dict[str, list[Evaluation]]:
    """Every rung evaluated, per block, in code order — for drawing the ladder."""
    H = {d.key: d for d in height_dets}; Oc = {d.key: d for d in occ_dets}
    out = {}
    for blk in b.blocks():
        majors = [O(v) for v in Oc[f"{blk}.major_occupancies"].value]
        primary = next((g for g in majors if g in LADDERS), None)
        if primary is None:
            continue
        out[blk] = [evaluate(r, H[f"{blk}.building_height_storeys"].value, H[f"{blk}.height_to_top_floor_m"].value,
                             H[f"{blk}.building_area_m2"].value, b.is_sprinklered, b.site.streets_faced,
                             H[f"{blk}.basements"].value != "none") for r in LADDERS[primary]]
    return out


def analyze(b: BuildingModel, height_dets: list[Determination], occ_dets: list[Determination],
            law: Optional[Bylaw] = None, chosen: Optional[dict[str, str]] = None) -> list[Determination]:
    """
    height_dets / occ_dets: outputs of height_area.analyze and occupancy.analyze.
    chosen: optional {block: article_id} the designer selected; otherwise the
            least demanding qualifying article is proposed.
    """
    law = law or Bylaw()
    H = {d.key: d for d in height_dets}
    Oc = {d.key: d for d in occ_dets}
    out: list[Determination] = []
    chosen = chosen or {}

    for blk in b.blocks():
        storeys = H[f"{blk}.building_height_storeys"].value
        height_m = H[f"{blk}.height_to_top_floor_m"].value
        area = H[f"{blk}.building_area_m2"].value
        majors = [O(v) for v in Oc[f"{blk}.major_occupancies"].value]
        primary = next((g for g in majors if g in LADDERS), None)
        if primary is None:
            out.append(Determination(key=f"{blk}.article", label="Governing 3.2.2 article", value=None, block=blk,
                                     clauses=[law.article("3.2.2.6", 1)],
                                     because=f"Major occupancies {[g.value for g in majors]}; the 3.2.2 ladder for these Groups is not encoded yet, so no article is proposed.",
                                     flags=[f"No ladder encoded yet for major occupancies {[g.value for g in majors]} — determine the governing article manually."]))
            continue

        has_bsmt = H[f"{blk}.basements"].value != "none"
        evals = [evaluate(r, storeys, height_m, area, b.is_sprinklered, b.site.streets_faced, has_bsmt) for r in LADDERS[primary]]
        qualifying = sorted([e for e in evals if e.qualifies], key=lambda e: e.rule.strictness())
        excluded = [e for e in evals if not e.qualifies]

        # governing = designer's choice if valid, else least demanding qualifying rung
        pick = None
        designer_fail = None
        if blk in chosen:
            pick = next((e for e in qualifying if e.rule.id == chosen[blk]), None)
            if pick is None:
                designer_fail = next((e for e in excluded if e.rule.id == chosen[blk]), None)
        if pick is None:
            pick = qualifying[0] if qualifying else None

        # candidates line
        cand_txt = "; ".join(
            f"{e.rule.id} ({e.rule.construction}, floors {e.rule.floor_frr_h:g} h)" for e in qualifying) or "none"
        excl_txt = "; ".join(
            f"{e.rule.id} fails " + ", ".join(f"{c} [{d}]" for c, p, d in e.checks if not p) for e in excluded) or "none"
        out.append(Determination(
            key=f"{blk}.article_candidates", label="Qualifying 3.2.2 articles", value=[e.rule.id for e in qualifying], block=blk,
            clauses=[law.article(e.rule.id, 1) for e in qualifying] or [law.article(LADDERS[primary][0].id, 1)],
            because=(f"Group {primary.value}, {storeys} storeys, {height_m:.2f} m to uppermost floor, building area {area:,.0f} m², "
                     f"{'sprinklered' if b.is_sprinklered else 'unsprinklered'}. Qualifying: {cand_txt}. Excluded: {excl_txt}."),
            inputs={"storeys": storeys, "height_m": height_m, "area_m2": area, "sprinklered": b.is_sprinklered},
        ))

        if pick is None:
            out.append(Determination(key=f"{blk}.article", label="Governing 3.2.2 article", value=None, block=blk,
                                     clauses=[law.article(LADDERS[primary][0].id)],
                                     flags=["No rung qualifies — check inputs; the default rung's conditions also failed."]))
            continue

        r = pick.rule
        d = Determination(
            key=f"{blk}.article", label="Governing 3.2.2 article", value=r.id, block=blk,
            clauses=[law.article(r.id, 1), law.article(r.id, 2)],
            because=(f"“{r.title}”. Conditions in Sentence (1): "
                     + "; ".join(f"{c} ✓ [{det}]" for c, p, det in pick.checks)
                     + (f". Selected by the designer." if blk in chosen and designer_fail is None else
                        f". Proposed as the least demanding qualifying rung; {len(qualifying) - 1} other(s) also qualify.")),
            inputs={"chosen_by_designer": blk in chosen and designer_fail is None},
        )
        if designer_fail is not None:
            d.flags.insert(0, f"DESIGNER SELECTED {designer_fail.rule.id} BUT IT DOES NOT QUALIFY: "
                              + "; ".join(f"{c} — {det}" for c, p, det in designer_fail.checks if not p)
                              + f". Falling back to {r.id}. Check the inputs (building area is the usual culprit) before accepting.")
        # other major occupancies: admitted by this article, or a 3.2.2.6/.7 problem
        superimposed = []
        for g in majors:
            if g == primary:
                continue
            if g.value in r.admits:
                d.flags.append(f"Group {g.value} present — admitted within {r.id} per Sentence {r.admits[g.value]}; confirm the storey condition.")
            elif g in LADDERS:
                superimposed.append(g)
                d.flags.append(f"Group {g.value} is a major occupancy not admitted by {r.id} — assessed under its own ladder per 3.2.2.7 (see below); confirm the occupancies are superimposed, otherwise 3.2.2.6 applies.")
            else:
                d.flags.append(f"Group {g.value} is a major occupancy not admitted by {r.id} — 3.2.2.6 (most restrictive governs) or 3.2.2.7 (superimposed) must be applied; no ladder encoded for {g.value}.")
        out.append(d)

        # 3.2.2.7: each superimposed occupancy's portion is treated as if the entire building
        # were of that occupancy, using the WHOLE building's height and area (3.2.2.5).
        for g in superimposed:
            ev = [evaluate(rr, storeys, height_m, area, b.is_sprinklered, b.site.streets_faced, has_bsmt) for rr in LADDERS[g]]
            q = sorted([e for e in ev if e.qualifies], key=lambda e: e.rule.strictness())
            if not q:
                out.append(Determination(key=f"{blk}.article.{g.value}", label=f"Article for Group {g.value} portion (3.2.2.7)", value=None, block=blk,
                                         clauses=[law.article("3.2.2.7", 1)], flags=[f"No {g.value} rung qualifies at {storeys} storeys / {area:,.0f} m²."]))
                continue
            rr = q[0].rule
            out.append(Determination(
                key=f"{blk}.article.{g.value}", label=f"Article for Group {g.value} portion (3.2.2.7)", value=rr.id, block=blk,
                clauses=[law.article("3.2.2.7", 1), law.article("3.2.2.5", 1), law.article(rr.id, 1), law.article(rr.id, 2)],
                because=(f"“{rr.title}”, applied to the {g.value} portion as if the entire building were Group {g.value}, using the whole "
                         f"building's height and area (3.2.2.5). Conditions: " + "; ".join(f"{c} ✓ [{det}]" for c, p, det in q[0].checks)
                         + f". Requires {rr.construction}, floors ≥ {rr.floor_frr_h:g} h."),
                flags=["The floor between the superimposed occupancies is rated by the LOWER occupancy's article and Table 3.1.3.1, whichever is greater (3.2.2.7.(2))."],
            ))

        # requirement lines from Sentence (2)
        req = [
            ("Construction", r.construction),
            ("Floor assemblies", f"fire separations, FRR ≥ {r.floor_frr_h:g} h"),
        ]
        if r.roof_frr_h is not None:
            req.append(("Roof assemblies", f"FRR ≥ {r.roof_frr_h:g} h"))
        if r.mezzanine_frr_h is not None:
            req.append(("Mezzanines", f"FRR ≥ {r.mezzanine_frr_h:g} h"))
        req.append(("Loadbearing walls, columns, arches", "FRR ≥ that of the supported assembly"))
        for label, val in req:
            dd = Determination(key=f"{blk}.req.{label}", label=label, value=val, block=blk,
                               clauses=[law.article(r.id, 2)], because=f"Required by {r.id}.(2). " + " ".join(r.notes))
            decl = b.declared_construction.get(blk)
            if label == "Construction" and decl and decl.lower().strip() != val.lower().strip():
                dd.value = f"{decl} (declared)"
                dd.because += f" The designer declares {decl}; {r.id} would permit {val}. The stricter declaration is shown."
            out.append(dd)
        if blk in b.slab_separated_blocks:
            out.append(Determination(
                key=f"{blk}.req.3.2.1.2 slab", label="Separating floor/roof assembly (3.2.1.2)", block=blk,
                value="2 h fire separation, noncombustible",
                clauses=[law.article("3.2.1.2", 1)],
                because="This block is a separate building only because it is a basement storage garage under a floor/roof assembly built as a 2 h noncombustible fire separation, protected per 3.1.10.2.(4)(a).",
            ))
            out.append(Determination(
                key=f"{blk}.req.3.2.1.2 walls", label="Exterior basement walls above ground (3.2.1.2)", block=blk,
                value="2 h fire separation, noncombustible",
                clauses=[law.article("3.2.1.2", 1), law.article("3.2.1.2", 2)],
                because="Openings permitted without closures only if sprinklered and the slab projects 1–2 m or upper storeys are recessed (Sentence (2)).",
                flags=["Confirm the slab projection / recess condition of 3.2.1.2.(2) on the plans where the parkade wall has openings."],
            ))
    return out


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    from codesheet import height_area, occupancy
    hd = height_area.analyze(project); od = occupancy.analyze(project)
    for d in analyze(project, hd, od, chosen={"North": "3.2.2.51", "South": "3.2.2.51"}):
        print(f"[{d.block}] {d.label:36} {str(d.value):46} {'; '.join(c.ref() for c in d.clauses)[:90]}")
        if d.because: print(f"      {d.because}")
        for f in d.flags: print(f"      ⚠ {f}")
