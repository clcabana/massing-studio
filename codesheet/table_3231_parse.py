"""
codesheet.table_3231_parse — parse Tables 3.2.3.1.-B and -C (unsprinklered) from the
bylaw PDF text into data/bylaw/vbbl-2025/table_3231_BC.json.

Layout in the extracted text, per face-area row:
    Less than 3 : 1   <pcts…>
    3 : 1 to 10 : 1   <pcts…>
    <area>                      ← the row's max face area, on its own line
     over 10 : 1      <pcts…>
Percentages are listed until they reach 100; later columns are implicitly 100.
"""
from __future__ import annotations

import json, pathlib, re
from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parents[1]
LD_COLS = [0, 1.2, 1.5, 2.0, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 25, 30, 35, 40, 45, 50]
RATIOS = ["lt3", "3to10", "gt10"]

# a 3-digit page number is sometimes glued to the front of a row label ("1983 : 1 to 10 : 1 …")
RE_LT = re.compile(r"^\s*(?:\d{3})?Less than 3\s*:\s*1\s+(.*)$")
RE_MID = re.compile(r"^\s*(?:\d{3})?3\s*:\s*1 to 10\s*:\s*1\s+(.*)$")
RE_GT = re.compile(r"^\s*(?:\d{3})?over 10\s*:\s*1\s+(.*)$")
AREA_SEQUENCE = [10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 250, 350, 500, 1000, 2000]


def _split_glued(tok: str, prev: int) -> list[int]:
    """Split a run of digits with lost spaces into a non-decreasing sequence of values ≤ 100."""
    best = None
    def rec(i, last, acc):
        nonlocal best
        if best is not None:
            return
        if i == len(tok):
            best = acc; return
        for n in (1, 2, 3):
            if i + n <= len(tok):
                v = int(tok[i:i + n])
                if v <= 100 and v >= last and (n == 1 or tok[i] != "0"):
                    rec(i + n, v, acc + [v])
    rec(0, prev, [])
    return best or [int(tok)]


def _pcts(s: str) -> list[int]:
    vals = []
    for tok in re.findall(r"\d+", s):
        v = int(tok)
        if v > 100:
            vals.extend(_split_glued(tok, vals[-1] if vals else 0))
        else:
            vals.append(v)
    # a stray area label at the end of the line (e.g. "… 84 100   80") — drop anything after the first 100
    if 100 in vals:
        vals = vals[:vals.index(100) + 1]
    vals = vals[:len(LD_COLS)]
    while len(vals) < len(LD_COLS):
        vals.append(100)
    return vals


def parse_table(pages: list[int], pdf: pathlib.Path) -> list[dict]:
    r = PdfReader(pdf)
    text = "\n".join((r.pages[p - 1].extract_text() or "") for p in pages)
    rows, cur = [], {}
    for line in text.split("\n"):
        m = RE_LT.match(line)
        if m:
            cur = {"lt3": _pcts(m.group(1))}; continue
        m = RE_MID.match(line)
        if m and "lt3" in cur:
            cur["3to10"] = _pcts(m.group(1)); continue
        m = RE_GT.match(line)
        if m and "3to10" in cur:
            cur["gt10"] = _pcts(m.group(1))
            rows.append(cur); cur = {}
    if len(rows) != len(AREA_SEQUENCE):
        raise ValueError(f"expected {len(AREA_SEQUENCE)} rows, parsed {len(rows)}")
    for r, a in zip(rows, AREA_SEQUENCE):
        r["area"] = float(a)
    return rows


if __name__ == "__main__":
    pdf = ROOT / "data/bylaw/vbbl-2025-vol1.pdf"
    out = {
        "ld_cols": LD_COLS,
        "B": {"groups": ["A", "B", "C", "D", "F3"], "pages": [213, 214], "rows": parse_table([213, 214], pdf)},
        "C": {"groups": ["E", "F1", "F2"], "pages": [215, 216], "rows": parse_table([215, 216], pdf)},
    }
    for k in ("B", "C"):
        print(k, len(out[k]["rows"]), "rows; areas:", [r["area"] for r in out[k]["rows"]])
    (ROOT / "data/bylaw/vbbl-2025/table_3231_BC.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
