"""
Build the GitHub Pages site: Massing Studio as one static page with the
in-browser engine, three.js self-hosted, iterations kept in localStorage.

    PYTHONPATH=. python app/build_pages.py [--out out/site]   →  out/site/index.html, out/site/vendor/three.min.js

The GitHub Actions workflow (.github/workflows/pages.yml) runs this on every
push to main and deploys out/site to Pages. All asset paths are relative so the
site works under a repository sub-path (https://<user>.github.io/<repo>/).
"""
from __future__ import annotations
import argparse, pathlib, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from app.build_artifact import build_parts, FONTS, STATIC   # noqa: E402

REPO_URL = "https://github.com/clcabana/massing-studio"


def pages_site(out_dir: pathlib.Path) -> pathlib.Path:
    p = build_parts(lib_fallback="this browser only (localStorage)")
    body = p["body"].replace(
        '<h1>Massing Studio<small>VBBL 2025</small></h1>',
        f'<h1>Massing Studio<small>VBBL 2025</small></h1><a class="repo" href="{REPO_URL}" target="_blank" rel="noopener" title="Source on GitHub">source</a>', 1)
    assert 'class="repo"' in body
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Massing Studio — VBBL 2025 massing and code check</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Draw a building massing on a Vancouver lot and watch its Part 3 code analysis (VBBL 2025) update live: building area, storeys, 3.2.2 article, spatial separation, occupant load, exits and washrooms. A draft for a registered professional's review.">
{FONTS}
{p["head_css"]}
<style>header a.repo{{font:500 11px "IBM Plex Mono",monospace;color:var(--mut);text-decoration:none;border:1px solid var(--rule);border-radius:3px;padding:2px 6px}} header a.repo:hover{{color:var(--ink);border-color:var(--ink)}}</style>
</head>
<body>
{body}
<script src="vendor/three.min.js"></script>
<script>{p["inline_data"]}</script>
<script>{p["engine"]}</script>
<script>{p["scripts"]}</script>
<script>{p["wizard"]}</script>
</body></html>
'''
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vendor").mkdir(exist_ok=True)
    shutil.copy(STATIC / "vendor" / "three.min.js", out_dir / "vendor" / "three.min.js")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")   # serve files as-is, no Jekyll pass
    index = out_dir / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "site"))
    a = ap.parse_args()
    index = pages_site(pathlib.Path(a.out))
    print("wrote", index, f"{index.stat().st_size // 1024} KB")
