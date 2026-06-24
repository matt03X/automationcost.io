"use strict";
/**
 * benchmark-sources/epoch.js — Epoch AI Benchmarking Hub (CC-BY).
 *
 * LIVE zdroj: https://epoch.ai/data/benchmarks.csv  (jeden CSV, ~5–6k běhů, vsechny benchmarky).
 * Licence: CC-BY (atribuce "Epoch AI"). Skóre = měřený fakt (Feist) → volně citovatelné.
 * Pull bere JEN agregované skóre per (model, task). NIKDY text otázek.
 *
 * Mapuje Epoch sloupec `task` → naše metric keys (models.json _meta.benchmarks.metrics).
 * Epoch DNES poskytuje: GPQA diamond, SWE-Bench verified (+ AIME/MATH/FrontierMath/SimpleQA — neregistrované).
 * MMLU-Pro Epoch NEMÁ → tu metriku plní jiný zdroj (HELM/jiný), zde se nevyrábí.
 *
 * Skóre: per (Model, task) bereme NEJLEPŠÍ best_score napříč běhy (různé reasoning-effort
 * varianty grok-4.3_high / *_max apod.) = leaderboard konvence. Hodnota 0..1 -> %.
 *
 * Export: pull(csvText) -> [{ extName, metric, value }]  (puller doplní source + asof).
 *         NIKDY nehádá — když chybí task mapping nebo skóre, řádek přeskočí.
 */

const SOURCE = "epoch";
const URL = "https://epoch.ai/data/benchmarks.csv";
const LICENSE = "CC-BY";
const ATTRIBUTION = "Epoch AI Benchmarking Hub (CC-BY)";

// Epoch task (lowercase, trim) -> naše metric key. Rozšiřitelné (Epoch má i AIME/MATH/FrontierMath).
const TASK_TO_METRIC = {
  "gpqa diamond": "gpqa_diamond",
  "swe-bench verified": "swe_bench_verified",
};

// RFC-4180-ish CSV parser (quotes, embedded commas/newlines, "" escape).
function parseCSV(text) {
  const rows = [];
  let field = "", row = [], inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
      else field += c;
    } else {
      if (c === '"') inQ = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
      else if (c === "\r") { /* skip */ }
      else field += c;
    }
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function pull(csvText) {
  const rows = parseCSV(csvText);
  if (!rows.length) throw new Error("epoch: prázdný CSV");
  const H = rows[0];
  const ci = (n) => H.indexOf(n);
  const cTask = ci("task"), cModel = ci("Model"), cBest = ci("best_score"), cMean = ci("mean_score");
  if (cTask < 0 || cModel < 0 || (cBest < 0 && cMean < 0)) {
    throw new Error("epoch: chybí očekávané sloupce (task/Model/best_score) — změna formátu?");
  }
  const best = new Map(); // extName||metric -> value(0..100)
  for (let r = 1; r < rows.length; r++) {
    const row = rows[r];
    const model = (row[cModel] || "").trim();
    if (!model) continue;
    const metric = TASK_TO_METRIC[(row[cTask] || "").toLowerCase().trim()];
    if (!metric) continue;
    let s = cBest >= 0 ? parseFloat(row[cBest]) : NaN;
    if (isNaN(s) && cMean >= 0) s = parseFloat(row[cMean]);
    if (isNaN(s) || s < 0 || s > 1) continue;            // Epoch skóre je 0..1; jinak skip (nehádáme)
    const pct = Math.round(s * 1000) / 10;               // 0..100, 1 desetinné
    const key = model + "||" + metric;
    if (!best.has(key) || pct > best.get(key)) best.set(key, pct);
  }
  return [...best.entries()].map(([k, value]) => {
    const ix = k.lastIndexOf("||");
    return { extName: k.slice(0, ix), metric: k.slice(ix + 2), value };
  });
}

module.exports = { SOURCE, URL, LICENSE, ATTRIBUTION, pull, parseCSV, TASK_TO_METRIC };
