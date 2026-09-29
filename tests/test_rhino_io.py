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
