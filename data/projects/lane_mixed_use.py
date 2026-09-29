"""
Second test project — SYNTHETIC. "Lane Mixed-Use", a typical Vancouver C-2 infill:
one 50' × 122' lot (15.24 × 37.19 m), retail at grade with three residential
storeys above, zero side yards, street to the south, 6 m lane to the north.
Sprinklered throughout (VBBL 3.2.2.18.(3) requires it for all new buildings).

It exists to exercise code paths Menno Hall does not touch:
  * superimposed major occupancies (E under C) — 3.2.2.7, and the 2 h C↔E separation
  * a 4-storey Group C rung (3.2.2.52) and the Group E ladder
  * limiting distance 0 on the side property lines (0% openings, 1 h noncombustible)
  * a lane exposure (LD to lane centreline)
  * real Opening objects, no synthesized windows

Every expectation in tests/test_lane_mixed_use.py is hand-computed from the tables.
Coordinates: x east, y north, origin at the SW lot corner. Street on the south.
"""
from codesheet.model import (
    BuildingModel, Site, Footprint, Point, Storey, Zone, ExteriorFace, Opening,
    OccupancyGroup as O, ExposureType as X,
)

P = lambda x, y: Point(x=x, y=y)
W, D = 15.24, 37.19               # lot
FRONT, REAR = 0.0, 1.0            # setbacks: build to the street line; 1 m off the lane
DEPTH = 30.0                      # building depth
Y0, Y1 = FRONT, FRONT + DEPTH     # 0 → 30 m
GRADE = 10.00
L1, L2, L3, L4, ROOF = 10.10, 13.60, 16.60, 19.60, 22.60

FP = Footprint(vertices=[P(0, Y0), P(W, Y0), P(W, Y1), P(0, Y1)])          # 457.2 m²

def windows(tag, count, w, h, sill, span, start=1.0):
    step = (span - 2 * start) / max(1, count - 1) if count > 1 else 0
    return [Opening(label=f"{tag}{i+1}", width_m=w, height_m=h, sill_m=sill, offset_m=round(start + i * step - w / 2, 2))
            for i in range(count)]

def res_face_windows(tag, span, count, w=1.8, h=1.5):
    out = []
    for lvl, z in (("2", L2), ("3", L3), ("4", L4)):
        out += windows(f"{tag}{lvl}-", count, w, h, z - GRADE + 0.9, span)
    return out

project = BuildingModel(
    project_name="Lane Mixed-Use (synthetic test)",
    project_number="TEST-02",
    permit_application_date="2026-03-01",
    site=Site(address="Synthetic C-2 lot, Vancouver BC", zoning_district="C-2",
              grade_elevation_m=GRADE, streets_faced=1),
    footprint=FP,
    is_sprinklered=True,
    storeys=[
        Storey(label="L1", elevation_m=L1, height_m=L2 - L1, footprint=FP, zones=[
            Zone(name="Retail CRU", description="retail shop", area_m2=380.0),
            Zone(name="Residential lobby", description="residential entry lobby and mail", area_m2=35.0),
            Zone(name="Garbage / bike", description="garbage, recycling and bike storage", area_m2=30.0),
        ]),
        Storey(label="L2", elevation_m=L2, height_m=L3 - L2, footprint=FP, zones=[
            Zone(name="Suites L2", description="apartment suites", area_m2=420.0)]),
        Storey(label="L3", elevation_m=L3, height_m=L4 - L3, footprint=FP, zones=[
            Zone(name="Suites L3", description="apartment suites", area_m2=420.0)]),
        Storey(label="L4", elevation_m=L4, height_m=ROOF - L4, footprint=FP, zones=[
            Zone(name="Suites L4", description="apartment suites", area_m2=420.0)]),
        Storey(label="Roof", elevation_m=ROOF, height_m=0.4, footprint=FP, is_roof=True),
    ],
    exterior_faces=[
        # South — street. LD = setback (0) + half of a 20 m road allowance = 10 m.
        ExteriorFace(label="South (street)", start=P(0, Y0), end=P(W, Y0), base_elevation_m=GRADE, top_elevation_m=ROOF,
                     exposure=X.STREET, limiting_distance_m=10.0, source_note="synthetic",
                     openings=windows("S1-", 3, 3.6, 3.0, L1 - GRADE + 0.3, W) + res_face_windows("S", W, 4)),
        # North — lane. LD = 1 m setback + 3 m to lane centreline = 4 m.
        ExteriorFace(label="North (lane)", start=P(W, Y1), end=P(0, Y1), base_elevation_m=GRADE, top_elevation_m=ROOF,
                     exposure=X.LANE, limiting_distance_m=4.0, source_note="synthetic",
                     openings=windows("N1-", 1, 2.4, 2.4, L1 - GRADE + 0.1, W, start=W / 2) + res_face_windows("N", W, 3, w=1.5, h=1.5)),
        # East and West — side property lines, zero setback. LD = 0.
        ExteriorFace(label="East (PL)", start=P(W, Y0), end=P(W, Y1), base_elevation_m=GRADE, top_elevation_m=ROOF,
                     exposure=X.PROPERTY_LINE, limiting_distance_m=0.0, source_note="synthetic", openings=[]),
        ExteriorFace(label="West (PL)", start=P(0, Y1), end=P(0, Y0), base_elevation_m=GRADE, top_elevation_m=ROOF,
                     exposure=X.PROPERTY_LINE, limiting_distance_m=0.0, source_note="synthetic", openings=[]),
    ],
    notes=["SYNTHETIC test project — not a real building. Geometry chosen to exercise superimposed E/C occupancies, LD 0 side walls and a lane exposure."],
)
