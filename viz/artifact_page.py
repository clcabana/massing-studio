"""
viz.artifact_page — render a BuildingModel as a self-contained artifact page:
title block + 3D massing viewer + "what the model knows" rail.
"""
from __future__ import annotations

import json, os, pathlib, sys, html

import plotly

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "data" / "projects")]

from codesheet.model import BuildingModel
from viz.massing3d import build_figure, OCC_COLOUR, first_storey_floor
from viz.section2d import build_figure as build_section
from codesheet.height_area import analyze as analyze_height
from codesheet import occupancy, articles, spatial
from viz.elevations import build_figure as build_elevations

PLOTLY_JS = pathlib.Path(plotly.__file__).parent / "package_data" / "plotly.min.js"


def storey_rows(b: BuildingModel, block: str) -> str:
    ff = first_storey_floor(b)
    rows = []
    for s in reversed(b.storeys_sorted(block)):
        if s.is_roof:
            rel = "roof"
        else:
            rel = "above grade" if s.elevation_m >= ff - 0.01 else "below grade"
        uses = ", ".join(z.name for z in s.zones) or "—"
        rows.append(f"<tr><td class='mono'>{html.escape(s.label)}</td><td class='mono'>{s.elevation_m:.2f}</td>"
                    f"<td class='mono'>{s.footprint.area() if s.footprint else b.footprint.area():,.0f}</td>"
                    f"<td><span class='tag {rel.split()[0]}'>{rel}</span></td><td class='uses'>{html.escape(uses)}</td></tr>")
    return "".join(rows)


def face_rows(b: BuildingModel) -> str:
    rows = []
    for f in b.exterior_faces:
        pct = 100 * f.unprotected_opening_area_m2() / f.area_m2()
        rows.append(f"<tr><td>{html.escape(f.label)}</td><td class='mono'>{f.length_m():.1f} × {f.height_m():.1f}</td>"
                    f"<td class='mono'>{f.area_m2():,.0f}</td><td class='mono'>{f.limiting_distance_m:g}</td>"
                    f"<td class='mono'>{pct:.0f}%</td><td class='src'>{html.escape(f.source_note or '')}</td></tr>")
    return "".join(rows)


def det_rows(dets) -> str:
    rows = []
    for d in dets:
        cites = "<br>".join(f"<span class='cite'>{html.escape(c.ref())}</span>" for c in d.clauses)
        flags = "".join(f"<div class='flagline'>⚠ {html.escape(f)}</div>" for f in d.flags)
        val = d.display() if not isinstance(d.value, list) else ", ".join(d.value)
        rows.append(f"<tr><td class='blk'>{html.escape(d.block or 'site')}</td><td>{html.escape(d.label)}</td>"
                    f"<td class='mono val'>{html.escape(val)}</td><td class='src'>{html.escape(d.because)}{flags}</td><td>{cites}</td></tr>")
    return "".join(rows)


def ladder_html(b, evals_by_block, art_dets) -> str:
    A = {d.key: d for d in art_dets}
    parts = []
    for blk, evals in evals_by_block.items():
        gov = A[f"{blk}.article"].value
        rungs = []
        for e in evals:
            chips = "".join(f"<span class='chip {'ok' if p else 'no'}'>{html.escape(c)} <b>{html.escape(d)}</b></span>" for c, p, d in e.checks)
            cls = "rung " + ("gov" if e.rule.id == gov else "q" if e.qualifies else "x")
            req = f"{html.escape(e.rule.construction)} · floors {e.rule.floor_frr_h:g} h" + (f" · roof {e.rule.roof_frr_h:g} h" if e.rule.roof_frr_h else "")
            tag = "governing" if e.rule.id == gov else "qualifies" if e.qualifies else "excluded"
            rungs.append(f"<div class='{cls}'><div class='rid mono'>{e.rule.id}</div><div class='rbody'><div class='rt'>{html.escape(e.rule.title)} <span class='rtag'>{tag}</span></div>"
                         f"<div class='rreq'>{req}</div><div class='chips'>{chips}</div></div></div>")
        flags = "".join(f"<div class='flagline'>⚠ {html.escape(f)}</div>" for f in A[f"{blk}.article"].flags)
        parts.append(f"<div class='ladder'><h3>{html.escape(blk)} Block — Group C ladder</h3>{''.join(rungs)}{flags}</div>")
    return "".join(parts)


