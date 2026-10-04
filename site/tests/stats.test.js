import test from "node:test";
import assert from "node:assert/strict";
import { depthBars, uniqueShareBars, maxDtmBars, deepest, lookup } from "../js/lib/stats.js";

const stats = {
  materials: {
    KQvk: { pieces: 3, max_dtm: 3, wtm: [[1, 4, 3], [3, 6, 0]], btm: [[0, 2, 2], [2, 8, 5]] },
    KRvk: { pieces: 3, max_dtm: 5, wtm: [], btm: [[0, 1, 1]] },
    Kvkq: { pieces: 3, max_dtm: null, wtm: [], btm: [] },
    KQvkq: { pieces: 4, max_dtm: 5, wtm: [], btm: [] },
  },
  total: { wtm: [[1, 4, 3]], btm: [] },
  by_pieces: { 4: { tables: 1, solvable: 10, unique: 1 }, 3: { tables: 3, solvable: 200, unique: 50 } },
};

test("depth bars carry cells and the unique part", () => {
  assert.deepEqual(depthBars([[1, 4, 3]]), [{ x: 1, value: 4, part: 3, title: "depth 1: 4 positions, 3 unique" }]);
});

test("unique share per piece count, ordered", () => {
  assert.deepEqual(uniqueShareBars(stats.by_pieces).map((b) => [b.x, b.value]), [["3", 25], ["4", 10]]);
});

test("unique share drops piece counts without solvable positions", () => {
  const bars = uniqueShareBars({ 2: { tables: 1, solvable: 0, unique: 0 }, 3: { tables: 2, solvable: 8, unique: 2 } });
  assert.deepEqual(bars.map((b) => [b.x, b.value]), [["3", 25]]);
});

test("materials per max DTM, markers excluded, gaps filled", () => {
  assert.deepEqual(maxDtmBars(stats.materials, "all").map((b) => b.value), [0, 0, 0, 1, 0, 2]);
  assert.deepEqual(maxDtmBars(stats.materials, "4").map((b) => b.value), [0, 0, 0, 0, 0, 1]);
});

test("deepest materials", () => {
  assert.deepEqual(deepest(stats.materials, 2), [{ material: "KQvkq", max_dtm: 5 }, { material: "KRvk", max_dtm: 5 }]);
});

test("lookup handles unknown names and markers", () => {
  assert.equal(lookup(stats, "KQvk").ok, true);
  assert.deepEqual(lookup(stats, "Nonsense"), { ok: false, message: "unknown material" });
  assert.deepEqual(lookup(stats, ""), { ok: false, message: "unknown material" });
  assert.deepEqual(lookup(stats, "Kvkq"), { ok: false, message: "no helpmate in this material" });
});
