"""
Export the rule data the JavaScript engine needs, from the same Python sources,
so the two implementations share one copy of every table and ladder.

    PYTHONPATH=. python3 codesheet/export_engine_data.py  →  app/static/engine_data.json
"""
from __future__ import annotations

import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from codesheet import articles, table_3231, separations, targets
from codesheet.determinations import Bylaw
from codesheet.occupancy import TABLE_3121


def ladder_json(rules):
    out = []
    for r in rules:
        out.append({
            "id": r.id, "group": r.group.value, "title": r.title, "requires_sprinklered": r.requires_sprinklered,
            "max_storeys": r.max_storeys, "max_height_m": r.max_height_m,
            "max_area_by_storeys": {str(k): v for k, v in (r.max_area_by_storeys or {}).items()} if r.max_area_by_storeys is not None else None,
            "max_area_by_storeys_streets": {str(k): {str(s): a for s, a in v.items()} for k, v in (r.max_area_by_storeys_streets or {}).items()} if r.max_area_by_storeys_streets else None,
            "no_basement_area_bonus": {str(k): v for k, v in (r.no_basement_area_bonus or {}).items()} if r.no_basement_area_bonus else None,
            "construction": r.construction, "floor_frr_h": r.floor_frr_h, "roof_frr_h": r.roof_frr_h, "mezzanine_frr_h": r.mezzanine_frr_h,
            "notes": r.notes, "admits": r.admits,
        })
    return out


def main():
    law = Bylaw("vbbl-2025")
    pages = {aid: law.articles[aid]["page"] for aid in ("3.1.2.1", "3.1.3.1", "3.2.1.1", "3.2.1.2", "3.2.2.5", "3.2.2.6", "3.2.2.7", "3.2.2.8",
                                                          "3.2.3.1", "3.2.3.7", "3.1.17.1", "3.4.2.1", "3.4.2.5", "3.4.3.2", "3.7.2.1", "3.7.2.2", "3.7.2.3", "3.7.2.9") if aid in law.articles}
    for lad in articles.LADDERS.values():
        for r in lad:
            if r.id in law.articles:
                pages[r.id] = law.articles[r.id]["page"]
    bc = json.loads((ROOT / "data/bylaw/vbbl-2025/table_3231_BC.json").read_text(encoding="utf-8"))
    sep = {f"{a}|{b}": v for (a, b), v in separations._T.items()}
    data = {
        "edition": law.edition,
        "definitions": {k: {"page": v[0], "text": v[1]} for k, v in Bylaw.DEFINITIONS.items()},
        "pages": pages,
        "table_3121": {k.value: v for k, v in TABLE_3121.items()},
        "ladders": {g.value: ladder_json(rules) for g, rules in articles.LADDERS.items()},
        "table_d": {"ld_cols": table_3231.LD_D, "rows": [[a, v] for a, v in table_3231.ROWS_D], "page": table_3231.PAGE_D},
        "table_bc": bc,
        "table_bc_pages": {"B": table_3231.PAGE_B, "C": table_3231.PAGE_C},
        "table_3237": {"rows": [[list(b), frr, cons, clad] for b, frr, cons, clad in table_3231.TABLE_3237_ABCDF3], "page": table_3231.PAGE_3237},
        "table_3131": {"map": sep, "page": separations.PAGE_3131},
        "subsidiary_fraction": 0.10,
        "targets": {
            "ol_rules": [[pat, f, label] for pat, f, label in targets.OL_RULES],
            "dwelling_re": targets.DWELLING_RE.pattern,
            "group_default": {g.value: list(v) for g, v in targets.GROUP_DEFAULT.items()},
            "mercantile": [targets.MERCANTILE_LOW, targets.MERCANTILE_UPPER],
            "m2_per_sleeping_room": targets.DEFAULT_M2_PER_SLEEPING_ROOM,
            "one_exit_a": targets.ONE_EXIT_A, "one_exit_b": targets.ONE_EXIT_B, "one_exit_max_ol": targets.ONE_EXIT_MAX_OL,
            "mm_per_person": targets.MM_PER_PERSON, "min_width": targets.MIN_WIDTH,
            "table_a": [list(r) for r in targets.TABLE_A],
        },
    }
    out = ROOT / "app/static/engine_data.json"
    out.write_text(json.dumps(data, indent=0, ensure_ascii=False), encoding="utf-8")
    print("wrote", out, f"{out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
