"""
Golden project — "Courtyard Commons", SYNTHETIC. Not a real building; every number was
chosen so that the expected results in tests/test_courtyard_commons.py can be worked by
hand from the VBBL 2025 text and tables.

Three buildings on one lot, the way a firewall and a 3.2.1.2 slab make them:

  North   5 storeys. Dining hall, kitchen, auditorium and offices at L1 (A2 with a
          15 % Group D portion), student suites above (C). Chosen article 3.2.2.51.
          Its north wall stands 4.6 m from the property line — the critical face.
  South   6 storeys of rental suites (C), also under 3.2.2.51 (1,400 m² < 1,500 m²).
  Parkade two below-grade levels (P2, P1) under a 2 h noncombustible slab (3.2.1.2),
          parking (F3) with a community room (A2) on P1; declared A2, noncombustible.

It exercises: the uppermost-storey-within-2-m rule for the first storey, basements that
carry occupancy but not height, the 10 % subsidiary test (3.2.2.8) both ways, declared
occupancies and construction, a designer-chosen article honoured and one refused, the
A2 ladder with a basement (no 3.2.2.27 bonus) and a streets-faced table (3.2.2.25),
Note (3) of Table 3.1.3.1 (C over A2 under 3.2.2.51 → 2 h), Table 3.2.3.1-D on the
"150 or more" row with stated opening percentages including one band that fails,
occupant loads by every rule of Table 3.1.17.1 the engine knows, exits, widths that
hit both minimums of Table 3.4.3.2-A, washrooms per Group and VBBL 3.7.2.9.

Coordinates: metres, x east, y north, origin at the SW lot corner. Grade 10.00.
"""
from codesheet.model import (
    BuildingModel, Site, Footprint, Point, Storey, Zone, ExteriorFace, Opening,
    OccupancyGroup as O, ExposureType as X,
)

P = lambda x, y: Point(x=x, y=y)
GRADE = 10.00

# --- level elevations (m) --------------------------------------------------------
P2, P1, L1, L2, L3, L4, L5, L6 = 4.0, 7.0, 10.5, 15.0, 18.0, 21.0, 24.0, 27.0
ROOF_N, ROOF_S = 27.0, 30.0
H1, H = 4.5, 3.0                           # ground-floor and typical floor-to-floor


def poly(*pts):
    return Footprint(vertices=[P(*p) for p in pts])


LOT      = poly((5, 5), (55, 5), (55, 55), (5, 55))        # 50 × 50 = 2,500 m² (parkade)
NORTH_FP = poly((5, 35), (55, 35), (55, 55), (5, 55))      # 50 × 20 = 1,000 m²
SOUTH_FP = poly((5, 5), (55, 5), (55, 33), (5, 33))        # 50 × 28 = 1,400 m²


def S(label, block, elev, h, fp, zones=None, **kw):
    return Storey(label=label, block=block, elevation_m=elev, height_m=h, footprint=fp, zones=zones or [], **kw)


def suites(label, area, rooms, units, who="student"):
    return Zone(name=f"{who.title()} suites {label}", description=f"{who} housing suites ({units} suites)",
                area_m2=area, sleeping_rooms=rooms, dwelling_units=units)


