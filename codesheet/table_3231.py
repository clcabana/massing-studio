"""
codesheet.table_3231 — the unprotected-opening tables of Article 3.2.3.1.

Only Table 3.2.3.1.-D (sprinklered; Groups A, B, C, D, F3) is encoded so far,
transcribed from VBBL 2025 p.217 (PDF page numbering). Rows are the maximum
area of the exposing building face in m²; columns are limiting distance in m;
cells are the maximum permitted unprotected openings as a % of the face.

Values between rows/columns are interpolated linearly (the tables' notes
permit interpolation). A face larger than the last row uses that row.
Tables -B/-C (unsprinklered) also key on the L/H ratio and will be added when
an unsprinklered project needs them.
"""
from __future__ import annotations

from bisect import bisect_left

# Table 3.2.3.1.-D — sprinklered, Groups A, B, C, D and F3
LD_D = [0, 1.2, 1.5, 2.0, 2.5, 3, 4, 5, 6, 7, 8, 9]
ROWS_D: list[tuple[float, list[int]]] = [
    (10,   [0, 16, 24, 42, 66, 100, 100, 100, 100, 100, 100, 100]),
    (15,   [0, 16, 20, 34, 50, 74, 100, 100, 100, 100, 100, 100]),
    (20,   [0, 16, 20, 30, 42, 60, 100, 100, 100, 100, 100, 100]),
    (25,   [0, 16, 18, 26, 38, 52, 90, 100, 100, 100, 100, 100]),
    (30,   [0, 14, 18, 24, 34, 46, 78, 100, 100, 100, 100, 100]),
    (40,   [0, 14, 16, 22, 30, 40, 64, 96, 100, 100, 100, 100]),
    (50,   [0, 14, 16, 20, 28, 36, 56, 82, 100, 100, 100, 100]),
    (60,   [0, 14, 16, 20, 26, 32, 50, 72, 98, 100, 100, 100]),
    (80,   [0, 14, 16, 18, 22, 28, 42, 58, 80, 100, 100, 100]),
    (100,  [0, 14, 16, 18, 22, 26, 36, 50, 68, 88, 100, 100]),
    (150,  [0, 14, 14, 16, 20, 22, 30, 40, 52, 66, 82, 100]),   # "150 or more"
]
PAGE_D = 217


def _interp(x, x0, x1, y0, y1):
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _row_lookup(values: list[int], ld: float) -> float:
    if ld >= LD_D[-1]:
        return 100.0
    i = bisect_left(LD_D, ld)
    if LD_D[i] == ld:
        return float(values[i])
    return _interp(ld, LD_D[i - 1], LD_D[i], values[i - 1], values[i])


def permitted_upo_sprinklered(face_area_m2: float, limiting_distance_m: float) -> tuple[float, str]:
    """
    Max % unprotected openings for a sprinklered face (Table 3.2.3.1.-D),
    bilinear interpolation on area and limiting distance. Returns (pct, how).
    """
    ld = max(0.0, limiting_distance_m)
    areas = [a for a, _ in ROWS_D]
    if face_area_m2 >= areas[-1]:
        v = _row_lookup(ROWS_D[-1][1], ld)
        return round(v, 1), f"row ≥{areas[-1]:g} m², LD {ld:g} m"
    if face_area_m2 <= areas[0]:
        v = _row_lookup(ROWS_D[0][1], ld)
        return round(v, 1), f"row {areas[0]:g} m², LD {ld:g} m"
    i = bisect_left(areas, face_area_m2)
    if areas[i] == face_area_m2:
        v = _row_lookup(ROWS_D[i][1], ld)
        return round(v, 1), f"row {areas[i]:g} m², LD {ld:g} m"
    lo, hi = ROWS_D[i - 1], ROWS_D[i]
    v = _interp(face_area_m2, lo[0], hi[0], _row_lookup(lo[1], ld), _row_lookup(hi[1], ld))
    return round(v, 1), f"interpolated between rows {lo[0]:g} and {hi[0]:g} m², LD {ld:g} m"


