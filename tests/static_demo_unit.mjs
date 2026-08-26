import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  alignedIdentity,
  normalizeSequence,
  predictFromModel,
} from "../docs/model.mjs";
import { screenCandidates } from "../docs/io.mjs";

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

// A sequence can be a close analogue yet still be outside the modeled residue-count
// range. The browser must never treat applicability alone as ranking eligibility.
const shortCloseAnalogue = "----TFTSDYSKYLDSRAASEFVQWLISE-";
const shortPrediction = predictFromModel(shortCloseAnalogue, model);
assert.equal(shortPrediction.applicability.tier, "close_analogue");
assert.equal(shortPrediction.input.standardResidueCount, 25);
assert.ok(shortPrediction.warnings.some((warning) => warning.includes("fewer residues")));
const screenedShort = screenCandidates(
  [{ candidateId: "short_close", alignedSequence: shortCloseAnalogue }],
  "dual",
  model,
  "eb7e99bbc3d83fdfb11ded4ba215fd7f6107a6e7d254f68e1b9610da6eb7e321",
);
assert.equal(screenedShort.status, "no_rankable_rows");
assert.equal(screenedShort.rows[0].status, "not_ranked_out_of_scope");
assert.equal(screenedShort.rows[0].ranking_eligible, "false");
assert.equal(screenedShort.rows[0].rank, "");
assert.match(screenedShort.rows[0].ranking_exclusion_reason, /below 26/);
process.stdout.write("static demo unit checks passed\n");
