// Pure transforms from site/data/stats.json to chart bars (tested in node).

export function depthBars(rows) {
  return rows.map(([d, cells, unique]) => ({ x: d, value: cells, part: unique,
    title: `depth ${d}: ${cells.toLocaleString("en")} positions, ${unique.toLocaleString("en")} unique` }));
}

export function uniqueShareBars(byPieces) {
  return Object.keys(byPieces).filter((k) => byPieces[k].solvable > 0).sort((a, b) => a - b).map((k) => {
    const { solvable, unique } = byPieces[k];
    const value = Math.round((unique / solvable) * 10000) / 100;
    return { x: k, value, title: `${k} pieces: ${value}% of solvable positions have one solution` };
  });
}

export function maxDtmBars(materials, pieces) {
  const ds = Object.values(materials)
    .filter((m) => m.max_dtm !== null && (pieces === "all" || String(m.pieces) === pieces))
    .map((m) => m.max_dtm);
  const top = ds.length ? Math.max(...ds) : -1;
  const counts = Array.from({ length: top + 1 }, () => 0);
  for (const d of ds) counts[d] += 1;
  return counts.map((n, d) => ({ x: d, value: n, title: `max DTM ${d}: ${n} materials` }));
}

export function deepest(materials, n = 10) {
  return Object.entries(materials).filter(([, m]) => m.max_dtm !== null)
    .map(([material, m]) => ({ material, max_dtm: m.max_dtm }))
    .sort((a, b) => b.max_dtm - a.max_dtm || a.material.localeCompare(b.material))
    .slice(0, n);
}

export function lookup(stats, name) {
  const entry = name ? stats.materials[name] : undefined;
  if (!entry) return { ok: false, message: "unknown material" };
  if (entry.max_dtm === null) return { ok: false, message: "no helpmate in this material" };
  return { ok: true, entry };
}
