"""
app.server — the local Massing Studio server.

    python -m app.server [--projects ./projects] [--port 8765]

Endpoints (all JSON unless noted):
  POST /api/analyze                 MassingSpec → live results (summary, headroom, faces, determinations, flags)
  GET  /api/iterations              list saved iterations (newest first)
  POST /api/iterations              save {spec, name, note, thumbnail?} → writes a folder, returns the record
  GET  /api/iterations/{id}         spec + results of one iteration
  DELETE /api/iterations/{id}
  GET  /api/iterations/{id}/summary.pdf   the code compliance summary sheet (generated on save)
  GET  /api/iterations/{id}/thumb.png
  GET  /api/examples/demo           the synthetic Courtyard Commons massing as a starting spec
  POST /api/rhino/export            {spec, path?} → writes site.3dm (layers: Site, Context, Massing::<Block>::L<n>), returns {path, mtime}
  GET  /api/rhino/status?path=      {exists, mtime} — the UI polls this while "watch" is on
  POST /api/rhino/import            {path} → {spec, warnings}: rebuilds the massing from the Massing layers
  GET  /api/rhino/file?path=        download the .3dm
  GET  /                            the editor UI

Iterations live on disk, one folder each, so a firm can keep them with the project:
  <projects>/<slug>/iterations/<timestamp>-<name>/{spec.json, results.json, summary.html, summary.pdf, thumb.png}
"""
from __future__ import annotations

import argparse, base64, datetime, json, pathlib, re, shutil, sys, time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "data" / "projects")]

from codesheet.massing import MassingSpec, analyze_massing, to_building_model     # noqa: E402
from codesheet import sheet                                                       # noqa: E402
from app import parcels as parcels_mod                                            # noqa: E402
try:
    from codesheet import rhino_io                                                # noqa: E402
except ImportError:                                                               # rhino3dm not installed
    rhino_io = None

app = FastAPI(title="Codesheet Massing Studio")
PROJECTS = ROOT / "projects"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "untitled"


class SaveRequest(BaseModel):
    spec: MassingSpec
    name: str
    note: str = ""
    thumbnail_png_b64: str | None = None


@app.post("/api/analyze")
def analyze(spec: MassingSpec):
    if not any(b.storeys for b in spec.blocks):
        raise HTTPException(422, "nothing to analyse: the massing has no storeys (add a block, or check the Rhino file's Massing layers)")
    try:
        return analyze_massing(spec)
    except (ValidationError, ValueError) as e:   # a spec the model can describe but the engine cannot build
        raise HTTPException(422, f"could not analyse this massing: {e}")


def _iter_dir(project: str) -> pathlib.Path:
    return PROJECTS / _slug(project) / "iterations"


def _record(d: pathlib.Path) -> dict:
    spec = json.loads((d / "spec.json").read_text(encoding="utf-8"))
    res = json.loads((d / "results.json").read_text(encoding="utf-8"))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
    return {"id": d.name, "project": spec.get("project_name"), "name": meta.get("name", d.name), "note": meta.get("note", ""),
            "saved": meta.get("saved"), "summary": res.get("summary"), "flags": len(res.get("flags", [])),
            "has_pdf": (d / "summary.pdf").exists(), "has_thumb": (d / "thumb.png").exists()}


@app.get("/api/iterations")
def list_iterations(project: str | None = None):
    out = []
    roots = [PROJECTS / _slug(project)] if project else [p for p in PROJECTS.glob("*") if p.is_dir()] if PROJECTS.exists() else []
    for r in roots:
        it = r / "iterations"
        if it.exists():
            for d in it.iterdir():
                if (d / "spec.json").exists():
                    out.append(_record(d))
    return sorted(out, key=lambda r: r["id"], reverse=True)


@app.post("/api/iterations")
def save_iteration(req: SaveRequest):
    res = analyze_massing(req.spec)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = _iter_dir(req.spec.project_name) / f"{ts}-{_slug(req.name)}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(req.spec.model_dump_json(indent=1), encoding="utf-8")
    (d / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"name": req.name, "note": req.note, "saved": datetime.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    if req.thumbnail_png_b64:
        try:
            (d / "thumb.png").write_bytes(base64.b64decode(req.thumbnail_png_b64.split(",")[-1]))
        except Exception:
            pass
    # compliance summary sheet
    b = to_building_model(req.spec)
    sd = sheet.run_all(b, chosen=req.spec.chosen_articles or None)
    html_path = d / "summary.html"
    html_path.write_text(sheet.render_html(sd, sheet_no="MS-01", revision=f"Massing iteration — {req.name}"), encoding="utf-8")
    try:
        sheet.to_pdf(html_path, d / "summary.pdf")
    except Exception as e:                       # PDF is a convenience; never fail the save
        (d / "pdf_error.txt").write_text(str(e), encoding="utf-8")
    return _record(d)


def _find(iid: str) -> pathlib.Path:
    for p in PROJECTS.glob("*/iterations/*"):
        if p.name == iid and (p / "spec.json").exists():
            return p
    raise HTTPException(404, "iteration not found")


@app.get("/api/iterations/{iid}")
def get_iteration(iid: str):
    d = _find(iid)
    return {"record": _record(d), "spec": json.loads((d / "spec.json").read_text(encoding="utf-8")), "results": json.loads((d / "results.json").read_text(encoding="utf-8"))}


@app.delete("/api/iterations/{iid}")
def delete_iteration(iid: str):
    shutil.rmtree(_find(iid))
    return {"ok": True}


@app.get("/api/iterations/{iid}/summary.pdf")
def iteration_pdf(iid: str):
    f = _find(iid) / "summary.pdf"
    if not f.exists():
        raise HTTPException(404, "no PDF (see pdf_error.txt)")
    return FileResponse(f, media_type="application/pdf", filename=f"{iid}-code-summary.pdf")


@app.get("/api/iterations/{iid}/summary.html")
def iteration_html(iid: str):
    return HTMLResponse((_find(iid) / "summary.html").read_text(encoding="utf-8"))


@app.get("/api/iterations/{iid}/thumb.png")
def iteration_thumb(iid: str):
    f = _find(iid) / "thumb.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/png")