def occ_rows(occ_dets) -> str:
    rows = []
    for d in occ_dets:
        if d.key.endswith("major_occupancies"):
            continue
        conf = d.inputs.get("confidence", 0)
        flag = f"<div class='flagline'>⚠ {html.escape(d.flags[0])}</div>" if d.flags else ""
        rows.append(f"<tr><td class='blk'>{html.escape(d.block)}</td><td>{html.escape(d.label)}</td><td class='mono'>{d.inputs['area_m2']:,.0f}</td>"
                    f"<td class='mono val'>{html.escape(str(d.value))}</td><td class='mono'>{conf:.2f}</td><td class='src'>{html.escape(d.because)}{flag}</td></tr>")
    return "".join(rows)


def render(b: BuildingModel, out: pathlib.Path):
    dets = analyze_height(b)
    occ = occupancy.analyze(b)
    arts = articles.analyze(b, dets, occ, chosen={"North": "3.2.2.51", "South": "3.2.2.51"})
    evals = articles.ladder(b, dets, occ)
    sp_dets, bands = spatial.analyze(b)
    elev = build_elevations(b, bands); elevjson = elev.to_json()
    sp_rows = []
    for face, rs in bands.items():
        worst = min(rs, key=lambda r: r.permitted_pct - r.actual_pct)
        cells = "".join(f"<td class='mono'><span class='chip {'ok' if r.ok else 'no'}'>{r.label} <b>{r.actual_pct:g}/{r.permitted_pct:g}%</b></span></td>" for r in rs)
        req = f"FRR ≥ {worst.frr_min} min · {worst.cladding} cladding" if worst.frr_min else "none (100% permitted)"
        sp_rows.append(f"<tr><td class='blk'>{html.escape(rs[0].face.block)}</td><td>{html.escape(face)}</td><td class='mono'>{rs[0].face.limiting_distance_m:g}</td>"
                       f"<td><div class='chips'>{cells}</div></td><td class='val'>{html.escape(req)}</td></tr>")
    sp_table = "".join(sp_rows)
    majors_html = "".join(
        f"<div class='maj'><span class='k'>{html.escape(d.block)} Block major occupancies</span>"
        f"<span class='v'>{' · '.join(f'<b>Group {v}</b>' for v in d.value)}</span>"
        f"<div class='src'>{html.escape(d.because)}</div>" + "".join(f"<div class='flagline'>⚠ {html.escape(f)}</div>" for f in d.flags) + "</div>"
        for d in occ if d.key.endswith("major_occupancies"))
    sec = build_section(b, dets)
    secjson = sec.to_json()
    fig = build_figure(b)
    fig.update_layout(title=None, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
    figjson = fig.to_json()
    # plotly.min.js contains one literal U+FFFD inside a regex; the publisher
    # rejects that character, so swap it for the equivalent escape.
    plotly_src = PLOTLY_JS.read_text(encoding="utf-8").replace("\ufffd", "\\uFFFD")
    blocks_html = ""
    for blk in b.blocks():
        ff = first_storey_floor(b)
        st = [s for s in b.storeys_sorted(blk) if not s.is_roof and s.elevation_m >= ff - 0.01]
        n_above = len({s.label for s in st if not s.is_part_of})
        blocks_html += f"""
        <section class="block">
          <header><h2>{html.escape(blk)} Block</h2>
            <div class="stats">
              <div><span class="k">storeys above grade</span><span class="v mono">{n_above}</span></div>
              <div><span class="k">building area</span><span class="v mono">{b.building_area_m2(blk):,.0f} m²</span></div>
              <div><span class="k">sprinklered</span><span class="v">{'yes' if b.is_sprinklered else 'no'}</span></div>
            </div></header>
          <div class="tscroll"><table>
            <thead><tr><th>Level</th><th>FFL (m)</th><th>Footprint m²</th><th>Grade</th><th>Uses</th></tr></thead>
            <tbody>{storey_rows(b, blk)}</tbody></table></div>
        </section>"""
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in b.notes)
    legend = "".join(f"<span class='sw'><i style='background:{c}'></i>{'Group '+k if k else 'Unclassified'}</span>"
                     for k, c in OCC_COLOUR.items() if k in {"C", "A2", "F3", None})

    page = f"""<title>{html.escape(b.project_name)} Massing</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{
  --paper:#f5f4ef; --sheet:#ffffff; --ink:#1e2126; --ink-2:#4b5563; --muted:#7a8291; --rule:#d9d8d1;
  --mark:#c8352b; --mark-soft:#fbe9e7; --above:#e3eefc; --above-ink:#1d4f9c; --below:#e9ece6; --below-ink:#4d5a45;
  --shadow:0 1px 2px rgba(20,25,35,.06),0 8px 24px -12px rgba(20,25,35,.18);
}}
@media (prefers-color-scheme: dark){{ :root:not([data-theme="light"]){{
  --paper:#14171c; --sheet:#1b1f26; --ink:#e7e9ee; --ink-2:#b4bac6; --muted:#8a92a1; --rule:#2c323c;
  --mark:#e8695f; --mark-soft:#3a2321; --above:#1f2f4a; --above-ink:#9ec0f5; --below:#262b25; --below-ink:#b9c7ad;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6);
}}}}
:root[data-theme="dark"]{{
  --paper:#14171c; --sheet:#1b1f26; --ink:#e7e9ee; --ink-2:#b4bac6; --muted:#8a92a1; --rule:#2c323c;
  --mark:#e8695f; --mark-soft:#3a2321; --above:#1f2f4a; --above-ink:#9ec0f5; --below:#262b25; --below-ink:#b9c7ad;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6);
}}
*{{box-sizing:border-box}}
body{{background:var(--paper);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:14px;line-height:1.45;
  padding-inline:16px;padding-block:16px 40px;max-width:1240px;margin:0 auto}}
.mono{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}}
h1,h2,h3{{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",system-ui,sans-serif;text-wrap:balance;margin:0}}
/* title block */
.tb{{display:grid;grid-template-columns:1fr auto;gap:12px 24px;border:1.5px solid var(--ink);background:var(--sheet);padding:14px 18px;box-shadow:var(--shadow)}}
.tb h1{{font-size:26px;font-weight:600;letter-spacing:-.01em;line-height:1.1}}
.tb .sub{{color:var(--ink-2);margin-top:2px}}
.tb .meta{{display:grid;grid-template-columns:repeat(3,auto);gap:4px 20px;align-content:center}}
.tb .meta span{{display:block}} .tb .meta .k{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}
.tb .meta .v{{font-weight:500}}
.sheetno{{font-family:"IBM Plex Sans Condensed",sans-serif;font-weight:600;font-size:18px;color:var(--mark);border:1.5px solid var(--mark);padding:2px 10px;justify-self:end;align-self:start}}
/* viewer */
.viewer{{margin-top:16px;background:var(--sheet);border:1px solid var(--rule);box-shadow:var(--shadow)}}
.viewer .bar{{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--rule)}}
.viewer .bar h2{{font-size:15px;font-weight:600;margin-right:auto}}
.sw{{display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);font-size:13px}} .sw i{{width:12px;height:12px;display:inline-block;border-radius:2px}}
#plot{{width:100%;height:min(68vh,640px);min-height:360px}}
.hint{{padding:8px 14px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--rule)}}
/* rail */
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}}
@media (max-width:820px){{.grid{{grid-template-columns:1fr}} .tb{{grid-template-columns:1fr}} .sheetno{{justify-self:start}}}}
.block,.faces,.notes{{background:var(--sheet);border:1px solid var(--rule);padding:14px 16px}}
.block header{{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:baseline;margin-bottom:10px}}
.block h2,.faces h2,.notes h2{{font-size:17px;font-weight:600}}
.stats{{display:flex;gap:18px;flex-wrap:wrap;margin-left:auto}} .stats .k{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} .stats .v{{font-weight:500}}
.tscroll{{overflow-x:auto}} details{{margin-top:8px}} summary{{cursor:pointer;color:var(--above-ink);font-weight:500}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th{{text-align:left;font-weight:500;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:6px 8px;border-bottom:1px solid var(--rule)}}
td{{padding:6px 8px;border-bottom:1px solid var(--rule);vertical-align:top}} tr:last-child td{{border-bottom:0}}
td.uses,td.src{{color:var(--ink-2);font-size:12.5px;min-width:180px}}
.tag{{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;white-space:nowrap}}
.tag.above{{background:var(--above);color:var(--above-ink)}} .tag.below{{background:var(--below);color:var(--below-ink)}} .tag.roof{{background:var(--rule);color:var(--ink-2)}}
.faces{{grid-column:1/-1}}
.dets{{grid-column:1/-1;background:var(--sheet);border:1px solid var(--rule);padding:14px 16px}}
.dets h2{{font-size:17px;font-weight:600}} .dets .lede{{color:var(--ink-2);margin:4px 0 10px;max-width:70ch}}
#section{{width:100%;height:560px}} #elev{{width:100%;height:1150px}} @media (max-width:820px){{#elev{{height:1900px}}}}
td.blk{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}}
td.val{{font-weight:500;white-space:nowrap}}
.cite{{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--above-ink);background:var(--above);padding:1px 6px;border-radius:3px;margin:1px 0}}
.flagline{{color:var(--mark);margin-top:4px}}
.maj{{padding:10px 0;border-bottom:1px solid var(--rule)}} .maj:last-child{{border-bottom:0}}
.maj .k{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} .maj .v{{font-size:15px}} .maj .src{{color:var(--ink-2);font-size:12.5px;margin-top:4px;max-width:90ch}}
.ladders{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media (max-width:820px){{.ladders{{grid-template-columns:1fr}}}}
.ladder h3{{font-size:14px;font-weight:600;margin:0 0 8px;color:var(--ink-2)}}
.rung{{display:grid;grid-template-columns:78px 1fr;gap:10px;padding:10px 12px;border:1px solid var(--rule);border-left-width:4px;margin-bottom:6px;background:var(--paper)}}
.rung.gov{{border-left-color:var(--mark);background:var(--sheet);box-shadow:var(--shadow)}} .rung.q{{border-left-color:var(--above-ink)}} .rung.x{{opacity:.62}}
.rid{{font-weight:500;font-size:13px}} .rt{{font-weight:500}} .rtag{{font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-left:6px}}
.rung.gov .rtag{{color:var(--mark)}} .rreq{{color:var(--ink-2);font-size:12.5px;margin:2px 0 6px}}
.chips{{display:flex;flex-wrap:wrap;gap:4px}} .chip{{font-size:11.5px;padding:1px 7px;border-radius:999px;white-space:nowrap}}
.chip.ok{{background:var(--above);color:var(--above-ink)}} .chip.no{{background:var(--mark-soft);color:var(--mark)}}
.chip b{{font-weight:500;font-family:"IBM Plex Mono",monospace}}
.notes ul{{margin:8px 0 0;padding-left:18px;color:var(--ink-2)}} .notes li{{margin:4px 0}}
.flag{{background:var(--mark-soft);color:var(--mark);border-left:3px solid var(--mark);padding:8px 12px;margin-top:12px;font-size:13px}}
</style>

<div class="tb">
  <div>
    <h1>{html.escape(b.project_name)} — Building Model</h1>
    <div class="sub">{html.escape(b.site.address)} · {html.escape(b.site.legal_description or '')}</div>
  </div>
  <div class="sheetno">CS-01</div>
  <div class="meta">
    <div><span class="k">Project no.</span><span class="v mono">{html.escape(b.project_number or '')}</span></div>
    <div><span class="k">Permit application</span><span class="v mono">{html.escape(b.permit_application_date or '')}</span></div>
    <div><span class="k">Grade (Div. A 1.4.1.2)</span><span class="v mono">{b.site.grade_elevation_m:.2f} m</span></div>
    <div><span class="k">Blocks</span><span class="v">{' · '.join(b.blocks())} (2 h firewall, 3.1.10)</span></div>
    <div><span class="k">Streets faced</span><span class="v mono">{b.site.streets_faced}</span></div>
    <div><span class="k">Source</span><span class="v">{html.escape(b.notes[0] if b.notes else 'building model')}</span></div>
  </div>
</div>

<div class="viewer">
  <div class="bar"><h2>3D massing by dominant occupancy</h2>{legend}</div>
  <div id="plot"></div>
  <div class="hint">Drag to orbit, scroll to zoom. Hover a floor for its zones and above/below-grade status; hover a face outline for its area, opening percentage and limiting distance; the dashed line on the ground is the limiting distance. The translucent green sheet is grade.</div>
</div>

<div class="grid">
  {blocks_html}
  <section class="dets">
    <h2>Determinations · height, grade and area</h2>
    <p class="lede">The first lines of the code sheet, computed from the model. Each carries the definition or article it rests on and the reasoning a reviewer should be able to check. The section drawing shows the same result: the shaded band is the 2 m first-storey test, the red outline is the first storey, and grey storeys are basements that exist but don't count.</p>
    <div id="section"></div>
    <div class="tscroll"><table>
      <thead><tr><th>Block</th><th>Item</th><th>Value</th><th>Because</th><th>Clause</th></tr></thead>
      <tbody>{det_rows(dets)}</tbody></table></div>
  </section>
  <section class="dets">
    <h2>Determinations · occupancy</h2>
    <p class="lede">Each zone classified under Table 3.1.2.1 by deterministic keyword rules with a confidence score, then rolled up per block. A Group that occupies more than 10% of any storey is a major occupancy (3.2.2.8.(1)); the sheet must list them all.</p>
    {majors_html}
    <details><summary>Zone-by-zone classification ({sum(1 for d in occ if not d.key.endswith('major_occupancies'))} zones)</summary>
    <div class="tscroll"><table>
      <thead><tr><th>Block</th><th>Zone</th><th>Area m²</th><th>Group</th><th>Conf.</th><th>Because</th></tr></thead>
      <tbody>{occ_rows(occ)}</tbody></table></div></details>
  </section>
  <section class="dets">
    <h2>Determinations · governing 3.2.2 article</h2>
    <p class="lede">Every rung of the Group C ladder is tested against the block's storeys, height and building area. Blue rungs qualify; the red-edged rung is the one used; faded rungs fail the chips shown in red. The designer's choice is honoured when it qualifies and refused, loudly, when it doesn't.</p>
    <div class="ladders">{ladder_html(b, evals, arts)}</div>
    <div class="tscroll" style="margin-top:12px"><table>
      <thead><tr><th>Block</th><th>Item</th><th>Value</th><th>Because</th><th>Clause</th></tr></thead>
      <tbody>{det_rows([d for d in arts if d.key.split('.')[1] in ('article','req')])}</tbody></table></div>
  </section>
  <section class="dets">
    <h2>Determinations · spatial separation (3.2.3)</h2>
    <p class="lede">Each exposing face is checked storey by storey. Permitted unprotected openings come from Table 3.2.3.1.-D (sprinklered) using the band's face area and limiting distance; the wall's rating, construction and cladding follow from the <em>permitted</em> percentage via Table 3.2.3.7. In the elevations, the pale bar is the permitted share and the blue bar the actual; red would mean over. Window openings are synthesized placeholders until the elevations arrive, so the actual percentages are illustrative; the permitted percentages and wall requirements are real.</p>
    <div id="elev"></div>
    <div class="tscroll" style="margin-top:12px"><table>
      <thead><tr><th>Block</th><th>Face</th><th>LD (m)</th><th>Actual / permitted UPO by storey</th><th>Wall requirement (tightest band)</th></tr></thead>
      <tbody>{sp_table}</tbody></table></div>
  </section>
  <section class="faces">
    <h2>Exposing building faces (inputs to 3.2.3)</h2>
    <div class="tscroll"><table>
      <thead><tr><th>Face</th><th>L × H (m)</th><th>Area m²</th><th>Limiting dist. (m)</th><th>UPO actual</th><th>Source</th></tr></thead>
      <tbody>{face_rows(b)}</tbody></table></div>
  </section>
  <section class="notes" style="grid-column:1/-1">
    <h2>Model notes</h2>
    <ul>{notes}</ul>
    <div class="flag">Determinations so far cover height, grade, area, occupancy, the governing 3.2.2 article and spatial separation; occupancy separations (3.1.3) and the assembled sheet are still to come. Footprints are as modelled and window openings may be synthesized to match stated UPO percentages.</div>
  </section>
</div>

<script>{plotly_src}</script>
<script>
(function(){{
  const fig = {figjson};
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue('--ink').trim(), rule = css.getPropertyValue('--rule').trim(), sheet = css.getPropertyValue('--sheet').trim();
  fig.layout.font = {{color: ink, family: '"IBM Plex Sans", system-ui, sans-serif'}};
  fig.layout.paper_bgcolor = 'rgba(0,0,0,0)';
  for (const ax of ['xaxis','yaxis','zaxis']) {{ fig.layout.scene[ax].gridcolor = rule; fig.layout.scene[ax].zerolinecolor = rule; fig.layout.scene[ax].color = ink; }}
  fig.layout.hoverlabel = {{bgcolor: sheet, bordercolor: rule, font: {{color: ink, family: '"IBM Plex Mono", monospace', size: 12}}}};
  Plotly.newPlot('plot', fig.data, fig.layout, {{responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage']}});
  const sec = {secjson};
  sec.layout.font = {{color: ink, family: '"IBM Plex Sans", system-ui, sans-serif'}};
  sec.layout.height = undefined;
  for (const k of Object.keys(sec.layout)) if (k.startsWith('yaxis')) sec.layout[k].gridcolor = rule;
  for (const a of (sec.layout.annotations||[])) if (a.bgcolor) {{ a.bgcolor = sheet; a.bordercolor = rule; }}
  Plotly.newPlot('section', sec.data, sec.layout, {{responsive: true, displaylogo: false, staticPlot: true}});
  const el = {elevjson};
  el.layout.font = {{color: ink, family: '"IBM Plex Sans", system-ui, sans-serif'}}; el.layout.height = undefined;
  for (const k of Object.keys(el.layout)) if (k.startsWith('yaxis')) el.layout[k].color = ink;
  Plotly.newPlot('elev', el.data, el.layout, {{responsive: true, displaylogo: false, staticPlot: true}});
}})();
</script>
"""
    out.write_text(page, encoding="utf-8")
    print("wrote", out, f"{out.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    from courtyard_commons import project
    render(project, ROOT / "out" / "example_massing_artifact.html")
