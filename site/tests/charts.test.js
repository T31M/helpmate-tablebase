import test from "node:test";
import assert from "node:assert/strict";
import { barChart, niceMax, scale } from "../js/lib/charts.js";

test("niceMax rounds up to 1/2/5 steps", () => {
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(7), 10);
  assert.equal(niceMax(1200), 2000);
  assert.equal(niceMax(4.2e9), 5e9);
});

test("scale is finite, also on a log axis with zeros", () => {
  assert.equal(scale(0, 100, true), 0);
  assert.equal(scale(100, 100, true), 1);
  assert.ok(scale(10, 100, true) > scale(10, 100, false));
  assert.equal(scale(5, 0, false), 0);
});

test("bars with a highlighted part and titles", () => {
  const svg = barChart({ bars: [{ x: 1, value: 10, part: 4, title: "d1" }, { x: 3, value: 0 }] });
  assert.match(svg, /^<svg[^>]*role="img"/);
  assert.equal((svg.match(/class="bar"/g) || []).length, 2);
  assert.equal((svg.match(/class="part"/g) || []).length, 1);
  assert.match(svg, /<title>d1<\/title>/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test("log axis with gaps stays finite", () => {
  const svg = barChart({ bars: [{ x: 0, value: 0 }, { x: 1, value: 3e9, part: 0 }, { x: 2, value: 1 }], log: true });
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test("empty data", () => {
  const svg = barChart({ bars: [] });
  assert.match(svg, /class="empty">no data</);
  assert.match(svg, /x="320"/);
  assert.match(svg, /y="120"/);
});

test("on a log axis the part keeps its true share of the bar", () => {
  const svg = barChart({ bars: [{ x: 1, value: 1000, part: 10 }], log: true });
  const h = (cls) => Number(svg.match(new RegExp(`class="${cls}"[^>]*height="([\\d.]+)"`))[1]);
  assert.ok(Math.abs(h("part") / h("bar") - 0.01) < 0.001);
});