class LotRequest(BaseModel):
    parcel: dict
    streets: list[dict] = []
    lanes: list[dict] = []
    zoning: list[dict] = []
    grade_m: float = 10.0


@app.get("/api/parcels")
def parcels_near(lat: float, lon: float, radius: float = 250):
    """Parcels, zoning and centrelines near a point (City of Vancouver Open Data, or the offline fixture)."""
    try:
        return parcels_mod.nearby(lat, lon, radius)
    except Exception as e:
        raise HTTPException(502, f"Open Data request failed: {e}. Start with CODESHEET_FIXTURE=1 to use the offline fixture.")


@app.post("/api/parcels/lot")
def parcel_lot(req: LotRequest):
    return parcels_mod.parcel_to_lot(req.parcel, req.streets, req.lanes, req.zoning, req.grade_m)


@app.get("/api/presets")
def presets():
    """Building-type presets for the block wizard: storey stacks and glazing by exposure."""
    C, E, D, A2 = "C", "E", "D", "A2"
    def st(occ, use, h): return {"occupancy": occ, "use": use, "floor_to_floor_m": h}
    return {
        "types": [
            {"id": "res", "label": "Residential (apartments)", "ground": st(C, "residential lobby and suites", 3.4), "upper": st(C, "apartment suites", 3.0), "default_storeys": 4},
            {"id": "mixed", "label": "Mixed-use — retail at grade, residential above", "ground": st(E, "retail CRU", 4.2), "upper": st(C, "apartment suites", 3.0), "default_storeys": 4},
            {"id": "mixed_office", "label": "Mixed-use — retail at grade, office above", "ground": st(E, "retail CRU", 4.2), "upper": st(D, "office", 3.6), "default_storeys": 4},
            {"id": "office", "label": "Office", "ground": st(D, "office lobby and suites", 4.0), "upper": st(D, "office", 3.6), "default_storeys": 4},
            {"id": "assembly_res", "label": "Community / assembly at grade, residential above", "ground": st(A2, "community hall, dining", 4.5), "upper": st(C, "suites", 3.0), "default_storeys": 5},
            {"id": "townhouse", "label": "Townhouses (stacked or row)", "ground": st(C, "townhouse", 3.0), "upper": st(C, "townhouse", 2.9), "default_storeys": 3},
        ],
        "glazing_by_exposure": {"street": 40, "lane": 30, "neighbour": 0},
        "row_widths": {"local street": 20.0, "arterial": 30.0, "major arterial": 40.0, "lane": 6.0},
        "frontages_m": {"33 ft": 10.06, "50 ft": 15.24, "66 ft": 20.12, "100 ft": 30.48, "132 ft": 40.23},
        "depths_m": {"100 ft": 30.48, "120 ft": 36.58, "122 ft": 37.19, "130 ft": 39.62},
    }


# --- Rhino round trip -----------------------------------------------------------------------

class RhinoExport(BaseModel):
    spec: MassingSpec
    path: str | None = None


class RhinoPath(BaseModel):
    path: str


def _rhino_default_path(spec: MassingSpec) -> pathlib.Path:
    return PROJECTS / _slug(spec.project_name) / "rhino" / f"{_slug(spec.project_name)}.3dm"


def _resolve_3dm(path: str) -> pathlib.Path:
    p = pathlib.Path(path).expanduser()
    if p.suffix.lower() != ".3dm":
        raise HTTPException(400, "path must end in .3dm")
    return p


@app.post("/api/rhino/export")
def rhino_export(req: RhinoExport):
    if rhino_io is None:
        raise HTTPException(501, "rhino3dm is not installed: pip install rhino3dm")
    path = _resolve_3dm(req.path) if req.path else _rhino_default_path(req.spec)
    rhino_io.export_3dm(req.spec, path)
    return {"path": str(path), "mtime": path.stat().st_mtime}


