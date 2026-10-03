// #/stats and #/stats/MATERIAL: corpus charts and one material's distribution.
import { barChart } from "./lib/charts.js";
import { depthBars, uniqueShareBars, maxDtmBars, deepest, lookup } from "./lib/stats.js";
import { esc } from "./lib/materials.js";

let S = null;
const state = { stm: "btm", log: true, pieces: "all" };
const decode = (s) => { try { return decodeURIComponent(s); } catch { return s; } };
const $ = (id) => document.getElementById(id);

function drawCorpus() {
  if (!S || !S.materials) return;
  $("stats-total").innerHTML = barChart({ bars: depthBars(S.total[state.stm]), log: state.log,
    xLabel: `depth (plies)${state.log ? " · log scale" : ""}`, yLabel: "positions per depth" });
  $("stats-share").innerHTML = barChart({ bars: uniqueShareBars(S.by_pieces), height: 200,
    xLabel: "pieces · unique share in %", yLabel: "unique share (%)" });
  $("stats-maxdtm").innerHTML = barChart({ bars: maxDtmBars(S.materials, state.pieces),
    xLabel: "maximum DTM (plies)", yLabel: "materials" });
  $("stats-deepest").innerHTML = deepest(S.materials).map((d) =>
    `<li><a href="#/stats/${esc(d.material)}">${esc(d.material)}</a> — ${d.max_dtm} plies</li>`).join("");
}

function drawMaterial(name) {
  if (!S || !S.materials) return;
  const box = $("stats-material");
  const r = lookup(S, name);
  if (!name) { box.innerHTML = ""; return; }
  if (!r.ok) { box.innerHTML = `<p class="status">${esc(name)}: ${esc(r.message)}</p>`; return; }
  const e = r.entry;
  box.innerHTML = `<h3>${esc(name)} — max DTM ${e.max_dtm}</h3>`
    + `<p><a href="material/${esc(name)}.html">material page</a></p>`
    + barChart({ bars: depthBars(e[state.stm]), log: state.log, xLabel: `depth (plies)${state.log ? " · log scale" : ""}`,
      yLabel: `${name} positions per depth` });
}

export function initStats({ stats }) {
  S = stats;
  const names = Object.keys(S.materials).filter((n) => S.materials[n].max_dtm !== null).sort();
  $("stats-names").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
  $("stats-pick").addEventListener("change", (ev) => { location.hash = `#/stats/${ev.target.value.trim()}`; });
  for (const [id, key, on] of [["stats-stm", "stm", "wtm"], ["stats-log", "log", true]]) {
    $(id).addEventListener("change", (ev) => {
      state[key] = key === "log" ? ev.target.checked : (ev.target.checked ? on : "btm");
      drawCorpus();
      drawMaterial(decode(location.hash.split("/")[2] || ""));
    });
  }
  $("stats-pieces").addEventListener("change", (ev) => { state.pieces = ev.target.value; drawCorpus(); });
  drawCorpus();
}

export function showStats(arg) {
  if (!S || !S.materials) return;
  const name = decode(arg || "");
  $("stats-pick").value = name;
  drawMaterial(name);
}
