"""The server-less builds (Claude artifact, GitHub Pages) assemble and contain no server calls."""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from app.build_artifact import build_parts, artifact_page
from app.build_pages import pages_site


def test_parts_have_no_server_calls():
    p = build_parts(lib_fallback="x")
    for k in ("scripts", "wizard"):
        assert "/api/" not in p[k], k
        assert "fetch(" not in p[k], k
    assert "CodesheetEngine.analyzeMassing" in p["scripts"]
    assert "rhinoPane" not in p["body"] and "dlgMap" not in p["body"]


def test_artifact_has_no_skeleton():
    page = artifact_page()
    assert "<!doctype" not in page.lower() and "<html" not in page
    assert "shared library unavailable" in page


def test_pages_site_is_a_complete_relative_document(tmp_path):
    index = pages_site(tmp_path)
    page = index.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert 'src="vendor/three.min.js"' in page and (tmp_path / "vendor" / "three.min.js").exists()
    assert 'src="/' not in page and 'href="/' not in page       # must work under /<repo>/
    assert (tmp_path / ".nojekyll").exists()
    assert "localStorage" in page and "claude.ai" not in page
