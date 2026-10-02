// wizard.js — guided setup: site (describe / pick on map / load / example) and block wizards.
// Relies on globals from index.html: spec, sel, changed(), newSpec(), loadLib(), snap(), polyArea().

let PRESETS = null;
async function loadPresets(){ if(!PRESETS) PRESETS = await (await fetch("/api/presets")).json(); return PRESETS; }

// ---------------------------------------------------------------- generic stepper
// steps: [{id, title, help, type:'choice'|'multi'|'number'|'text', options:[{label, desc, value}], default, when(answers)->bool}]
function runStepper(title, steps){
  return new Promise(resolve=>{
    const dlg=document.getElementById("dlgWiz"); const body=dlg.querySelector(".wbody"); const ttl=dlg.querySelector(".wtitle"); const prog=dlg.querySelector(".wprog");
    const answers={}; let i=0;
    const visible=()=>steps.filter(s=>!s.when||s.when(answers));
    function render(){
      const vs=visible(); if(i>=vs.length){ dlg.close(); resolve(answers); return; }
      const s=vs[i]; ttl.textContent=title; prog.textContent=`Step ${i+1} of ${vs.length}`;
      let h=`<h3>${s.title}</h3>${s.help?`<p class="whelp">${s.help}</p>`:""}`;
      if(s.type==="choice"||s.type==="multi"){
        h+=`<div class="wopts">${s.options.map((o,k)=>{const on=s.type==="multi"?(answers[s.id]||s.default||[]).includes(o.value):(answers[s.id]??s.default)===o.value; return `<label class="wopt ${on?"on":""}"><input type="${s.type==="multi"?"checkbox":"radio"}" name="${s.id}" value="${k}" ${on?"checked":""}><span class="wl">${o.label}</span>${o.desc?`<span class="wd">${o.desc}</span>`:""}</label>`;}).join("")}</div>`;
        if(s.custom) h+=`<div class="wcustom"><label>${s.custom.label}</label><input type="number" step="${s.custom.step||0.1}" id="wCustom" placeholder="${s.custom.placeholder||""}"></div>`;
      } else if(s.type==="number"){ h+=`<input type="number" id="wNum" step="${s.step||0.1}" value="${answers[s.id]??s.default??""}" style="width:160px">${s.unit?` <span class="whelp">${s.unit}</span>`:""}`; }
      else { h+=`<input type="text" id="wTxt" value="${answers[s.id]??s.default??""}" style="width:100%">`; }
      body.innerHTML=h;
      dlg.querySelector(".wback").disabled=i===0;
      dlg.querySelector(".wnext").textContent=i===vs.length-1?"Finish":"Next";
      body.querySelectorAll(".wopt input").forEach(inp=>inp.onchange=()=>{ body.querySelectorAll(".wopt").forEach(l=>l.classList.toggle("on",l.querySelector("input").checked)); if(s.type==="choice"&&!s.custom){ collect(s); i++; render(); } });
    }
    function collect(s){
      if(s.type==="choice"){ const c=document.getElementById("wCustom"); if(c&&c.value!==""){ answers[s.id]=+c.value; return; } const inp=[...document.querySelectorAll(`.wopt input[name="${s.id}"]`)].find(x=>x.checked); answers[s.id]=inp?s.options[+inp.value].value:(answers[s.id]??s.default); }
      else if(s.type==="multi"){ answers[s.id]=[...document.querySelectorAll(`.wopt input[name="${s.id}"]`)].filter(x=>x.checked).map(x=>s.options[+x.value].value); }
      else if(s.type==="number"){ answers[s.id]=+document.getElementById("wNum").value; }
      else { answers[s.id]=document.getElementById("wTxt").value; }
    }
    dlg.querySelector(".wnext").onclick=()=>{ const vs=visible(); collect(vs[i]); i++; render(); };
    dlg.querySelector(".wback").onclick=()=>{ if(i>0){ i--; render(); } };
    dlg.querySelector(".wcancel").onclick=()=>{ dlg.close(); resolve(null); };
    if(!dlg.open) dlg.showModal(); render();
  });
}

