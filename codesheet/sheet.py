"""
codesheet.sheet — piece 9: assemble the determinations into a code analysis sheet.

run_all()      runs every rule module in dependency order and returns the
               determinations grouped into the sections a code sheet uses.
render_html()  lays them out as an A3 landscape sheet: title block, numbered
               sections, one line per determination with its value and clause,
               a reviewer-flags panel, and an honest "not covered" panel.
               Clause references are links to `<edition>.pdf#page=N`, so if
               the bylaw PDF sits beside the sheet, clicking opens the page.
The same SheetData becomes an Excel workbook with codesheet.xlsx_sheet.to_xlsx().

The sheet is a DRAFT for a registered professional's review. It says so.
"""
from __future__ import annotations

import html, pathlib, datetime
from dataclasses import dataclass, field
from typing import Optional

from codesheet.model import BuildingModel
from codesheet.determinations import Determination, Bylaw
from codesheet import height_area, occupancy, articles, spatial, separations, targets

ROOT = pathlib.Path(__file__).resolve().parents[1]
PDF_NAME = {"vbbl-2025": "vbbl-2025-vol1.pdf", "bcbc-2024": "bcbc-2024-rev2.pdf"}


@dataclass
class Section:
    number: str
    title: str
    dets: list[Determination]
    note: str = ""


@dataclass
class SheetData:
    building: BuildingModel
    sections: list[Section]
    flags: list[tuple[str, str]] = field(default_factory=list)      # (where, text)
    not_covered: list[str] = field(default_factory=list)


NOT_COVERED = [
    "Egress LAYOUT: exit locations, dead ends, door swings, access to exit (3.3, 3.4.2.3–.4) — only the targets (count, travel limit, width) are computed",
    "Washroom accessibility layout (3.8.3) — only fixture counts are computed",
    "Fire alarm, standpipe and sprinkler design requirements (3.2.4, 3.2.5)",
    "Firefighting access routes and street-facing perimeter (3.2.5.4–.5, 3.2.2.10.(3))",
    "High building provisions (3.2.6) — applicability check only",
    "Interior finishes, fire blocks, concealed spaces (3.1.5, 3.1.11–.12)",
    "Encapsulation and mass-timber-specific limits (3.1.6, 3.2.2.93)",
    "Alternative Solutions — listed from the model notes, not evaluated",
    "Energy (VBBL Book I Part 10) and accessibility (3.8)",
]