# Table 3.2.3.7 — construction of the exposing building face, Groups A, B, C, D, F3
# (permitted UPO band → FRR (min), construction, cladding), VBBL 2025 p.219
TABLE_3237_ABCDF3 = [
    ((0, 10),    60, "noncombustible",                                "noncombustible"),
    ((10, 25),   60, "combustible, EMTC or noncombustible",          "noncombustible"),
    ((25, 50),   45, "combustible, EMTC or noncombustible",          "noncombustible"),
    ((50, 100),  45, "combustible, EMTC or noncombustible",          "combustible or noncombustible"),
    ((100, 101),  0, "combustible, EMTC or noncombustible",          "combustible or noncombustible"),
]
PAGE_3237 = 219


def exposing_face_requirements(permitted_upo_pct: float) -> tuple[int, str, str, str]:
    """Return (FRR minutes, construction, cladding, band label) from Table 3.2.3.7."""
    p = permitted_upo_pct
    if p >= 100:
        frr, cons, clad = TABLE_3237_ABCDF3[-1][1:]
        return frr, cons, clad, "100 (no exposing-face requirement)"
    for (lo, hi), frr, cons, clad in TABLE_3237_ABCDF3[:-1]:
        if p <= hi if lo == 0 else lo < p <= hi:
            return frr, cons, clad, (f"0 to {hi}" if lo == 0 else f"> {lo} to {hi}")
    return 60, "noncombustible", "noncombustible", "0 to 10"


# ---------------------------------------------------------------------------
# Tables 3.2.3.1.-B and -C — unsprinklered, parsed from the PDF by table_3231_parse.py
# ---------------------------------------------------------------------------
import json as _json, pathlib as _pathlib

_BC_PATH = _pathlib.Path(__file__).resolve().parents[1] / "data/bylaw/vbbl-2025/table_3231_BC.json"
_BC = _json.loads(_BC_PATH.read_text(encoding="utf-8")) if _BC_PATH.exists() else None
PAGE_B, PAGE_C = 213, 215


def _ratio_key(length_m: float, height_m: float) -> tuple[str, float]:
    r = max(length_m / height_m, height_m / length_m) if length_m and height_m else 1.0
    return ("lt3" if r < 3 else "3to10" if r <= 10 else "gt10"), r


def permitted_upo_unsprinklered(face_area_m2: float, limiting_distance_m: float, length_m: float, height_m: float,
                                group: str = "C") -> tuple[float, str]:
    """
    Max % unprotected openings for an UNSPRINKLERED face. Table -B for Groups A, B, C,
    D, F3; Table -C for E, F1, F2. Row by face area (interpolated), sub-row by the
    greater of L/H and H/L (Note 1), column by limiting distance (interpolated).
    """
    if _BC is None:
        raise RuntimeError("table_3231_BC.json missing — run codesheet/table_3231_parse.py")
    table = "C" if group in ("E", "F1", "F2") else "B"
    cols = _BC["ld_cols"]; rows = _BC[table]["rows"]
    rkey, ratio = _ratio_key(length_m, height_m)
    ld = max(0.0, limiting_distance_m)

    def col_lookup(vals):
        if ld >= cols[-1]:
            return float(vals[-1])
        i = bisect_left(cols, ld)
        if cols[i] == ld:
            return float(vals[i])
        return _interp(ld, cols[i - 1], cols[i], vals[i - 1], vals[i])

    areas = [r["area"] for r in rows]
    if face_area_m2 >= areas[-1]:
        v = col_lookup(rows[-1][rkey]); how = f"Table 3.2.3.1.-{table}, row ≥{areas[-1]:g} m²"
    elif face_area_m2 <= areas[0]:
        v = col_lookup(rows[0][rkey]); how = f"Table 3.2.3.1.-{table}, row {areas[0]:g} m²"
    else:
        i = bisect_left(areas, face_area_m2)
        if areas[i] == face_area_m2:
            v = col_lookup(rows[i][rkey]); how = f"Table 3.2.3.1.-{table}, row {areas[i]:g} m²"
        else:
            lo, hi = rows[i - 1], rows[i]
            v = _interp(face_area_m2, lo["area"], hi["area"], col_lookup(lo[rkey]), col_lookup(hi[rkey]))
            how = f"Table 3.2.3.1.-{table}, interpolated between rows {lo['area']:g} and {hi['area']:g} m²"
    how += f", ratio {ratio:.1f}:1 ({ {'lt3': '<3:1', '3to10': '3:1–10:1', 'gt10': '>10:1'}[rkey] }), LD {ld:g} m"
    return round(v, 1), how
