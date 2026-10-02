# Massing Studio

**Live: https://clcabana.github.io/massing-studio/**

Draw a building massing on a Vancouver lot and watch its Part 3 code analysis update as you drag.
The rule engine reads the **Vancouver Building By-law 2025** (Part 3) and reports, per block:

- grade, first storey, storeys and height, building area (Div. A 1.4.1.2)
- major occupancies with the 10 % subsidiary test (3.2.2.8) and the governing 3.2.2 article for
  Groups C, A2 and E, every qualifying rung, and the **headroom** left before the article flips
- superimposed occupancies (3.2.2.7) and the fire separations between them (Table 3.1.3.1)
- spatial separation per exposing face and storey (Tables 3.2.3.1-B/-C/-D, 3.2.3.7), with limiting
  distances measured from each footprint edge to the lot line plus half the right-of-way
- **targets**: occupant load (Table 3.1.17.1), exits, travel distance and exit width (3.4.2, 3.4.3),
  washrooms (3.7.2) and the Vancouver gender-neutral count (3.7.2.9)

Every line cites its clause and PDF page, and says why. Anything uncertain is flagged.

> This is a **draft generator for a registered professional's review**, not a compliance determination.

Built in the UBC M.Arch course ARCH 540 (AI Workflows) as a Claude project, then moved here to keep building.

## Two ways to run it

**The published page** ([clcabana.github.io/massing-studio](https://clcabana.github.io/massing-studio/)) runs
the whole engine in the browser. Saved iterations stay in your browser's localStorage. The parcel map
and the Rhino round trip need the local server and are switched off there.

**The local app** adds the City of Vancouver parcel picker (the lot, plus the neighbouring buildings with
LiDAR heights, the street trees and the street names, all from City of Vancouver Open Data), saved iterations
on disk with an A3 PDF code summary each, and a live link to Rhino (export `.3dm`, edit in Rhino, save, the
analysis updates).

```bash
pip install -r requirements.txt
python -m playwright install chromium      # only for PDF export
python -m app.server --port 8765           # then open http://127.0.0.1:8765
```

`CODESHEET_FIXTURE=1` serves a synthetic block of lots so the map picker works offline.
See [app/README.md](app/README.md) for the full tour of the UI.

## Layout

    codesheet/      the rule engine: Python 3.11+, pydantic 2, pure functions over data/
    app/            FastAPI server, the UI (static/index.html), engine.js (the JavaScript port),
                    build_pages.py (this site) and build_artifact.py (the Claude artifact)
    data/bylaw/     VBBL 2025 Part 3 articles and Table 3.2.3.1-B/-C extracted to JSON
    data/projects/  two synthetic projects: Courtyard Commons (the golden project) and a lane mixed-use lot
    tests/          hand-worked golden values, tables, occupant-load and egress targets, JS ↔ Python parity
    viz/            plotly sections, elevations and 3D massing for the printed sheet

Python is the source of truth. `engine.js` mirrors it, `tests/test_engine_js.py` fails if they drift,
and `codesheet/export_engine_data.py` regenerates the shared tables after any change in Python.

## Tests and deployment

```bash
python -m pytest -q                        # the JS parity tests need node on the PATH
python app/build_pages.py                  # → out/site/index.html
```

Every push to `main` runs the tests, builds `out/site` and deploys it to GitHub Pages
([.github/workflows/pages.yml](.github/workflows/pages.yml)).

## Scope

Blocks are assumed firewall-separated. Glazing is a ratio per face, not a window schedule. Exit
*layout* (3.3, 3.4.2.3–.4) and washroom accessibility layout (3.8) are out of scope by design.
Group A covers A2 only. The bylaw PDFs are not in the repository; the extracted JSON is enough to run
everything, the PDFs only make the clause links in the printed sheet open.