// ---------------------------------------------------------------- site wizard
async function siteWizard(){
  const P=await loadPresets();
  const a0=await runStepper("Set up the site",[
    {id:"mode", title:"How do you want to start?", type:"choice", options:[
      {label:"Pick a site on the map", desc:"Click a parcel on a map of Vancouver. Lot outline, street and lane edges, zoning, the neighbouring buildings with their heights, the street trees and the street names are read from City of Vancouver Open Data.", value:"map"},
      {label:"Describe the site", desc:"Answer a few questions: frontage, depth, which edges face a street or lane, grade.", value:"describe"},
      {label:"Load a saved iteration", desc:"Reopen a massing from the library.", value:"load"},
      {label:"Worked example", desc:"Courtyard Commons, a synthetic two-block project with an assembly ground floor, as a massing.", value:"example"}]}]);
  if(!a0) return;
  if(a0.mode==="example"){ document.getElementById("btnExample").click(); return; }
  if(a0.mode==="load"){ return; }                     // library is visible on the right
  if(a0.mode==="map"){ const lot=await mapPicker(); if(!lot) return; applyLot(lot, a0); return blockWizard(true); }

  const a=await runStepper("Describe the site",[
    {id:"frontage", title:"Lot frontage (east–west width)", type:"choice", options:Object.entries(P.frontages_m).map(([k,v])=>({label:k, desc:`${v} m`, value:v})), custom:{label:"or enter metres", step:0.01}},
    {id:"depth", title:"Lot depth (north–south)", type:"choice", options:Object.entries(P.depths_m).map(([k,v])=>({label:k, desc:`${v} m`, value:v})), custom:{label:"or enter metres", step:0.01}},
    {id:"streets", title:"Which edges face a street?", help:"The front is drawn at the bottom (south). A corner lot has two.", type:"multi", default:["south"], options:[
      {label:"Front (south)", value:"south"},{label:"Left side (west)", value:"west"},{label:"Right side (east)", value:"east"},{label:"Rear (north)", value:"north"}]},
    {id:"frontRow", title:"Right-of-way width of the front street", help:"Limiting distance is measured to the street centreline, so this matters for the front face.", type:"choice", default:20,
      options:Object.entries(P.row_widths).filter(([k])=>k!=="lane").map(([k,v])=>({label:k, desc:`${v} m`, value:v})), custom:{label:"or enter metres", step:0.5}},
    {id:"lane", title:"Is there a lane at the rear?", type:"choice", default:"yes", options:[{label:"Yes — 6 m lane", value:"yes"},{label:"No — rear neighbour", value:"no"}], when:x=>!(x.streets||[]).includes("north")},
    {id:"grade", title:"Grade elevation", help:"Lowest average finished ground level adjoining the walls (Div. A). Any datum is fine; storeys are counted from it.", type:"number", default:10, unit:"m"},
    {id:"spr", title:"Sprinklered throughout?", help:"VBBL 3.2.2.18.(3) requires sprinklers in all new buildings; choose no only for an existing-building study.", type:"choice", default:"yes", options:[{label:"Yes", value:"yes"},{label:"No", value:"no"}]},
    {id:"name", title:"Project name", type:"text", default:"New site"},
  ]);
  if(!a) return;
  spec=newSpec(); spec.blocks=[]; spec.project_name=a.name||"New site"; spec.sprinklered=a.spr!=="no";
  spec.lot={width_m:a.frontage, depth_m:a.depth, grade_m:a.grade, polygon:null, edge_kinds:null, source:"described",
    edges:{south:{kind:"neighbour",row_width_m:0},north:{kind:"neighbour",row_width_m:0},east:{kind:"neighbour",row_width_m:0},west:{kind:"neighbour",row_width_m:0}}};
  for(const s of a.streets||[]) spec.lot.edges[s]={kind:"street", row_width_m: s==="south"?a.frontRow:20};
  if(a.lane==="yes" && !(a.streets||[]).includes("north")) spec.lot.edges.north={kind:"lane", row_width_m:6};
  sel=0; changed(true);
  return blockWizard(true);
}

