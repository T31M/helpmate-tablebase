import { makeBoard } from "./board.js";
import { contributorCards, sixProgress } from "./lib/materials.js";
import { stipulation, humanBytes } from "./lib/solution.js";

const fmt = (n) => Number(n).toLocaleString("en-US");

export async function initFront({ corpus, deepest, status }) {
  const dl = document.getElementById("corpus-numbers");
  const six = corpus.by_pieces["6"] || 0;
  const items = [
    ["tables", fmt(corpus.tables)],
    ["on disk", humanBytes(corpus.size_bytes)],
    ["positions with a helpmate", fmt(corpus.solvable)],
    ["with a unique solution", fmt(corpus.unique)],
    ["deepest mate", `${stipulation(corpus.deepest.dtm)} (${corpus.deepest.material})`],
    ["six-piece classes", `${six} of 645`],
  ];
  dl.innerHTML = items.map(([k, v]) => `<div><dd>${v}</dd><dt>${k}</dt></div>`).join("");
  document.getElementById("build-note").textContent =
    `${corpus.tables} tables, complete through five pieces.`;

  document.getElementById("contrib-cards").innerHTML = contributorCards(status);
  document.getElementById("contrib-progress").textContent = sixProgress(status, corpus);

  // The front board shows the deepest sound six-piece problem and plays it.
  const pick = [...deepest].sort((a, b) => b.pieces - a.pieces || b.dtm - a.dtm)[0];
  const board = makeBoard(document.getElementById("front-board"));
  const readout = document.getElementById("front-readout");
  board.show(pick.fen, true);
  readout.innerHTML = `<span><strong>${pick.material}</strong> · ${stipulation(pick.dtm)}, unique</span>` +
    `<a href="#/deepest/${pick.material}">see the line →</a>`;
  let ply = 0;
  const step = () => {
    ply = (ply + 1) % (pick.plies.length + 3);
    if (ply === 0) board.show(pick.fen);
    else if (ply <= pick.plies.length) board.show(pick.plies[ply - 1].fen);
  };
  const timer = setInterval(step, 1400);
  window.addEventListener("hashchange", () => {
    if (location.hash && location.hash !== "#/" && location.hash !== "#") clearInterval(timer);
  }, { once: true });
}
