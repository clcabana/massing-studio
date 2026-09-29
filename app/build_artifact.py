"""
Build the self-contained, server-less versions of Massing Studio from the local
app's sources: engine.js + engine_data.json inlined, server calls replaced by
the in-page engine, the Rhino link and parcel map removed (they need the local
server), the iteration library kept in the browser.

Two targets share this code:

    PYTHONPATH=. python app/build_artifact.py   →  out/massing_studio_artifact.html
        the Claude artifact: no document skeleton (the publisher wraps the page),
        three.js from cdnjs, iteration library on the artifact `db` capability
        with a localStorage fallback

    PYTHONPATH=. python app/build_pages.py      →  out/site/index.html (+ vendor/)
        the GitHub Pages site: a complete HTML document, three.js self-hosted,
        iteration library in localStorage
"""
from __future__ import annotations
import json, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from app.server import presets, example_demo   # noqa: E402

STATIC = ROOT / "app" / "static"


def cut(src: str, start_marker: str, end_marker: str, replacement: str) -> str:
    a = src.index(start_marker); b = src.index(end_marker) + len(end_marker)
    return src[:a] + replacement + src[b:]


# ---- the in-browser iteration library --------------------------------------------------
# `claude.use("db")` exists only inside a published Claude artifact; everywhere else the
# library falls back to localStorage. @@LIB_FALLBACK@@ is the wording shown in that case.
LIBRARY_JS = r'''// library (artifact db when available, localStorage otherwise)
const Library = {
  db: null, ready: null, mem: [],
  key: "massing-studio-iterations",
  ls(){ try{ return JSON.parse(localStorage.getItem(this.key)||"[]"); }catch(e){ return this.mem; } },
  lsSet(all){ try{ localStorage.setItem(this.key,JSON.stringify(all)); }catch(e){ this.mem=all; } },
  async list(){ await this.ready; if(this.db){ try{ const snap=await this.db.collection("iterations").orderBy("saved","desc").limit(200).get(); return snap.docs.map(d=>({id:d.id,...d.data()})); }catch(e){ console.warn(e); } }
    return this.ls().slice().sort((a,b)=>b.saved.localeCompare(a.saved)); },
  async save(rec){ await this.ready; if(this.db){ try{ const ref=this.db.collection("iterations").doc(); await ref.set(rec); return ref.id; }catch(e){ console.warn("db save failed, using localStorage",e); } }
    const all=this.ls().slice(); const id=Date.now().toString(36); all.push({id,...rec}); this.lsSet(all); return id; },
  async get(id){ await this.ready; if(this.db){ try{ const s=await this.db.doc("iterations/"+id).get(); if(s.exists) return {id,...s.data()}; }catch(e){} } return this.ls().find(x=>x.id===id)||null; },
  async remove(id){ await this.ready; if(this.db){ try{ await this.db.doc("iterations/"+id).delete(); }catch(e){} } this.lsSet(this.ls().filter(x=>x.id!==id)); },
};
Library.ready=(async()=>{ try{ Library.db = (window.claude && claude.use) ? await claude.use("db") : null; }catch(e){ Library.db=null; } })();
async function loadLib(){ const items=await Library.list(); const where=Library.db?"shared with everyone who can open this artifact":"@@LIB_FALLBACK@@";
  $("#libWhere").textContent=where;
  $("#libList").innerHTML=items.map(it=>`<div class="it ${compareSel.includes(it.id)?"cmp":""}" data-id="${it.id}">${it.thumb?`<img src="${it.thumb}">`:"<div></div>"}<div><div class="nm">${esc(it.name)}</div><div class="sub">${esc(it.project||"")} · ${(it.saved||"").replace("T"," ").slice(0,16)} · ${Object.entries(it.summary||{}).map(([b,s])=>`${b}: ${s.storeys} st, ${fmt(s.area)} m², ${s.article||"—"}`).join(" · ")} · ${it.flags} flags</div></div><div><button class="sm sum" data-id="${it.id}">Summary</button> <button class="sm del" data-id="${it.id}" title="delete">×</button></div></div>`).join("")||"<div class='hint'>Nothing saved yet.</div>";
  document.querySelectorAll(".lib .it").forEach(el=>el.onclick=async ev=>{ if(ev.target.closest("button")) return; const id=el.dataset.id;
    if(ev.shiftKey){ compareSel=compareSel.includes(id)?compareSel.filter(x=>x!==id):[...compareSel,id].slice(-3); $("#btnCompare").disabled=compareSel.length<2; loadLib(); return; }
    const d=await Library.get(id); if(!d) return; spec=normalize(d.spec); sel=0; editStorey=null; changed(true); });
  document.querySelectorAll(".lib .del").forEach(el=>el.onclick=async ev=>{ ev.stopPropagation(); if(confirm("Delete this saved iteration?")){ await Library.remove(el.dataset.id); compareSel=compareSel.filter(x=>x!==el.dataset.id); loadLib(); } });
  document.querySelectorAll(".lib .sum").forEach(el=>el.onclick=async ev=>{ ev.stopPropagation(); const d=await Library.get(el.dataset.id); if(d) showSummary(d.spec, await apiAnalyze(d.spec), d.name); });
  $("#btnCompare").disabled=compareSel.length<2;
}
$("#btnSave").onclick=()=>{ $("#svName").value=""; $("#svNote").value=""; $("#dlgSave").showModal(); };
$("#dlgSave").addEventListener("close",async()=>{ if($("#dlgSave").returnValue!=="ok") return; render3d();
  let thumb=null; try{ if(renderer){ const c2=document.createElement("canvas"); c2.width=240; c2.height=150; c2.getContext("2d").drawImage(canvas,0,0,240,150); thumb=c2.toDataURL("image/jpeg",0.7); } }catch(e){}
  const r=results||await apiAnalyze(spec);
  const rec={name:$("#svName").value||"Untitled", note:$("#svNote").value||"", project:spec.project_name, saved:new Date().toISOString(), spec:JSON.parse(JSON.stringify(spec)), summary:r.summary, headroom:r.headroom, targets:Object.fromEntries(Object.entries(r.targets||{}).map(([k,v])=>[k,k==="_site"?v:{total:v.total,egress:v.egress,gender_neutral:v.gender_neutral}])), flags:r.flags.length, thumb};
  $("#status").textContent="saving…"; $("#status").className="status busy"; const id=await Library.save(rec); $("#status").textContent=id?"saved":"save failed"; $("#status").className="status"; loadLib(); });
$("#btnCompare").onclick=async()=>{ const rows=(await Promise.all(compareSel.map(id=>Library.get(id)))).filter(Boolean);
  const blocks=[...new Set(rows.flatMap(r=>Object.keys(r.summary||{})))];
  let h=`<table class="cmp"><tr><th>Iteration</th>${blocks.map(b=>`<th>${esc(b)}</th>`).join("")}<th>Flags</th></tr>`;
  for(const r of rows){ h+=`<tr><td><b>${esc(r.name)}</b><br><span class="sub">${esc(r.note||"")}</span></td>${blocks.map(b=>{const s=(r.summary||{})[b]; if(!s) return "<td>—</td>"; const hr=((r.headroom||{})[b]||{}).items||[]; const a=hr.find(i=>i.what==="building area"); const tg=((r.targets||{})[b]); return `<td class="mono">${s.storeys} st · ${fmt(s.area)} m²<br>${s.article||"—"}<br>${a?`${fmt(a.headroom)} m² headroom`:""}${tg?`<br>${fmt(tg.total.net)} p. · ${tg.egress?tg.egress.exits+" stairs @ "+tg.egress.stair_each_mm+" mm":""}`:""}</td>`;}).join("")}<td>${r.flags}</td></tr>`; }
  $("#cmp").innerHTML=h+"</table>"; };'''

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600'
         '&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Mono:wght@400;500&display=swap">')


