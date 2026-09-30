# Massing Studio (local)

A designer-facing front end for the codesheet engine. Drag a massing, watch
the code compliance update live, save iterations you like (each with a PDF
code compliance summary), reopen and compare them later.

## Run

    pip install -r requirements.txt          # fastapi, uvicorn, pydantic, plotly, pypdf, playwright
    python -m playwright install chromium    # once, for PDF export
    python -m app.server --projects ./projects --port 8765

then open http://127.0.0.1:8765

    CODESHEET_FIXTURE=1 python -m app.server     # offline: the map shows a synthetic block of lots instead of real parcels

## Guided setup

The app opens with a questionnaire (multiple choice wherever possible):

1. **How to start** — pick a site on the map · describe the site · load a saved iteration · worked example (Courtyard Commons, synthetic)
2. **Describe the site** — frontage (33/50/66/100/132 ft or metres), depth, which edges face a street,
   right-of-way width of the front street (local 20 m / arterial 30 m / major 40 m), lane at the rear,
   grade, sprinklered, project name
3. **Add a block** (also from the "+ block…" button) — building type preset (residential, mixed-use retail+res,
   retail+office, office, assembly+res, townhouse), storeys, front/side/rear setbacks, glazing by exposure
   (street 40 %, lane 30 %, neighbour 0 %) or uniform, **upper-storey stepback** (3 m above the 2nd or 4th storey,
   or a 6 m podium/tower), **courtyard** (central or rear light well), **roof** (parapet, elevator/stair penthouse
   which is not a storey under 3.2.1.1, or an amenity room which is), **neighbouring buildings** (west / east /
   across the lane, context only), block name. The footprint is the lot inset by the setbacks; the storey stack
   and per-edge glazing are filled in from the preset and the edge exposures.

Everything the wizard sets is editable afterwards in the Lot, Blocks and Context panels.

## Shaping the massing (v2)

* **Per-storey outlines.** Click a storey number (L1, L2…) in the Blocks panel to edit that storey's own outline
  in the plan; "Give L5 its own outline" copies the block footprint, "Inset 1.5 m" steps it back. Storeys with
  their own outline are marked ◧ and ghosted in the plan. Building area follows the largest storey; exposing
  faces are computed per run of identical outlines (e.g. `south (street) L1–L2` and `south (street) L3–L6`),
  each with its own limiting distance. A stepped-back wall that stays on a party line keeps that edge's 0 % glazing.
* **Courtyards.** "+ courtyard" adds a hole (draggable, reshapeable) to the block or to one storey. The area is
  subtracted; courtyard faces of one building are not exposing building faces (noted, with a reminder to check
  for a firewall across the court).
* **Two buildings facing each other on the lot** now get an *imaginary line* halfway between them
  (Div. A "Limiting distance"), so a courtyard split by a firewall is measured correctly.
* **Roof.** Parapet height, a rooftop enclosure (service penthouse: not a storey per 3.2.1.1.(1); amenity room:
  counts as a storey and is added to the stack), balconies per edge (3D only).
* **Context.** Neighbouring buildings with a height, drawn in the plan, cast shadows in 3D and export to Rhino.
  They do not enter the code analysis (limiting distance is to the property line).
* **3D.** Orbit (drag), pan (right-drag / shift-drag), zoom (wheel), double-click to reset; sun azimuth and
  altitude sliders with cast shadows; storeys coloured by occupancy; **face check** paints faces red where
  unprotected openings exceed the permitted percentage and amber where the wall needs a fire-resistance rating.
* **Undo / redo** (⌘/Ctrl Z, ⇧⌘Z), light / dark theme (◐), Esc leaves storey-edit mode.

## Rhino round trip

1. **Export .3dm** in the Rhino panel (default `projects/<name>/rhino/<name>.3dm`, or type a path — e.g. a folder
   Rhino has open). Layers, metres, **z = 0 is grade**:

       Site::Property line      closed polyline; user text grade_m, address, zoning
       Site::Lot edges          one line per edge (kind = street | lane | neighbour, row_width_m) + far ROW edges
       Site::ROW centrelines    where limiting distance is measured to
       Site::Setbacks           the setback envelope (when the lot carries setbacks)
       Site::Grade              a thin slab at z = 0 covering the lot
       Context::Neighbours      one extrusion per neighbour (name, height_m)
       Massing::<Block>::L<n>   ONE EXTRUSION PER STOREY, base at its floor level, height = floor-to-floor,
                                user text occupancy / use / f2f / beds / units / ded / glazing
       Massing::<Block>::Roof   rooftop enclosure extrusion + parapet outline

   The exported spec is also stored as document user text (`codesheet.spec`) so non-geometric settings survive.
