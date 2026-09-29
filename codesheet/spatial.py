"""
codesheet.spatial — piece 7: spatial separation of exposing building faces (3.2.3).

The idea in one breath: a wall close to the property line could set the
neighbour alight, so the closer it is (the smaller its *limiting distance*),
the smaller the share of it that may be window (*unprotected openings*), and
the more the wall itself must resist fire.

Per face, per storey band (each storey is its own fire compartment when the
floors are fire separations, 3.2.3.2), we compute:

  face area          length × band height  (3.2.3.1.(3): projection of the wall)
  permitted UPO %    Table 3.2.3.1.-D (sprinklered) from area + limiting distance
  actual UPO %       aggregate opening area in the band / face area (3.2.3.1.(2))
  pass/fail          actual ≤ permitted
  wall requirements  Table 3.2.3.7 keyed on the PERMITTED %: FRR, construction, cladding

Why bands and not the whole face: the code lets you evaluate each fire
compartment separately, and a 6-storey face treated whole would have a huge
area and a very different table row. Code consultants' sheets do it per storey
band, and that is what we reproduce.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from codesheet.model import BuildingModel, ExteriorFace, Storey
from codesheet.determinations import Determination, Bylaw, Clause
from codesheet.table_3231 import (permitted_upo_sprinklered, permitted_upo_unsprinklered, exposing_face_requirements,
                                  PAGE_D, PAGE_B, PAGE_C, PAGE_3237)


@dataclass
class BandResult:
    face: ExteriorFace
    label: str                  # e.g. "L2"
    z0: float
    z1: float
    face_area_m2: float
    opening_area_m2: float
    actual_pct: float
    permitted_pct: float
    how: str
    frr_min: int
    construction: str
    cladding: str
    band_label: str

    @property
    def ok(self) -> bool:
        return self.actual_pct <= self.permitted_pct + 1e-9


def _bands_for_face(b: BuildingModel, f: ExteriorFace) -> list[tuple[str, float, float]]:
    """Storey bands (label, z0, z1) of the face's block clipped to the face's extent."""
    st = [s for s in b.storeys_sorted(f.block) if not s.is_roof and not s.is_mezzanine and not s.is_part_of]
    out = []
    for s in st:
        z0, z1 = max(s.elevation_m, f.base_elevation_m), min(s.elevation_m + s.height_m, f.top_elevation_m)
        if z1 - z0 > 0.3:
            out.append((s.label, z0, z1))
    return out


def evaluate_face(b: BuildingModel, f: ExteriorFace, group: str = "C") -> list[BandResult]:
    sprinklered = f.is_sprinklered_behind if f.is_sprinklered_behind is not None else b.is_sprinklered
    L = f.length_m()
    results = []
    for label, z0, z1 in _bands_for_face(b, f):
        area = L * (z1 - z0)
        # an opening belongs to the band containing its centre
        openings = [o for o in f.openings if not o.is_protected
                    and z0 <= f.base_elevation_m + o.sill_m + o.height_m / 2 < z1]
        oa = sum(o.area_m2() for o in openings)
        actual = 100 * oa / area if area else 0.0
        if label in f.stated_upo_pct:                    # measured on the drawings beats schematic windows
            actual = f.stated_upo_pct[label]
            oa = actual / 100 * area
        if sprinklered:
            permitted, how = permitted_upo_sprinklered(area, f.limiting_distance_m)
        else:
            permitted, how = permitted_upo_unsprinklered(area, f.limiting_distance_m, L, z1 - z0, group)
        frr, cons, clad, band = exposing_face_requirements(permitted)
        results.append(BandResult(f, label, z0, z1, area, oa, round(actual, 1), permitted, how, frr, cons, clad, band))
    return results


def analyze(b: BuildingModel, law: Optional[Bylaw] = None, groups_by_block: Optional[dict[str, str]] = None
            ) -> tuple[list[Determination], dict[str, list[BandResult]]]:
    """groups_by_block: primary major occupancy per block (E/F1/F2 select Table -C when unsprinklered)."""
    law = law or Bylaw()
    groups_by_block = groups_by_block or {}
    sprinklered_all = b.is_sprinklered
    t_d = (Clause(id="Table 3.2.3.1.-D", edition=law.edition, page=PAGE_D, title="Unprotected Opening Limits — Sprinklered")
           if sprinklered_all else
           Clause(id="Table 3.2.3.1.-B / -C", edition=law.edition, page=PAGE_B, title="Unprotected Opening Limits — not Sprinklered"))
    t_7 = Clause(id="Table 3.2.3.7", edition=law.edition, page=PAGE_3237, title="Minimum Construction Requirements for Exposing Building Faces")
    out: list[Determination] = []
    bands: dict[str, list[BandResult]] = {}
    for f in b.exterior_faces:
        rs = evaluate_face(b, f, groups_by_block.get(f.block, "C"))
        bands[f.label] = rs
        worst = min(rs, key=lambda r: r.permitted_pct - r.actual_pct) if rs else None
        for r in rs:
            d = Determination(
                key=f"{f.block}.face.{f.label}.{r.label}", label=f"{f.label} · {r.label}", block=f.block,
                value=f"{r.actual_pct:g}% of {r.permitted_pct:g}% permitted — {'OK' if r.ok else 'EXCEEDS'}",
                clauses=[law.article("3.2.3.1", 1), t_d, law.article("3.2.3.7", 1), t_7],
                because=(f"Exposing face {L:.1f} m × {r.z1 - r.z0:.2f} m = {r.face_area_m2:,.0f} m² at limiting distance "
                         f"{f.limiting_distance_m:g} m ({f.exposure.value.replace('_', ' ')}). {'Table 3.2.3.1.-D (' + r.how + ')' if sprinklered_all else r.how} permits "
                         f"{r.permitted_pct:g}%. Unprotected openings in band: {r.opening_area_m2:,.1f} m² = {r.actual_pct:g}%. "
                         f"Table 3.2.3.7 for permitted {r.band_label}%: FRR ≥ {r.frr_min} min, {r.construction}, {r.cladding} cladding."
                         if (L := f.length_m()) else ""),
                inputs={"face_area_m2": round(r.face_area_m2, 1), "opening_area_m2": round(r.opening_area_m2, 1),
                        "actual_pct": r.actual_pct, "permitted_pct": r.permitted_pct, "ld_m": f.limiting_distance_m,
                        "frr_min": r.frr_min, "construction": r.construction, "cladding": r.cladding},
            )
            if not r.ok:
                d.flags.append(f"Openings exceed the permitted area by {r.actual_pct - r.permitted_pct:.1f} points — reduce openings, increase limiting distance, or protect openings (3.2.3.10–.12).")
            if r.label in f.stated_upo_pct:
                d.inputs["actual_source"] = "stated on drawings"
            elif f.source_note and "synthesized" in f.source_note:
                d.flags.append("Opening areas are synthesized placeholders — replace from elevations before relying on the actual %.")
            out.append(d)
        if worst is not None:
            out.append(Determination(
                key=f"{f.block}.face.{f.label}.summary", label=f"{f.label} — governing band", block=f.block,
                value=f"{worst.label}: FRR ≥ {worst.frr_min} min, {worst.cladding} cladding",
                clauses=[law.article("3.2.3.7", 1), t_7],
                because=f"Tightest band is {worst.label} ({worst.actual_pct:g}% of {worst.permitted_pct:g}%). Wall requirements follow the permitted percentage, not the actual.",
            ))
    return out, bands


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    dets, bands = analyze(project)
    for face, rs in bands.items():
        print(f"\n{face}  (LD {rs[0].face.limiting_distance_m} m)")
        for r in rs:
            print(f"   {r.label:4} area {r.face_area_m2:6.0f} m²  permitted {r.permitted_pct:5.1f}%  actual {r.actual_pct:5.1f}%  {'OK ' if r.ok else 'FAIL'}  FRR {r.frr_min:>3} min, {r.cladding} cladding")
