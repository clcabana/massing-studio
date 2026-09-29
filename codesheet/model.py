"""
codesheet.model — the Building Model.

This is the single data shape that every other piece of the tool reads.
Think of it as "everything the bylaw needs to know about the building,
and nothing it doesn't."

Design rule: this file describes the building only. It contains NO
bylaw logic. Occupancy classification, height counting, article
selection etc. all live in separate modules that *consume* this model.
Keeping description and determination apart is what makes each piece
testable on its own.

Units: metres and square metres throughout (the VBBL is metric).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations — the fixed vocabularies the bylaw uses
# ---------------------------------------------------------------------------

class OccupancyGroup(str, Enum):
    """
    Major occupancy classification, VBBL Div. B Table 3.1.2.1.
    We store the Group+Division code (e.g. "C", "D", "E", "F2") because
    that is what every downstream table is keyed on.

    Only the groups a typical Vancouver mixed-use / residential project
    meets are listed for now. Add A1/A3/A4/B1/B3/F1 as needed.
    """
    A1 = "A1"   # Assembly, performing arts (theatres)
    A2 = "A2"   # Assembly, other than A1/A3/A4 (restaurants, cafés, lobbies, daycares)
    B2 = "B2"   # Care / treatment (hospitals, care homes)
    C = "C"     # Residential (dwelling units, hotels)
    D = "D"     # Business & personal services (offices, clinics, salons)
    E = "E"     # Mercantile (retail, grocery)
    F2 = "F2"   # Medium-hazard industrial (most storage / repair garages)
    F3 = "F3"   # Low-hazard industrial (parking garages, storage of noncombustibles)


class ExposureType(str, Enum):
    """What an exterior face looks across. Drives the limiting distance."""
    PROPERTY_LINE = "property_line"   # measured to the lot line
    STREET = "street"                 # measured to the street centreline
    LANE = "lane"                     # Vancouver treats lanes like streets here
    SAME_LOT = "same_lot"             # measured to an imaginary line between buildings


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

class Point(BaseModel):
    x: float
    y: float


class Footprint(BaseModel):
    """
    Plan outline of the building as a closed polygon, optionally with holes
    (courtyards, light wells). Coordinates are in metres in any consistent
    local system. Vertex order should be counter-clockwise; we don't enforce it yet.
    """
    vertices: list[Point] = Field(..., min_length=3)
    holes: list[list[Point]] = Field(default_factory=list, description="inner rings (courtyards); each subtracted from the area")

    @staticmethod
    def _ring_area(v: list[Point]) -> float:
        s = 0.0
        for i in range(len(v)):
            j = (i + 1) % len(v)
            s += v[i].x * v[j].y - v[j].x * v[i].y
        return abs(s) / 2.0

    def area(self) -> float:
        """Shoelace formula, holes subtracted. Building area for a single storey."""
        return self._ring_area(self.vertices) - sum(self._ring_area(h) for h in self.holes)


# ---------------------------------------------------------------------------
# The parts of a building the bylaw cares about
# ---------------------------------------------------------------------------

class Zone(BaseModel):
    """
    A room, suite, or grouped area on one storey with a single use.
    On a code sheet these become the occupancy rows for that floor.
    """
    name: str
    description: str = Field(
        ..., description="Plain-language use, e.g. 'café with commercial kitchen'."
    )
    area_m2: float = Field(..., gt=0)
    occupancy: Optional[OccupancyGroup] = Field(
        None,
        description=(
            "Leave None to let the occupancy classifier decide from the "
            "description; set it to override."
        ),
    )
    occupant_load: Optional[int] = Field(
        None, description="Designer-stated count (e.g. fixed seats, 3.1.17.1.(1)(a)). Otherwise computed from Table 3.1.17.1."
    )
    sleeping_rooms: Optional[int] = Field(
        None, description="Dwelling-unit zones: number of bedrooms → 2 persons each (3.1.17.1.(1)(b))."
    )
    dwelling_units: Optional[int] = Field(None, description="Number of suites in the zone, for the 1 WC per dwelling unit rule (3.7.2.2.(9)).")
    net_deduction_pct: float = Field(
        0.0, ge=0, le=100,
        description="Circulation / duplicate-use / fixed-furnishing deduction applied to reach the designed (net) occupant load."
    )
    ol_factor_m2: Optional[float] = Field(
        None, gt=0, description="Override the Table 3.1.17.1 area per person (m²) chosen from the description."
    )


class Storey(BaseModel):
    """
    One level of the building.

    'elevation_m' is the finished floor level. 'height_m' is floor-to-floor.
    Whether a storey counts as 'above grade' is NOT stored here — it's a
    determination made later against the grade elevation in Site.
    """
    label: str = Field(..., description="e.g. 'P1', 'L1', 'L2', 'Roof'")
    block: str = Field(
        "A",
        description=(
            "Which fire-separated block this storey belongs to. Blocks divided by a "
            "firewall (3.1.10) are treated as SEPARATE BUILDINGS for height, area and "
            "3.2.2 article selection. A single-block project just leaves this as 'A'."
        ),
    )
    elevation_m: float
    height_m: float = Field(..., gt=0)
    zones: list[Zone] = Field(default_factory=list)
    footprint: Optional[Footprint] = Field(
        None,
        description="Per-storey outline if it differs from the building footprint (setbacks, podium).",
    )
    floor_area_m2: Optional[float] = Field(
        None,
        description=(
            "Authoritative floor area for this storey (e.g. from the architect's area "
            "schedule). When set, it is used for building area and the 10% subsidiary "
            "test in preference to the footprint polygon, which then serves drawing only."
        ),
    )
    is_mezzanine: bool = False
    is_roof: bool = False
    is_part_of: Optional[str] = Field(
        None,
        description=(
            "Label of another storey in the same block at the same level that this "
            "one is a detached piece of (e.g. a lounge pavilion beside the main L1). "
            "Its area still counts toward that level's building area."
        ),
    )

    def gross_area_m2(self) -> float:
        return sum(z.area_m2 for z in self.zones)

    def plan_area_m2(self, fallback: Optional["Footprint"] = None) -> float:
        """Stated floor area if given, else the polygon's area."""
        if self.floor_area_m2 is not None:
            return self.floor_area_m2
        if self.footprint is not None:
            return self.footprint.area()
        return fallback.area() if fallback else 0.0


