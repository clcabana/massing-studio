"""Rhino round trip: export → import gives the same analysis; a box drawn in Rhino becomes a storey."""
import sys, pathlib
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
rh = pytest.importorskip("rhino3dm")
from codesheet.massing import MassingSpec, analyze_massing
from codesheet import rhino_io
from test_engine_js import SPECS


@pytest.mark.parametrize("name", ["podium_tower_court", "two_blocks_a2", "lane_mixed"])
def test_round_trip_is_lossless_for_the_analysis(tmp_path, name):
    spec = MassingSpec(**SPECS[name])
    p = rhino_io.export_3dm(spec, tmp_path / f"{name}.3dm")
    spec2, warnings = rhino_io.import_3dm(p)
    assert warnings == []
    a, b = analyze_massing(spec), analyze_massing(spec2)
    assert a["summary"] == b["summary"] and a["targets"] == b["targets"]
    assert {k: v["ld"] for k, v in a["faces"].items()} == {k: v["ld"] for k, v in b["faces"].items()}


def test_layers_and_user_text(tmp_path):
    spec = MassingSpec(**SPECS["podium_tower_court"])
    m = rh.File3dm.Read(str(rhino_io.export_3dm(spec, tmp_path / "x.3dm")))
    paths = {m.Layers[i].FullPath for i in range(len(m.Layers))}
    assert {"Site::Property line", "Site::ROW centrelines", "Context::Neighbours", "Massing::T::L1", "Massing::T::Roof"} <= paths
    l1 = next(o for o in m.Objects if o.Attributes.Name == "T L1")
    assert l1.Attributes.GetUserString("occupancy") == "E" and l1.Attributes.GetUserString("f2f") == "4.5"
    assert m.Strings[rhino_io.DOC_KEY].startswith("{")


def test_box_drawn_in_rhino_becomes_a_storey(tmp_path):
    spec = MassingSpec(**SPECS["lane_mixed"])
    p = rhino_io.export_3dm(spec, tmp_path / "lane.3dm")
    m = rh.File3dm.Read(str(p))
    top = max(o.Geometry.GetBoundingBox().Max.Z for o in m.Objects if (o.Attributes.GetUserString("kind") == "storey"))
    li = next(i for i in range(len(m.Layers)) if m.Layers[i].FullPath == "Massing::A")
    box = rh.Brep.CreateFromBox(rh.Box(rh.BoundingBox(rh.Point3d(2, 0, top), rh.Point3d(13.24, 24, top + 3.0))))
    at = rh.ObjectAttributes(); at.LayerIndex = li; m.Objects.AddBrep(box, at)
    m.Write(str(p), 8)
    spec2, warnings = rhino_io.import_3dm(p)
    assert len(spec2.blocks[0].storeys) == 5 and spec2.blocks[0].storeys[-1].footprint == [[2.0, 0.0], [13.24, 0.0], [13.24, 24.0], [2.0, 24.0]]
    assert spec2.blocks[0].storeys[-1].occupancy.value == "C"      # inherits the last exported storey's attributes
    r = analyze_massing(spec2)
    assert r["summary"]["A"]["storeys"] == 5


def _rhino_style_resave(p, edit=None):
    """What Rhino 8 does to our file on Save after the designer touches the massing: every edited storey
    comes back as a Brep, not an Extrusion (seen in the first real save test, 2026-09-29)."""
    m = rh.File3dm.Read(str(p))
    for o in list(m.Objects):
        if o.Attributes.GetUserString("kind") == "storey" and isinstance(o.Geometry, rh.Extrusion):
            brep = o.Geometry.ToBrep(False)
            if edit:
                brep = edit(o, brep) or brep
            src = o.Attributes
            at = rh.ObjectAttributes(); at.LayerIndex = src.LayerIndex; at.Name = src.Name
            for k in ("kind", "block", "storey", "occupancy", "use", "f2f", "beds", "units", "ded", "glazing"):
                v = src.GetUserString(k)
                if v:
                    at.SetUserString(k, v)
            m.Objects.Delete(o.Attributes.Id)
            m.Objects.AddBrep(brep, at)
    m.Write(str(p), 8)
    return p


def test_storeys_resaved_by_rhino_as_breps_import_unchanged(tmp_path):
    spec = MassingSpec(**SPECS["podium_tower_court"])
    p = _rhino_style_resave(rhino_io.export_3dm(spec, tmp_path / "t.3dm"))
    m = rh.File3dm.Read(str(p))
    assert all(isinstance(o.Geometry, rh.Brep) for o in m.Objects if o.Attributes.GetUserString("kind") == "storey")
    spec2, warnings = rhino_io.import_3dm(p)
    assert warnings == []
    a, b = analyze_massing(spec), analyze_massing(spec2)
    assert a["summary"] == b["summary"] and a["targets"] == b["targets"]


