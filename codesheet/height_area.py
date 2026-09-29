"""
codesheet.height_area — piece 5: grade, first storey, building height, building area.

This is the first module that applies the bylaw to the model, and it is where
code sheets most often go wrong, because "storeys" on the drawings (P2, P1,
L1…L6) and "storeys in building height" under the code are different things.

The chain, each step citing its definition:

  grade            given in the model (Site.grade_elevation_m). We don't compute
                   it from finished ground yet; the surveyor's/architect's figure
                   is entered and cited.
  first storey     the UPPERMOST storey whose floor is not more than 2 m above
                   grade. Note "uppermost": on a sloping site two storeys can
                   pass the 2 m test and the higher one wins.
  basements        everything below the first storey. They exist, they have
                   occupancies, but they do not count toward building height.
  building height  storeys between the roof and the floor of the first storey,
                   inclusive of the first storey, EXCLUDING rooftop enclosures
                   (3.2.1.1.(1)) and mezzanines that meet 3.2.1.1.(3)/(4).
  building area    greatest horizontal area ABOVE GRADE within exterior walls,
                   to the centreline of firewalls. So below-grade parking never
                   sets the building area, and each firewall-separated block
                   has its own.

Everything is computed per block, because a firewall makes separate buildings.
"""
from __future__ import annotations

from typing import Optional

from codesheet.model import BuildingModel, Storey
from codesheet.determinations import Determination, Bylaw

FIRST_STOREY_MAX_ABOVE_GRADE_M = 2.0


def _main_storeys(b: BuildingModel, block: str) -> list[Storey]:
    """Storeys that could count: not roofs, not mezzanines, not detached parts."""
    return [s for s in b.storeys_sorted(block) if not s.is_roof and not s.is_mezzanine and not s.is_part_of]


def first_storey(b: BuildingModel, block: str, law: Bylaw) -> Determination:
    g = b.site.grade_elevation_m
    cands = [s for s in _main_storeys(b, block) if s.elevation_m <= g + FIRST_STOREY_MAX_ABOVE_GRADE_M]
    if not cands:
        return Determination(key=f"{block}.first_storey", label="First storey", value=None, block=block,
                             clauses=[law.definition("First storey")],
                             flags=["No storey has its floor within 2 m above grade — check grade elevation."])
    fs = max(cands, key=lambda s: s.elevation_m)
    passing = ", ".join(f"{s.label} ({s.elevation_m - g:+.2f} m)" for s in cands)
    return Determination(
        key=f"{block}.first_storey", label="First storey", value=fs.label, block=block,
        clauses=[law.definition("First storey"), law.definition("Grade")],
        because=(f"Grade is {g:.2f} m. Storeys with floor ≤ 2 m above grade: {passing}. "
                 f"The uppermost of these is {fs.label} at {fs.elevation_m:.2f} m ({fs.elevation_m - g:+.2f} m)."),
        inputs={"grade_m": g, "candidates": [s.label for s in cands]},
    )


def basements(b: BuildingModel, block: str, law: Bylaw, fs_label: str) -> Determination:
    st = _main_storeys(b, block)
    fs = next(s for s in st if s.label == fs_label)
    below = [s.label for s in sorted(st, key=lambda s: -s.elevation_m) if s.elevation_m < fs.elevation_m]  # top-down, as a sheet reads
    return Determination(
        key=f"{block}.basements", label="Basements", value=below or "none", block=block,
        clauses=[law.definition("Basement")],
        because=f"Storeys below the first storey ({fs_label}): {', '.join(below) or 'none'}. They carry occupancies but do not count toward building height.",
    )


