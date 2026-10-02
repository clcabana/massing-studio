// engine.js — JavaScript port of the codesheet rule engine for the massing layer.
// Reads engine_data.json (exported from the Python sources) so tables and ladders
// are shared, not retyped. Kept honest against Python by tests/test_engine_js.py,
// which runs both on the same specs and compares results.
//
// Exposes: analyzeMassing(spec, DATA) → {summary, headroom, faces, zoning, determinations, flags, ladder, building}
(function (root) {
  const OCC_A_LIKE = new Set(["A1", "A2", "A3", "A4", "B1", "B2", "B3", "C", "D", "F3"]);

  // ------------------------------------------------------------------ geometry
  function polyArea(pts) { let s = 0; for (let i = 0; i < pts.length; i++) { const p = pts[i], q = pts[(i + 1) % pts.length]; s += p[0] * q[1] - q[0] * p[1]; } return Math.abs(s) / 2; }
  function ccw(pts) { let s = 0; for (let i = 0; i < pts.length; i++) { const p = pts[i], q = pts[(i + 1) % pts.length]; s += p[0] * q[1] - q[0] * p[1]; } return s > 0 ? pts.slice() : pts.slice().reverse(); }
  function lotBoundary(lot) {
    if (lot.polygon) { const k = lot.edge_kinds || []; return lot.polygon.map((p, i) => ({ a: p, b: lot.polygon[(i + 1) % lot.polygon.length], kind: k[i] || { kind: "neighbour", row_width_m: 0 }, label: `edge ${i}` })); }
    const W = lot.width_m, D = lot.depth_m, E = lot.edges || {}; const g = s => E[s] || { kind: "neighbour", row_width_m: 0 };
    return [{ a: [0, 0], b: [W, 0], kind: g("south"), label: "south" }, { a: [W, 0], b: [W, D], kind: g("east"), label: "east" }, { a: [W, D], b: [0, D], kind: g("north"), label: "north" }, { a: [0, D], b: [0, 0], kind: g("west"), label: "west" }];
  }
  function rayHit(px, py, nx, ny, a, b) { const ex = b[0] - a[0], ey = b[1] - a[1]; const den = nx * ey - ny * ex; if (Math.abs(den) < 1e-9) return null; const t = ((a[0] - px) * ey - (a[1] - py) * ex) / den; const u = ((a[0] - px) * ny - (a[1] - py) * nx) / den; return (t >= -0.15 && u >= -1e-6 && u <= 1 + 1e-6) ? Math.max(t, 0) : null; }
  function edgeExposure(lot, a, b, others) {
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2; const ux = b[0] - a[0], uy = b[1] - a[1]; const L = Math.hypot(ux, uy) || 1; const nx = uy / L, ny = -ux / L;
    let best = null; for (const s of lotBoundary(lot)) { const t = rayHit(mx, my, nx, ny, s.a, s.b); if (t !== null && (best === null || t < best.t)) best = { t, kind: s.kind, label: s.label }; }
    if (!best) return { exposure: "property_line", ld: 0, side: "interior" };
    const r2 = v => Math.round(v * 100) / 100;
    for (const [name, poly] of (others || [])) for (let i = 0; i < poly.length; i++) { const t = rayHit(mx, my, nx, ny, poly[i], poly[(i + 1) % poly.length]); if (t !== null && t > 0.05 && t < best.t) best = { t, kind: { kind: "neighbour", row_width_m: 0 }, label: `imaginary line to ${name}` }; }
    if (best.label.startsWith("imaginary line")) return { exposure: "same_lot", ld: r2(best.t / 2), side: best.label };
    const e = best.kind; const d = Math.max(0, best.t);
    if (e.kind === "street") return { exposure: "street", ld: r2(d + e.row_width_m / 2), side: best.label };
    if (e.kind === "lane") return { exposure: "lane", ld: r2(d + e.row_width_m / 2), side: best.label };
    return { exposure: "property_line", ld: r2(d), side: best.label };
  }
  function edgeGlazing(blk, blkPts, a, b, idx) {
    const G = blk.glazing_pct_by_edge || {}; const dflt = blk.default_glazing_pct;
    if (idx !== null) return G[idx] != null ? +G[idx] : dflt;
    if (!Object.keys(G).length) return dflt;
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, ux = b[0] - a[0], uy = b[1] - a[1];
    for (let i = 0; i < blkPts.length; i++) { const p = blkPts[i], q = blkPts[(i + 1) % blkPts.length]; const vx = q[0] - p[0], vy = q[1] - p[1];
      if (Math.abs(ux * vy - uy * vx) > 1e-6 * Math.max(1, Math.abs(ux * vx + uy * vy)) || ux * vx + uy * vy <= 0) continue;
      const L = Math.hypot(vx, vy) || 1; const dist = Math.abs((mx - p[0]) * vy - (my - p[1]) * vx) / L; if (dist < 0.02) return G[i] != null ? +G[i] : dflt; }
    return dflt;
  }
  const SERVICE_RE = /elevator|machine|stair|mechanical|service|hvac|electrical|penthouse/;
  const ringArea = polyArea;
  function fpArea(pts, holes) { return ringArea(pts) - (holes || []).reduce((a, h) => a + ringArea(h), 0); }
  const samePoly = (a, b) => a.length === b.length && a.every((p, i) => p[0] === b[i][0] && p[1] === b[i][1]);
  const sameHoles = (a, b) => a.length === b.length && a.every((h, i) => samePoly(h, b[i]));

  // ------------------------------------------------------------------ massing → building
  function toBuilding(spec) {
    const lot = spec.lot; const bnd = lotBoundary(lot);
    const streets = spec.streets_faced != null ? spec.streets_faced : new Set(bnd.filter(s => s.kind.kind === "street" || s.kind.kind === "lane").map(s => s.label)).size;
    const storeys = [], faces = [], notes = ["Generated from a massing spec: one zone per storey, glazing ratios assumed, LD measured from footprint edges to lot lines."];
    const outlines = {}; for (const blk of spec.blocks) outlines[blk.name] = blk.storeys.map(st => ccw((st.footprint || blk.footprint).map(p => [p[0], p[1]])));
    for (const blk of spec.blocks) {
      const others = []; for (const [n, polys] of Object.entries(outlines)) { if (n === blk.name) continue; const seen = new Set(); for (const poly of polys) { const k = JSON.stringify(poly); if (!seen.has(k)) { seen.add(k); others.push([n, poly]); } } }
      const blkPts = ccw(blk.footprint.map(p => [p[0], p[1]]));
      let z = lot.grade_m + blk.first_floor_above_grade_m, top = z; const runs = [];
      blk.storeys.forEach((st, i) => { const label = `L${i + 1}`; const pts = ccw((st.footprint || blk.footprint).map(p => [p[0], p[1]])); const holes = (st.holes != null ? st.holes : (blk.holes || [])).map(h => ccw(h.map(p => [p[0], p[1]]))); const area = fpArea(pts, holes);
        storeys.push({ label, block: blk.name, elevation_m: +z.toFixed(3), height_m: st.floor_to_floor_m, footprint: pts, holes, area, zones: [{ name: `${label} ${st.use || st.occupancy}`, description: st.use || `Group ${st.occupancy}`, area_m2: +(area * 0.92).toFixed(1), occupancy: st.occupancy, net_deduction_pct: st.net_deduction_pct || 0, ol_factor_m2: st.ol_factor_m2 || null, sleeping_rooms: st.sleeping_rooms != null ? st.sleeping_rooms : null, dwelling_units: st.dwelling_units != null ? st.dwelling_units : null, occupant_load: null }] });
        const z1 = z + st.floor_to_floor_m; const last = runs[runs.length - 1];
        if (last && samePoly(last.pts, pts) && sameHoles(last.holes, holes)) { last.l1 = label; last.z1 = z1; } else runs.push({ pts, holes, l0: label, l1: label, z0: z, z1 });
        z = z1; top = z; });
      const roof = blk.roof || {}; const enc = roof.enclosure; let roofZ = top;
      if (enc) { if (SERVICE_RE.test(enc.use.toLowerCase())) notes.push(`${blk.name}: rooftop enclosure '${enc.use}' (${Math.round(ringArea(enc.footprint))} m², ${enc.height_m} m) is not a storey — 3.2.1.1.(1), provided it serves only elevator machinery, stairs or service rooms.`);
        else { const label = `L${blk.storeys.length + 1}`; const pts = ccw(enc.footprint.map(p => [p[0], p[1]])); const area = ringArea(pts);
          storeys.push({ label, block: blk.name, elevation_m: +top.toFixed(3), height_m: enc.height_m, footprint: pts, holes: [], area, zones: [{ name: `${label} ${enc.use}`, description: enc.use, area_m2: +(area * 0.92).toFixed(1), occupancy: enc.occupancy || "C", net_deduction_pct: 0, ol_factor_m2: null, sleeping_rooms: null, dwelling_units: null, occupant_load: null }] });
          runs.push({ pts, holes: [], l0: label, l1: label, z0: top, z1: top + enc.height_m }); roofZ = top + enc.height_m;
          notes.push(`${blk.name}: rooftop enclosure '${enc.use}' is occupied space, so it COUNTS as a storey (3.2.1.1.(1) exempts only elevator machinery, stairs and service rooms).`); } }
      const lastRun = runs[runs.length - 1];
      storeys.push({ label: "Roof", block: blk.name, elevation_m: +roofZ.toFixed(3), height_m: Math.max(0.4, roof.parapet_m != null ? roof.parapet_m : 0.6), footprint: lastRun.pts, holes: lastRun.holes, area: fpArea(lastRun.pts, lastRun.holes), zones: [], is_roof: true });
      const labels = {}; let holeEdges = 0;
      for (const run of runs) { holeEdges += run.holes.reduce((a, h) => a + h.length, 0); const band = run.l0 === run.l1 ? run.l0 : `${run.l0}–${run.l1}`;
        for (let i = 0; i < run.pts.length; i++) { const a = run.pts[i], b = run.pts[(i + 1) % run.pts.length]; const ex = edgeExposure(lot, a, b, others); if (ex.side === "interior") continue;
          const key = ex.side + "|" + band; const n = (labels[key] || 0) + 1; labels[key] = n;
          const glaz = edgeGlazing(blk, blkPts, a, b, samePoly(run.pts, blkPts) ? i : null);
          const stated = {}; for (const s of storeys) if (s.block === blk.name && !s.is_roof && run.z0 - 0.01 <= s.elevation_m && s.elevation_m < run.z1 - 0.01) stated[s.label] = glaz;
          faces.push({ label: `${blk.name} · ${ex.side}${n === 1 ? "" : " " + n} (${ex.exposure.replace("_", " ")})` + (runs.length > 1 ? ` ${band}` : ""), block: blk.name, start: a, end: b, base_elevation_m: run.z0 > lot.grade_m ? +run.z0.toFixed(3) : lot.grade_m, top_elevation_m: +run.z1.toFixed(3), exposure: ex.exposure, limiting_distance_m: ex.ld, stated_upo_pct: stated, glazing: glaz, band }); } }
      if (holeEdges) notes.push(`${blk.name}: ${holeEdges} courtyard edge(s) face the same building and are not exposing building faces under 3.2.3 (no separate building or fire compartment across the court). Confirm no firewall divides the court.`);
    }
    return { project_name: spec.project_name, site: { grade_elevation_m: lot.grade_m, streets_faced: Math.max(0, Math.min(3, streets)), address: lot.address || spec.project_name, zoning_district: lot.zoning || null }, storeys, exterior_faces: faces, is_sprinklered: spec.sprinklered, blocks: [...new Set(spec.blocks.map(b => b.name))], notes, context: spec.context || [] };
  }

  // ------------------------------------------------------------------ determinations
  const D = (key, label, value, extra) => Object.assign({ key, label, value, unit: "", clauses: [], because: "", flags: [], block: null, inputs: {} }, extra || {});
  const clause = (DATA, id, sentence) => ({ id: id + (sentence ? `.(${sentence})` : ""), page: DATA.pages[id] || null, edition: DATA.edition });
  const defn = (DATA, term) => ({ id: `Div. A 1.4.1.2 “${term}”`, page: DATA.definitions[term].page, edition: DATA.edition });
  const fmt = v => Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });

  function heightArea(b, DATA) {
    const out = []; const g = b.site.grade_elevation_m;
    out.push(D("site.grade_m", "Grade", g, { unit: "m", clauses: [defn(DATA, "Grade")], because: "Entered from the site plan / survey as the lowest average finished ground level adjoining the exterior walls." }));
    for (const blk of b.blocks) {
      const main = b.storeys.filter(s => s.block === blk && !s.is_roof).sort((a, c) => a.elevation_m - c.elevation_m);
      const cands = main.filter(s => s.elevation_m <= g + 2.0);
      if (!cands.length) { out.push(D(`${blk}.first_storey`, "First storey", null, { block: blk, clauses: [defn(DATA, "First storey")], flags: ["No storey has its floor within 2 m above grade — check grade elevation."] })); continue; }
      const fs = cands.reduce((a, c) => c.elevation_m > a.elevation_m ? c : a);
      out.push(D(`${blk}.first_storey`, "First storey", fs.label, { block: blk, clauses: [defn(DATA, "First storey"), defn(DATA, "Grade")], because: `Grade is ${g.toFixed(2)} m. Storeys with floor ≤ 2 m above grade: ${cands.map(s => `${s.label} (${(s.elevation_m - g >= 0 ? "+" : "") + (s.elevation_m - g).toFixed(2)} m)`).join(", ")}. The uppermost of these is ${fs.label} at ${fs.elevation_m.toFixed(2)} m.` }));
      const below = main.filter(s => s.elevation_m < fs.elevation_m).map(s => s.label).reverse();
      out.push(D(`${blk}.basements`, "Basements", below.length ? below : "none", { block: blk, clauses: [defn(DATA, "Basement")], because: `Storeys below the first storey (${fs.label}): ${below.join(", ") || "none"}. They carry occupancies but do not count toward building height.` }));
      const counted = main.filter(s => s.elevation_m >= fs.elevation_m - 0.01);
      out.push(D(`${blk}.building_height_storeys`, "Building height", counted.length, { unit: "storeys", block: blk, clauses: [defn(DATA, "Building height"), clause(DATA, "3.2.1.1", 1)], because: `Storeys from the first storey (${fs.label}) to the roof: ${counted.map(s => s.label).join(", ")}. Rooftop enclosures for elevator machinery, service rooms and stair access are not storeys (3.2.1.1.(1)).`, inputs: { counted: counted.map(s => s.label) } }));
      const top = main.reduce((a, c) => c.elevation_m > a.elevation_m ? c : a); const h = +(top.elevation_m - fs.elevation_m).toFixed(2);
      out.push(D(`${blk}.height_to_top_floor_m`, "Height, first-storey floor to uppermost floor", h, { unit: "m", block: blk, clauses: [clause(DATA, "3.2.2.51", 1)], because: `Uppermost floor ${top.label} at ${top.elevation_m.toFixed(2)} m minus first-storey floor ${fs.label} at ${fs.elevation_m.toFixed(2)} m.` }));
      const perLevel = {}; for (const s of counted) perLevel[s.label] = (perLevel[s.label] || 0) + s.area;
      const biggest = Object.keys(perLevel).reduce((a, k) => perLevel[k] > perLevel[a] ? k : a);
      const area = Math.round(perLevel[biggest]);
      out.push(D(`${blk}.building_area_m2`, "Building area", area, { unit: "m²", block: blk, clauses: [defn(DATA, "Building area")], because: `Greatest horizontal area above grade, measured to the centreline of the firewall (from footprint polygons). Per level: ${Object.entries(perLevel).map(([k, v]) => `${k} ${fmt(Math.round(v))} m²`).join(", ")}. Governing level: ${biggest}.`, flags: b.blocks.length > 1 ? ["Firewall-separated block: area measured to the firewall centreline; the other block is a separate building."] : [] }));
    }
    return out;
  }

  function occupancy(b, DATA) {
    const out = []; const frac = DATA.subsidiary_fraction;
    for (const blk of b.blocks) {
      const majorAny = {}, present = {};
      for (const s of b.storeys.filter(s => s.block === blk && !s.is_roof).sort((a, c) => a.elevation_m - c.elevation_m)) {
        const per = {}; for (const z of s.zones) { per[z.occupancy] = (per[z.occupancy] || 0) + z.area_m2; present[z.occupancy] = (present[z.occupancy] || 0) + z.area_m2;
          out.push(D(`${blk}.${s.label}.${z.name}.occupancy`, `${s.label} — ${z.name}`, z.occupancy, { block: blk, clauses: [clause(DATA, "3.1.2.1", 1)], because: `${z.description}. set explicitly in the model. Table 3.1.2.1: “${DATA.table_3121[z.occupancy] || ""}”.`, inputs: { area_m2: z.area_m2, confidence: 1.0 } })); }
        for (const [g, a] of Object.entries(per)) { const f = a / s.area; if (f > frac || g === "F2") (majorAny[g] = majorAny[g] || []).push(`${s.label} (${fmt(Math.round(a))} m², ${Math.round(f * 100)}% of storey)`); }
      }
      const majors = Object.keys(majorAny).sort((x, y) => present[y] - present[x]);
      const minors = Object.keys(present).filter(g => !majorAny[g]);
      const d = D(`${blk}.major_occupancies`, "Major occupancies", majors, { block: blk, clauses: [clause(DATA, "3.1.2.1", 2), clause(DATA, "3.2.2.8", 1)],
        because: `Classified by all major occupancies (3.1.2.1.(2)). A Group whose aggregate area on a storey is ≤ 10% of that storey's floor area need not be treated as major there (3.2.2.8.(1)). ` + Object.entries(majorAny).map(([g, v]) => `${g}: major on ${v.join("; ")}.`).join(" ") + (minors.length ? ` Subsidiary only: ${minors.map(g => `${g} (${fmt(Math.round(present[g]))} m² total)`).join(", ")}.` : ""), inputs: { areas_m2: present } });
      if (majors.length > 1) d.flags.push("Multiple major occupancies — 3.2.2.6 (most restrictive governs) or 3.2.2.7 (superimposed) applies; occupancy separations per 3.1.3.1.");
      out.push(d);
    }
    return out;
  }

  // ------------------------------------------------------------------ 3.2.2 ladder
  function strictness(r) { return [r.floor_frr_h, r.construction === "noncombustible" ? 1 : 0, -(r.max_storeys || 99)]; }
  function cmpStrict(a, b) { const x = strictness(a), y = strictness(b); for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0; }
  function evaluate(r, storeys, height, area, spr, streets, hasBsmt) {
    const checks = [];
    if (r.requires_sprinklered) checks.push(["sprinklered throughout", spr, spr ? "yes" : "no"]);
    if (r.max_storeys != null) checks.push([`≤ ${r.max_storeys} storeys`, storeys <= r.max_storeys, `${storeys} storeys`]);
    if (r.max_height_m != null) checks.push([`≤ ${fmt(r.max_height_m)} m to uppermost floor`, height <= r.max_height_m, `${height.toFixed(2)} m`]);
    const within = r.max_storeys == null || storeys <= r.max_storeys;
    if (r.max_area_by_storeys_streets && within) { const row = r.max_area_by_storeys_streets[String(storeys)] || {}; const cap = row[String(Math.min(Math.max(streets, 1), 3))]; if (cap != null) checks.push([`building area ≤ ${fmt(cap)} m² at ${storeys} storeys facing ${streets} street(s)`, area <= cap, `${fmt(area)} m²`]); }
    else if (r.max_area_by_storeys && within) { let cap = r.max_area_by_storeys[String(storeys)];
      if (r.no_basement_area_bonus && !hasBsmt && r.no_basement_area_bonus[String(storeys)] != null) { cap = r.no_basement_area_bonus[String(storeys)]; checks.push([`building area ≤ ${fmt(cap)} m² at ${storeys} storeys, no basement`, area <= cap, `${fmt(area)} m²`]); }
      else if (cap == null) checks.push(["building area", true, `${fmt(area)} m² — not limited at ${storeys} storeys`]);
      else checks.push([`building area ≤ ${fmt(cap)} m² at ${storeys} storeys`, area <= cap, `${fmt(area)} m²`]); }
    return { rule: r, qualifies: checks.every(c => c[1]), checks };
  }
  function articles(b, hd, od, DATA, chosen) {
    chosen = chosen || {}; const H = Object.fromEntries(hd.map(d => [d.key, d])), O = Object.fromEntries(od.map(d => [d.key, d]));
    const out = [], ladder = {};
    for (const blk of b.blocks) {
      const storeys = H[`${blk}.building_height_storeys`].value, height = H[`${blk}.height_to_top_floor_m`].value, area = H[`${blk}.building_area_m2`].value;
      const hasBsmt = H[`${blk}.basements`].value !== "none"; const majors = O[`${blk}.major_occupancies`].value;
      const primary = majors.find(g => DATA.ladders[g]);
      if (!primary) { out.push(D(`${blk}.article`, "Governing 3.2.2 article", null, { block: blk, clauses: [clause(DATA, "3.2.2.6", 1)], because: `Major occupancies ${JSON.stringify(majors)}; no ladder encoded for these Groups.`, flags: [`No ladder encoded yet for major occupancies ${JSON.stringify(majors)} — determine the governing article manually.`] })); continue; }
      const evals = DATA.ladders[primary].map(r => evaluate(r, storeys, height, area, b.is_sprinklered, b.site.streets_faced, hasBsmt)); ladder[blk] = evals;
      const qualifying = evals.filter(e => e.qualifies).sort((x, y) => cmpStrict(x.rule, y.rule)); const excluded = evals.filter(e => !e.qualifies);
      let pick = null, designerFail = null;
      if (chosen[blk]) { pick = qualifying.find(e => e.rule.id === chosen[blk]) || null; if (!pick) designerFail = excluded.find(e => e.rule.id === chosen[blk]) || null; }
      if (!pick) pick = qualifying[0] || null;
      out.push(D(`${blk}.article_candidates`, "Qualifying 3.2.2 articles", qualifying.map(e => e.rule.id), { block: blk, clauses: qualifying.map(e => clause(DATA, e.rule.id, 1)),
        because: `Group ${primary}, ${storeys} storeys, ${height.toFixed(2)} m to uppermost floor, building area ${fmt(area)} m², ${b.is_sprinklered ? "sprinklered" : "unsprinklered"}. Qualifying: ${qualifying.map(e => `${e.rule.id} (${e.rule.construction}, floors ${fmt(e.rule.floor_frr_h)} h)`).join("; ") || "none"}. Excluded: ${excluded.map(e => `${e.rule.id} fails ` + e.checks.filter(c => !c[1]).map(c => `${c[0]} [${c[2]}]`).join(", ")).join("; ") || "none"}.`, inputs: { storeys, height_m: height, area_m2: area, sprinklered: b.is_sprinklered } }));
      if (!pick) { out.push(D(`${blk}.article`, "Governing 3.2.2 article", null, { block: blk, flags: ["No rung qualifies — check inputs."] })); continue; }
      const r = pick.rule;
      const d = D(`${blk}.article`, "Governing 3.2.2 article", r.id, { block: blk, clauses: [clause(DATA, r.id, 1), clause(DATA, r.id, 2)],
        because: `“${r.title}”. Conditions in Sentence (1): ${pick.checks.map(c => `${c[0]} ✓ [${c[2]}]`).join("; ")}` + (chosen[blk] && !designerFail ? ". Selected by the designer." : `. Proposed as the least demanding qualifying rung; ${qualifying.length - 1} other(s) also qualify.`), inputs: { chosen_by_designer: !!(chosen[blk] && !designerFail) } });
      if (designerFail) d.flags.unshift(`DESIGNER SELECTED ${designerFail.rule.id} BUT IT DOES NOT QUALIFY: ${designerFail.checks.filter(c => !c[1]).map(c => `${c[0]} — ${c[2]}`).join("; ")}. Falling back to ${r.id}. Check the inputs (building area is the usual culprit) before accepting.`);
      const superimposed = [];
      for (const g of majors) { if (g === primary) continue;
        if (r.admits[g]) d.flags.push(`Group ${g} present — admitted within ${r.id} per Sentence ${r.admits[g]}; confirm the storey condition.`);
        else if (DATA.ladders[g]) { superimposed.push(g); d.flags.push(`Group ${g} is a major occupancy not admitted by ${r.id} — assessed under its own ladder per 3.2.2.7 (see below); confirm the occupancies are superimposed, otherwise 3.2.2.6 applies.`); }
        else d.flags.push(`Group ${g} is a major occupancy not admitted by ${r.id} — 3.2.2.6 (most restrictive governs) or 3.2.2.7 (superimposed) must be applied; no ladder encoded for ${g}.`); }
      out.push(d);
      for (const g of superimposed) { const ev = DATA.ladders[g].map(rr => evaluate(rr, storeys, height, area, b.is_sprinklered, b.site.streets_faced, hasBsmt)); const q = ev.filter(e => e.qualifies).sort((x, y) => cmpStrict(x.rule, y.rule));
        if (!q.length) { out.push(D(`${blk}.article.${g}`, `Article for Group ${g} portion (3.2.2.7)`, null, { block: blk, clauses: [clause(DATA, "3.2.2.7", 1)], flags: [`No ${g} rung qualifies at ${storeys} storeys / ${fmt(area)} m².`] })); continue; }
        const rr = q[0].rule; out.push(D(`${blk}.article.${g}`, `Article for Group ${g} portion (3.2.2.7)`, rr.id, { block: blk, clauses: [clause(DATA, "3.2.2.7", 1), clause(DATA, "3.2.2.5", 1), clause(DATA, rr.id, 1), clause(DATA, rr.id, 2)], because: `“${rr.title}”, applied to the ${g} portion as if the entire building were Group ${g}, using the whole building's height and area (3.2.2.5). Conditions: ${q[0].checks.map(c => `${c[0]} ✓ [${c[2]}]`).join("; ")}. Requires ${rr.construction}, floors ≥ ${fmt(rr.floor_frr_h)} h.`, flags: ["The floor between the superimposed occupancies is rated by the LOWER occupancy's article and Table 3.1.3.1, whichever is greater (3.2.2.7.(2))."] })); }
      const req = [["Construction", r.construction], ["Floor assemblies", `fire separations, FRR ≥ ${fmt(r.floor_frr_h)} h`]];
      if (r.roof_frr_h != null) req.push(["Roof assemblies", `FRR ≥ ${fmt(r.roof_frr_h)} h`]);
      if (r.mezzanine_frr_h != null) req.push(["Mezzanines", `FRR ≥ ${fmt(r.mezzanine_frr_h)} h`]);
      req.push(["Loadbearing walls, columns, arches", "FRR ≥ that of the supported assembly"]);
      for (const [label, val] of req) out.push(D(`${blk}.req.${label}`, label, val, { block: blk, clauses: [clause(DATA, r.id, 2)], because: `Required by ${r.id}.(2). ${r.notes.join(" ")}` }));
    }
    return { dets: out, ladder };
  }

  // ------------------------------------------------------------------ spatial separation
  function interp(x, x0, x1, y0, y1) { return x1 === x0 ? y0 : y0 + (y1 - y0) * (x - x0) / (x1 - x0); }
  function colLookup(cols, vals, ld) { if (ld >= cols[cols.length - 1]) return +vals[vals.length - 1]; let i = cols.findIndex(c => c >= ld); if (cols[i] === ld) return +vals[i]; return interp(ld, cols[i - 1], cols[i], vals[i - 1], vals[i]); }
  function permittedD(DATA, area, ld) {
    const cols = DATA.table_d.ld_cols, rows = DATA.table_d.rows; ld = Math.max(0, ld); const areas = rows.map(r => r[0]); let v, how;
    if (area >= areas[areas.length - 1]) { v = colLookup(cols, rows[rows.length - 1][1], ld); how = `row ≥${areas[areas.length - 1]} m², LD ${ld} m`; }
    else if (area <= areas[0]) { v = colLookup(cols, rows[0][1], ld); how = `row ${areas[0]} m², LD ${ld} m`; }
    else { const i = areas.findIndex(a => a >= area); if (areas[i] === area) { v = colLookup(cols, rows[i][1], ld); how = `row ${areas[i]} m², LD ${ld} m`; } else { const lo = rows[i - 1], hi = rows[i]; v = interp(area, lo[0], hi[0], colLookup(cols, lo[1], ld), colLookup(cols, hi[1], ld)); how = `interpolated between rows ${lo[0]} and ${hi[0]} m², LD ${ld} m`; } }
    return [Math.round(v * 10) / 10, how];
  }
  function permittedBC(DATA, area, ld, L, H, group) {
    const table = ["E", "F1", "F2"].includes(group) ? "C" : "B"; const cols = DATA.table_bc.ld_cols, rows = DATA.table_bc[table].rows; ld = Math.max(0, ld);
    const ratio = L && H ? Math.max(L / H, H / L) : 1; const rkey = ratio < 3 ? "lt3" : ratio <= 10 ? "3to10" : "gt10"; const areas = rows.map(r => r.area); let v, how;
    if (area >= areas[areas.length - 1]) { v = colLookup(cols, rows[rows.length - 1][rkey], ld); how = `Table 3.2.3.1.-${table}, row ≥${areas[areas.length - 1]} m²`; }
    else if (area <= areas[0]) { v = colLookup(cols, rows[0][rkey], ld); how = `Table 3.2.3.1.-${table}, row ${areas[0]} m²`; }
    else { const i = areas.findIndex(a => a >= area); if (areas[i] === area) { v = colLookup(cols, rows[i][rkey], ld); how = `Table 3.2.3.1.-${table}, row ${areas[i]} m²`; } else { const lo = rows[i - 1], hi = rows[i]; v = interp(area, lo.area, hi.area, colLookup(cols, lo[rkey], ld), colLookup(cols, hi[rkey], ld)); how = `Table 3.2.3.1.-${table}, interpolated between rows ${lo.area} and ${hi.area} m²`; } }
    how += `, ratio ${ratio.toFixed(1)}:1, LD ${ld} m`; return [Math.round(v * 10) / 10, how];
  }
  function faceReq(DATA, p) {
    const rows = DATA.table_3237.rows; if (p >= 100) { const r = rows[rows.length - 1]; return { frr_min: r[1], construction: r[2], cladding: r[3], band: "100 (no exposing-face requirement)" }; }
    for (const r of rows.slice(0, -1)) { const [lo, hi] = r[0]; if (lo === 0 ? p <= hi : (lo < p && p <= hi)) return { frr_min: r[1], construction: r[2], cladding: r[3], band: lo === 0 ? `0 to ${hi}` : `> ${lo} to ${hi}` }; }
    return { frr_min: 60, construction: "noncombustible", cladding: "noncombustible", band: "0 to 10" };
  }
  function spatial(b, DATA, groups) {
    const out = [], faces = {}; const spr = b.is_sprinklered;
    const tD = spr ? { id: "Table 3.2.3.1.-D", page: DATA.table_d.page, edition: DATA.edition } : { id: "Table 3.2.3.1.-B / -C", page: DATA.table_bc_pages.B, edition: DATA.edition };
    const t7 = { id: "Table 3.2.3.7", page: DATA.table_3237.page, edition: DATA.edition };
    for (const f of b.exterior_faces) {
      const L = Math.hypot(f.end[0] - f.start[0], f.end[1] - f.start[1]); const group = groups[f.block] || "C";
      const st = b.storeys.filter(s => s.block === f.block && !s.is_roof).sort((a, c) => a.elevation_m - c.elevation_m); const bands = [];
      for (const s of st) { const z0 = Math.max(s.elevation_m, f.base_elevation_m), z1 = Math.min(s.elevation_m + s.height_m, f.top_elevation_m); if (z1 - z0 <= 0.3) continue;
        const area = L * (z1 - z0); const actual = f.stated_upo_pct[s.label] != null ? f.stated_upo_pct[s.label] : 0;
        const [permitted, how] = spr ? permittedD(DATA, area, f.limiting_distance_m) : permittedBC(DATA, area, f.limiting_distance_m, L, z1 - z0, group);
        const rq = faceReq(DATA, permitted); const ok = actual <= permitted + 1e-9;
        bands.push({ label: s.label, z0, z1, face_area_m2: +area.toFixed(1), actual: +(+actual).toFixed(1), permitted, ok, frr_min: rq.frr_min, construction: rq.construction, cladding: rq.cladding, how });
        const d = D(`${f.block}.face.${f.label}.${s.label}`, `${f.label} · ${s.label}`, `${fmt(+actual)}% of ${fmt(permitted)}% permitted — ${ok ? "OK" : "EXCEEDS"}`, { block: f.block, clauses: [clause(DATA, "3.2.3.1", 1), tD, clause(DATA, "3.2.3.7", 1), t7],
          because: `Exposing face ${L.toFixed(1)} m × ${(z1 - z0).toFixed(2)} m = ${fmt(Math.round(area))} m² at limiting distance ${fmt(f.limiting_distance_m)} m (${f.exposure.replace("_", " ")}). ${spr ? "Table 3.2.3.1.-D (" + how + ")" : how} permits ${fmt(permitted)}%. Unprotected openings in band: ${fmt(+actual)}% (glazing ratio assumed). Table 3.2.3.7 for permitted ${rq.band}%: FRR ≥ ${rq.frr_min} min, ${rq.construction}, ${rq.cladding} cladding.`,
          inputs: { face_area_m2: +area.toFixed(1), actual_pct: +actual, permitted_pct: permitted, ld_m: f.limiting_distance_m, frr_min: rq.frr_min, construction: rq.construction, cladding: rq.cladding } });
        if (!ok) d.flags.push(`Openings exceed the permitted area by ${(actual - permitted).toFixed(1)} points — reduce openings, increase limiting distance, or protect openings (3.2.3.10–.12).`);
        out.push(d); }
      faces[f.label] = { block: f.block, ld: f.limiting_distance_m, exposure: f.exposure, bands };
      if (bands.length) { const w = bands.reduce((a, c) => (c.permitted - c.actual) < (a.permitted - a.actual) ? c : a); out.push(D(`${f.block}.face.${f.label}.summary`, `${f.label} — governing band`, `${w.label}: FRR ≥ ${w.frr_min} min, ${w.cladding} cladding`, { block: f.block, clauses: [clause(DATA, "3.2.3.7", 1), t7], because: `Tightest band is ${w.label} (${fmt(w.actual)}% of ${fmt(w.permitted)}%). Wall requirements follow the permitted percentage, not the actual.` })); }
    }
    return { dets: out, faces };
  }

  // ------------------------------------------------------------------ separations
  function tableFrr(DATA, a, b) { if (a === b) return null; const m = DATA.table_3131.map; return m[`${a}|${b}`] !== undefined ? m[`${a}|${b}`] : (m[`${b}|${a}`] !== undefined ? m[`${b}|${a}`] : null); }
  function requiredFrr(DATA, a, b, article) { const base = tableFrr(DATA, a, b); const pair = new Set([a, b]);
    if (pair.has("C") && pair.has("A2") && article === "3.2.2.51") return [2, "Table 3.1.3.1 gives 1 h; Note (3) raises it to 2 h for buildings built to 3.2.2.51"];
    if (pair.has("D") && pair.has("A2") && article === "3.2.2.60") return [2, "Table 3.1.3.1 gives 1 h; Note (4) raises it to 2 h for buildings built to 3.2.2.60"];
    if (base === "X") return ["X", "combination prohibited by 3.1.3.2.(1)"]; if (base === null) return [null, "Table 3.1.3.1 shows no requirement (—) for this pair"]; return [+base, `Table 3.1.3.1: ${base} h`]; }
  function separations(b, ad, DATA) {
    const A = Object.fromEntries(ad.map(d => [d.key, d])); const out = []; const t = { id: "Table 3.1.3.1", page: DATA.table_3131.page, edition: DATA.edition };
    for (const blk of b.blocks) { const article = A[`${blk}.article`] ? A[`${blk}.article`].value : null; let floorFrr = null; const fa = A[`${blk}.req.Floor assemblies`]; if (fa) { const m = /≥\s*([\d.]+)\s*h/.exec(fa.value); if (m) floorFrr = +m[1]; }
      const st = b.storeys.filter(s => s.block === blk && !s.is_roof).sort((a, c) => a.elevation_m - c.elevation_m);
      const groupsOn = {}; for (const s of st) { const per = {}; for (const z of s.zones) per[z.occupancy] = (per[z.occupancy] || 0) + z.area_m2; groupsOn[s.label] = Object.fromEntries(Object.entries(per).filter(([g, a]) => a / s.area > 0.10)); }
      for (const s of st) { const gs = Object.keys(groupsOn[s.label]).sort((x, y) => groupsOn[s.label][y] - groupsOn[s.label][x]); for (let i = 0; i < gs.length; i++) for (let j = i + 1; j < gs.length; j++) { const [frr, why] = requiredFrr(DATA, gs[i], gs[j], article); out.push(D(`${blk}.sep.${s.label}.${gs[i]}-${gs[j]}`, `${s.label}: ${gs[i]} ↔ ${gs[j]} (vertical separation)`, frr === "X" ? "prohibited" : frr === null ? "none required" : `${fmt(frr)} h`, { block: blk, clauses: [clause(DATA, "3.1.3.1", 1), t], because: `Both occupancies occur on ${s.label}. ${why}.`, flags: ["Adjacency inferred from co-location on the storey; confirm on plan whether these occupancies actually adjoin."] })); } }
      for (let k = 0; k + 1 < st.length; k++) { const lo = st[k], up = st[k + 1]; const gl = Object.keys(groupsOn[lo.label]).reduce((a, g) => a === null || groupsOn[lo.label][g] > groupsOn[lo.label][a] ? g : a, null); const gu = Object.keys(groupsOn[up.label]).reduce((a, g) => a === null || groupsOn[up.label][g] > groupsOn[up.label][a] ? g : a, null);
        if (!gl || !gu || gl === gu) continue; const [frr, why] = requiredFrr(DATA, gl, gu, article); const req = typeof frr === "number" ? frr : 0; const gov = Math.max(req, floorFrr || 0);
        out.push(D(`${blk}.sep.${lo.label}|${up.label}.${gl}-${gu}`, `Floor ${lo.label}/${up.label}: ${gl} below, ${gu} above`, `${fmt(gov)} h`, { block: blk, clauses: [clause(DATA, "3.1.3.1", 1), t, clause(DATA, "3.2.2.7", 2)], because: `${gu} on ${up.label} sits over ${gl} on ${lo.label}. ${why}.` + (floorFrr != null ? ` The floor is also a fire separation under ${article}.(2) at ${fmt(floorFrr)} h; the greater governs (3.2.2.7.(2)).` : "") })); } }
    return out;
  }

  // ------------------------------------------------------------------ headroom
  function headroom(b, hd, ad, ladder) {
    const H = Object.fromEntries(hd.map(d => [d.key, d])), A = Object.fromEntries(ad.map(d => [d.key, d])); const out = {};
    for (const [blk, evals] of Object.entries(ladder)) { const govId = A[`${blk}.article`] ? A[`${blk}.article`].value : null; const e = evals.find(x => x.rule.id === govId); if (!e) continue; const r = e.rule;
      const storeys = H[`${blk}.building_height_storeys`].value, height = H[`${blk}.height_to_top_floor_m`].value, area = H[`${blk}.building_area_m2`].value; const items = [];
      if (r.max_storeys != null) items.push({ what: "storeys", value: storeys, cap: r.max_storeys, headroom: r.max_storeys - storeys, unit: "storeys" });
      if (r.max_height_m != null) items.push({ what: "height to top floor", value: height, cap: r.max_height_m, headroom: +(r.max_height_m - height).toFixed(2), unit: "m" });
      let cap = null; if (r.max_area_by_storeys_streets) cap = (r.max_area_by_storeys_streets[String(storeys)] || {})[String(b.site.streets_faced)]; else if (r.max_area_by_storeys) cap = r.max_area_by_storeys[String(storeys)];
      if (cap) items.push({ what: "building area", value: area, cap, headroom: Math.round(cap - area), unit: "m²" });
      let nxt = null; if (r.max_storeys != null) { const more = evals.map(x => evaluate(x.rule, storeys + 1, height + 3.0, area, b.is_sprinklered, b.site.streets_faced, H[`${blk}.basements`].value !== "none")).filter(x => x.qualifies).sort((x, y) => cmpStrict(x.rule, y.rule)); nxt = more.length ? more[0].rule.id : null; }
      out[blk] = { article: govId, title: r.title, items, if_one_more_storey: nxt, qualifying: evals.filter(x => x.qualifies).map(x => x.rule.id), excluded: Object.fromEntries(evals.filter(x => !x.qualifies).map(x => [x.rule.id, x.checks.filter(c => !c[1]).map(c => c[0])])) }; }
    return out;
  }


  // ------------------------------------------------------------------ targets: occupant load, egress, washrooms
  const ceil = x => Math.ceil(x - 1e-9);
  function olFactor(T, z, group, idx) {
    const flags = [];
    if (z.ol_factor_m2) return { f: z.ol_factor_m2, label: `designer factor ${z.ol_factor_m2} m²/person`, flags };
    const text = `${z.name} ${z.description}`.toLowerCase();
    if (group === "C" && new RegExp(T.dwelling_re).test(text) && !text.includes("dormitor")) return { f: null, label: "dwelling units — 2 persons per sleeping room", flags };
    for (const [pat, f, label] of T.ol_rules) {
      if (new RegExp(pat).test(text)) {
        if (f === null && label.includes("mercantile")) { const low = idx == null || idx <= 1; if (idx === 2) flags.push(`${z.name}: second storey — 3.70 applies only with a principal entrance from a pedestrian thoroughfare or parking area, else 5.60`);
          return { f: low ? T.mercantile[0] : T.mercantile[1], label: low ? "mercantile — basements and first storeys" : "mercantile — other storeys", flags }; }
        if (label.includes("not listed")) flags.push(`${z.name}: ${label}`);
        return { f, label, flags };
      }
    }
    if (T.group_default[group]) { const [f, label] = T.group_default[group]; flags.push(`${z.name}: no Table 3.1.17.1 row matched the description — Group ${group} default '${label}' (${f} m²/person) applied`); return { f, label, flags }; }
    if (group === "E") return { f: T.mercantile[0], label: "mercantile — basements and first storeys", flags };
    if (group === "C") return { f: null, label: "dwelling units — 2 persons per sleeping room", flags };
    flags.push(`${z.name}: occupant load factor could not be determined`); return { f: null, label: "unknown", flags };
  }
  function zoneLoad(T, z, group, idx) {
    const { f, label, flags } = olFactor(T, z, group, idx); const ded = z.net_deduction_pct || 0;
    const net = Math.round(z.area_m2 * (1 - ded / 100) * 10) / 10;
    const row = { zone: z.name, group, area: z.area_m2, deduction_pct: ded, net_area: net, factor: f, row: label, flags, dwelling: false };
    if (z.occupant_load != null) return Object.assign(row, { gross: z.occupant_load, net_load: z.occupant_load, basis: "designer count / fixed seats (3.1.17.1.(1)(a),(c))" });
    if (f === null && label.startsWith("dwelling")) { row.dwelling = true;
      if (z.sleeping_rooms != null) { const n = z.sleeping_rooms * 2; return Object.assign(row, { gross: n, net_load: n, basis: `${z.sleeping_rooms} sleeping rooms × 2 (3.1.17.1.(1)(b))` }); }
      const rooms = ceil(net / T.m2_per_sleeping_room), n = rooms * 2; row.flags.push(`${z.name}: sleeping rooms estimated from area — count bedrooms when the plan exists`);
      return Object.assign(row, { gross: n, net_load: n, basis: `≈${rooms} sleeping rooms assumed at ${T.m2_per_sleeping_room} m² each × 2 (3.1.17.1.(1)(b))` }); }
    if (f === null) return Object.assign(row, { gross: 0, net_load: 0, basis: "not determined" });
    return Object.assign(row, { gross: ceil(z.area_m2 / f), net_load: ceil(net / f), basis: `area ÷ ${f} m²/person` });
  }
  function exitsRequired(T, group, area, ol, storeys, spr) {
    if (storeys > 2) return [2, ["building height > 2 storeys — Sentence (2) not available"]];
    if (ol > T.one_exit_max_ol) return [2, [`occupant load ${ol} > 60`]];
    const g = (group === "A1" || group === "A2") ? "A" : (group === "B2" ? "B" : (group || "C"));
    if (spr) { const cap = T.one_exit_b[g]; if (cap && area <= cap) return [1, [`one exit permitted: ≤ 2 storeys, load ${ol} ≤ 60, floor area ${area} ≤ ${cap} m² (Table 3.4.2.1.-B), travel ≤ 25 m`]]; return [2, [`floor area ${area} m² > ${cap} m² (Table 3.4.2.1.-B)`]]; }
    const cap = T.one_exit_a[g]; if (cap && area <= cap[0]) return [1, [`one exit permitted: ≤ 2 storeys, load ${ol} ≤ 60, floor area ${area} ≤ ${cap[0]} m², travel ≤ ${cap[1]} m (Table 3.4.2.1.-A)`]];
    return [2, [`floor area ${area} m² > ${cap ? cap[0] : "—"} m² (Table 3.4.2.1.-A)`]];
  }
  function travelLimit(groups, spr, text) {
    if (spr) { if (groups.has("F3") && /parking|parkade|garage/.test(text)) return [60, "(1)(e) storage garage conforming to 3.2.2.92 (else 45 m sprinklered)"]; return [45, "(1)(c) sprinklered throughout"]; }
    if (groups.size === 1 && groups.has("D")) return [40, "(1)(b) business and personal services"];
    return [30, "(1)(f) any other floor area, not sprinklered"];
  }
  function exitWidths(T, ol, n, above) {
    const dAgg = ol * T.mm_per_person.door, sAgg = ol * T.mm_per_person.stair, per = Math.max(n, 1); const sMin = above > 2 ? T.min_width.stair_high : T.min_width.stair_low;
    return { door_aggregate_mm: ceil(dAgg), stair_aggregate_mm: ceil(sAgg), door_each_mm: Math.max(T.min_width.door, ceil(dAgg / per)), stair_each_mm: Math.max(sMin, ceil(sAgg / per)), corridor_min_mm: T.min_width.corridor, stair_min_mm: sMin, note: "stair rise ≤ 180 / run ≥ 280 assumed (8 mm/person); 9.2 mm/person otherwise" };
  }
  function wcAssembly(T, n) { for (const [cap, m, f] of T.table_a) if (n <= cap) return [m, f]; return [7 + ceil((n - 400) / 200), 13 + ceil((n - 400) / 100)]; }
  function wcBusiness(n) { return n <= 25 ? 1 : n <= 50 ? 2 : 3 + ceil((n - 50) / 50); }
  function wcIndustrial(n) { for (const [cap, v] of [[10, 1], [25, 2], [50, 3], [75, 4], [100, 5]]) if (n <= cap) return v; return 6 + ceil((n - 100) / 30); }
  function washroomsFor(T, group, ol, area, text, du, isDwelling) {
    const n = ceil(ol / 2); const out = { group, load: ol, each_sex: n, male_wc: null, female_wc: null, rule: "", sentence: null, alternatives: [], lavatories: null, urinals_max: null };
    if (ol === 0) { out.rule = "no occupant load"; return out; }
    const set = (m, f, rule, s) => Object.assign(out, { male_wc: m, female_wc: f, rule, sentence: s });
    if (group === "C") { if (isDwelling) return Object.assign(out, { rule: "at least one water closet per dwelling unit", sentence: 9, dwelling_units: du, wc_total: du }); set(ceil(n / 10), ceil(n / 10), "residential (not dwelling units): 1 per 10 persons of each sex", 8); }
    else if (group === "B2") set(ceil(n / 10), ceil(n / 10), "care occupancy: 1 per 10 persons of each sex", 8);
    else if (group === "A1" || group === "A2") {
      if (/worship|church|mosque|temple|synagogue|chapel|undertak|funeral/.test(text)) set(ceil(n / 150), ceil(n / 150), "place of worship / undertaking premises: 1 per 150 of each sex", 6);
      else if (/daycare|day care|primary school|elementary/.test(text)) set(ceil(n / 30), ceil(n / 25), "primary school / daycare: 1 per 30 males, 1 per 25 females", 5);
      else { const [m, f] = wcAssembly(T, n); set(m, f, "assembly — Table 3.7.2.2.-A", 4); }
      if (ol > 60 && ol <= 100) out.alternatives.push("3 unisex toilet rooms (1 WC + 1 lavatory each, one accessible) may serve 61–100 persons (3.7.2.2.(16))");
    } else if (group === "D") { const m = wcBusiness(n); set(m, m, "business and personal services — Table 3.7.2.2.-B", 10); }
    else if (group === "E") { set(ceil(n / 300), ceil(n / 150), "mercantile: 1 per 300 males, 1 per 150 females", 11); if (area <= 500) out.alternatives.push("suite ≤ 500 m²: may be based on staff only, Table 3.7.2.2.-B (3.7.2.2.(14))"); }
    else { const m = wcIndustrial(n); set(m, m, "industrial — Table 3.7.2.2.-C", 12); if (/parking|parkade|garage/.test(text)) out.alternatives.push("storage garage: load may be based on staff only (3.7.2.1.(2))"); }
    if (group !== "C" && ol <= 25) out.alternatives.push("load ≤ 25: one water closet may serve both sexes (3.7.2.2.(2))");
    if (group !== "C" && group !== "B2" && area <= 200 && ol <= 60) out.alternatives.push("suite ≤ 200 m² and ≤ 60 persons: 2 unisex toilet rooms (1 WC + 1 lavatory each, one accessible) (3.7.2.2.(15))");
    if (out.male_wc !== null) { const m = out.male_wc; out.urinals_max = m === 2 ? 1 : Math.floor(m * 2 / 3); out.lavatories = { male: ceil(m / 2), female: ceil(out.female_wc / 2) }; out.wc_total = m + out.female_wc; }
    return out;
  }
  function genderNeutral(ol) { if (ol <= 200) return [0, `non-residential load ${ol} ≤ 200 — not triggered`]; const n = 1 + ceil((ol - 200) / 100); return [n, `1 + (${ol} − 200) ÷ 100 → ${n} water closets in gender-neutral facilities, at least one accessible`]; }

  function targets(b, hd, DATA) {
    const T = DATA.targets; const H = Object.fromEntries(hd.map(d => [d.key, d])); const out = [], tg = {}; let siteG = 0, siteN = 0;
    const c3117 = clause(DATA, "3.1.17.1");
    for (const blk of b.blocks) {
      const storeys = b.storeys.filter(s => s.block === blk && !s.is_roof).sort((a, c) => a.elevation_m - c.elevation_m);
      const first = H[`${blk}.first_storey`] ? H[`${blk}.first_storey`].value : null; const bh = H[`${blk}.building_height_storeys`] ? H[`${blk}.building_height_storeys`].value : storeys.length;
      const labels = storeys.map(s => s.label); const fi = Math.max(0, labels.indexOf(first)); const idx = Object.fromEntries(labels.map((l, i) => [l, i - fi + 1]));
      let bg = 0, bn = 0; const rows = [];
      for (const s of storeys) {
        const zrows = [], flags = [], loads = {}, areas = {}, texts = {}; let du = 0, dwAny = false, dwKnown = true;
        for (const z of s.zones) { const g = z.occupancy; const r = zoneLoad(T, z, g, idx[s.label]); flags.push(...r.flags); delete r.flags; zrows.push(r);
          if (g) { loads[g] = (loads[g] || 0) + r.net_load; areas[g] = (areas[g] || 0) + z.area_m2; texts[g] = (texts[g] || "") + ` ${z.name} ${z.description}`.toLowerCase(); if (r.dwelling) { dwAny = true; if (z.dwelling_units != null) du += z.dwelling_units; else dwKnown = false; } } }
        const gross = zrows.reduce((a, r) => a + r.gross, 0), net = zrows.reduce((a, r) => a + r.net_load, 0); bg += gross; bn += net;
        const floorArea = Math.round(s.area * 10) / 10; const groups = new Set(Object.keys(loads));
        const dom = Object.keys(loads).length ? Object.keys(loads).reduce((a, g) => areas[g] > areas[a] ? g : a) : null;
        const alltext = Object.values(texts).join(" ");
        const [nEx, why] = exitsRequired(T, dom, floorArea, net, bh, b.is_sprinklered); const [td, tdWhy] = travelLimit(groups, b.is_sprinklered, alltext);
        const above = Math.max(0, (idx[s.label] || 1) - 1); const w = exitWidths(T, net, nEx, above);
        const wash = Object.keys(loads).filter(g => loads[g] > 0).sort().map(g => washroomsFor(T, g, loads[g], areas[g], texts[g], (dwKnown && du) ? du : null, dwAny && g === "C"));
        rows.push({ label: s.label, index_above_grade: idx[s.label], floor_area: floorArea, gross, net, rows: zrows, exits: nEx, exits_why: why, travel_m: td, travel_why: tdWhy, widths: w, washrooms: wash, groups: [...groups].sort(), flags });
        out.push(D(`${blk}.${s.label}.occupant_load`, `Occupant load — ${s.label}`, net, { unit: "persons", block: blk, clauses: [c3117], inputs: { gross, net, rows: zrows },
          because: `${zrows.length} area(s): ` + zrows.map(r => r.factor ? `${r.zone} ${r.net_area} m² ÷ ${r.factor} = ${r.net_load}` : `${r.zone} ${r.net_load} (${r.basis})`).join("; ") + (gross !== net ? `. Gross (no deductions) ${gross}.` : ""), flags }));
        out.push(D(`${blk}.${s.label}.egress`, `Egress — ${s.label}`, `${nEx} exit${nEx > 1 ? "s" : ""} · travel ≤ ${td} m · stair ${w.stair_each_mm} mm · door ${w.door_each_mm} mm`, { block: blk,
          clauses: [clause(DATA, "3.4.2.1", nEx === 2 ? 1 : 2), clause(DATA, "3.4.2.5", 1), clause(DATA, "3.4.3.2", 1), clause(DATA, "3.4.3.2", 8)], inputs: Object.assign({ floor_area: floorArea, load: net, building_storeys: bh, exits: nEx, travel_m: td }, w),
          because: `Exits: ${why.join("; ")}. Travel distance: ${tdWhy}. Width: ${net} persons × 8 mm = ${w.stair_aggregate_mm} mm aggregate stair ÷ ${nEx}, min ${w.stair_min_mm} mm (Table 3.4.3.2.-A); doors ${net} × 6.1 mm = ${w.door_aggregate_mm} mm aggregate, min 850 mm each; corridors ≥ 1 100 mm.`,
          flags: nEx === 2 ? [] : ["single exit: travel distance also limited by 3.4.2.1.(2) (25 m sprinklered / Table -A)"] }));
        if (wash.length) { const bits = wash.map(x => x.male_wc !== null ? `Group ${x.group} (${x.load} p.): ${x.male_wc} M + ${x.female_wc} F water closets, ${x.lavatories.male}+${x.lavatories.female} lavatories` : (x.group === "C" && x.rule.startsWith("at least one") ? `Group C: ≥ 1 water closet per dwelling unit` + (x.dwelling_units ? ` (${x.dwelling_units} units)` : "") : null)).filter(Boolean);
          out.push(D(`${blk}.${s.label}.washrooms`, `Washrooms — ${s.label}`, bits.join("; ") || "—", { block: blk, clauses: [...wash.filter(x => x.sentence).map(x => clause(DATA, "3.7.2.2", x.sentence)), clause(DATA, "3.7.2.3", 1)], inputs: { by_group: wash },
            because: wash.every(x => x.male_wc === null) ? "Each dwelling unit has its own water closet (3.7.2.2.(9)); no common washrooms required by 3.7.2." : "Persons of each sex = load ÷ 2 (3.7.2.2.(1)); lavatories 1 per 2 water closets (3.7.2.3.(1)); urinals may replace up to ⅔ of male water closets (3.7.2.2.(3)).", flags: wash.flatMap(x => x.alternatives) })); }
      }
      siteG += bg; siteN += bn;
      out.push(D(`${blk}.occupant_load_total`, "Occupant load — building", bn, { unit: "persons", block: blk, clauses: [c3117], inputs: { gross: bg, net: bn }, because: `Sum of storeys. Gross ${bg}, designed (net) ${bn}.` }));
      let egress = null; if (rows.length) { const gov = rows.reduce((a, r) => r.net > a.net ? r : a); const nEx = Math.max(...rows.map(r => r.exits)); const w = exitWidths(T, gov.net, nEx, Math.max(0, Math.max(...rows.map(r => r.index_above_grade || 1)) - 1));
        egress = { exits: nEx, governing_storey: gov.label, governing_load: gov.net, stair_each_mm: w.stair_each_mm, door_each_mm: w.door_each_mm, travel_m: Math.min(...rows.map(r => r.travel_m)) };
        out.push(D(`${blk}.egress`, "Exit stairs — building", nEx, { unit: "exit stairs", block: blk, clauses: [clause(DATA, "3.4.2.1", 1), clause(DATA, "3.4.3.2", 4)], inputs: egress, because: `Exit width need not be cumulative between storeys (3.4.3.2.(4)): size each stair for the busiest storey, ${gov.label} at ${gov.net} persons → ${w.stair_each_mm} mm clear per stair.` })); }
      const nonRes = rows.reduce((a, st) => a + st.rows.filter(r => r.group && r.group !== "C").reduce((x, r) => x + r.net_load, 0), 0); const [gn, gnWhy] = genderNeutral(nonRes);
      out.push(D(`${blk}.gender_neutral_wc`, "Gender-neutral washroom (VBBL)", gn, { unit: "water closets", block: blk, clauses: [clause(DATA, "3.7.2.9", 1)], inputs: { non_residential_load: nonRes }, because: gnWhy, flags: gn ? ["Vancouver-specific provision — not in BCBC 2024"] : [] }));
      tg[blk] = { storeys: rows, total: { gross: bg, net: bn }, egress, gender_neutral: { wc: gn, non_residential_load: nonRes } };
    }
    out.push(D("site.occupant_load_total", "Occupant load — project", siteN, { unit: "persons", clauses: [c3117], inputs: { gross: siteG, net: siteN }, because: `All buildings. Gross ${siteG}, designed (net) ${siteN}.` }));
    tg._site = { gross: siteG, net: siteN };
    return { dets: out, targets: tg };
  }

  // ------------------------------------------------------------------ zoning (Zoning and Development By-law No. 3575) — mirrors codesheet/zoning.py
  const Z_SERVICE_RE = SERVICE_RE;
  const zr = (x, nd) => Math.floor(+x.toFixed(6) * 10 ** nd + 0.5 + 1e-9) / 10 ** nd;   // round half up after a 6-decimal snap — same as zoning.py _r()
  const r2 = v => zr(v, 2), r1 = v => zr(v, 1);
  const g_ = v => (typeof v === "number" ? (+v.toPrecision(6)).toString() : String(v));            // Python's :g, near enough
  const n0 = v => Math.round(v).toLocaleString("en-US");
  function normalizeCode(code) { if (!code) return null; const c = String(code).replace(/\s*\(.*\)\s*$/, "").trim().toUpperCase(); return c || null; }
  function tableEntry(Z, code) { const c = normalizeCode(code) || ""; return Z.districts[Z.aliases[c] || c] || null; }
  function districtRules(Z, code) {
    const c = normalizeCode(code); if (!c) return [null, []];
    const notes = []; let key = c;
    if (!Z.districts[key] && Z.aliases[key]) { const target = Z.aliases[key]; const note = Z.alias_note[key] || Object.entries(Z.alias_note).map(([k, v]) => Z.aliases[k] === target ? v : null).find(Boolean); if (note) notes.push(note); key = target; }
    const d = Z.districts[key]; if (!d) return [null, [`${c} is not in the district table (encoded: ${Object.keys(Z.districts).join(", ")}). Enter its limits in the Lot panel.`]];
    const r = { district: c, label: d.label, uses: Object.assign({}, d.uses), height_m: d.height_m, height_m_conditional: d.height_m_conditional, max_storeys: d.max_storeys, max_storeys_conditional: d.max_storeys_conditional,
      fsr: d.fsr, fsr_conditional: d.fsr_conditional, coverage_pct: d.coverage_pct, front_m: d.front_m, side_m: d.side_m, side_pct: d.side_pct, flank_m: d.flank_m, rear_m: d.rear_m, min_site_m2: d.min_site_m2, min_frontage_m: d.min_frontage_m, toa: null, designer_edited: false, source: d.schedule };
    return [r, notes];
  }
  function resolveZoning(Z, lot) {
    const given = lot.zoning_rules || null; const code = (given && given.district) || lot.zoning || null;
    const [table, notes] = districtRules(Z, code); const entry = tableEntry(Z, code) || {};
    if (!given) return [table, entry, notes];
    const merged = Object.assign({}, table || {}); for (const [k, v] of Object.entries(given)) if (v !== null && v !== undefined && k !== "uses") merged[k] = v;
    merged.uses = (given.uses && Object.keys(given.uses).length) ? given.uses : (table ? table.uses : {}); merged.district = normalizeCode(code);
    if (given.designer_edited) notes.push("Zoning limits were entered by the designer; the district table was not used for those figures.");
    return [merged, entry, notes];
  }
  function lotPoints(lot) { return lot.polygon ? lot.polygon.map(p => [p[0], p[1]]) : [[0, 0], [lot.width_m, 0], [lot.width_m, lot.depth_m], [0, lot.depth_m]]; }
  function orientation(pts) { let s = 0; for (let i = 0; i < pts.length; i++) { const p = pts[i], q = pts[(i + 1) % pts.length]; s += p[0] * q[1] - q[0] * p[1]; } return s >= 0 ? 1 : -1; }
  function signedInside(p, a, b, orient) { const ux = b[0] - a[0], uy = b[1] - a[1]; const L = Math.hypot(ux, uy) || 1; return orient * ((ux * (p[1] - a[1]) - uy * (p[0] - a[0])) / L); }
  function edgeRoles(lot) {
    const segs = lotBoundary(lot); const kinds = segs.map(s => s.kind.kind);
    let front = kinds[0] === "street" ? 0 : kinds.findIndex(k => k === "street"); if (front < 0) front = 0;
    const fa = segs[front].a, fb = segs[front].b; const fL = Math.hypot(fb[0] - fa[0], fb[1] - fa[1]) || 1; const fdir = [(fb[0] - fa[0]) / fL, (fb[1] - fa[1]) / fL];
    let best = null; segs.forEach((s, i) => { if (i === front) return; const L = Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) || 1; const dot = (s.b[0] - s.a[0]) / L * fdir[0] + (s.b[1] - s.a[1]) / L * fdir[1]; const score = dot - (s.kind.kind === "lane" ? 0.3 : 0); if (best === null || score < best[0]) best = [score, i]; });
    const rear = best ? best[1] : null;
    return segs.map((s, i) => ({ a: s.a, b: s.b, kind: s.kind.kind, label: s.label, role: i === front ? "front" : i === rear ? "rear" : ((s.kind.kind === "street" || s.kind.kind === "lane") ? "flank" : "side") }));
  }
  function zTier(value, outright, conditional, toa) {
    const caps = [outright, conditional, toa].filter(c => c !== null && c !== undefined); if (!caps.length) return ["unlimited", null];
    const cap = Math.max(...caps);
    if (outright != null && value <= outright + 1e-9) return ["outright", cap];
    if (conditional != null && value <= conditional + 1e-9) return ["conditional", cap];
    if (toa != null && value <= toa + 1e-9) return ["toa", cap];
    return ["exceeds", cap];
  }
  const Z_TIER_WORDS = { outright: "within the outright limit", conditional: "above the outright limit but within the conditional maximum (Director of Planning approval)", toa: "above the district's limits but within the Transit-Oriented Area minimum the City may not refuse", exceeds: "EXCEEDS the district maximum — a rezoning or variance", unlimited: "no limit encoded" };
  function zoning(spec, b, hd, DATA) {
    const Z = DATA.zoning; const lot = spec.lot; const [rules, entry, notes] = resolveZoning(Z, lot); const H = Object.fromEntries(hd.map(d => [d.key, d]));
    const zc = (what) => { const sec = (entry.sections || {})[what]; const name = rules && rules.district && rules.district !== "CD-1" ? `${rules.district} District Schedule` : "CD-1 By-law for the site"; return { id: `${name}${sec ? " " + sec : ""}`, page: null, edition: Z.edition }; };
    const sitePts = lotPoints(lot); const siteArea = r1(polyArea(sitePts)); const out = [];
    const summary = { district: normalizeCode(rules ? rules.district : lot.zoning), label: rules ? rules.label : null, site_area_m2: siteArea, items: [], yards: [], uses: [], notes: [], status: null, source: rules ? rules.source : null, designer_edited: !!(rules && rules.designer_edited) };
    if (!rules) {
      const d = D("site.zoning.district", "Zoning district", lot.zoning || null, { clauses: [{ id: "Zoning District Plan", page: null, edition: Z.edition }],
        because: !lot.zoning ? "No zoning district is set for this lot. Pick one in the Lot panel (or a site from the map) to check height, FSR, coverage, yards and uses against its schedule." : `District '${lot.zoning}' is not in the table; enter its limits in the Lot panel.`,
        flags: ["Zoning not checked: no district or limits for this lot."].concat(notes) });
      out.push(d); summary.status = "unknown"; summary.notes = d.flags; return { dets: out, zoning: summary };
    }
    const unverified = entry.unverified || []; const genFlags = notes.slice();
    for (const f of unverified) genFlags.push(`${rules.district}: the ${f.replace("_m", " (m)").replace("_pct", " (%)").replace(/_/g, " ")} figure is transcribed but not verified against the current schedule — confirm it.`);
    const toa = rules.toa ? Z.toa.tiers[rules.toa] : null;
    out.push(D("site.zoning.district", "Zoning district", rules.district, { clauses: [zc("uses")],
      because: `${rules.label || ""}. Limits from ${rules.source || "the designer"}${rules.designer_edited ? " (designer-edited)" : ""}.` + (toa ? ` TOA tier applied: ${toa.label} — at least ${toa.min_storeys} storeys and FSR ${g_(toa.min_fsr)} may not be refused.` : "") + " " + (entry.notes || []).join(" "), flags: genFlags }));
    // uses
    const o2u = Z.occupancy_to_use;
    for (const blk of b.blocks) {
      const groups = []; for (const s of b.storeys.filter(s => s.block === blk).sort((x, y) => x.elevation_m - y.elevation_m)) for (const z of s.zones) if (z.occupancy && !groups.includes(z.occupancy)) groups.push(z.occupancy);
      const parts = [], flags = []; const hasUses = Object.keys(rules.uses || {}).length > 0;
      for (const g of groups) { const use = o2u[g] || "other"; let tier = hasUses ? (rules.uses[use] || null) : null; if (use === "parking") tier = tier || "outright"; const note = (entry.use_notes || {})[use];
        if (!hasUses) parts.push(`Group ${g} → ${use}: uses not encoded`);
        else if (tier) parts.push(`Group ${g} → ${use}: ${tier}` + (note ? ` (${note})` : ""));
        else { parts.push(`Group ${g} → ${use}: NOT a listed use`); flags.push(`${blk}: Group ${g} (${Z.use_classes[use] || use}) is not a listed use in ${rules.district} — a rezoning, or a different use.`); }
        if (tier === "conditional" && hasUses) flags.push(`${blk}: ${Z.use_classes[use] || use} is a conditional approval use in ${rules.district} — Director of Planning discretion, design guidelines apply.`); }
      const notOk = parts.some(p => p.includes("NOT a listed"));
      summary.uses.push({ block: blk, groups, ok: !notOk, text: parts.join("; ") });
      out.push(D(`site.zoning.uses.${blk}`, `Permitted uses — ${blk}`, notOk ? "not permitted" : (parts.some(p => p.includes(": conditional")) ? "conditional" : (hasUses ? "outright" : "not encoded")), { block: blk, clauses: [zc("uses")], because: parts.join("; ") + ".", flags }));
    }
    const item = (what, value, outright, conditional, unit, key, because, toaCap, extraFlags, clauseKey) => {
      const [tier, cap] = zTier(value, outright, conditional, toaCap == null ? null : toaCap);
      const it = { what, value, outright: outright == null ? null : outright, conditional: conditional == null ? null : conditional, toa: toaCap == null ? null : toaCap, cap, unit, status: tier, headroom: cap === null ? null : (unit === "storeys" ? cap - value : r2(cap - value)) };
      summary.items.push(it);
      const lim = [outright != null ? `outright ${g_(outright)}` : null, conditional != null ? `conditional ${g_(conditional)}` : null, toaCap != null ? `TOA ${g_(toaCap)}` : null].filter(Boolean).join(" / ");
      const flags = (extraFlags || []).slice();
      if (tier === "exceeds") flags.push(`${what} ${g_(value)} ${unit} exceeds the ${rules.district} maximum (${lim}).`);
      else if (tier === "conditional") flags.push(`${what} ${g_(value)} ${unit} relies on the conditional maximum (${lim}) — Director of Planning approval.`);
      out.push(D(`site.zoning.${key}`, `Zoning — ${what}`, value, { unit, clauses: [zc(clauseKey || key)], because: `${because} Limit: ${lim || "none encoded"}: ${Z_TIER_WORDS[tier]}.`, inputs: { cap, status: tier }, flags }));
    };
    // height
    const g = lot.grade_m; const hbits = []; let worst = 0, parapetOver = false;
    for (const blk of spec.blocks) { const roof = b.storeys.find(s => s.block === blk.name && s.is_roof); if (!roof) continue; const hroof = r2(roof.elevation_m - g); const par = (blk.roof || {}).parapet_m != null ? blk.roof.parapet_m : 0.6; const enc = (blk.roof || {}).enclosure; worst = Math.max(worst, hroof);
      let txt = `${blk.name}: roof ${g_(hroof)} m above grade` + (par ? `, parapet to ${(hroof + par).toFixed(2)} m` : "");
      if (enc && Z_SERVICE_RE.test(enc.use.toLowerCase())) txt += `, service penthouse to ${(hroof + enc.height_m).toFixed(2)} m (excluded; Section 10.1.1 lets the Director of Planning permit elevator machine rooms and mechanical above the limit)`;
      hbits.push(txt); const capsH = [rules.height_m, rules.height_m_conditional].filter(c => c != null); const capH = capsH.length ? Math.max(...capsH) : null; if (capH !== null && hroof <= capH + 1e-9 && capH < hroof + par) parapetOver = true; }
    const hflags = []; if (parapetOver) hflags.push("The parapet rises above the height limit while the roof does not — confirm it is a permitted projection.");
    if (toa) hflags.push("TOA minimums are set in storeys; the height limit in metres for a Transit-Oriented Area comes from the TOA designation by-law — confirm.");
    item("height", r2(worst), rules.height_m, rules.height_m_conditional, "m", "height", "Highest roof above grade (massing grade, not the zoning base surface). " + hbits.join("; ") + ".", null, hflags);
    // storeys
    const stMax = Math.max(0, ...b.blocks.map(blk => H[`${blk}.building_height_storeys`] ? H[`${blk}.building_height_storeys`].value : 0));
    if (rules.max_storeys != null || rules.max_storeys_conditional != null || toa) item("storeys", stMax, rules.max_storeys, rules.max_storeys_conditional, "storeys", "storeys", `Tallest block: ${stMax} storeys in building height (Part 3 count; zoning counts storeys from the base surface, so a half-basement may differ).`, toa ? toa.min_storeys : null, [], "height");
    // FSR
    let floorArea = 0; const fbits = [], tall = [];
    for (const blk of b.blocks) { const fs = H[`${blk}.first_storey`]; const st = b.storeys.filter(s => s.block === blk && !s.is_roof).sort((x, y) => x.elevation_m - y.elevation_m); const fsEl = (fs && st.find(s => s.label === fs.value)) ? st.find(s => s.label === fs.value).elevation_m : (st.length ? st[0].elevation_m : g);
      const above = st.filter(s => s.elevation_m >= fsEl - 0.01); const a = above.reduce((x, s) => x + s.area, 0); floorArea += a; fbits.push(`${blk} ${above.map(s => s.label).join(", ")}: ${n0(a)} m²`);
      for (const s of above) if (s.height_m > Z.fsr_double_count_f2f_m + 1e-9) tall.push(`${blk} ${s.label} (${g_(s.height_m)} m)`); }
    floorArea = r1(floorArea); const fsr = siteArea ? r2(floorArea / siteArea) : 0;
    const fflags = ["Gross floor area from the storey outlines: zoning exclusions (below-grade parking, balconies up to the permitted share, some amenity and stair/elevator areas) are not deducted, so the FSR shown is conservative."];
    if (tall.length) fflags.push(`Floor-to-floor over ${g_(Z.fsr_double_count_f2f_m)} m may be counted twice in the FSR computation of many schedules: ${tall.join(", ")} — confirm.`);
    item("floor space ratio", fsr, rules.fsr, rules.fsr_conditional, "FSR", "fsr", `Above-grade floor area ${n0(floorArea)} m² ÷ site area ${n0(siteArea)} m² = ${g_(fsr)}. ` + fbits.join("; ") + ".", toa ? toa.min_fsr : null, fflags);
    summary.floor_area_m2 = floorArea;
    // coverage
    let covArea = 0; const cbits = [];
    for (const blk of b.blocks) { const st = b.storeys.filter(s => s.block === blk && !s.is_roof); const a = st.length ? Math.max(...st.map(s => s.area)) : 0; covArea += a; cbits.push(`${blk} ${n0(a)} m²`); }
    const cov = siteArea ? r1(100 * covArea / siteArea) : 0;
    if (rules.coverage_pct != null) item("site coverage", cov, rules.coverage_pct, null, "%", "coverage", `Largest footprint of each block (${cbits.join("; ")}) = ${n0(covArea)} m² of ${n0(siteArea)} m².`, null, []);
    summary.coverage_pct = cov;
    // yards
    const W = lot.width_m; const sideCands = [rules.side_m, rules.side_pct ? rules.side_pct * W / 100 : null].filter(x => x != null);
    const req = { front: rules.front_m == null ? null : rules.front_m, rear: rules.rear_m == null ? null : rules.rear_m, side: sideCands.length ? Math.max(...sideCands) : null, flank: rules.flank_m == null ? null : rules.flank_m };
    if (req.flank === null) req.flank = req.side;
    const orient = orientation(sitePts); const footprints = []; for (const blk of spec.blocks) for (const st of blk.storeys) footprints.push((st.footprint || blk.footprint).map(p => [p[0], p[1]]));
    const roles = edgeRoles(lot);
    for (const e of roles) { const need = req[e.role]; let measured = null; for (const fp of footprints) for (const p of fp) { const d = signedInside(p, e.a, e.b, orient); if (measured === null || d < measured) measured = d; } if (measured === null) continue; measured = r2(measured);
      const role = { front: "front yard", rear: "rear yard", side: "side yard", flank: "flanking side yard (street side)" }[e.role]; const ok = need === null ? null : measured + 1e-9 >= need;
      summary.yards.push({ edge: e.label, kind: e.kind, role: e.role, measured_m: measured, required_m: need, ok });
      const flags = []; if (ok === false) flags.push(`${role} on the ${e.label} (${e.kind}): ${g_(measured)} m provided, ${g_(need)} m required — short by ${(need - measured).toFixed(2)} m.`);
      if (e.role === "flank" && rules.flank_m == null && need !== null) flags.push(`Corner lot: the ${e.label} side faces a ${e.kind}; the schedule may set a different flanking yard — the side yard ${g_(need)} m was used.`);
      out.push(D(`site.zoning.yard.${e.label.replace(/ /g, "_")}`, `Zoning — ${role}, ${e.label}`, measured, { unit: "m", clauses: [zc("yards")], because: `Closest storey outline to the ${e.label} lot line (${e.kind}) is ${g_(measured)} m inside it. ` + (need !== null ? `Minimum ${role} ${g_(need)} m: ${ok ? "OK" : "SHORT"}.` : `No minimum ${role} encoded for ${rules.district}.`), inputs: { required_m: need, ok }, flags })); }
    // site
    if (rules.min_site_m2 != null || rules.min_frontage_m != null) { const front = roles.find(e => e.role === "front"); const frontage = front ? r2(Math.hypot(front.b[0] - front.a[0], front.b[1] - front.a[1])) : W; const bits = [], flags = [];
      if (rules.min_site_m2 != null) { bits.push(`site area ${n0(siteArea)} m² vs minimum ${g_(rules.min_site_m2)} m²`); if (siteArea + 1e-9 < rules.min_site_m2) flags.push(`Site area ${n0(siteArea)} m² is below the ${rules.district} minimum of ${g_(rules.min_site_m2)} m² for this form.`); }
      if (rules.min_frontage_m != null) { bits.push(`frontage ${g_(frontage)} m vs minimum ${g_(rules.min_frontage_m)} m`); if (frontage + 1e-9 < rules.min_frontage_m) flags.push(`Frontage ${g_(frontage)} m is below the ${rules.district} minimum of ${g_(rules.min_frontage_m)} m.`); }
      out.push(D("site.zoning.site", "Zoning — site area and frontage", flags.length ? "below minimum" : "OK", { clauses: [zc("site")], because: bits.join("; ") + ".", flags })); summary.site = { area_m2: siteArea, frontage_m: frontage, ok: !flags.length }; }
    const statuses = summary.items.map(i => i.status).concat(summary.yards.filter(y => y.ok === false).map(() => "exceeds"), summary.uses.filter(u => !u.ok).map(() => "exceeds"));
    summary.status = ["exceeds", "toa", "conditional", "outright", "unlimited"].find(s => statuses.includes(s)) || "outright";
    summary.notes = (entry.notes || []).concat(notes); summary.flag_count = out.reduce((a, d) => a + d.flags.length, 0);
    return { dets: out, zoning: summary };
  }

  // ------------------------------------------------------------------ entry point
  function analyzeMassing(spec, DATA) {
    const b = toBuilding(spec);
    const hd = heightArea(b, DATA), od = occupancy(b, DATA);
    const { dets: ad, ladder } = articles(b, hd, od, DATA, spec.chosen_articles);
    const groups = Object.fromEntries(od.filter(d => d.key.endsWith("major_occupancies")).map(d => [d.block, d.value[0] || "C"]));
    const { dets: sp, faces } = spatial(b, DATA, groups); const sd = separations(b, ad, DATA);
    const { dets: td, targets: tg } = targets(b, hd, DATA);
    const { dets: zd, zoning: zs } = zoning(spec, b, hd, DATA);
    const all = [...hd, ...od, ...ad, ...sp, ...sd, ...td, ...zd];
    const flagSet = new Map(); for (const d of all) for (const f of d.flags) flagSet.set(`${d.block || "site"}|${f}`, [d.block || "site", f]);
    const summary = {}; for (const blk of b.blocks) { const g = k => { const d = all.find(x => x.key === k); return d ? d.value : null; };
      summary[blk] = { storeys: g(`${blk}.building_height_storeys`), area: g(`${blk}.building_area_m2`), height: g(`${blk}.height_to_top_floor_m`), majors: g(`${blk}.major_occupancies`), article: g(`${blk}.article`), construction: g(`${blk}.req.Construction`), floors: g(`${blk}.req.Floor assemblies`) }; }
    return { building: b, targets: tg, zoning: zs, determinations: all, headroom: headroom(b, hd, ad, ladder), faces, flags: [...flagSet.values()].sort((x, y) => (x[0] + x[1]).localeCompare(y[0] + y[1])), summary, ladder: Object.fromEntries(Object.entries(ladder).map(([k, v]) => [k, v.map(e => ({ id: e.rule.id, title: e.rule.title, qualifies: e.qualifies, checks: e.checks, construction: e.rule.construction, floor_frr_h: e.rule.floor_frr_h, roof_frr_h: e.rule.roof_frr_h }))])) };
  }
  root.CodesheetEngine = { analyzeMassing, toBuilding, polyArea, edgeExposure, lotBoundary, edgeRoles, districtRules, normalizeCode };
})(typeof window !== "undefined" ? window : globalThis);
