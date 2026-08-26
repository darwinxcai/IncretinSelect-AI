import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  alignedIdentity,
  normalizeSequence,
  predictFromModel,
} from "../docs/app.mjs";

const model = JSON.parse(
  await readFile(new URL("../docs/assets/incretin_ridge_v1.json", import.meta.url), "utf8"),
);
const example = "HSQGTFTSDYSKYLDSRAASEFVQWLISH-";
assert.equal(normalizeSequence(`  ${example.toLowerCase()}\n`, model), example);
for (const invalid of [example.slice(0, -1), `${example}A`, example.replace("S", "X"), "-".repeat(30)]) {
  assert.throws(() => normalizeSequence(invalid, model));
}
assert.throws(() => normalizeSequence(`>query\n${example}`, model));
assert.equal(alignedIdentity("A--C", "A--C"), 1);
assert.equal(alignedIdentity("A--C", "A--D"), 1 / 2);
const prediction = predictFromModel(example, model);
assert.ok(Number.isFinite(prediction.predictions.gcgr.log10Ec50Pm));
assert.ok(Number.isFinite(prediction.predictions.glp1r.log10Ec50Pm));
const outside = predictFromModel("A".repeat(30), model);
assert.equal(outside.applicability.tier, "outside_reference_neighborhood");
assert.ok(outside.warnings.some((warning) => warning.includes("should not be used to rank")));
process.stdout.write("static demo unit checks passed\n");
