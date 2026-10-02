"""
codesheet.zoning — the lot's zoning district and what its schedule allows.

Part 3 of the Building By-law says how a building of a given size must be built;
the Zoning and Development By-law (No. 3575) says how big it may be on this lot
at all. A massing that passes 3.2.2 but is twice the district's FSR is not a
massing. So, next to the code analysis, this module reads the district schedule
for the lot and reports, with the same Determination shape and plain-language
reasoning:

  * permitted uses       each block's occupancy groups → zoning use classes → outright /
                         conditional (Director of Planning approval) / not a listed use
  * height               highest roof above grade, against the district limit; parapets
                         and service penthouses noted (Section 10.1.1 lets the Director
                         permit them above the limit)
  * storeys              where the schedule caps them
  * floor space ratio    gross above-grade floor area of every block ÷ site area
  * site coverage        sum of the blocks' largest footprints ÷ site area
  * yards                front / side / flanking / rear setbacks measured from every
                         storey outline to the lot line, against the minimum yards
  * site                 minimum site area and frontage where the schedule has them

Three tiers, because Vancouver schedules work that way: an OUTRIGHT limit, a
CONDITIONAL maximum the Director of Planning may approve, and beyond that a
rezoning. Transit-Oriented Area minimums (Bill 47) can be layered on as a tier
the City may not refuse.

The district table lives in data/zoning/vancouver/districts.json with its
source and date. Where a figure could not be verified against the current
schedule text it is listed under `unverified` and comes out as a flag. Every
limit can be overridden in the MassingSpec (Lot.zoning_rules): the designer's
numbers are honoured and labelled as theirs.

This is a draft check, not a zoning determination: FSR exclusions (below-grade
parking, balconies, amenity), base-surface height, view cones, heritage and
area-plan overlays are not modelled.
"""
from __future__ import annotations

import json, math, pathlib, re
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from codesheet.determinations import Determination, Clause

if TYPE_CHECKING:                                     # massing imports this module; avoid the cycle
    from codesheet.massing import MassingSpec
    from codesheet.model import BuildingModel

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "zoning" / "vancouver" / "districts.json"
DATA: dict = json.loads(DATA_PATH.read_text(encoding="utf-8"))
EDITION = DATA["edition"]

UseTier = Optional[str]      # "outright" | "conditional" | None (not a listed use)
SERVICE_RE = re.compile(r"elevator|machine|stair|mechanical|service|hvac|electrical|penthouse")   # same test as massing.py


class ZoningRules(BaseModel):
    """
    The limits applied to a lot. Normally filled from the district table; a designer may
    override any field (e.g. a CD-1 by-law, or an area plan). Fields left None are not checked.
    """
    district: Optional[str] = Field(None, description="e.g. 'RM-4'. Looked up in the district table when the other fields are None.")
    label: Optional[str] = None
    uses: dict[str, UseTier] = Field(default_factory=dict, description="use class → 'outright' | 'conditional'; absent = not permitted")
    height_m: Optional[float] = Field(None, ge=0)
    height_m_conditional: Optional[float] = Field(None, ge=0)
    max_storeys: Optional[int] = Field(None, ge=0)
    max_storeys_conditional: Optional[int] = Field(None, ge=0)
    fsr: Optional[float] = Field(None, ge=0)
    fsr_conditional: Optional[float] = Field(None, ge=0)
    coverage_pct: Optional[float] = Field(None, ge=0, le=100)
    front_m: Optional[float] = Field(None, ge=0)
    side_m: Optional[float] = Field(None, ge=0)
    side_pct: Optional[float] = Field(None, ge=0, description="side yard as % of lot width, if the schedule works that way; the greater of this and side_m applies")
    flank_m: Optional[float] = Field(None, ge=0, description="side yard on a flanking street (corner lot); side rule applies when None")
    rear_m: Optional[float] = Field(None, ge=0)
    min_site_m2: Optional[float] = Field(None, ge=0)
    min_frontage_m: Optional[float] = Field(None, ge=0)
    toa: Optional[str] = Field(None, description="Transit-Oriented Area tier key (see districts.json → toa.tiers), or None")
    designer_edited: bool = Field(False, description="True when any limit was typed in rather than read from the table")
    source: Optional[str] = None


