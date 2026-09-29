"""
Python engine vs JavaScript port: same massing specs in, same numbers out.
Requires node. Compares summary, headroom items, every face band
(permitted / actual / FRR / cladding) and every separation value.
"""
import json, pathlib, subprocess, sys, shutil
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from codesheet.massing import MassingSpec, analyze_massing

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SPECS = {
  "lane_mixed": {"project_name": "lane", "lot": {"width_m": 15.24, "depth_m": 37.19, "grade_m": 10,
      "edges": {"south": {"kind": "street", "row_width_m": 20}, "north": {"kind": "lane", "row_width_m": 6}, "east": {"kind": "neighbour", "row_width_m": 0}, "west": {"kind": "neighbour", "row_width_m": 0}}},
      "sprinklered": True, "chosen_articles": {"A": "3.2.2.52"},
      "blocks": [{"name": "A", "footprint": [[0, 0], [15.24, 0], [15.24, 30], [0, 30]], "first_floor_above_grade_m": 0.1, "default_glazing_pct": 30, "glazing_pct_by_edge": {"1": 0, "3": 0},
                  "storeys": [{"occupancy": "E", "use": "retail", "floor_to_floor_m": 4.2}] + [{"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0}] * 3}]},
  "corner_poly_unsprinklered": {"project_name": "corner", "sprinklered": False,
      "lot": {"width_m": 30, "depth_m": 30, "grade_m": 5, "polygon": [[0, 0], [30, 0], [30, 30], [0, 12]],
              "edge_kinds": [{"kind": "street", "row_width_m": 20}, {"kind": "street", "row_width_m": 30}, {"kind": "lane", "row_width_m": 6}, {"kind": "neighbour", "row_width_m": 0}]},
      "blocks": [{"name": "A", "footprint": [[2, 2], [26, 2], [26, 26], [2, 14]], "first_floor_above_grade_m": 0.2, "default_glazing_pct": 25, "glazing_pct_by_edge": {},
                  "storeys": [{"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0}] * 2}]},
  "two_blocks_a2": {"project_name": "two", "sprinklered": True,
      "lot": {"width_m": 60, "depth_m": 70, "grade_m": 90, "edges": {"south": {"kind": "street", "row_width_m": 40}, "north": {"kind": "neighbour", "row_width_m": 0}, "east": {"kind": "street", "row_width_m": 30}, "west": {"kind": "street", "row_width_m": 30}}},
      "blocks": [{"name": "North", "footprint": [[5, 40], [55, 40], [55, 65], [5, 65]], "first_floor_above_grade_m": 0.5, "default_glazing_pct": 20, "glazing_pct_by_edge": {},
                  "storeys": [{"occupancy": "A2", "use": "hall", "floor_to_floor_m": 4.5}] + [{"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0}] * 4},
                 {"name": "South", "footprint": [[5, 5], [50, 5], [50, 30], [5, 30]], "first_floor_above_grade_m": 0.5, "default_glazing_pct": 35, "glazing_pct_by_edge": {},
                  "storeys": [{"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0}] * 6}]},
  "small_two_storey_office": {"project_name": "small", "sprinklered": True,
      "lot": {"width_m": 20, "depth_m": 30, "grade_m": 3, "edges": {"south": {"kind": "street", "row_width_m": 20}, "north": {"kind": "lane", "row_width_m": 6}, "east": {"kind": "neighbour", "row_width_m": 0}, "west": {"kind": "neighbour", "row_width_m": 0}}},
      "blocks": [{"name": "A", "footprint": [[2, 2], [14, 2], [14, 20], [2, 20]], "first_floor_above_grade_m": 0.1, "default_glazing_pct": 40, "glazing_pct_by_edge": {},
                  "storeys": [{"occupancy": "E", "use": "retail CRU", "floor_to_floor_m": 4.0, "net_deduction_pct": 15},
                              {"occupancy": "D", "use": "dental clinic", "floor_to_floor_m": 3.5, "ol_factor_m2": 9.3},
                              ]}]},
  "podium_tower_court": {"project_name": "podium", "sprinklered": True,
      "lot": {"width_m": 40, "depth_m": 40, "grade_m": 20, "edges": {"south": {"kind": "street", "row_width_m": 20}, "north": {"kind": "lane", "row_width_m": 6}, "east": {"kind": "street", "row_width_m": 20}, "west": {"kind": "neighbour", "row_width_m": 0}}},
      "context": [{"name": "west neighbour", "footprint": [[-12, 0], [-1, 0], [-1, 30], [-12, 30]], "height_m": 12}],
      "blocks": [{"name": "T", "footprint": [[0, 0], [40, 0], [40, 36], [0, 36]], "holes": [[[12, 12], [28, 12], [28, 24], [12, 24]]], "first_floor_above_grade_m": 0.3, "default_glazing_pct": 40, "glazing_pct_by_edge": {"3": 0},
                  "roof": {"parapet_m": 1.0, "enclosure": {"footprint": [[10, 30], [20, 30], [20, 34], [10, 34]], "height_m": 3.2, "use": "rooftop amenity lounge", "occupancy": "C"}},
                  "storeys": [{"occupancy": "E", "use": "retail", "floor_to_floor_m": 4.5},
                              {"occupancy": "E", "use": "retail", "floor_to_floor_m": 4.0},
                              {"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0, "footprint": [[4, 4], [36, 4], [36, 36], [4, 36]], "holes": []},
                              {"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0, "footprint": [[4, 4], [36, 4], [36, 36], [4, 36]], "holes": []},
                              {"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0, "footprint": [[8, 8], [36, 8], [36, 36], [8, 36]], "holes": []}]}]},
  "stepback_party": {"project_name": "step", "sprinklered": True,
      "lot": {"width_m": 15.24, "depth_m": 37.19, "grade_m": 10, "setbacks": {"front": 0, "side": 0, "rear": 1}, "edges": {"south": {"kind": "street", "row_width_m": 20}, "north": {"kind": "lane", "row_width_m": 6}, "east": {"kind": "neighbour", "row_width_m": 0}, "west": {"kind": "neighbour", "row_width_m": 0}}},
      "blocks": [{"name": "A", "footprint": [[0, 0], [15.24, 0], [15.24, 36.19], [0, 36.19]], "first_floor_above_grade_m": 0.1, "default_glazing_pct": 30, "glazing_pct_by_edge": {"0": 40, "1": 0, "2": 30, "3": 0},
                  "roof": {"parapet_m": 0.6, "enclosure": {"footprint": [[5, 15], [10, 15], [10, 20], [5, 20]], "height_m": 3.0, "use": "elevator machine room, stair"}},
                  "storeys": [{"occupancy": "E", "use": "retail CRU", "floor_to_floor_m": 4.2}, {"occupancy": "C", "use": "apartment suites", "floor_to_floor_m": 3.0}]
                             + [{"occupancy": "C", "use": "apartment suites", "floor_to_floor_m": 3.0, "footprint": [[0, 3], [15.24, 3], [15.24, 36.19], [0, 36.19]]}] * 3}]},
}

JS_RUNNER = """
const fs=require('fs'); const DATA=JSON.parse(fs.readFileSync(process.argv[2],'utf8')); require(process.argv[3]);
const specs=JSON.parse(fs.readFileSync(process.argv[4],'utf8')); const out={};
for(const [k,s] of Object.entries(specs)){ const r=CodesheetEngine.analyzeMassing(s,DATA);
  out[k]={summary:r.summary, headroom:r.headroom, faces:Object.fromEntries(Object.entries(r.faces).map(([f,v])=>[f,{ld:v.ld,bands:v.bands.map(b=>({label:b.label,permitted:b.permitted,actual:b.actual,frr_min:b.frr_min,cladding:b.cladding}))}])),
    seps:Object.fromEntries(r.determinations.filter(d=>d.key.includes('.sep.')).map(d=>[d.key,d.value])),
    articles:Object.fromEntries(r.determinations.filter(d=>/\\.article(\\.|$)/.test(d.key)).map(d=>[d.key,d.value])),
    targets:r.targets, tdets:Object.fromEntries(r.determinations.filter(d=>/occupant_load|egress|washrooms|gender_neutral/.test(d.key)).map(d=>[d.key,[d.value,d.because,d.flags,d.clauses.map(c=>c.id+':'+c.page)]])) }; }
process.stdout.write(JSON.stringify(out));
"""


def _py(spec):
    r = analyze_massing(MassingSpec(**spec))
    return {"summary": r["summary"], "headroom": r["headroom"],
            "faces": {f: {"ld": v["ld"], "bands": [{"label": b["label"], "permitted": b["permitted"], "actual": b["actual"], "frr_min": b["frr_min"], "cladding": b["cladding"]} for b in v["bands"]]} for f, v in r["faces"].items()},
            "seps": {d["key"]: d["value"] for d in r["determinations"] if ".sep." in d["key"]},
            "articles": {d["key"]: d["value"] for d in r["determinations"] if d["key"].split(".")[1] == "article"},
            "targets": r["targets"],
            "tdets": {d["key"]: [d["value"], d["because"], d["flags"], [c["id"] + ":" + str(c["page"]) for c in d["clauses"]]] for d in r["determinations"] if any(k in d["key"] for k in ("occupant_load", "egress", "washrooms", "gender_neutral"))}}


def _js():
    tmp = ROOT / "out" / "_specs.json"; tmp.parent.mkdir(exist_ok=True); tmp.write_text(json.dumps(SPECS), encoding="utf-8")
    runner = ROOT / "out" / "_runner.js"; runner.write_text(JS_RUNNER, encoding="utf-8")
    res = subprocess.run(["node", str(runner), str(ROOT / "app/static/engine_data.json"), str(ROOT / "app/static/engine.js"), str(tmp)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(res.stdout)


@pytest.mark.parametrize("name", list(SPECS))
def test_js_matches_python(name):
    py = _py(SPECS[name]); js = _js()[name]
    assert js["summary"] == py["summary"], (js["summary"], py["summary"])
    assert js["articles"] == py["articles"]
    assert js["seps"] == py["seps"]
    for blk, h in py["headroom"].items():
        assert js["headroom"][blk]["article"] == h["article"] and js["headroom"][blk]["if_one_more_storey"] == h["if_one_more_storey"]
        assert js["headroom"][blk]["items"] == h["items"], blk
        assert js["headroom"][blk]["qualifying"] == h["qualifying"]
    assert set(js["faces"]) == set(py["faces"])
    for f, v in py["faces"].items():
        assert js["faces"][f]["ld"] == v["ld"], f
        assert js["faces"][f]["bands"] == v["bands"], f
    assert js["targets"] == py["targets"], name
    assert js["tdets"] == py["tdets"], name