class Opening(BaseModel):
    """A window, door or other unprotected opening on an exterior face."""
    label: str
    width_m: float = Field(..., gt=0)
    height_m: float = Field(..., gt=0)
    sill_m: float = Field(0.0, description="Height of sill above the face's base, for drawing.")
    offset_m: float = Field(0.0, description="Horizontal offset from the face's left edge, for drawing.")
    is_protected: bool = Field(
        False, description="True if a closure with a fire-protection rating (rare on exposing faces)."
    )

    def area_m2(self) -> float:
        return self.width_m * self.height_m


class ExteriorFace(BaseModel):
    """
    One exposing building face for the spatial separation calc (3.2.3).

    The face is defined in plan by its two end points (so we can draw it and
    compute its length and orientation), and in elevation by base and top.
    Limiting distance is the perpendicular distance to whatever it exposes.
    """
    label: str = Field(..., description="e.g. 'North (Lane)', 'East (PL)'")
    block: str = "A"
    source_note: Optional[str] = Field(
        None, description="Where these numbers came from, e.g. 'code sheet note' or 'openings synthesized to match stated UPO %'."
    )
    start: Point
    end: Point
    base_elevation_m: float
    top_elevation_m: float
    exposure: ExposureType
    limiting_distance_m: float = Field(..., ge=0)
    openings: list[Opening] = Field(default_factory=list)
    stated_upo_pct: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Measured actual unprotected-opening % per storey label, taken from the "
            "drawings (e.g. code sheet notes). When present for a band it overrides the % "
            "computed from `openings`, which may then be schematic."
        ),
    )
    is_sprinklered_behind: Optional[bool] = Field(
        None, description="Override; defaults to the building-wide sprinkler flag."
    )

    def length_m(self) -> float:
        dx = self.end.x - self.start.x
        dy = self.end.y - self.start.y
        return (dx * dx + dy * dy) ** 0.5

    def height_m(self) -> float:
        return self.top_elevation_m - self.base_elevation_m

    def area_m2(self) -> float:
        return self.length_m() * self.height_m()

    def unprotected_opening_area_m2(self) -> float:
        return sum(o.area_m2() for o in self.openings if not o.is_protected)

    @model_validator(mode="after")
    def _top_above_base(self):
        if self.top_elevation_m <= self.base_elevation_m:
            raise ValueError(f"Face {self.label}: top must be above base")
        return self


