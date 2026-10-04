import { stipulation, humanBytes } from "./lib/solution.js";
import { mergeStatus, filterRows, defaultOrder, sortMaterials, parseQuery, toQuery, priorityLabel, esc }
  from "./lib/materials.js";

const fmt = (n) => Number(n).toLocaleString("en-US");
let rows = [], key = null, dir = "asc", initialised = false;
const TEXT_COLUMNS = new Set(["material", "state", "contributor"]);
const controls = () => [...document.querySelectorAll("#materials-controls [data-f]")];

export function initMaterials({ materials, corpus, status }) {
  rows = mergeStatus(materials, status);
  const six = status && status.counts ? status.counts.six : null;
  document.getElementById("materials-lede").textContent = six
    ? `${corpus.tables} tables published. Six men: ${Number(six.done)} done, ` +
      `${Number(six["in review"])} in review, ${Number(six.claimed)} claimed, ${Number(six.open)} open. Priority P1 has one White piece besides the king — ` +
      `typically the longest, deepest helpmates — so start there.`
    : `${corpus.tables} tables published. Priority P1 has one White piece besides the king — start there.`;
  document.getElementById("materials-asof").textContent = status
    ? `State as of ${status.generated_at.replace("T", " ").replace("Z", " UTC")}.`
    : "State unavailable — showing done from the last build; everything else as open.";
  const who = document.querySelector('#materials-controls [data-f="contributor"]');
  const names = [...new Set(rows.map((r) => r.contributor).filter(Boolean))].sort();
  who.insertAdjacentHTML("beforeend", names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join(""));
  for (const el of controls()) el.addEventListener(el.tagName === "INPUT" ? "input" : "change", onChange);
  document.querySelectorAll("#materials-table th").forEach((th) => th.addEventListener("click", () => {
    if (key === th.dataset.key) dir = dir === "asc" ? "desc" : "asc";
    else { key = th.dataset.key; dir = "asc"; }
    render();
  }));
  initialised = true;
}

export function showMaterials() {
  if (!initialised) return;   // app.js calls this even when init failed
  const q = parseQuery(location.hash);
  for (const el of controls()) {
    const v = q[el.dataset.f] ?? (el.tagName === "INPUT" ? "" : "all");
    // a contributor from the hash with no rows here: offer it, so the view honestly shows 0 rows
    if (el.tagName === "SELECT" && el.dataset.f === "contributor" && ![...el.options].some((o) => o.value === v)) {
      el.insertAdjacentHTML("beforeend", `<option value="${esc(v)}">${esc(v)}</option>`);
    }
    el.value = v;
  }
  render();
}

function current() {
  const f = {};
  for (const el of controls()) f[el.dataset.f] = el.value;
  return f;
}

function onChange() {
  const q = toQuery(current());
  history.replaceState(null, "", `#/materials${q ? `?${q}` : ""}`);   // no hashchange: no re-route
  render();
}

function render() {
  const shown0 = filterRows(rows, current());
  const shown = key ? sortMaterials(shown0, key, dir) : defaultOrder(shown0);
  document.getElementById("materials-count").textContent = `${shown.length} of ${rows.length}`;
  document.querySelectorAll("#materials-table th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.key === key);
    th.classList.toggle("asc", th.dataset.key === key && dir === "asc");
    th.classList.toggle("num", !TEXT_COLUMNS.has(th.dataset.key));
  });
  document.querySelector("#materials-table tbody").innerHTML = shown.map((r) => {
    const cls = esc(String(r.state).replace(/ /g, "-"));
    const name = r.page ? `<a href="material/${esc(r.material)}.html">${esc(r.material)}</a>` : esc(r.material);
    const state = r.state === "in review" && r.hf_pr
      ? `<a href="https://huggingface.co/datasets/osick/helpmate-tables/discussions/${Number(r.hf_pr)}">in review</a>`
      : r.state === "claimed" && r.claim
        ? `<a href="https://github.com/osick/helpmate-tablebase/issues/${Number(r.claim)}">claimed</a>` : esc(r.state);
    const statsLink = r.done ? ` <a class="stats-link" href="#/stats/${esc(r.material)}">stats</a>` : "";
    const marker = r.done && r.max_dtm === null;
    const stat = (v, f) => (r.done ? f(v) : "");
    return `<tr class="state-${cls}">
      <td class="mono">${name}${statsLink}</td><td class="num">${r.pieces}</td>
      <td class="num">${priorityLabel(r.priority)}</td><td class="state-${cls}">${state}</td>
      <td>${esc(r.contributor || "")}</td><td class="num">${r.ram_gib ? `${r.ram_gib} GiB` : ""}</td>
      <td class="num">${r.done ? (marker ? "—" : stipulation(r.max_dtm)) : ""}</td>
      <td class="num">${stat(r.solvable, fmt)}</td><td class="num">${stat(r.unique, fmt)}</td>
      <td class="num">${stat(r.size_bytes, humanBytes)}</td></tr>`;
  }).join("");
}
