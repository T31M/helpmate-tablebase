// Pure logic for the Materials page and the front page's contributor block.
import { sortRows } from "./solution.js";

export const STATES = ["open", "claimed", "in review", "done", "not needed"];
const KEYS = ["pieces", "state", "prio", "pawns", "contributor", "q"];

export function priorityLabel(p) { return p ? `P${p}` : "—"; }

function sides(s) {
  const m = /^K([QRBNP?]*)vk([qrbnp?]*)$/.exec(s);
  return m ? [m[1], m[2]] : null;
}
function sideMatch(have, pat) {
  if (have.length !== pat.length) return false;
  const rest = [...have];
  for (const c of pat) {
    if (c === "?") continue;
    const i = rest.indexOf(c);
    if (i < 0) return false;
    rest.splice(i, 1);
  }
  return true;
}
export function wildcardMatch(name, pattern) {
  const p = (pattern || "").trim();
  if (!p) return true;
  if (!p.includes("?")) return name.toLowerCase().includes(p.toLowerCase());
  const n = sides(name), q = sides(p);
  return !!(n && q && sideMatch(n[0], q[0]) && sideMatch(n[1], q[1]));
}

export function mergeStatus(rows, status) {
  const st = status && status.materials ? status.materials : {};
  return rows.map((r) => {
    const s = st[r.material];
    const state = s ? s.state : r.done ? "done" : r.priority === null ? "not needed" : "open";
    return { ...r, state, contributor: s ? s.contributor : null,
      hf_pr: s ? s.hf_pr : null, claim: s ? s.claim : null };
  });
}

const on = (v) => v !== undefined && v !== "" && v !== "all";
export function filterRows(rows, f) {
  return rows.filter((r) =>
    (!on(f.pieces) || String(r.pieces) === String(f.pieces)) &&
    (!on(f.state) || r.state === f.state) &&
    (!on(f.prio) || String(r.priority) === String(f.prio)) &&
    (!on(f.pawns) || String(r.pawns) === String(f.pawns)) &&
    (!on(f.contributor) || r.contributor === f.contributor) &&
    wildcardMatch(r.material, f.q));
}

// Unknown states rank after every known one.
const stateRank = (r) => { const i = STATES.indexOf(r.state); return i < 0 ? 99 : i; };

export function defaultOrder(rows) {
  const rank = stateRank;
  const pr = (r) => (r.priority === null || r.priority === undefined ? 99 : r.priority);
  return [...rows].sort((a, b) => rank(a) - rank(b) || pr(a) - pr(b) || a.pawns - b.pawns ||
    (a.material < b.material ? -1 : a.material > b.material ? 1 : 0));
}

// Column sort for the Materials table: state sorts in STATES order, the rest by value.
export function sortMaterials(rows, key, dir) {
  if (key !== "state") return sortRows(rows, key, dir);
  const s = dir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => (stateRank(a) - stateRank(b)) * s ||
    (a.material < b.material ? -1 : a.material > b.material ? 1 : 0));
}

// status.json is built at deploy time; a malformed one is treated as missing.
export function validStatus(s) {
  const obj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  if (!obj(s) || typeof s.generated_at !== "string" || !obj(s.materials) ||
      !Array.isArray(s.contributors) || !obj(s.counts) || !obj(s.counts.six)) return false;
  return STATES.every((k) => typeof s.counts.six[k] === "number" && Number.isFinite(s.counts.six[k]));
}

export function parseQuery(hash) {
  const i = (hash || "").indexOf("?");
  if (i < 0) return {};
  const out = {};
  for (const [k, v] of new URLSearchParams(hash.slice(i + 1))) if (KEYS.includes(k)) out[k] = v;
  return out;
}
export function toQuery(obj) {
  const p = new URLSearchParams();
  for (const k of KEYS) if (on(obj[k])) p.set(k, obj[k]);
  return p.toString();
}

export function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function contributorCards(status) {
  if (!status || !status.contributors || !status.contributors.length) return "";
  return status.contributors.map((c) => {
    const links = c.anonymous ? "" :
      [c.hf ? `<a href="https://huggingface.co/${encodeURIComponent(c.hf)}">Hugging Face</a>` : "",
       c.github ? `<a href="https://github.com/${encodeURIComponent(c.github)}">GitHub</a>` : ""]
        .filter(Boolean).join(" · ");
    return `<div class="card"><strong>${esc(c.display)}</strong>
      <span>${Number(c.tables)} table${Number(c.tables) === 1 ? "" : "s"}${Number(c.six) ? `, ${Number(c.six)} with six men` : ""}</span>
      ${links ? `<span>${links}</span>` : ""}
      <a href="#/materials?contributor=${encodeURIComponent(c.display)}">their tables →</a></div>`;
  }).join("");
}

export function sixProgress(status, corpus) {
  const s = status && status.counts ? status.counts.six : null;
  const complete = s && STATES.every((k) => Number.isFinite(s[k]));
  if (!complete) return `Six men: ${(corpus.by_pieces || {})[6] || 0} of 645 done.`;
  return `Six men: ${Number(s.done)} done, ${Number(s["in review"])} in review, ` +
    `${Number(s.claimed)} claimed, ${Number(s.open)} open of 645.`;
}