def building_height_storeys(b: BuildingModel, block: str, law: Bylaw, fs_label: str) -> Determination:
    st = _main_storeys(b, block)
    fs = next(s for s in st if s.label == fs_label)
    counted = [s for s in st if s.elevation_m >= fs.elevation_m - 0.01]
    excluded = [s.label for s in b.storeys_sorted(block) if s.is_mezzanine]
    d = Determination(
        key=f"{block}.building_height_storeys", label="Building height", value=len(counted), unit="storeys", block=block,
        clauses=[law.definition("Building height"), law.article("3.2.1.1", 1)],
        because=(f"Storeys from the first storey ({fs_label}) to the roof: {', '.join(s.label for s in counted)}. "
                 f"Rooftop enclosures for elevator machinery, service rooms and stair access are not storeys (3.2.1.1.(1))."
                 + (f" Mezzanines not counted (subject to 3.2.1.1.(3)/(4)): {', '.join(excluded)}." if excluded else "")),
        inputs={"counted": [s.label for s in counted]},
    )
    if excluded:
        d.flags.append("Mezzanine present — confirm it meets 3.2.1.1.(3) or (4) or it counts as a storey.")
    return d


def building_height_metres(b: BuildingModel, block: str, law: Bylaw, fs_label: str) -> Determination:
    """Height from the first-storey floor to the uppermost floor level — the figure
    articles like 3.2.2.48.(1)(c) and 3.2.2.51.(1)(c) test against."""
    st = _main_storeys(b, block)
    fs = next(s for s in st if s.label == fs_label)
    top = max(st, key=lambda s: s.elevation_m)
    h = top.elevation_m - fs.elevation_m
    return Determination(
        key=f"{block}.height_to_top_floor_m", label="Height, first-storey floor to uppermost floor", value=round(h, 2), unit="m", block=block,
        clauses=[law.article("3.2.2.51", 1)],
        because=f"Uppermost floor {top.label} at {top.elevation_m:.2f} m minus first-storey floor {fs.label} at {fs.elevation_m:.2f} m.",
        inputs={"top_floor_m": top.elevation_m, "first_storey_floor_m": fs.elevation_m},
    )


def building_area(b: BuildingModel, block: str, law: Bylaw, fs_label: str) -> Determination:
    st = [s for s in b.storeys_sorted(block) if not s.is_roof and not s.is_mezzanine]
    fs = next(s for s in st if s.label == fs_label)
    above = [s for s in st if s.elevation_m >= fs.elevation_m - 0.01]
    # sum detached parts at the same level into their parent
    per_level: dict[str, float] = {}
    for s in above:
        key = s.is_part_of or s.label
        per_level[key] = per_level.get(key, 0.0) + s.plan_area_m2(b.footprint)
    biggest = max(per_level, key=per_level.get)
    d = Determination(
        key=f"{block}.building_area_m2", label="Building area", value=round(per_level[biggest], 0), unit="m²", block=block,
        clauses=[law.definition("Building area")],
        because=(f"Greatest horizontal area above grade, measured to the centreline of the firewall"
                 + (" (stated areas from the architect's schedule)" if any(s.floor_area_m2 is not None for s in above) else " (from footprint polygons)") + ". "
                 f"Per level: " + ", ".join(f"{k} {v:,.0f} m²" for k, v in per_level.items()) + f". Governing level: {biggest}."),
        inputs={"per_level_m2": per_level},
    )
    if len(b.blocks()) > 1:
        d.flags.append("Firewall-separated block: area measured to the firewall centreline; the other block is a separate building.")
    return d


def analyze(b: BuildingModel, law: Optional[Bylaw] = None) -> list[Determination]:
    law = law or Bylaw()
    out: list[Determination] = []
    out.append(Determination(key="site.grade_m", label="Grade", value=b.site.grade_elevation_m, unit="m",
                             clauses=[law.definition("Grade")],
                             because="Entered from the site plan / survey as the lowest average finished ground level adjoining the exterior walls."))
    for blk in b.blocks():
        fs = first_storey(b, blk, law); out.append(fs)
        if fs.value is None:
            continue
        out.append(basements(b, blk, law, fs.value))
        out.append(building_height_storeys(b, blk, law, fs.value))
        out.append(building_height_metres(b, blk, law, fs.value))
        out.append(building_area(b, blk, law, fs.value))
    return out


if __name__ == "__main__":
    import sys, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "data" / "projects")]
    from courtyard_commons import project
    for d in analyze(project):
        print(f"[{d.block or 'site':5}] {d.label:44} {d.display():>14}   {'; '.join(c.ref() for c in d.clauses)}")
        print(f"        {d.because}")
        for f in d.flags:
            print(f"        ⚠ {f}")