def _newer_copies(p: pathlib.Path) -> list[dict]:
    """Same-named .3dm files in the user's Downloads folder that are newer than `p`.

    The Download button hands the browser a copy; when the designer opens that copy in Rhino and saves,
    the file the server wrote never changes. The UI follows the newest such copy instead."""
    downloads = pathlib.Path.home() / "Downloads"
    ref = p.stat().st_mtime if p.exists() else 0.0
    out = []
    if downloads.is_dir():
        for q in downloads.glob(f"{p.stem}*.3dm"):
            try:
                st = q.stat()
            except OSError:
                continue
            if q.resolve() != p.resolve() and st.st_mtime > ref + 0.001:
                out.append({"path": str(q), "mtime": st.st_mtime, "size": st.st_size})
    return sorted(out, key=lambda d: -d["mtime"])


def _settled(p: pathlib.Path, wait: float = 0.3, tries: int = 10) -> bool:
    """Rhino writes a .3dm in place over some hundreds of ms; wait until size and mtime stop changing."""
    last = None
    for _ in range(tries):
        st = p.stat()
        cur = (st.st_size, st.st_mtime)
        if cur == last:
            return True
        last = cur
        time.sleep(wait)
    return False


@app.get("/api/rhino/status")
def rhino_status(path: str):
    p = _resolve_3dm(path)
    st = p.stat() if p.exists() else None
    return {"exists": st is not None, "mtime": st.st_mtime if st else None, "size": st.st_size if st else None,
            "newer_copies": _newer_copies(p)}


@app.post("/api/rhino/import")
def rhino_import(req: RhinoPath):
    if rhino_io is None:
        raise HTTPException(501, "rhino3dm is not installed: pip install rhino3dm")
    p = _resolve_3dm(req.path)
    if not p.exists():
        raise HTTPException(404, f"{p} not found")
    _settled(p)
    err = "unknown error"
    for attempt in range(3):                     # a half-written file mid-save reads as None or as an empty model
        try:
            spec, warnings = rhino_io.import_3dm(p)
            if spec.blocks:
                break
            err = "no storey volumes found under a Massing::<Block> layer"
        except Exception as e:                   # foreign geometry, or still being written
            err = str(e)
        time.sleep(0.4)
    else:
        raise HTTPException(422, f"could not read {p.name}: {err}")
    return {"spec": spec.model_dump(mode="json"), "warnings": warnings, "mtime": p.stat().st_mtime}


@app.get("/api/rhino/file")
def rhino_file(path: str):
    p = _resolve_3dm(path)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/octet-stream", filename=p.name)


@app.get("/api/examples/demo")
def example_demo():
    """The synthetic Courtyard Commons project (data/projects/courtyard_commons.py) as a massing spec:
    two above-grade blocks either side of a firewall, parkade omitted."""
    C, A2 = "C", "A2"
    return {
        "project_name": "Courtyard Commons (example)",
        "lot": {"width_m": 60.0, "depth_m": 60.0, "grade_m": 10.0,
                "edges": {"south": {"kind": "street", "row_width_m": 34.0}, "west": {"kind": "street", "row_width_m": 40.0},
                          "east": {"kind": "neighbour", "row_width_m": 0}, "north": {"kind": "neighbour", "row_width_m": 0}}},
        "sprinklered": True, "streets_faced": 2,
        "chosen_articles": {"North": "3.2.2.51", "South": "3.2.2.51"},
        "blocks": [
            {"name": "North", "first_floor_above_grade_m": 0.5, "default_glazing_pct": 25,
             "footprint": [[5.0, 35.0], [55.0, 35.0], [55.0, 55.0], [5.0, 55.0]],
             "storeys": [{"occupancy": A2, "use": "dining hall, kitchen, auditorium, offices", "floor_to_floor_m": 4.5},
                         {"occupancy": C, "use": "student suites", "floor_to_floor_m": 3.0, "sleeping_rooms": 24, "dwelling_units": 20},
                         {"occupancy": C, "use": "student suites", "floor_to_floor_m": 3.0, "sleeping_rooms": 24, "dwelling_units": 20},
                         {"occupancy": C, "use": "student suites", "floor_to_floor_m": 3.0, "sleeping_rooms": 24, "dwelling_units": 20},
                         {"occupancy": C, "use": "student suites", "floor_to_floor_m": 3.0, "sleeping_rooms": 20, "dwelling_units": 16}]},
            {"name": "South", "first_floor_above_grade_m": 0.5, "default_glazing_pct": 35,
             "footprint": [[5.0, 5.0], [55.0, 5.0], [55.0, 33.0], [5.0, 33.0]],
             "storeys": [{"occupancy": C, "use": "rental lobby and suites", "floor_to_floor_m": 4.5, "sleeping_rooms": 10, "dwelling_units": 8}] +
                        [{"occupancy": C, "use": "rental suites", "floor_to_floor_m": 3.0, "sleeping_rooms": 16, "dwelling_units": 12} for _ in range(5)]},
        ],
    }


app.mount("/", StaticFiles(directory=str(ROOT / "app" / "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", default=str(PROJECTS))
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    PROJECTS = pathlib.Path(a.projects)
    PROJECTS.mkdir(parents=True, exist_ok=True)
    print(f"Massing Studio → http://127.0.0.1:{a.port}   (iterations saved under {PROJECTS})")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