class Site(BaseModel):
    """Things about the lot and its context that the bylaw needs."""
    address: str
    legal_description: Optional[str] = None
    zoning_district: Optional[str] = Field(None, description="e.g. 'C-2', 'RM-4'. Informational.")
    grade_elevation_m: float = Field(
        ...,
        description=(
            "The 'grade' as defined in Div. A 1.4.1.2 — lowest of the average "
            "finished ground levels adjoining each exterior wall. Storey "
            "counting and building height are measured from this."
        ),
    )
    streets_faced: int = Field(..., ge=0, le=3, description="Number of streets the building faces (3.2.2.10).")


class BuildingModel(BaseModel):
    """The whole project. One of these = one code analysis sheet."""
    project_name: str
    project_number: Optional[str] = None
    permit_application_date: Optional[str] = Field(
        None, description="ISO date. Pins which bylaw edition/amendments apply."
    )
    site: Site
    footprint: Footprint
    storeys: list[Storey] = Field(..., min_length=1)
    exterior_faces: list[ExteriorFace] = Field(default_factory=list)
    is_sprinklered: bool = Field(
        ..., description="Sprinklered throughout per NFPA 13 (or 13R where permitted)."
    )
    slab_separated_blocks: list[str] = Field(
        default_factory=list,
        description="Blocks that are separate buildings only by virtue of 3.2.1.2 (basement storage garage under a 2 h noncombustible slab).",
    )
    declared_construction: dict[str, str] = Field(
        default_factory=dict,
        description="Per block, the construction type the designer declares (e.g. 'noncombustible'); compared against the article's permission.",
    )
    declared_major_occupancies: dict[str, list[OccupancyGroup]] = Field(
        default_factory=dict,
        description=(
            "Per block, the major occupancies the designer DECLARES (e.g. from the "
            "architect's project data). The classifier still computes its own list by "
            "area; declared groups are honoured as major and any disagreement is flagged."
        ),
    )
    has_high_building_features: Optional[bool] = Field(
        None, description="Set later by the 3.2.6 check; here for completeness."
    )
    notes: list[str] = Field(default_factory=list)

    # --- convenience accessors (no bylaw logic!) ---------------------------

    def blocks(self) -> list[str]:
        seen = []
        for s in self.storeys:
            if s.block not in seen:
                seen.append(s.block)
        return seen

    def building_area_m2(self, block: Optional[str] = None) -> float:
        """
        Largest single-storey footprint area (def'n of 'building area').
        With a block given, only that block's storeys count — each firewall-
        separated block is its own building for this purpose.
        """
        storeys = [s for s in self.storeys if (block is None or s.block == block) and not s.is_roof]
        areas = [s.plan_area_m2(self.footprint) for s in storeys if s.footprint or s.floor_area_m2]
        if block is None:
            areas.append(self.footprint.area())
        return max(areas) if areas else 0.0

    def storeys_sorted(self, block: Optional[str] = None) -> list[Storey]:
        return sorted((s for s in self.storeys if block is None or s.block == block),
                      key=lambda s: s.elevation_m)

    def all_zones(self) -> list[tuple[Storey, Zone]]:
        return [(s, z) for s in self.storeys_sorted() for z in s.zones]

    @field_validator("storeys")
    @classmethod
    def _unique_labels(cls, v):
        keys = [(s.block, s.label) for s in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Storey labels must be unique within a block")
        return v

    @model_validator(mode="after")
    def _storeys_dont_overlap(self):
        for blk in self.blocks():
            s = self.storeys_sorted(blk)
            for a, b in zip(s, s[1:]):
                if a.is_roof or a.is_mezzanine or a.is_part_of or b.is_part_of:
                    continue
                if a.elevation_m + a.height_m > b.elevation_m + 0.01:
                    raise ValueError(
                        f"Block {blk}: storey {a.label} (top {a.elevation_m + a.height_m:.2f}) "
                        f"overlaps {b.label} (floor {b.elevation_m:.2f})"
                    )
        return self
