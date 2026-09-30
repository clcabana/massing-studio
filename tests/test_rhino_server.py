"""The server side of the Rhino watch loop: following the copy Rhino saved, waiting out a save, clear errors."""
import os, pathlib, sys, time
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
pytest.importorskip("rhino3dm")
pytest.importorskip("fastapi")
from fastapi import HTTPException
from codesheet.massing import MassingSpec
from codesheet import rhino_io
from app import server
from test_engine_js import SPECS


def _touch(p: pathlib.Path, when: float):
    os.utime(p, (when, when))


def test_newer_copies_finds_the_downloads_copy_rhino_saved(tmp_path, monkeypatch):
    home = tmp_path / "home"; (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    served = tmp_path / "projects" / "x" / "rhino" / "site.3dm"; served.parent.mkdir(parents=True)
    served.write_bytes(b"x"); _touch(served, 1_000_000.0)
    old = home / "Downloads" / "site.3dm"; old.write_bytes(b"x"); _touch(old, 999_000.0)          # downloaded, never saved
    saved = home / "Downloads" / "site(1).3dm"; saved.write_bytes(b"xx"); _touch(saved, 1_000_500.0)  # Rhino saved this one
    other = home / "Downloads" / "unrelated.3dm"; other.write_bytes(b"x"); _touch(other, 1_000_900.0)
    copies = server._newer_copies(served)
    assert [pathlib.Path(c["path"]).name for c in copies] == ["site(1).3dm"]
    assert copies[0]["size"] == 2 and copies[0]["mtime"] == pytest.approx(1_000_500.0)


def test_newer_copies_is_empty_without_a_downloads_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    p = tmp_path / "site.3dm"; p.write_bytes(b"x")
    assert server._newer_copies(p) == []


def test_status_reports_size_and_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    p = tmp_path / "site.3dm"; p.write_bytes(b"abc")
    s = server.rhino_status(str(p))
    assert s["exists"] and s["size"] == 3 and s["newer_copies"] == [] and s["mtime"] == pytest.approx(p.stat().st_mtime)
    assert server.rhino_status(str(tmp_path / "missing.3dm")) == {"exists": False, "mtime": None, "size": None, "newer_copies": []}


def test_settled_waits_for_a_growing_file(tmp_path):
    p = tmp_path / "grow.3dm"; p.write_bytes(b"a")
    sizes = iter([1, 2, 3, 3])
    real_stat = pathlib.Path.stat

    class St:
        def __init__(self, n): self.st_size = n; self.st_mtime = 1.0
    calls = []
    pathlib.Path.stat = lambda self, *a, **k: (calls.append(1), St(next(sizes)))[1] if self == p else real_stat(self, *a, **k)
    try:
        assert server._settled(p, wait=0.0, tries=10) is True
    finally:
        pathlib.Path.stat = real_stat
    assert len(calls) == 4                        # 1, 2, 3, 3 → stable on the fourth stat


def test_import_endpoint_round_trips_an_exported_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    spec = MassingSpec(**SPECS["lane_mixed"])
    p = rhino_io.export_3dm(spec, tmp_path / "lane.3dm")
    out = server.rhino_import(server.RhinoPath(path=str(p)))
    assert out["warnings"] == [] and len(out["spec"]["blocks"]) == len(spec.blocks)
    assert out["mtime"] == pytest.approx(p.stat().st_mtime)


def test_import_endpoint_explains_an_unreadable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    p = tmp_path / "junk.3dm"; p.write_bytes(b"not a rhino file")
    with pytest.raises(HTTPException) as e:
        server.rhino_import(server.RhinoPath(path=str(p)))
    assert e.value.status_code == 422 and "could not read junk.3dm" in e.value.detail


def test_import_endpoint_rejects_a_file_with_no_massing(tmp_path, monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    import rhino3dm as rh
    m = rh.File3dm(); m.Write(str(tmp_path / "empty.3dm"), 8)
    with pytest.raises(HTTPException) as e:
        server.rhino_import(server.RhinoPath(path=str(tmp_path / "empty.3dm")))
    assert e.value.status_code == 422 and "no storey volumes" in e.value.detail


def test_analyze_rejects_a_massing_without_storeys():
    spec = MassingSpec(**SPECS["lane_mixed"])
    empty = spec.model_copy(update={"blocks": []})
    with pytest.raises(HTTPException) as e:
        server.analyze(empty)
    assert e.value.status_code == 422 and "no storeys" in e.value.detail