function applyLot(lotResp, a0){
  spec=newSpec(); spec.blocks=[]; spec.lot=lotResp.lot; spec.project_name=lotResp.lot.address||"Picked site";
  // site context in the lot's frame: neighbours (with heights), public trees, street names
  spec.context=lotResp.context||[]; spec.trees=lotResp.trees||[]; spec.streets=lotResp.streets||[];
  if(lotResp.context_warning) toast(lotResp.context_warning);
  else if(spec.context.length||spec.trees.length) toast(`${spec.context.length} neighbouring buildings, ${spec.trees.length} trees and ${new Set(spec.streets.map(s=>s.name)).size} street names loaded`);
  if(!spec.lot.edges) spec.lot.edges={south:{kind:"neighbour",row_width_m:0},north:{kind:"neighbour",row_width_m:0},east:{kind:"neighbour",row_width_m:0},west:{kind:"neighbour",row_width_m:0}};
  sel=0; changed(true);
}

// ---------------------------------------------------------------- block wizard
function lotBoundary(){ const L=spec.lot; if(L.polygon){ const k=L.edge_kinds||[]; return L.polygon.map((p,i)=>({a:p,b:L.polygon[(i+1)%L.polygon.length],kind:(k[i]||{kind:"neighbour"}).kind})); }
  const W=L.width_m,D=L.depth_m,E=L.edges; return [{a:[0,0],b:[W,0],kind:E.south.kind},{a:[W,0],b:[W,D],kind:E.east.kind},{a:[W,D],b:[0,D],kind:E.north.kind},{a:[0,D],b:[0,0],kind:E.west.kind}]; }
function edgeExposure(fp,i){ // client-side twin of massing._edge_exposure (kind only)
  const a=fp[i], b=fp[(i+1)%fp.length]; const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2; const ux=b[0]-a[0],uy=b[1]-a[1]; const L=Math.hypot(ux,uy)||1; let nx=uy/L,ny=-ux/L;
  // ensure CCW-outward: if polygon is CW flip
  let s=0; for(let k=0;k<fp.length;k++){const p=fp[k],q=fp[(k+1)%fp.length]; s+=p[0]*q[1]-q[0]*p[1];} if(s<0){nx=-nx;ny=-ny;}
  let best=null; for(const seg of lotBoundary()){ const ex=seg.b[0]-seg.a[0],ey=seg.b[1]-seg.a[1]; const den=nx*ey-ny*ex; if(Math.abs(den)<1e-9) continue; const t=((seg.a[0]-mx)*ey-(seg.a[1]-my)*ex)/den; const u=((seg.a[0]-mx)*ny-(seg.a[1]-my)*nx)/den; if(t>=-1e-6&&u>=-1e-6&&u<=1+1e-6&&(best===null||t<best.t)) best={t,kind:seg.kind}; }
  return best?best.kind:"neighbour";
}
function insetBBox(front,side,rear){ const L=spec.lot; let minx=0,miny=0,maxx=L.width_m,maxy=L.depth_m; if(L.polygon){ minx=Math.min(...L.polygon.map(p=>p[0])); maxx=Math.max(...L.polygon.map(p=>p[0])); miny=Math.min(...L.polygon.map(p=>p[1])); maxy=Math.max(...L.polygon.map(p=>p[1])); }
  const r2=v=>Math.round(v*100)/100;   // snap to 1 cm here so a 10.06 m lot keeps its exact edge
  const x0=r2(Math.max(minx,minx+side)), x1=r2(Math.min(maxx,maxx-side)), y0=r2(Math.max(miny,miny+front)), y1=r2(Math.min(maxy,maxy-rear)); return [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]; }

