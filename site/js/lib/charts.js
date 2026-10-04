// Bar charts as SVG strings: no chart library, colours from the page's CSS
// variables (classes bar / part / axis / empty), so dark mode follows the site.

export function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

export function scale(v, max, log) {
  if (!(v > 0) || !(max > 0)) return 0;
  return log ? Math.log10(1 + v) / Math.log10(1 + max) : v / max;
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (v) => (v >= 1e9 ? `${+(v / 1e9).toFixed(1)}G` : v >= 1e6 ? `${+(v / 1e6).toFixed(1)}M`
  : v >= 1e3 ? `${+(v / 1e3).toFixed(1)}k` : `${v}`);

export function barChart({ bars, width = 640, height = 240, log = false, xLabel = "", yLabel = "" }) {
  const open = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(yLabel || "chart")}">`;
  if (!bars.length) return `${open}<text x="${width / 2}" y="${height / 2}" text-anchor="middle" class="empty">no data</text></svg>`;
  const left = 48, bottom = 52, top = 8, plotW = width - left - 8, plotH = height - top - bottom;
  const max = log ? Math.max(...bars.map((b) => b.value), 1) : niceMax(Math.max(...bars.map((b) => b.value)));
  const step = plotW / bars.length, bw = Math.max(1, step * 0.8);
  const y = (v) => top + plotH * (1 - scale(v, max, log));
  let out = open;
  out += `<line class="axis" x1="${left}" y1="${top + plotH}" x2="${left + plotW}" y2="${top + plotH}"/>`;
  out += `<text class="axis" x="4" y="${top + 10}">${esc(fmt(max))}</text>`;
  out += `<text class="axis" x="4" y="${top + plotH}">0</text>`;
  const every = Math.ceil(bars.length / 20);
  bars.forEach((b, i) => {
    const x = left + i * step + (step - bw) / 2;
    const h = top + plotH - y(b.value);
    out += `<g><title>${esc(b.title ?? `${b.x}: ${b.value}`)}</title>`;
    out += `<rect class="bar" x="${x.toFixed(1)}" y="${y(b.value).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}"/>`;
    if (b.part > 0) {
      const ph = b.value > 0 ? h * Math.min(b.part / b.value, 1) : 0;   // true share on both axes
      out += `<rect class="part" x="${x.toFixed(1)}" y="${(top + plotH - ph).toFixed(1)}" width="${bw.toFixed(1)}" height="${ph.toFixed(1)}"/>`;
    }
    out += "</g>";
    if (i % every === 0) out += `<text class="axis" x="${(x + bw / 2).toFixed(1)}" y="${height - 34}" text-anchor="middle">${esc(b.x)}</text>`;
  });
  if (xLabel) out += `<text class="axis" x="${left + plotW / 2}" y="${height - 4}" text-anchor="middle">${esc(xLabel)}</text>`;
  return `${out}</svg>`;
}