def build_parts(lib_fallback: str) -> dict:
    """The server-less page in pieces: head CSS, body, main script, wizard, engine, data."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    wizard = (STATIC / "wizard.js").read_text(encoding="utf-8")
    engine = (STATIC / "engine.js").read_text(encoding="utf-8")
    data = (STATIC / "engine_data.json").read_text(encoding="utf-8")

    # ---- strip the document skeleton; each target adds its own -------------------
    head_css = html[html.index("<style>"):html.index("</style>") + len("</style>")]
    body = html[html.index("<header>"):html.index('<script src="/vendor/leaflet.js">')]
    scripts = html[html.index("<script>", html.index('<script src="/vendor/three.min.js">')) + len("<script>"):html.index('</script>\n<script src="/wizard.js">')]

    # ---- API: in-page engine instead of the server --------------------------------
    scripts = cut(scripts, "// @@API-START", "// @@API-END", '''// in-page engine (server-less build)
async function apiAnalyze(sp){ return CodesheetEngine.analyzeMassing(JSON.parse(JSON.stringify(sp)), ENGINE_DATA); }
async function apiExample(){ return JSON.parse(JSON.stringify(EXAMPLE)); }
const ENGINE_LABEL="VBBL 2025 · in-browser engine";''')

    # ---- library: browser-side ---------------------------------------------------------
    scripts = cut(scripts, "// @@LIBRARY-START", "// @@LIBRARY-END", LIBRARY_JS.replace("@@LIB_FALLBACK@@", lib_fallback))

    # ---- Rhino link: needs the local server ---------------------------------------------
    scripts = cut(scripts, "// @@RHINO-START", "// @@RHINO-END", "// Rhino link: local app only")
    body = re.sub(r'<div class="pane" id="rhinoPane">.*?</div>\n    </div>\n', '''<div class="pane"><h2>Rhino</h2><div class="hint">The Rhino round trip (export site.3dm → edit in Rhino → live update here) runs in the local Massing Studio app, which can read files on your disk. This published page cannot.</div></div>
''', body, flags=re.S)

    # ---- wizard: presets inline, map disabled ----------------------------------------
    wizard = wizard.replace('''async function loadPresets(){ if(!PRESETS) PRESETS = await (await fetch("/api/presets")).json(); return PRESETS; }''',
                            '''async function loadPresets(){ return PRESETS_INLINE; }''')
    wizard = wizard.replace('''      {label:"Pick a site on the map", desc:"Click a parcel on a map of Vancouver. Lot outline, street and lane edges and zoning are read from City of Vancouver Open Data.", value:"map"},''',
                            '''      {label:"Pick a site on the map — local app only", desc:"The parcel map reads City of Vancouver Open Data and map tiles, which this published page cannot reach. Run the local Massing Studio app for the map picker; here, describe the site instead.", value:"describe"},''')
    wizard = wizard.replace('''  if(a0.mode==="map"){ const lot=await mapPicker(); if(!lot) return; applyLot(lot, a0); return blockWizard(true); }''', '')
    mp_start = wizard.index("// ---------------------------------------------------------------- map picker (Leaflet)")
    mp_end = wizard.index("// ---------------------------------------------------------------- wire up")
    wizard = wizard[:mp_start] + wizard[mp_end:]
    wizard = wizard.replace('''if(!location.hash.includes("nowizard")) window.addEventListener("load",()=>setTimeout(siteWizard,300));''',
                            '''setTimeout(siteWizard, 400);''')

    # ---- body tweaks ----------------------------------------------------------------------
    body = body.replace('''kept <span id="libWhere">in the project's <span class="mono">iterations/</span> folder</span>''', '''kept <span id="libWhere">…</span>''')
    body = re.sub(r'<dialog id="dlgMap">.*?</dialog>\n', '', body, flags=re.S)
    for a in ("<!doctype html>", "<html", "</html>"):
        assert a not in body
    assert "/api/" not in scripts, "server call left in the page scripts"
    assert "/api/" not in wizard, "server call left in the wizard"

    inline_data = f'''const ENGINE_DATA={data};
const PRESETS_INLINE={json.dumps(presets())};
const EXAMPLE={json.dumps(example_demo())};'''
    return {"head_css": head_css, "body": body, "scripts": scripts, "wizard": wizard, "engine": engine, "inline_data": inline_data}


def artifact_page() -> str:
    """The Claude artifact: no skeleton (the publisher wraps it), three.js from cdnjs."""
    p = build_parts(lib_fallback="this browser only (shared library unavailable)")
    return f'''<title>Massing Studio</title>
{FONTS}
{p["head_css"]}
{p["body"]}
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>{p["inline_data"]}</script>
<script>{p["engine"]}</script>
<script>{p["scripts"]}</script>
<script>{p["wizard"]}</script>
'''


if __name__ == "__main__":
    out = ROOT / "out/massing_studio_artifact.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(artifact_page(), encoding="utf-8")
    print("wrote", out, f"{out.stat().st_size // 1024} KB")
