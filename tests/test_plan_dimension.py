"""
The plan editor's typed wall lengths: double-click a wall's length tag, type a number, the wall takes that
length about its centre and the walls beside it move. Drives the built GitHub Pages site in Playwright's
Chromium (the UI lives in index.html, not in engine.js, so there is no node runner for it).
"""
import json, pathlib, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from app.build_pages import pages_site


def _has_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_playwright(), reason="playwright not installed")

SPEC = {"project_name": "dims", "sprinklered": True,
        "lot": {"width_m": 15.24, "depth_m": 37.19, "grade_m": 10, "zoning": "C-2",
                "edges": {"south": {"kind": "street", "row_width_m": 20}, "north": {"kind": "lane", "row_width_m": 6},
                          "east": {"kind": "neighbour", "row_width_m": 0}, "west": {"kind": "neighbour", "row_width_m": 0}}},
        "context": [{"name": "east neighbour", "footprint": [[17, 0], [27, 0], [27, 20], [17, 20]], "height_m": 9}],
        "blocks": [{"name": "A", "footprint": [[2, 2], [12, 2], [12, 30], [2, 30]], "holes": [[[5, 10], [9, 10], [9, 16], [5, 16]]],
                    "first_floor_above_grade_m": 0.1, "default_glazing_pct": 30, "glazing_pct_by_edge": {},
                    "storeys": [{"occupancy": "C", "use": "suites", "floor_to_floor_m": 3.0}] * 3}]}

LOAD = "s=>{ spec=normalize(s); sel=0; editStorey=null; ctxSel=null; hist.last=JSON.stringify(spec); changed(true); }"


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright, Error as PWError
    out = ROOT / "out" / "_dimtest"
    index = pages_site(out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page(viewport={"width": 1400, "height": 900})
            pg.goto(index.as_uri())
            pg.wait_for_function("typeof changed==='function' && typeof resizeEdge==='function'")
            # the built page opens the site wizard shortly after load (build_artifact rewrites the #nowizard guard); dismiss it
            pg.wait_for_function("document.getElementById('dlgWiz').open")
            pg.evaluate("document.getElementById('dlgWiz').close()")
            yield pg
            browser.close()
    except PWError as e:
        pytest.skip(f"playwright browser unavailable: {str(e)[:120]}")


def _type_length(page, selector, text, key="Enter"):
    page.locator(selector).dblclick()
    box = page.locator("#planBox .dimEdit")
    box.wait_for(state="visible")
    shown = box.input_value()
    box.fill(text)
    box.press(key)
    box.wait_for(state="detached")
    return shown


def test_block_wall_takes_the_typed_length_about_its_centre(page):
    page.evaluate(LOAD, SPEC)
    shown = _type_length(page, '#plan .edgeH[data-b="0"][data-e="0"]:not([data-h])', "8")
    assert shown == "10.0"
    fp = page.evaluate("spec.blocks[0].footprint")
    assert fp == [[3, 2], [11, 2], [11, 30], [3, 30]]          # south wall 10 → 8: east and west walls each move 1 m in
    shown = _type_length(page, '#plan .edgeH[data-b="0"][data-e="1"]:not([data-h])', "30")
    assert shown == "28.0"
    assert page.evaluate("spec.blocks[0].footprint") == [[3, 1], [11, 1], [11, 31], [3, 31]]
    assert page.evaluate("hist.past.length") >= 2                # each typed length is one undo step


def test_escape_cancels_and_a_bad_value_changes_nothing(page):
    page.evaluate(LOAD, SPEC)
    _type_length(page, '#plan .edgeH[data-b="0"][data-e="0"]:not([data-h])', "20", key="Escape")
    assert page.evaluate("spec.blocks[0].footprint") == [[2, 2], [12, 2], [12, 30], [2, 30]]
    _type_length(page, '#plan .edgeH[data-b="0"][data-e="0"]:not([data-h])', "abc")
    assert page.evaluate("spec.blocks[0].footprint") == [[2, 2], [12, 2], [12, 30], [2, 30]]
    assert page.evaluate("document.querySelectorAll('.dimEdit').length") == 0


def test_lot_boundary_holds_a_block_wall(page):
    page.evaluate(LOAD, SPEC)
    _type_length(page, '#plan .edgeH[data-b="0"][data-e="0"]:not([data-h])', "40")
    fp = page.evaluate("spec.blocks[0].footprint")
    assert fp == [[0, 2], [15.24, 2], [15.24, 30], [0, 30]]      # clamped to the 15.24 m lot, like a drag


def test_courtyard_and_neighbour_walls_edit_too(page):
    page.evaluate(LOAD, SPEC)
    _type_length(page, '#plan .edgeH[data-b="0"][data-h="0"][data-e="0"]', "6")
    assert page.evaluate("spec.blocks[0].holes[0]") == [[4, 10], [10, 10], [10, 16], [4, 16]]
    page.evaluate("()=>{ ctxSel=0; drawPlan(); }")
    _type_length(page, '#plan .edgeH[data-c="0"][data-e="1"]', "24")
    assert page.evaluate("spec.context[0].footprint") == [[17, -2], [27, -2], [27, 22], [17, 22]]   # no lot to clamp a neighbour to


def test_resize_edge_keeps_a_skewed_polygon_s_other_walls_in_direction(page):
    # a parallelogram: lengthening the bottom wall pushes the two slanted walls out parallel to themselves
    pts = [[0, 0], [10, 0], [14, 6], [4, 6]]
    out = page.evaluate("p=>resizeEdge(p,0,14)", pts)
    assert [[round(v, 6) for v in q] for q in out] == [[-2, 0], [12, 0], [16, 6], [2, 6]]
    # the midpoint of the edited wall does not move and the wall keeps its direction
    assert (out[0][0] + out[1][0]) / 2 == 5 and out[0][1] == out[1][1] == 0
    # a triangle: the two other walls are each other's neighbours, and both move
    tri = page.evaluate("p=>resizeEdge(p,0,6)", [[0, 0], [4, 0], [2, 3]])
    assert [[round(v, 6) for v in q] for q in tri] == [[-1, 0], [5, 0], [2, 4.5]]