2. Open it in Rhino 7/8. Move, scale, redraw or add solids under `Massing::<Block>` (a Box on the block's layer is
   enough — it inherits the attributes of the storey it replaces or the last exported one). Closed curves with
   user text `kind=hole` on a storey's layer are courtyards. Redraw the property line to change the lot.
3. **Save** in Rhino. With **watch file** ticked, the app polls the file every 1.2 s, waits until Rhino has
   finished writing it (same size and time on two polls), re-reads the Massing layers, rebuilds the storey stack
   (sorted by base elevation), and re-runs the whole analysis. Rhino re-saves edited storeys as Breps rather than
   extrusions; the importer reads both. Warnings (storeys that don't sit on each other, a changed footprint that
   resets per-edge glazing, a redrawn lot) appear under the panel. "Import now" does the same on demand.
   "Download" fetches the file through the browser into your Downloads folder; if you open **that** copy in
   Rhino and save it, the watch notices the newer same-named file in Downloads and follows it (the path box
   updates so you can see which file is live).

`pip install rhino3dm` is the only extra dependency. The published artifact cannot read files on your disk, so the
Rhino panel is local-app only.

## Pick a site (parcel map)

"Pick a site on the map" opens a Leaflet map of Vancouver. Zoom to the block (zoom >= 16) and the app loads
parcels, zoning, street centrelines and lane centrelines around the map centre from **City of Vancouver Open
Data** (datasets `property-parcel-polygons`, `zoning-districts-and-labels`, `public-streets`, `lanes`; ids and
field names are in `app/parcels.py` -> `DATASETS`). Click a parcel and it becomes the lot: outline simplified
and rotated so the principal street edge is at the bottom, one kind per edge (street / lane / neighbour) from
the nearest centreline just outside that edge, right-of-way width ~ 2 x the distance to the centreline,
zoning district from the polygon the parcel sits in. Check the inferred edge kinds in the Lot panel — the
inference is geometric and a corner cut or an odd parcel can fool it.

Note: the live Open Data query was written against the documented API but could not be exercised from the
build environment (no internet). First run it on a connected machine; if a dataset id or field has changed,
fix it in `DATASETS`. The fixture mode (`CODESHEET_FIXTURE=1`) exercises the full picker offline.

Lots picked from the map are polygons, not rectangles: limiting distances are measured by casting from each
footprint edge to the lot boundary, so angled and irregular parcels are handled.


## What it checks live (VBBL 2025)

* grade, first storey, storeys in building height, height to top floor, building area — per block
* major occupancies from the storey stack, with the 10 % subsidiary test (3.2.2.8)
* the governing 3.2.2 article for Groups C, A2 and E, every qualifying rung, and **headroom**:
  how many storeys, metres and square metres remain before the article flips
* superimposed occupancies per 3.2.2.7, and fire separations between them (Table 3.1.3.1 + notes)
* spatial separation per face and storey (Tables 3.2.3.1.-B/-C/-D, Table 3.2.3.7), with
  limiting distances measured from each footprint edge to the lot line plus half the right-of-way
* **targets** (v1.2) per storey and per block — occupant load (Table 3.1.17.1: area per person by
  use, 2 persons per bedroom for suites, fixed seats / designer counts honoured; gross and designed
  load after the deductions you enter), exits required (3.4.2.1 incl. the one-exit criteria), travel
  distance limit (3.4.2.5), aggregate and per-stair exit width with the Table 3.4.3.2.-A minimums,
  water closets and lavatories per Group (3.7.2.2 Tables -A/-B/-C, 3.7.2.3, urinal and unisex
  alternatives) and the Vancouver gender-neutral washroom count (3.7.2.9). Storey rows take
  *beds / units* for Group C and a *deduction %* for other uses. Validated row for row against a
  hand-worked occupant-load table (tests/test_courtyard_commons.py).

Every line in the saved summary cites its clause and page.

## Saved iterations

    projects/<project>/iterations/<timestamp>-<name>/
        spec.json       the massing you drew
        results.json    every determination, headroom, faces, flags
        summary.html    the code compliance summary (clause links open the bylaw PDF if stored beside it)
        summary.pdf     the same, A3 landscape
        thumb.png       3D thumbnail

## Known limitations

* Blocks are assumed firewall-separated (each is its own building).
* Rhino import reads the bottom face of each solid as the storey outline: fine for extrusions and boxes; a
  sculpted Brep is reduced to its bounding outline, and curved outlines are polygonised (48 points).
* Balconies are drawn in 3D only; they do not enter the spatial-separation or area calculations.
* Glazing is a ratio per face, not a window schedule.
* Targets are targets: exit *locations*, dead ends, access to exit (3.3, 3.4.2.3–.4) and washroom
  accessibility layout (3.8.3) are not assessed. Bedrooms are estimated at 1 per 35 m² until entered.
* This is a DRAFT generator for a registered professional's review, not a compliance determination.