async function blockWizard(first){
  const P=await loadPresets();
  const a=await runStepper(first?"Add the first block":"Add a block",[
    {id:"type", title:"What kind of building is this block?", type:"choice", options:P.types.map(t=>({label:t.label, desc:`ground: ${t.ground.use} (${t.ground.occupancy}) · above: ${t.upper.use} (${t.upper.occupancy})`, value:t.id}))},
    {id:"storeys", title:"How many storeys?", help:"Storeys above grade. You can add or remove later.", type:"choice", default:4, options:[2,3,4,5,6,8,12].map(n=>({label:`${n}`, value:n})), custom:{label:"or enter", step:1}},
    {id:"front", title:"Front setback from the street", type:"choice", default:0, options:[{label:"0 m — build to the line",value:0},{label:"1.2 m",value:1.2},{label:"3 m",value:3},{label:"6 m",value:6}], custom:{label:"or enter metres"}},
    {id:"side", title:"Side setbacks", help:"0 m gives party walls at the property line: no windows permitted and a 1 h noncombustible wall.", type:"choice", default:0, options:[{label:"0 m — party walls",value:0},{label:"1.2 m",value:1.2},{label:"3 m",value:3},{label:"4.5 m",value:4.5}], custom:{label:"or enter metres"}},
    {id:"rear", title:"Rear setback", type:"choice", default:1, options:[{label:"0 m",value:0},{label:"1 m",value:1},{label:"6 m",value:6},{label:"Half the lot (courtyard/yard)",value:"half"}], custom:{label:"or enter metres"}},
    {id:"stepback", title:"Upper-storey stepback?", help:"Upper storeys pull back from the street; each storey then carries its own outline you can reshape in the plan.", type:"choice", default:"none", options:[
      {label:"None — straight extrusion", value:"none"},{label:"3 m from the street above the 2nd storey", value:"3@3"},{label:"3 m from the street above the 4th storey", value:"3@5"},{label:"6 m on all sides above the 2nd storey (podium + tower)", value:"6all@3"}]},
    {id:"court", title:"Courtyard?", help:"A courtyard is subtracted from the building area; its inner faces do not expose each other (same building).", type:"choice", default:"none", options:[
      {label:"None", value:"none"},{label:"Central courtyard, ¼ of the footprint", value:"quarter"},{label:"Rear light well, 6 × 6 m", value:"well"}]},
    {id:"roof", title:"Roof", type:"multi", default:["parapet"], options:[
      {label:"Parapet 0.6 m", value:"parapet"},{label:"Elevator / stair penthouse (not a storey, 3.2.1.1)", value:"service"},{label:"Rooftop amenity room (counts as a storey)", value:"amenity"}]},
    {id:"glaz", title:"Glazing", help:"Ratios by what each face looks at; the party walls get 0 %. Adjust per edge afterwards.", type:"choice", default:"auto", options:[
      {label:`By exposure — street ${P.glazing_by_exposure.street} %, lane ${P.glazing_by_exposure.lane} %, neighbour ${P.glazing_by_exposure.neighbour} %`, value:"auto"},{label:"Uniform 30 %", value:30},{label:"Uniform 50 %", value:50}]},
    {id:"neigh", title:"Neighbouring buildings (for the 3D view and the Rhino file)", help:"Context only — limiting distance is measured to the property line, not to the neighbour.", type:"multi", default:[], options:[
      {label:"Left (west) neighbour, 3 storeys", value:"west"},{label:"Right (east) neighbour, 3 storeys", value:"east"},{label:"Across the lane / rear, 2 storeys", value:"north"}], when:()=>first&&!(spec.context||[]).length},   // skipped when the map already brought the real neighbours
    {id:"name", title:"Block name", type:"text", default:String.fromCharCode(65+spec.blocks.length)},
  ]);
  if(!a) return;
  const t=P.types.find(x=>x.id===a.type); const n=Math.max(1,Math.round(a.storeys||t.default_storeys));
  const rear = a.rear==="half" ? (spec.lot.depth_m*0.5) : a.rear;
  const fp=insetBBox(a.front,a.side,rear);
  const blk={name:a.name||"A", footprint:fp, holes:[], roof:{parapet_m:(a.roof||[]).includes("parapet")?0.6:0, enclosure:null, balconies:[]}, first_floor_above_grade_m:0.1, default_glazing_pct: a.glaz==="auto"?30:a.glaz, glazing_pct_by_edge:{},
    storeys:[{...t.ground}].concat(Array.from({length:n-1},()=>({...t.upper})))};
  if(a.glaz==="auto") fp.forEach((p,i)=>{ blk.glazing_pct_by_edge[i]=P.glazing_by_exposure[edgeExposure(fp,i)]; });
  spec.lot.setbacks={front:a.front, side:a.side, rear:rear};
  // stepbacks → per-storey outlines
  if(a.stepback&&a.stepback!=="none"){ const [d,from]=a.stepback.replace("all","").split("@").map(Number); const all=a.stepback.includes("all");
    const r2=v=>Math.round(v*100)/100; const [[x0,y0],[x1,,],[,y1]]=[fp[0],fp[1],fp[2]];
    const up=all?[[r2(x0+d),r2(y0+d)],[r2(x1-d),r2(y0+d)],[r2(x1-d),r2(y1-d)],[r2(x0+d),r2(y1-d)]]:[[x0,r2(y0+d)],[x1,r2(y0+d)],[x1,y1],[x0,y1]];
    blk.storeys.forEach((s,i)=>{ if(i+1>=from) s.footprint=up.map(p=>p.slice()); }); }
  // courtyard
  if(a.court&&a.court!=="none"){ const [[x0,y0],[x1,,],[,y1]]=[fp[0],fp[1],fp[2]]; const w=x1-x0, d=y1-y0; const r2=v=>Math.round(v*100)/100;
    if(a.court==="quarter"){ const cw=w/2, cd=d/2; const cx=x0+w/2, cy=y0+d/2; blk.holes=[[[r2(cx-cw/2),r2(cy-cd/2)],[r2(cx+cw/2),r2(cy-cd/2)],[r2(cx+cw/2),r2(cy+cd/2)],[r2(cx-cw/2),r2(cy+cd/2)]]]; }
    else { const cx=x0+w/2, cy=y1-3-Math.min(3,d*0.15); blk.holes=[[[r2(cx-3),r2(cy-3)],[r2(cx+3),r2(cy-3)],[r2(cx+3),r2(cy+3)],[r2(cx-3),r2(cy+3)]]]; } }
  // roof enclosure
  const roofSel=a.roof||[]; if(roofSel.includes("service")||roofSel.includes("amenity")){ const top=blk.storeys[blk.storeys.length-1].footprint||fp; const xs=top.map(p=>p[0]), ys=top.map(p=>p[1]); const cx=(Math.min(...xs)+Math.max(...xs))/2, cy=(Math.min(...ys)+Math.max(...ys))/2; const hw=Math.min(4,(Math.max(...xs)-Math.min(...xs))/4), hd=Math.min(4,(Math.max(...ys)-Math.min(...ys))/4); const r2=v=>Math.round(v*100)/100;
    blk.roof.enclosure={footprint:[[r2(cx-hw),r2(cy-hd)],[r2(cx+hw),r2(cy-hd)],[r2(cx+hw),r2(cy+hd)],[r2(cx-hw),r2(cy+hd)]], height_m:roofSel.includes("amenity")?3.2:3.0, use:roofSel.includes("amenity")?"rooftop amenity lounge":"elevator machine room, stair", occupancy:"C"}; }
  // neighbours
  if(first&&(a.neigh||[]).length){ const L=spec.lot; spec.context=spec.context||[]; const W=L.width_m, D=L.depth_m;
    if(a.neigh.includes("west")) spec.context.push({name:"west neighbour", footprint:[[-12,2],[-1,2],[-1,D*0.7],[-12,D*0.7]], height_m:9.5});
    if(a.neigh.includes("east")) spec.context.push({name:"east neighbour", footprint:[[W+1,2],[W+12,2],[W+12,D*0.7],[W+1,D*0.7]], height_m:9.5});
    if(a.neigh.includes("north")) spec.context.push({name:"across the lane", footprint:[[0,D+(L.edges.north.row_width_m||6)+1],[W,D+(L.edges.north.row_width_m||6)+1],[W,D+(L.edges.north.row_width_m||6)+15],[0,D+(L.edges.north.row_width_m||6)+15]], height_m:6.5}); }
  spec.blocks.push(blk); sel=spec.blocks.length-1; changed(true);
}