def run_all(b: BuildingModel, chosen: Optional[dict[str, str]] = None, edition: str = "vbbl-2025") -> SheetData:
    law = Bylaw(edition)
    hd = height_area.analyze(b, law)
    od = occupancy.analyze(b, law)
    ad = articles.analyze(b, hd, od, law, chosen=chosen)
    groups = {d.block: (d.value[0] if d.value else "C") for d in od if d.key.endswith("major_occupancies")}
    sp, _bands = spatial.analyze(b, law, groups)
    sd = separations.analyze(b, ad, law)
    td, _targets = targets.analyze(b, hd, law)

    majors = [d for d in od if d.key.endswith("major_occupancies")]
    zones = [d for d in od if not d.key.endswith("major_occupancies")]
    art_main = [d for d in ad if d.key.split(".")[1] in ("article_candidates", "article")]
    art_req = [d for d in ad if d.key.split(".")[1] == "req"]
    sp_summary = [d for d in sp if d.key.endswith("summary")]
    sp_bands = [d for d in sp if not d.key.endswith("summary")]
    ol_lines = [d for d in td if d.key.endswith("occupant_load") or d.key.endswith("occupant_load_total")]
    eg_lines = [d for d in td if d.key.split(".")[-1] == "egress"]
    wc_lines = [d for d in td if d.key.split(".")[-1] in ("washrooms", "gender_neutral_wc")]
    ol_rows = []
    for d in ol_lines:
        for r in d.inputs.get("rows", []):
            basis = (f"{r['area']:g} m²" + (f" − {r['deduction_pct']:g}% = {r['net_area']:g} m²" if r['deduction_pct'] else "")
                     + (f" ÷ {r['factor']:g} m²/person ({r['row']})" if r['factor'] else f" — {r['basis']}")
                     + (f"; gross {r['gross']}" if r['gross'] != r['net_load'] else ""))
            ol_rows.append(Determination(key=d.key + "." + r["zone"], label=f"{d.label.split('— ')[-1]} — {r['zone']}", value=r["net_load"], unit="persons",
                                         block=d.block, clauses=d.clauses, because=basis))

    sections = [
        Section("1", "Building classification — major occupancies", majors, "Per block. Zone-level classification in Appendix A."),
        Section("2", "Grade, first storey, building height and area", hd),
        Section("3", "Governing article, Subsection 3.2.2", art_main),
        Section("4", "Construction and fire-resistance ratings required by the governing article", art_req),
        Section("5", "Fire separations between major occupancies (3.1.3)", sd),
        Section("6", "Spatial separation — exposing building faces (3.2.3)", sp_summary, "Per-band detail in Appendix B."),
        Section("7", "Occupant load (3.1.17, Table 3.1.17.1)", ol_lines, "Designed (net) load shown; gross in the reasoning. Row detail in Appendix C."),
        Section("8", "Egress targets — exits, travel distance, exit width (3.4.2, 3.4.3)", eg_lines, "Targets for the plan, not a check of it."),
        Section("9", "Washroom fixture targets (3.7.2, incl. VBBL 3.7.2.9)", wc_lines),
        Section("A", "Appendix A — zone classification (Table 3.1.2.1)", zones),
        Section("B", "Appendix B — spatial separation by storey band", sp_bands),
        Section("C", "Appendix C — occupant load by area (Table 3.1.17.1)", ol_rows),
    ]
    raw = [(f"{s.number}. {d.label}" + (f" [{d.block}]" if d.block else ""), f) for s in sections for d in s.dets for f in d.flags]
    # collapse identical flag texts (e.g. the same placeholder warning on 24 bands) into one line with a count
    seen: dict[str, list[str]] = {}
    for where, text in raw:
        seen.setdefault(text, []).append(where)
    flags = []
    for text, wheres in seen.items():
        where = wheres[0] if len(wheres) == 1 else f"{wheres[0].split('.')[0]}. ×{len(wheres)} lines"
        flags.append((where, text))
    return SheetData(b, sections, flags, NOT_COVERED)


# ---------------------------------------------------------------------------

def _val(d: Determination) -> str:
    if isinstance(d.value, list):
        return ", ".join(str(v) for v in d.value) or "—"
    return d.display() if d.value is not None else "—"


def _cite(d: Determination, edition: str) -> str:
    pdf = PDF_NAME.get(edition, "")
    out = []
    for c in d.clauses:
        txt = c.id + (f".({c.sentence})" if c.sentence else "")
        href = f"{pdf}#page={c.page}" if c.page and pdf else None
        pg = f" p.{c.page}" if c.page else ""
        out.append(f"<a href='{href}' title='{html.escape(c.edition)}'>{html.escape(txt)}{pg}</a>" if href else html.escape(txt + pg))
    return "<br>".join(out)


