"use strict";

const fs = require("fs");
const { getStorageUpgradeErrors } = require("@openzeppelin/upgrades-core");

const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const rows = [];
for (const pair of manifest.pairs) {
  const oldLayout = JSON.parse(fs.readFileSync(pair.old_layout, "utf8"));
  const newLayout = JSON.parse(fs.readFileSync(pair.new_layout, "utf8"));
  const started = process.hrtime.bigint();
  let errors = [];
  let error = "";
  try {
    errors = getStorageUpgradeErrors(oldLayout, newLayout);
  } catch (caught) {
    error = String(caught && caught.message ? caught.message : caught);
  }
  const runtimeMs = Number(process.hrtime.bigint() - started) / 1e6;
  rows.push({
    pair_id: pair.pair_id,
    verdict: error ? "Unknown" : errors.length ? "Unsafe" : "Safe",
    runtime_ms: runtimeMs,
    issue_count: errors.length,
    error
  });
}
fs.writeFileSync(manifest.result_path, JSON.stringify(rows, null, 2));
process.stdout.write(JSON.stringify({ pairs: rows.length, result_path: manifest.result_path }));

