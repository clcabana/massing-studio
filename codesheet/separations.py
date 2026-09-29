"""
codesheet.separations — piece 8: fire separations between major occupancies (3.1.3).

Where two different major occupancies touch — side by side on a storey, or
one stacked over another — the wall or floor between them must be a fire
separation rated per Table 3.1.3.1. Two subtleties the table's notes carry:

  Note (3)  in a building built to 3.2.2.51 (the 6-storey combustible article),
            C ↔ A2 needs 2 h, not the table's 1 h.  (Suites over a dining hall — the common case.)
  Note (4)  same for D ↔ A2 under 3.2.2.60.
  3.2.2.7.(2) when one occupancy sits over another, the floor between them is
            rated by the LOWER occupancy's 3.2.2 article as well; the greater of
            the two requirements governs.

Adjacency is inferred from the model: any two Groups present on the same storey
are treated as adjacent (we have areas, not room adjacency, so this is
conservative and flagged), and the dominant Group of storey N is stacked on
the dominant Group of storey N-1.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from codesheet.model import BuildingModel, OccupancyGroup as O
from codesheet.determinations import Determination, Bylaw, Clause
from codesheet.occupancy import classify_storey

# Table 3.1.3.1 — minimum FRR (h) between major occupancies. VBBL 2025 p.124.
# Symmetric; None = no requirement ("—"); "X" = prohibited combination (3.1.3.2).
_T = {
    ("A1","A2"):1, ("A1","A3"):1, ("A1","A4"):1, ("A1","B1"):2, ("A1","B2"):2, ("A1","B3"):2, ("A1","C"):1, ("A1","D"):1, ("A1","E"):2, ("A1","F2"):2, ("A1","F3"):1,
    ("A2","A3"):1, ("A2","A4"):1, ("A2","B1"):2, ("A2","B2"):2, ("A2","B3"):2, ("A2","C"):1, ("A2","D"):1, ("A2","E"):2, ("A2","F2"):2, ("A2","F3"):1,
    ("A3","A4"):1, ("A3","B1"):2, ("A3","B2"):2, ("A3","B3"):2, ("A3","C"):1, ("A3","D"):1, ("A3","E"):2, ("A3","F2"):2, ("A3","F3"):1,
    ("A4","B1"):2, ("A4","B2"):2, ("A4","B3"):2, ("A4","C"):1, ("A4","D"):1, ("A4","E"):2, ("A4","F2"):2, ("A4","F3"):1,
    ("B1","B2"):2, ("B1","B3"):2, ("B1","C"):2, ("B1","D"):2, ("B1","E"):2, ("B1","F2"):2, ("B1","F3"):2,
    ("B2","B3"):1, ("B2","C"):2, ("B2","D"):2, ("B2","E"):2, ("B2","F2"):2, ("B2","F3"):2,
    ("B3","C"):1, ("B3","D"):2, ("B3","E"):2, ("B3","F2"):2, ("B3","F3"):2,
    ("C","D"):1, ("C","E"):2, ("C","F2"):2, ("C","F3"):1,
    ("D","E"):None, ("D","F1"):3, ("D","F2"):None, ("D","F3"):None,
    ("E","F1"):3, ("E","F2"):None, ("E","F3"):None,
    ("F1","F2"):2, ("F1","F3"):2, ("F2","F3"):None,
}
for g in ("A1","A2","A3","A4","B1","B2","B3","C"):
    _T[(g,"F1")] = "X"        # note (2): 3.1.3.2.(1) prohibits F1 with A, B or C
PAGE_3131 = 124


def table_frr(a: str, b: str) -> Optional[float | str]:
    if a == b:
        return None
    return _T.get((a, b), _T.get((b, a)))


def required_frr(a: str, b: str, article: Optional[str]) -> tuple[Optional[float | str], str]:
    """Table value plus the article-specific notes. Returns (hours or 'X' or None, why)."""
    base = table_frr(a, b)
    pair = {a, b}
    if pair == {"C", "A2"} and article == "3.2.2.51":
        return 2.0, "Table 3.1.3.1 gives 1 h; Note (3) raises it to 2 h for buildings built to 3.2.2.51"
    if pair == {"D", "A2"} and article == "3.2.2.60":
        return 2.0, "Table 3.1.3.1 gives 1 h; Note (4) raises it to 2 h for buildings built to 3.2.2.60"
    if base == "X":
        return "X", "combination prohibited by 3.1.3.2.(1)"
    if base is None:
        return None, "Table 3.1.3.1 shows no requirement (—) for this pair"
    return float(base), f"Table 3.1.3.1: {base:g} h"


def analyze(b: BuildingModel, article_dets: list[Determination], law: Optional[Bylaw] = None) -> list[Determination]:
    law = law or Bylaw()
    A = {d.key: d for d in article_dets}
    t = Clause(id="Table 3.1.3.1", edition=law.edition, page=PAGE_3131, title="Major Occupancy Fire Separations")
    out: list[Determination] = []
    for blk in b.blocks():
        article = A.get(f"{blk}.article").value if A.get(f"{blk}.article") else None
        floor_frr = None
        if A.get(f"{blk}.req.Floor assemblies"):
            v = A[f"{blk}.req.Floor assemblies"].value           # "fire separations, FRR ≥ 1 h"
            try:
                floor_frr = float(v.split("≥")[1].split("h")[0])
            except Exception:
                pass
        storeys = [s for s in b.storeys_sorted(blk) if not s.is_roof and not s.is_mezzanine]
        groups_on: dict[str, dict[str, float]] = {}
        for s in storeys:
            parent = next((p for p in storeys if p.label == s.is_part_of), None) if s.is_part_of else None
            per = defaultdict(float)
            for z, g, conf, note in classify_storey(s, parent):
                if g is not None:
                    per[g.value] += z.area_m2
            # only groups that are MAJOR on this storey (>10% of its floor area, 3.2.2.8 logic)
            floor_area = s.plan_area_m2(b.footprint)
            groups_on[s.label] = {g: a for g, a in per.items() if floor_area and a / floor_area > 0.10}

        seen = set()
        # same-storey adjacencies
        for s in storeys:
            gs = sorted(groups_on[s.label], key=lambda g: -groups_on[s.label][g])
            for i in range(len(gs)):
                for j in range(i + 1, len(gs)):
                    a_, b_ = gs[i], gs[j]
                    frr, why = required_frr(a_, b_, article)
                    key = (s.label, a_, b_)
                    if key in seen:
                        continue
                    seen.add(key)
                    val = "prohibited" if frr == "X" else ("none required" if frr is None else f"{frr:g} h")
                    d = Determination(
                        key=f"{blk}.sep.{s.label}.{a_}-{b_}", label=f"{s.label}: {a_} ↔ {b_} (vertical separation)", value=val, block=blk,
                        clauses=[law.article("3.1.3.1", 1), t],
                        because=f"Both occupancies occur on {s.label} ({a_} {groups_on[s.label][a_]:,.0f} m², {b_} {groups_on[s.label][b_]:,.0f} m²). {why}.",
                        flags=["Adjacency inferred from co-location on the storey; confirm on plan whether these occupancies actually adjoin."],
                    )
                    if frr == "X":
                        d.flags.insert(0, "PROHIBITED combination — 3.1.3.2.(1).")
                    out.append(d)
        # stacked adjacencies (dominant over dominant)
        for lower, upper in zip(storeys, storeys[1:]):
            if upper.is_part_of or lower.is_part_of:
                continue
            gl = max(groups_on[lower.label], key=groups_on[lower.label].get, default=None)
            gu = max(groups_on[upper.label], key=groups_on[upper.label].get, default=None)
            if not gl or not gu or gl == gu:
                continue
            frr, why = required_frr(gl, gu, article)
            req = frr if isinstance(frr, float) else 0.0
            governing = max(req, floor_frr or 0.0)
            because = (f"{gu} on {upper.label} sits over {gl} on {lower.label}. {why}. "
                       f"The floor is also a fire separation under {article}.(2) at {floor_frr:g} h; the greater governs (3.2.2.7.(2))."
                       if floor_frr is not None else f"{gu} on {upper.label} sits over {gl} on {lower.label}. {why}.")
            out.append(Determination(
                key=f"{blk}.sep.{lower.label}|{upper.label}.{gl}-{gu}", label=f"Floor {lower.label}/{upper.label}: {gl} below, {gu} above",
                value=f"{governing:g} h", block=blk,
                clauses=[law.article("3.1.3.1", 1), t, law.article("3.2.2.7", 2)], because=because,
            ))
    return out


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    from codesheet import height_area, occupancy, articles
    hd = height_area.analyze(project); od = occupancy.analyze(project)
    ad = articles.analyze(project, hd, od, chosen={"North": "3.2.2.51", "South": "3.2.2.51"})
    for d in analyze(project, ad):
        print(f"[{d.block}] {d.label:52} {d.value:>14}   {d.because}")