def render_html(sd: SheetData, edition: str = "vbbl-2025", sheet_no: str = "A0.01", revision: str = "Draft") -> str:
    b = sd.building
    law = Bylaw(edition)
    today = datetime.date.today().isoformat()

    def section_html(s: Section) -> str:
        rows = []
        for d in s.dets:
            flag_marks = "".join("<sup class='fl'>⚠</sup>" for _ in d.flags[:1])
            rows.append(
                f"<tr><td class='blk'>{html.escape(d.block or '')}</td><td class='lab'>{html.escape(d.label)}{flag_marks}</td>"
                f"<td class='val'>{html.escape(_val(d))}</td><td class='why'>{html.escape(d.because)}</td><td class='ref'>{_cite(d, edition)}</td></tr>")
        note = f"<div class='snote'>{html.escape(s.note)}</div>" if s.note else ""
        return (f"<section class='sec'><h2><span class='n'>{s.number}</span>{html.escape(s.title)}</h2>{note}"
                f"<table><colgroup><col class='c-blk'><col class='c-lab'><col class='c-val'><col class='c-why'><col class='c-ref'></colgroup><thead><tr><th>Block</th><th>Item</th><th>Value</th><th>Basis</th><th>Clause</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>")

    body_secs = [s for s in sd.sections if not s.number.startswith(("A", "B", "C"))]
    col1 = "".join(section_html(s) for s in body_secs if s.number in ("1", "2", "7"))
    col2 = "".join(section_html(s) for s in body_secs if s.number not in ("1", "2", "7"))
    appx = "".join(section_html(s) for s in sd.sections if s.number.startswith(("A", "B", "C")))
    flags = "".join(f"<li><span class='where'>{html.escape(w)}</span> {html.escape(t)}</li>" for w, t in sd.flags)
    ncov = "".join(f"<li>{html.escape(t)}</li>" for t in sd.not_covered)
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in b.notes)
    blocks = " · ".join(b.blocks())

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(b.project_name)} — Code Analysis {sheet_no}</title>
<style>
@page {{ size: A3 landscape; margin: 10mm; }}
:root{{--ink:#1e2126;--ink2:#4b5563;--mut:#7a8291;--rule:#c9cbd0;--mark:#c8352b;--soft:#f3f4f6;--link:#1d4f9c}}
*{{box-sizing:border-box}} body{{margin:0;font:9.2pt/1.32 "IBM Plex Sans","Helvetica Neue",Arial,sans-serif;color:var(--ink);background:#fff}}
.sheet{{width:400mm;margin:0 auto;border:1.2pt solid var(--ink);padding:5mm}}
.tb{{display:grid;grid-template-columns:1fr auto auto;gap:6mm;border-bottom:1.2pt solid var(--ink);padding-bottom:3mm;align-items:end}}
.tb h1{{margin:0;font-size:17pt;letter-spacing:-.01em}} .tb .sub{{color:var(--ink2)}}
.meta{{display:grid;grid-template-columns:repeat(4,auto);gap:1mm 6mm;font-size:8.3pt}} .meta .k{{color:var(--mut);text-transform:uppercase;letter-spacing:.06em;font-size:6.8pt;display:block}}
.stamp{{border:1.2pt solid var(--mark);color:var(--mark);padding:2mm 4mm;text-align:center;font-weight:600}} .stamp small{{display:block;font-weight:400;font-size:7pt}}
.cols{{display:grid;grid-template-columns:1fr 1fr 0.72fr;gap:5mm;align-items:start;margin-top:4mm}}
.sec{{margin-bottom:3.5mm}} tr{{break-inside:avoid}} .sec h2{{font-size:9.6pt;margin:0 0 1mm;display:flex;gap:2mm;align-items:baseline}}
.sec h2 .n{{background:var(--ink);color:#fff;font-size:7.5pt;padding:0 1.6mm;border-radius:1px}} .snote{{color:var(--mut);font-size:7.6pt;margin-bottom:1mm}}
table{{width:100%;border-collapse:collapse;font-size:7.7pt;table-layout:fixed}}
col.c-blk{{width:7%}} col.c-lab{{width:19%}} col.c-val{{width:15%}} col.c-why{{width:43%}} col.c-ref{{width:16%}} th{{text-align:left;font-weight:500;color:var(--mut);font-size:6.6pt;text-transform:uppercase;letter-spacing:.06em;border-bottom:.6pt solid var(--ink);padding:.6mm 1mm}}
td{{padding:.9mm 1mm;border-bottom:.4pt solid var(--rule);vertical-align:top}}
td.blk{{color:var(--mut);font-size:6.6pt;text-transform:uppercase;white-space:nowrap}} td.lab{{font-weight:500}} td.val{{font-family:"IBM Plex Mono",Menlo,monospace;font-size:7.4pt;font-weight:500;overflow-wrap:anywhere}}
td.why{{color:var(--ink2);font-size:7pt}} td.ref{{font-family:"IBM Plex Mono",Menlo,monospace;font-size:6.8pt;overflow-wrap:anywhere}} td.ref a{{color:var(--link);text-decoration:none}}
sup.fl{{color:var(--mark);font-size:7pt;margin-left:1px}}
.panel{{border:.8pt solid var(--ink);padding:2.5mm 3mm;margin-bottom:3.5mm;background:var(--soft)}} .panel h3{{margin:0 0 1.5mm;font-size:8.6pt}}
.panel ul{{margin:0;padding-left:4mm;font-size:7.3pt}} .panel li{{margin:.6mm 0}} .where{{color:var(--mut);font-family:"IBM Plex Mono",monospace;font-size:6.6pt}}
.panel.flags{{border-color:var(--mark)}} .panel.flags h3{{color:var(--mark)}}
.appx{{margin-top:2mm;border-top:1.2pt solid var(--ink);padding-top:3mm;columns:2;column-gap:5mm}} .appx .sec{{break-inside:auto;page-break-inside:auto}} .appx tr{{break-inside:avoid}}
.foot{{display:flex;justify-content:space-between;border-top:1.2pt solid var(--ink);padding-top:2mm;margin-top:3mm;font-size:7pt;color:var(--ink2)}}
@media print{{ .sheet{{border:none;padding:0;width:auto}} }}
</style></head><body>
<div class="sheet">
  <header class="tb">
    <div><h1>{html.escape(b.project_name)} — Building Code Analysis</h1>
      <div class="sub">{html.escape(b.site.address)} · {html.escape(b.site.legal_description or '')}</div></div>
    <div class="meta">
      <div><span class="k">Applicable code</span>{html.escape(law.edition)}</div>
      <div><span class="k">Project no.</span>{html.escape(b.project_number or '—')}</div>
      <div><span class="k">Permit application</span>{html.escape(b.permit_application_date or '—')}</div>
      <div><span class="k">Blocks (firewall-separated)</span>{html.escape(blocks)}</div>
      <div><span class="k">Sprinklered</span>{'yes — throughout' if b.is_sprinklered else 'no'}</div>
      <div><span class="k">Streets faced</span>{b.site.streets_faced}</div>
      <div><span class="k">Generated</span>{today}</div>
      <div><span class="k">Sheet</span>{html.escape(sheet_no)} · {html.escape(revision)}</div>
    </div>
    <div class="stamp">DRAFT — FOR REVIEW<small>Generated by rules; every line cites its clause.<br>Not a compliance determination. To be reviewed and sealed by the Coordinating Registered Professional.</small></div>
  </header>
  <div class="cols">
    <div>{col1}</div>
    <div>{col2}</div>
    <div>
      <div class="panel flags"><h3>Reviewer flags ({len(sd.flags)})</h3><ul>{flags}</ul></div>
      <div class="panel"><h3>Model notes</h3><ul>{notes}</ul></div>
      <div class="panel"><h3>Not covered by this draft</h3><ul>{ncov}</ul></div>
    </div>
  </div>
  <div class="appx">{appx}</div>
  <footer class="foot"><span>Clause references link to {html.escape(PDF_NAME.get(edition,''))} at the cited page when the PDF is stored beside this sheet.</span><span>codesheet v0.7 — draft generator</span></footer>
</div></body></html>"""


if __name__ == "__main__":
    import sys
    sys.path[:0] = [str(ROOT), str(ROOT / "data" / "projects")]
    from courtyard_commons import project
    from codesheet.xlsx_sheet import to_xlsx
    sd = run_all(project, chosen={"North": "3.2.2.51", "South": "3.2.2.51"})
    out = ROOT / "out" / "example_code_sheet.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render_html(sd), encoding="utf-8")
    to_xlsx(sd, ROOT / "out" / "example_code_sheet.xlsx")
    print("wrote", out, "and .xlsx;", sum(len(s.dets) for s in sd.sections), "lines,", len(sd.flags), "flags")
