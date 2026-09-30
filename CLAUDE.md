# Codesheet / Massing Studio — project brief for Claude Code

VBBL 2025 (Vancouver Building By-law, Part 3) code-analysis engine plus an interactive massing tool.
Built in a Claude Cowork session for Claudio (GenEnv, UBC). Continue here.

## What is where

    codesheet/           the rule engine (Python 3.11, pydantic 2). Pure functions, no I/O except reading data/.
      model.py           BuildingModel: Site, Storey, Zone, Footprint (with holes), ExteriorFace — description only
      determinations.py  Determination + Clause dataclasses; Bylaw reader over data/bylaw/<edition>/articles.json
      height_area.py     grade, first storey, building height, building area (Div. A 1.4.1.2)
      occupancy.py       zone → Group (Table 3.1.2.1), major occupancies with the 10 % rule (3.2.2.8)
      articles.py        3.2.2 ladders for Groups C, A2, E; qualifying rungs, headroom, requirements
      spatial.py, table_3231.py   exposing faces, Tables 3.2.3.1-B/-C/-D, Table 3.2.3.7
      separations.py     Table 3.1.3.1 + notes (3),(4); 3.2.2.7 stacked occupancies
      targets.py         occupant load (Table 3.1.17.1), exits/travel/width (3.4.2, 3.4.3), washrooms (3.7.2, VBBL 3.7.2.9)
      sheet.py           assembles the A3 code sheet (HTML → PDF via Playwright)
      massing.py         MassingSpec (lot, blocks, per-storey footprints, holes, roof, context) → BuildingModel; analyze_massing()
      rhino_io.py        export_3dm / import_3dm with rhino3dm (layers Site / Context / Massing::<Block>::L<n>)
      export_engine_data.py → app/static/engine_data.json (tables shared with the JS port)
    app/
      server.py          FastAPI: /api/analyze, /api/iterations, /api/rhino/*, /api/parcels, /api/presets
      static/index.html  the UI (plan editor, three.js 3D, panels, results, Rhino panel, summary dialog)
      static/wizard.js   guided site / block questionnaires + parcel map picker
      static/engine.js   JavaScript port of the engine (kept equal to Python by tests/test_engine_js.py)
      build_artifact.py  build_parts() strips the server (markers @@API/@@LIBRARY/@@RHINO); artifact_page() → out/massing_studio_artifact.html
      build_pages.py     the GitHub Pages site → out/site/ (complete document, relative paths, three.js self-hosted)
      parcels.py         City of Vancouver Open Data parcel → lot (untested live from the sandbox)
    data/bylaw/vbbl-2025/   articles.json (569 Part 3 articles extracted from the PDF), table_3231_BC.json
    data/projects/courtyard_commons.py   SYNTHETIC golden project (3 blocks incl. a 3.2.1.2 parkade); lane_mixed_use.py synthetic
    tests/               hand-worked golden values on the synthetic projects, tables, targets, JS↔Python parity, Rhino round trip, the server-less builds
    private/             NOT in git: a golden project transcribed from a firm's drawing set plus the tests that quote it.
                         Runs locally with pytest when present; never publish it (see private/README.md).

Not included here (put them back if needed): the bylaw PDFs (`data/bylaw/vbbl-2025-vol1.pdf`, `bcbc-2024-rev2.pdf`).
The extracted JSON is enough to run everything; the PDFs are only needed to re-extract or to follow the clause links
in the printed sheet.

## Run

    pip install -r requirements.txt            # fastapi uvicorn pydantic plotly pypdf playwright pytest rhino3dm
    python -m playwright install chromium      # PDF export only
    python -m pytest -q                        # public suite (+ private/ tests when that folder exists)
    python -m app.server --port 8765           # http://127.0.0.1:8765 ; CODESHEET_FIXTURE=1 for an offline parcel map
    PYTHONPATH=. python codesheet/export_engine_data.py   # after changing any table or ladder in Python
    PYTHONPATH=. python app/build_artifact.py             # → out/massing_studio_artifact.html
    PYTHONPATH=. python app/build_pages.py                # → out/site/  (what GitHub Pages serves)

## Repository and GitHub Pages

Public repo https://github.com/clcabana/massing-studio, live site https://clcabana.github.io/massing-studio/.
`.github/workflows/pages.yml` runs pytest (with node, so the JS parity tests run), builds `out/site`
with `app/build_pages.py` and deploys it on every push to `main`. Nothing generated is committed:
`out/`, `projects/` and `.venv/` are ignored. On this Windows machine git comes bundled with GitHub
Desktop and Python 3.12 is a per-user install; a `.venv` in the repo root has the requirements.

## Conventions

- Every rule returns `Determination`s with clauses (id, edition, PDF page) and a plain-language `because`.
  Never a silent number. Anything uncertain goes in `flags`.
- The tool proposes, the designer decides: designer-declared occupancies, construction and chosen articles are
  honoured and loudly flagged when they don't qualify.
- Python is the source of truth; `engine.js` mirrors it and `tests/test_engine_js.py` fails if they drift.
  Change Python first, re-export engine_data.json, then mirror in JS.
- Rhino file convention: metres, z = 0 is grade, one extrusion per storey, user text carries attributes,
  the exported spec is stored as document user text `codesheet.spec`.

## The published artifact

Massing Studio is published as a Claude artifact: https://claude.ai/artifact/9JHhyGr6kweTfZ6ffhVYEJ
(version 3, `db` capability for the shared iteration library). To republish from Claude Code, rebuild
`out/massing_studio_artifact.html` and publish it to that URL with the Artifact tool (read it first).

## Open items

- Parcel map: DATASETS ids/fields verified live against opendata.vancouver.ca on 2026-09-29. The Explore API
  caps `limit` at 100 per request, so `_ods` pages with `offset`; `tests/test_parcels.py` pins that.
- First real Save-in-Rhino test of the watch loop (verified only with rhino3dm round trips).
- Group A ladder covers A2 only; Table 3.2.2.68 not extracted; BCBC 2024 text parser not built.
- Egress *layout* (3.3, 3.4.2.3–.4) and washroom accessibility layout (3.8) are out of scope by design.