# ---------------------------------------------------------------------------- table lookup

def normalize_code(code: Optional[str]) -> Optional[str]:
    """'CD-1 (123)' → 'CD-1'; 'RT-7 (fixture)' → 'RT-7'; ' rm-4n ' → 'RM-4N'."""
    if not code:
        return None
    c = re.sub(r"\s*\(.*\)\s*$", "", str(code)).strip().upper()
    return c or None


def district_rules(code: Optional[str]) -> tuple[Optional[ZoningRules], list[str]]:
    """The table's rules for a district code (aliases resolved), plus the notes a reviewer should see."""
    c = normalize_code(code)
    if not c:
        return None, []
    notes = []
    key = c
    if key not in DATA["districts"] and key in DATA["aliases"]:
        alias_note = DATA["alias_note"].get(key) or next((v for k, v in DATA["alias_note"].items() if DATA["aliases"].get(k) == DATA["aliases"][key]), None)
        if alias_note:
            notes.append(alias_note)
        key = DATA["aliases"][key]
    d = DATA["districts"].get(key)
    if not d:
        return None, [f"{c} is not in the district table (encoded: {', '.join(DATA['districts'])}). Enter its limits in the Lot panel."]
    r = ZoningRules(district=c, label=d["label"], uses=dict(d["uses"]), height_m=d["height_m"], height_m_conditional=d["height_m_conditional"],
                    max_storeys=d["max_storeys"], max_storeys_conditional=d["max_storeys_conditional"], fsr=d["fsr"], fsr_conditional=d["fsr_conditional"],
                    coverage_pct=d["coverage_pct"], front_m=d["front_m"], side_m=d["side_m"], side_pct=d["side_pct"], flank_m=d["flank_m"], rear_m=d["rear_m"],
                    min_site_m2=d["min_site_m2"], min_frontage_m=d["min_frontage_m"], source=d["schedule"])
    return r, notes


def table_entry(code: Optional[str]) -> dict:
    c = normalize_code(code) or ""
    return DATA["districts"].get(DATA["aliases"].get(c, c), {})


def resolve(lot) -> tuple[Optional[ZoningRules], dict, list[str]]:
    """(rules, table entry or {}, notes). Designer overrides win over the table."""
    given = getattr(lot, "zoning_rules", None)
    code = (given.district if given and given.district else None) or lot.zoning
    table, notes = district_rules(code)
    entry = table_entry(code)
    if given is None:
        return table, entry, notes
    merged = (table.model_dump() if table else {}) | {k: v for k, v in given.model_dump().items() if v is not None and k not in ("uses",)}
    merged["uses"] = given.uses or (table.uses if table else {})
    merged["district"] = normalize_code(code)
    if given.designer_edited:
        notes.append("Zoning limits were entered by the designer; the district table was not used for those figures.")
    return ZoningRules(**merged), entry, notes


# ---------------------------------------------------------------------------- geometry

def _r(x: float, nd: int) -> float:
    """Round half up after snapping to 6 decimals — the same arithmetic as engine.js's zr(), so a tie like
    5368 / 1600 = 3.355 rounds the same way in both engines (Python's round() and JS Math.round() differ)."""
    return math.floor(float(f"{x:.6f}") * 10 ** nd + 0.5 + 1e-9) / 10 ** nd


def _area(pts) -> float:
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def _orientation(pts) -> float:
    s = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    return 1.0 if s >= 0 else -1.0