def test_storey_moved_up_in_rhino_is_reported(tmp_path):
    spec = MassingSpec(**SPECS["lane_mixed"])
    top_name = f"A L{len(spec.blocks[0].storeys)}"

    def lift_top(o, brep):
        if o.Attributes.Name == top_name:
            brep.Translate(rh.Vector3d(0, 0, 0.5))
        return brep

    p = _rhino_style_resave(rhino_io.export_3dm(spec, tmp_path / "lane.3dm"), lift_top)
    spec2, warnings = rhino_io.import_3dm(p)
    assert len(spec2.blocks[0].storeys) == len(spec.blocks[0].storeys)
    assert any("does not sit on the one below" in w for w in warnings)


def test_parcel_polygon_lot_untouched_gives_no_lot_warning(tmp_path):
    d = dict(SPECS["lane_mixed"])
    d["lot"] = {**d["lot"], "polygon": [[0, 0], [15.0, 0], [15.5, 38.0], [0, 37.0]], "width_m": 15.5, "depth_m": 38.0,
                "edge_kinds": [{"kind": "street", "row_width_m": 20.0}, {"kind": "neighbour", "row_width_m": 0.0},
                               {"kind": "lane", "row_width_m": 6.0}, {"kind": "neighbour", "row_width_m": 0.0}]}
    spec = MassingSpec(**d)
    p = _rhino_style_resave(rhino_io.export_3dm(spec, tmp_path / "poly.3dm"))
    spec2, warnings = rhino_io.import_3dm(p)
    assert warnings == []
    assert [e.kind for e in spec2.lot.edge_kinds] == ["street", "neighbour", "lane", "neighbour"]
    assert spec2.lot.polygon == spec.lot.polygon


def test_trees_and_street_names_round_trip(tmp_path):
    d = dict(SPECS["lane_mixed"])
    d["trees"] = [{"x": -3.0, "y": 5.0, "height_m": 9.0, "crown_m": 6.0, "name": "Crimean Linden"}, {"x": 20.0, "y": -4.0, "height_m": 7.5, "crown_m": 4.2, "name": "Red Maple"}]
    d["streets"] = [{"name": "W 11th Ave", "line": [[-30.0, -10.0], [40.0, -10.0]]}]
    d["context"] = [{"name": "2158 W 11TH AV", "footprint": [[17, 2], [27, 2], [27, 17], [17, 17]], "height_m": 7.4, "source": "CoV footprint 2015 · height 2009 LiDAR"}]
    spec = MassingSpec(**d)
    p = rhino_io.export_3dm(spec, tmp_path / "ctx.3dm")
    m = rh.File3dm.Read(str(p))
    paths = {m.Layers[i].FullPath for i in range(len(m.Layers))}
    assert {"Context::Neighbours", "Context::Trees", "Context::Street names"} <= paths
    assert sum(1 for o in m.Objects if o.Attributes.GetUserString("kind") == "tree") == 2
    spec2, warnings = rhino_io.import_3dm(p)
    assert warnings == []
    assert [t.model_dump() for t in spec2.trees] == [t.model_dump() for t in spec.trees]
    assert [s.model_dump() for s in spec2.streets] == [s.model_dump() for s in spec.streets]
    assert len(spec2.context) == 1 and spec2.context[0].name == "2158 W 11TH AV" and spec2.context[0].source.endswith("2009 LiDAR")
    assert analyze_massing(spec)["summary"] == analyze_massing(spec2)["summary"]


def test_same_ring_ignores_start_vertex_and_winding():
    ring = [[0, 0], [10, 0], [10, 20], [0, 20]]
    assert rhino_io._same_ring(ring, ring[2:] + ring[:2])
    assert rhino_io._same_ring(ring, ring[::-1])
    assert not rhino_io._same_ring(ring, [[0, 0], [10, 0], [10, 21], [0, 20]])
    assert not rhino_io._same_ring(ring, ring[:3])


def test_half_written_file_raises_instead_of_returning_an_empty_massing(tmp_path):
    spec = MassingSpec(**SPECS["lane_mixed"])
    p = rhino_io.export_3dm(spec, tmp_path / "lane.3dm")
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 3])
    with pytest.raises(Exception):
        rhino_io.import_3dm(p)