storeys = [
    # ---- Parkade: P2 and P1 both have their floor below grade + 2 m; P1 is the uppermost → first storey
    S("P2", "Parkade", P2, P1 - P2, LOT, [
        Zone(name="Parking P2", description="parking", area_m2=2500.0, occupancy=O.F3)]),
    S("P1", "Parkade", P1, L1 - P1, LOT, [
        Zone(name="Parking P1", description="parking", area_m2=1800.0, occupancy=O.F3),
        Zone(name="Community multi-purpose room", description="multi-purpose room for building events", area_m2=300.0, net_deduction_pct=20),
        Zone(name="Bike storage", description="bicycle storage and service rooms", area_m2=200.0, occupancy=O.F3)]),

    # ---- North: assembly at L1, student suites L2–L5
    S("L1", "North", L1, H1, NORTH_FP, [
        Zone(name="Dining hall", description="dining and community hall", area_m2=300.0, net_deduction_pct=20),
        Zone(name="Kitchen", description="commercial kitchen", area_m2=100.0),
        Zone(name="Auditorium", description="auditorium with fixed seating", area_m2=150.0, occupancy=O.A2, occupant_load=120),
        Zone(name="Office", description="business office", area_m2=150.0),
        Zone(name="Lobby", description="entry lobby", area_m2=50.0, net_deduction_pct=100)]),
    S("L2", "North", L2, H, NORTH_FP, [suites("L2", 800.0, 24, 20),
        Zone(name="Communal lounge L2", description="communal lounge and study room", area_m2=60.0, net_deduction_pct=100)]),
    S("L3", "North", L3, H, NORTH_FP, [suites("L3", 800.0, 24, 20),
        Zone(name="Communal lounge L3", description="communal lounge and study room", area_m2=60.0, net_deduction_pct=100)]),
    S("L4", "North", L4, H, NORTH_FP, [suites("L4", 800.0, 24, 20),
        Zone(name="Communal lounge L4", description="communal lounge and study room", area_m2=60.0, net_deduction_pct=100)]),
    S("L5", "North", L5, H, NORTH_FP, [suites("L5", 800.0, 20, 16),
        Zone(name="Communal lounge L5", description="communal lounge and study room", area_m2=60.0, net_deduction_pct=100)]),
    S("Roof", "North", ROOF_N, 0.4, NORTH_FP, [], is_roof=True),

    # ---- South: rental suites L1–L6
    S("L1", "South", L1, H1, SOUTH_FP, [
        Zone(name="Rental lobby", description="rental housing entry lobby", area_m2=40.0, net_deduction_pct=100),
        suites("L1", 500.0, 10, 8, who="rental")]),
    S("L2", "South", L2, H, SOUTH_FP, [suites("L2", 600.0, 16, 12, who="rental")]),
    S("L3", "South", L3, H, SOUTH_FP, [suites("L3", 600.0, 16, 12, who="rental")]),
    S("L4", "South", L4, H, SOUTH_FP, [suites("L4", 600.0, 16, 12, who="rental")]),
    S("L5", "South", L5, H, SOUTH_FP, [suites("L5", 600.0, 16, 12, who="rental")]),
    S("L6", "South", L6, H, SOUTH_FP, [suites("L6", 600.0, 16, 12, who="rental")]),
    S("Roof", "South", ROOF_S, 0.4, SOUTH_FP, [], is_roof=True),
]


def windows(tag, count, w, h, sill, span, start=2.0):
    step = (span - 2 * start) / max(1, count - 1) if count > 1 else 0
    return [Opening(label=f"{tag}{i+1}", width_m=w, height_m=h, sill_m=sill, offset_m=round(start + i * step - w / 2, 2))
            for i in range(count)]


faces = [
    # North wall of the North block: 50 m long, 4.6 m to the property line. Actual openings
    # are STATED per storey (as a drawing set would), and L4 is deliberately over the limit.
    ExteriorFace(label="North (PL)", block="North", start=P(55, 55), end=P(5, 55),
                 base_elevation_m=GRADE, top_elevation_m=ROOF_N, exposure=X.PROPERTY_LINE, limiting_distance_m=4.6,
                 source_note="stated opening percentages per storey",
                 stated_upo_pct={"L1": 30, "L2": 20, "L3": 20, "L4": 40, "L5": 15}),
    # West wall of the North block faces a street: 25 m to the centreline.
    ExteriorFace(label="West (street)", block="North", start=P(5, 55), end=P(5, 35),
                 base_elevation_m=GRADE, top_elevation_m=ROOF_N, exposure=X.STREET, limiting_distance_m=25.0,
                 source_note="openings synthesized at ~30%",
                 openings=sum((windows(f"W{lvl}-", 4, 1.8, 1.5, z - GRADE + 0.9, 20.0) for lvl, z in (("2", L2), ("3", L3), ("4", L4), ("5", L5))), [])),
    # South wall of the South block faces the main street: 22 m to the centreline.
    ExteriorFace(label="South (street)", block="South", start=P(5, 5), end=P(55, 5),
                 base_elevation_m=GRADE, top_elevation_m=ROOF_S, exposure=X.STREET, limiting_distance_m=22.0,
                 source_note="openings synthesized at ~35%",
                 openings=sum((windows(f"S{lvl}-", 8, 2.4, 1.5, z - GRADE + 0.9, 50.0) for lvl, z in (("2", L2), ("3", L3), ("4", L4), ("5", L5), ("6", L6))), [])),
]

project = BuildingModel(
    project_name="Courtyard Commons (synthetic example)",
    project_number="TEST-01",
    permit_application_date="2026-03-01",
    site=Site(address="Synthetic corner lot, Vancouver BC", zoning_district="CD-1", grade_elevation_m=GRADE, streets_faced=2),
    footprint=LOT,
    storeys=storeys,
    exterior_faces=faces,
    is_sprinklered=True,
    declared_major_occupancies={"North": [O.C, O.A2], "South": [O.C], "Parkade": [O.A2]},
    declared_construction={"Parkade": "noncombustible"},
    slab_separated_blocks=["Parkade"],
    notes=[
        "SYNTHETIC golden project — not a real building. Every expected value in tests/test_courtyard_commons.py is worked by hand.",
        "North and South blocks are divided by a 2 h firewall (3.1.10) → two buildings. The parkade is a third under a 3.2.1.2 slab.",
    ],
)