// ---------------------------------------------------------------- map picker (Leaflet)
let map=null, mapLayers=null, mapData=null;
function mapPicker(){
  return new Promise(resolve=>{
    const dlg=document.getElementById("dlgMap"); dlg.showModal();
    const status=document.getElementById("mapStatus");
    if(!map){
      map=L.map("map",{zoomControl:true}).setView([49.263,-123.155],17);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:20,attribution:"© OpenStreetMap"}).addTo(map);
      mapLayers=L.layerGroup().addTo(map);
      map.on("moveend",()=>fetchParcels());
    }
    setTimeout(()=>{ map.invalidateSize(); fetchParcels(); },50);
    document.getElementById("mapGo").onclick=()=>{ const v=document.getElementById("mapLatLon").value.split(/[ ,]+/).map(Number); if(v.length===2&&!v.some(isNaN)) map.setView([v[0],v[1]],18); };
    document.getElementById("mapCancel").onclick=()=>{ dlg.close(); resolve(null); };
    async function fetchParcels(){
      if(map.getZoom()<16){ status.textContent="Zoom in to load parcels (zoom ≥ 16)."; mapLayers.clearLayers(); return; }
      const c=map.getCenter(); status.textContent="loading parcels…";
      try{ const r=await fetch(`/api/parcels?lat=${c.lat}&lon=${c.lng}&radius=220`); if(!r.ok){ status.textContent=(await r.json()).detail||"request failed"; return; }
        mapData=await r.json(); mapLayers.clearLayers();
        mapData.streets.forEach(s=>L.polyline(s.line.map(p=>[p[1],p[0]]),{color:"#c8352b",weight:2,opacity:.6}).addTo(mapLayers).bindTooltip(s.name||"street"));
        mapData.lanes.forEach(s=>L.polyline(s.line.map(p=>[p[1],p[0]]),{color:"#b26b00",weight:2,dashArray:"4 4",opacity:.8}).addTo(mapLayers).bindTooltip("lane"));
        mapData.parcels.forEach(p=>{ const poly=L.polygon(p.ring.map(q=>[q[1],q[0]]),{color:"#1d4f9c",weight:1,fillOpacity:.12}).addTo(mapLayers);
          poly.bindTooltip(p.address||p.id); poly.on("mouseover",()=>poly.setStyle({fillOpacity:.35})); poly.on("mouseout",()=>poly.setStyle({fillOpacity:.12}));
          poly.on("click",async()=>{ status.textContent="reading lot…"; const rr=await fetch("/api/parcels/lot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({parcel:p,streets:mapData.streets,lanes:mapData.lanes,zoning:mapData.zoning,parcels:mapData.parcels,grade_m:10})});
            const lot=await rr.json(); dlg.close(); resolve(lot); }); });
        status.textContent=`${mapData.parcels.length} parcels${mapData.fixture?" — OFFLINE FIXTURE (synthetic block), not real parcels":""}. Click one.`;
      }catch(e){ status.textContent="could not load parcels: "+e; }
    }
  });
}

// ---------------------------------------------------------------- wire up
document.getElementById("btnWizard").onclick=siteWizard;
document.getElementById("btnAddBlockWiz").onclick=()=>blockWizard(false);
if(!location.hash.includes("nowizard")) window.addEventListener("load",()=>setTimeout(siteWizard,300));
