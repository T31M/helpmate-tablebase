// Hash-routed single page: #/ (front), #/deepest[/MATERIAL], #/puzzles,
// #/materials. Each screen is a module with init(data) run once on first
// show; data files are fetched once and shared.
import { initFront } from "./front.js";
import { initDeepest, showDeepest } from "./deepest.js";
import { initPuzzles } from "./puzzles.js";
import { initMaterials, showMaterials } from "./materials.js";
import { validStatus } from "./lib/materials.js";

const screens = {
  front: { init: initFront, data: ["corpus", "deepest", "status"] },
  deepest: { init: initDeepest, data: ["deepest"] },
  puzzles: { init: initPuzzles, data: ["puzzles"] },
  materials: { init: initMaterials, data: ["materials", "corpus", "status"] },
};
// Deploy stamp: CI (tools/stamp_site.py) rewrites this exact line to
// `const V = "?v=<commit>";` so data fetches cannot mix with a stale cache.
const V = "";
const loaded = {};
const cache = {};

// status.json is never committed and may be missing or malformed; it is
// optional, and an invalid one counts as missing.
const OPTIONAL = { status: validStatus };

async function data(name) {
  if (!cache[name]) {
    const req = fetch(`data/${name}.json${V}`).then((r) => {
      if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
      return r.json();
    });
    const valid = OPTIONAL[name];
    cache[name] = valid
      ? req.then((v) => {
        if (!valid(v)) throw new Error("malformed");
        return v;
      }).catch((e) => { console.warn(`${name}.json unavailable: ${e.message}`); return null; })
      : req;
  }
  return cache[name];
}

function route() {
  const hash = location.hash.replace(/^#\/?/, "").split("?")[0];
  const [name, ...rest] = hash.split("/");
  return { name: screens[name] ? name : "front", arg: rest.join("/") };
}

async function show() {
  const { name, arg } = route();
  for (const s of Object.keys(screens)) {
    document.getElementById(`screen-${s}`).hidden = s !== name;
  }
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.screen === name));
  if (!loaded[name]) {
    loaded[name] = (async () => {
      const bundle = {};
      for (const d of screens[name].data) bundle[d] = await data(d);
      await screens[name].init(bundle);
    })().catch((err) => {
      document.getElementById(`screen-${name}`).insertAdjacentHTML(
        "afterbegin", `<p class="status bad">Could not load this screen: ${err.message}</p>`);
    });
  }
  await loaded[name];
  if (name === "materials") showMaterials();
  if (name === "deepest" && arg) showDeepest(arg);
}

window.addEventListener("hashchange", show);
show();