def _signed_inside(p, a, b, orient: float) -> float:
    """Distance from p to the line through lot edge ab, positive on the lot's inside."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ux, uy) or 1.0
    return orient * ((ux * (p[1] - a[1]) - uy * (p[0] - a[0])) / L)


def edge_roles(lot) -> list[dict]:
    """
    Which lot edge is the front, which the rear, which are sides (a side on a street is a
    flanking side). Front: the principal street edge — 'south' / edge 0 when it is a street,
    else the first street edge, else south / edge 0. Rear: the edge pointing the opposite way,
    a lane preferred. Returns [{a, b, kind, label, role}] in boundary order.
    """
    segs = lot.boundary()
    kinds = [e.kind for _, _, e, _ in segs]
    front = 0 if kinds[0] == "street" else next((i for i, k in enumerate(kinds) if k == "street"), 0)
    fa, fb = segs[front][0], segs[front][1]
    fL = math.hypot(fb[0] - fa[0], fb[1] - fa[1]) or 1.0
    fdir = ((fb[0] - fa[0]) / fL, (fb[1] - fa[1]) / fL)
    best = None
    for i, (a, b, e, _) in enumerate(segs):
        if i == front:
            continue
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        dot = (b[0] - a[0]) / L * fdir[0] + (b[1] - a[1]) / L * fdir[1]
        score = dot - (0.3 if e.kind == "lane" else 0.0)          # most anti-parallel wins; a lane gets a nudge
        if best is None or score < best[0]:
            best = (score, i)
    rear = best[1] if best else None
    out = []
    for i, (a, b, e, label) in enumerate(segs):
        role = "front" if i == front else "rear" if i == rear else ("flank" if e.kind in ("street", "lane") else "side")
        out.append({"a": a, "b": b, "kind": e.kind, "label": label, "role": role})
    return out


def _lot_points(lot) -> list:
    return [tuple(p) for p in lot.polygon] if lot.polygon else [(0, 0), (lot.width_m, 0), (lot.width_m, lot.depth_m), (0, lot.depth_m)]


# ---------------------------------------------------------------------------- the check

def _tier(value: float, outright: Optional[float], conditional: Optional[float], toa: Optional[float] = None) -> tuple[str, Optional[float]]:
    """('outright' | 'conditional' | 'toa' | 'exceeds' | 'unlimited', the cap the headroom is measured to)."""
    caps = [c for c in (outright, conditional, toa) if c is not None]
    if not caps:
        return "unlimited", None
    cap = max(caps)
    if outright is not None and value <= outright + 1e-9:
        return "outright", cap
    if conditional is not None and value <= conditional + 1e-9:
        return "conditional", cap
    if toa is not None and value <= toa + 1e-9:
        return "toa", cap
    return "exceeds", cap


def _clause(rules: ZoningRules, entry: dict, what: str) -> Clause:
    sec = (entry.get("sections") or {}).get(what)
    name = f"{rules.district} District Schedule" if rules.district and rules.district != "CD-1" else "CD-1 By-law for the site"
    return Clause(id=f"{name}{' ' + sec if sec else ''}", edition=EDITION, title=rules.label)


_TIER_WORDS = {"outright": "within the outright limit", "conditional": "above the outright limit but within the conditional maximum (Director of Planning approval)",
               "toa": "above the district's limits but within the Transit-Oriented Area minimum the City may not refuse", "exceeds": "EXCEEDS the district maximum — a rezoning or variance", "unlimited": "no limit encoded"}


def analyze(m: "MassingSpec", b: "BuildingModel", hd: list[Determination]) -> tuple[list[Determination], dict]:
    """Determinations (keys site.zoning.*) and a compact summary for the live panel."""
    lot = m.lot
    rules, entry, notes = resolve(lot)
    H = {d.key: d for d in hd}
    site_pts = _lot_points(lot)
    site_area = _r(_area(site_pts), 1)
    out: list[Determination] = []
    summary = {"district": normalize_code(rules.district if rules else lot.zoning), "label": rules.label if rules else None, "site_area_m2": site_area,
               "items": [], "yards": [], "uses": [], "notes": [], "status": None, "source": rules.source if rules else None, "designer_edited": bool(rules and rules.designer_edited)}
    if rules is None:
        d = Determination(key="site.zoning.district", label="Zoning district", value=lot.zoning or None, unit="",
                          clauses=[Clause(id="Zoning District Plan", edition=EDITION)],
                          because=("No zoning district is set for this lot. Pick one in the Lot panel (or a site from the map) to check height, FSR, coverage, yards and uses against its schedule."
                                   if not lot.zoning else f"District '{lot.zoning}' is not in the table; enter its limits in the Lot panel."),
                          flags=["Zoning not checked: no district or limits for this lot."] + notes)
        out.append(d)
        summary["status"] = "unknown"; summary["notes"] = d.flags
        return out, summary

    unverified = entry.get("unverified") or []
    gen_flags = list(notes)
    for f in unverified:
        gen_flags.append(f"{rules.district}: the {f.replace('_m', ' (m)').replace('_pct', ' (%)').replace('_', ' ')} figure is transcribed but not verified against the current schedule — confirm it.")
    toa = DATA["toa"]["tiers"].get(rules.toa) if rules.toa else None

    # --- district line ----------------------------------------------------------------------------
    out.append(Determination(key="site.zoning.district", label="Zoning district", value=rules.district, unit="",
                             clauses=[_clause(rules, entry, "uses")],
                             because=(f"{rules.label or ''}. Limits from {rules.source or 'the designer'}" + (" (designer-edited)" if rules.designer_edited else "") + "."
                                      + (f" TOA tier applied: {toa['label']} — at least {toa['min_storeys']} storeys and FSR {toa['min_fsr']:g} may not be refused." if toa else "")
                                      + " " + " ".join(entry.get("notes") or [])),
                             flags=gen_flags))

    # --- uses --------------------------------------------------------------------------------------
    o2u = DATA["occupancy_to_use"]
    for blk in b.blocks():
        groups = []
        for s in b.storeys_sorted(blk):
            for z in s.zones:
                g = z.occupancy.value if z.occupancy else None
                if g and g not in groups:
                    groups.append(g)
        parts, flags = [], []
        for g in groups:
            use = o2u.get(g, "other")
            tier = rules.uses.get(use) if rules.uses else None
            if use == "parking":
                tier = tier or "outright"
            note = (entry.get("use_notes") or {}).get(use)
            if not rules.uses:
                parts.append(f"Group {g} → {use}: uses not encoded")
            elif tier:
                parts.append(f"Group {g} → {use}: {tier}" + (f" ({note})" if note else ""))
            else:
                parts.append(f"Group {g} → {use}: NOT a listed use")
                flags.append(f"{blk}: Group {g} ({DATA['use_classes'].get(use, use)}) is not a listed use in {rules.district} — a rezoning, or a different use.")
            if tier == "conditional" and rules.uses:
                flags.append(f"{blk}: {DATA['use_classes'].get(use, use)} is a conditional approval use in {rules.district} — Director of Planning discretion, design guidelines apply.")
        summary["uses"].append({"block": blk, "groups": groups, "ok": not any("NOT a listed" in p for p in parts), "text": "; ".join(parts)})
        out.append(Determination(key=f"site.zoning.uses.{blk}", label=f"Permitted uses — {blk}", value="not permitted" if any("NOT a listed" in p for p in parts) else ("conditional" if any(": conditional" in p for p in parts) else ("outright" if rules.uses else "not encoded")),
                                 block=blk, clauses=[_clause(rules, entry, "uses")], because="; ".join(parts) + ".", flags=flags))

    def item(what, value, outright, conditional, unit, key, because, toa_cap=None, extra_flags=(), clause_key=None):
        clause_key = clause_key or key
        tier, cap = _tier(value, outright, conditional, toa_cap)
        it = {"what": what, "value": value, "outright": outright, "conditional": conditional, "toa": toa_cap, "cap": cap, "unit": unit, "status": tier,
              "headroom": None if cap is None else (_r(cap - value, 2) if unit != "storeys" else cap - value)}
        summary["items"].append(it)
        lim = " / ".join(x for x in ((f"outright {outright:g}" if outright is not None else None), (f"conditional {conditional:g}" if conditional is not None else None), (f"TOA {toa_cap:g}" if toa_cap is not None else None)) if x)
        flags = list(extra_flags)
        if tier == "exceeds":
            flags.append(f"{what} {value:g} {unit} exceeds the {rules.district} maximum ({lim}).")
        elif tier == "conditional":
            flags.append(f"{what} {value:g} {unit} relies on the conditional maximum ({lim}) — Director of Planning approval.")
        out.append(Determination(key=f"site.zoning.{key}", label=f"Zoning — {what}", value=value, unit=unit, clauses=[_clause(rules, entry, clause_key)],
                                 because=f"{because} Limit: {lim or 'none encoded'}: {_TIER_WORDS[tier]}.", inputs={"cap": cap, "status": tier}, flags=flags))

    # --- height -------------------------------------------------------------------------------------
    g = lot.grade_m
    hbits, worst, parapet_over = [], 0.0, False
    for blk in m.blocks:
        roof = next((s for s in b.storeys if s.block == blk.name and s.is_roof), None)
        if not roof:
            continue
        hroof = _r(roof.elevation_m - g, 2)
        par = blk.roof.parapet_m
        enc = blk.roof.enclosure
        worst = max(worst, hroof)
        txt = f"{blk.name}: roof {hroof:g} m above grade" + (f", parapet to {hroof + par:.2f} m" if par else "")
        if enc is not None and SERVICE_RE.search(enc.use.lower()):
            txt += f", service penthouse to {hroof + enc.height_m:.2f} m (excluded; Section 10.1.1 lets the Director of Planning permit elevator machine rooms and mechanical above the limit)"
        hbits.append(txt)
        cap_h = max([c for c in (rules.height_m, rules.height_m_conditional) if c is not None], default=None)
        if cap_h is not None and hroof <= cap_h + 1e-9 < hroof + par:
            parapet_over = True
    hflags = []
    if parapet_over:
        hflags.append("The parapet rises above the height limit while the roof does not — confirm it is a permitted projection.")
    if toa:
        hflags.append("TOA minimums are set in storeys; the height limit in metres for a Transit-Oriented Area comes from the TOA designation by-law — confirm.")
    item("height", _r(worst, 2), rules.height_m, rules.height_m_conditional, "m", "height",
         "Highest roof above grade (massing grade, not the zoning base surface). " + "; ".join(hbits) + ".", extra_flags=hflags)

    # --- storeys -------------------------------------------------------------------------------------
    st_max = max((H[f"{blk}.building_height_storeys"].value for blk in b.blocks() if f"{blk}.building_height_storeys" in H), default=0)
    if rules.max_storeys is not None or rules.max_storeys_conditional is not None or toa:
        item("storeys", st_max, rules.max_storeys, rules.max_storeys_conditional, "storeys", "storeys",
             f"Tallest block: {st_max} storeys in building height (Part 3 count; zoning counts storeys from the base surface, so a half-basement may differ).",
             toa_cap=toa["min_storeys"] if toa else None, clause_key="height")

    # --- FSR ------------------------------------------------------------------------------------------
    floor_area, fbits, tall = 0.0, [], []
    for blk in b.blocks():
        fs = H.get(f"{blk}.first_storey")
        st = [s for s in b.storeys_sorted(blk) if not s.is_roof]
        fs_el = next((s.elevation_m for s in st if fs and s.label == fs.value), st[0].elevation_m if st else g)
        above = [s for s in st if s.elevation_m >= fs_el - 0.01]
        a = sum(s.footprint.area() for s in above)
        floor_area += a
        fbits.append(f"{blk} {', '.join(s.label for s in above)}: {a:,.0f} m²")
        tall += [f"{blk} {s.label} ({s.height_m:g} m)" for s in above if s.height_m > DATA["fsr_double_count_f2f_m"] + 1e-9]
    floor_area = _r(floor_area, 1)
    fsr = _r(floor_area / site_area, 2) if site_area else 0.0
    fflags = ["Gross floor area from the storey outlines: zoning exclusions (below-grade parking, balconies up to the permitted share, some amenity and stair/elevator areas) are not deducted, so the FSR shown is conservative."]
    if tall:
        fflags.append(f"Floor-to-floor over {DATA['fsr_double_count_f2f_m']:g} m may be counted twice in the FSR computation of many schedules: {', '.join(tall)} — confirm.")
    item("floor space ratio", fsr, rules.fsr, rules.fsr_conditional, "FSR", "fsr",
         f"Above-grade floor area {floor_area:,.0f} m² ÷ site area {site_area:,.0f} m² = {fsr:g}. " + "; ".join(fbits) + ".",
         toa_cap=toa["min_fsr"] if toa else None, extra_flags=fflags)
    summary["floor_area_m2"] = floor_area

    # --- coverage ---------------------------------------------------------------------------------------
    cov_area = 0.0
    cbits = []
    for blk in b.blocks():
        st = [s for s in b.storeys_sorted(blk) if not s.is_roof]
        a = max((s.footprint.area() for s in st), default=0.0)
        cov_area += a
        cbits.append(f"{blk} {a:,.0f} m²")
    cov = _r(100 * cov_area / site_area, 1) if site_area else 0.0
    if rules.coverage_pct is not None:
        item("site coverage", cov, rules.coverage_pct, None, "%", "coverage",
             f"Largest footprint of each block ({'; '.join(cbits)}) = {cov_area:,.0f} m² of {site_area:,.0f} m².")
    summary["coverage_pct"] = cov

    # --- yards --------------------------------------------------------------------------------------------
    W = lot.width_m
    req = {"front": rules.front_m, "rear": rules.rear_m,
           "side": max([x for x in (rules.side_m, (rules.side_pct or 0) * W / 100 if rules.side_pct else None) if x is not None], default=None),
           "flank": rules.flank_m}
    if req["flank"] is None:
        req["flank"] = req["side"]
    orient = _orientation(site_pts)
    footprints = [[tuple(p) for p in (st.footprint or blk.footprint)] for blk in m.blocks for st in blk.storeys]
    for e in edge_roles(lot):
        need = req[e["role"]]
        measured = min((_signed_inside(p, e["a"], e["b"], orient) for fp in footprints for p in fp), default=None)
        if measured is None:
            continue
        measured = _r(measured, 2)
        role = {"front": "front yard", "rear": "rear yard", "side": "side yard", "flank": "flanking side yard (street side)"}[e["role"]]
        ok = None if need is None else measured + 1e-9 >= need
        y = {"edge": e["label"], "kind": e["kind"], "role": e["role"], "measured_m": measured, "required_m": need, "ok": ok}
        summary["yards"].append(y)
        flags = []
        if ok is False:
            flags.append(f"{role} on the {e['label']} ({e['kind']}): {measured:g} m provided, {need:g} m required — short by {need - measured:.2f} m.")
        if e["role"] == "flank" and rules.flank_m is None and need is not None:
            flags.append(f"Corner lot: the {e['label']} side faces a {e['kind']}; the schedule may set a different flanking yard — the side yard {need:g} m was used.")
        out.append(Determination(key=f"site.zoning.yard.{e['label'].replace(' ', '_')}", label=f"Zoning — {role}, {e['label']}", value=measured, unit="m", clauses=[_clause(rules, entry, "yards")],
                                 because=(f"Closest storey outline to the {e['label']} lot line ({e['kind']}) is {measured:g} m inside it. "
                                          + (f"Minimum {role} {need:g} m: {'OK' if ok else 'SHORT'}." if need is not None else f"No minimum {role} encoded for {rules.district}.")),
                                 inputs={"required_m": need, "ok": ok}, flags=flags))

    # --- site -----------------------------------------------------------------------------------------------
    if rules.min_site_m2 is not None or rules.min_frontage_m is not None:
        front = next((e for e in edge_roles(lot) if e["role"] == "front"), None)
        frontage = _r(math.hypot(front["b"][0] - front["a"][0], front["b"][1] - front["a"][1]), 2) if front else W
        bits, flags = [], []
        if rules.min_site_m2 is not None:
            bits.append(f"site area {site_area:,.0f} m² vs minimum {rules.min_site_m2:g} m²")
            if site_area + 1e-9 < rules.min_site_m2:
                flags.append(f"Site area {site_area:,.0f} m² is below the {rules.district} minimum of {rules.min_site_m2:g} m² for this form.")
        if rules.min_frontage_m is not None:
            bits.append(f"frontage {frontage:g} m vs minimum {rules.min_frontage_m:g} m")
            if frontage + 1e-9 < rules.min_frontage_m:
                flags.append(f"Frontage {frontage:g} m is below the {rules.district} minimum of {rules.min_frontage_m:g} m.")
        out.append(Determination(key="site.zoning.site", label="Zoning — site area and frontage", value="OK" if not flags else "below minimum", clauses=[_clause(rules, entry, "site")],
                                 because="; ".join(bits) + ".", flags=flags))
        summary["site"] = {"area_m2": site_area, "frontage_m": frontage, "ok": not flags}

    statuses = [it["status"] for it in summary["items"]] + ["exceeds" for y in summary["yards"] if y["ok"] is False] + ["exceeds" for u in summary["uses"] if not u["ok"]]
    order = ["exceeds", "toa", "conditional", "outright", "unlimited"]
    summary["status"] = next((s for s in order if s in statuses), "outright")
    summary["notes"] = (entry.get("notes") or []) + notes
    summary["flag_count"] = sum(len(d.flags) for d in out)
    return out, summary
