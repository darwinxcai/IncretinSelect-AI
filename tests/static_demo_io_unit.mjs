import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  MAX_BROWSER_BYTES,
  MAX_BROWSER_ROWS,
  buildBatchArtifacts,
  buildSingleResultDocument,
  parseCandidateCsv,
  parseSingleFasta,
  renderScreeningCsv,
  renderSingleResultCsv,
  renderSingleResultJson,
  screenCandidates,
  spreadsheetSafeText,
} from "../docs/io.mjs";
import { predictFromModel } from "../docs/model.mjs";

const model = JSON.parse(
  await readFile(new URL("../docs/assets/incretin_ridge_v1.json", import.meta.url), "utf8"),
);
const sha256 = "eb7e99bbc3d83fdfb11ded4ba215fd7f6107a6e7d254f68e1b9610da6eb7e321";
const ref93 = "HSQGTFTSDYSKYLDSRAASEFVQWLISE-";
const ref11 = "HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG";
const leadingGap = "-HQGTFTSDYSKYLDSRRASEFVQWLISE-";
const outside = "A".repeat(30);

const wrappedFasta = (
  `\uFEFF>candidate 93\r\n${ref93.slice(0, 15).toLowerCase()}\r\n` +
  `${ref93.slice(15)}\r\n`
);
const fasta = parseSingleFasta(wrappedFasta, model);
assert.equal(fasta.header, "candidate 93");
assert.equal(fasta.alignedSequence, ref93);
for (const invalid of [
  ref93,
  `>\n${ref93}`,
  ">empty\n",
  `>first\n${ref93}\n>second\n${ref11}\n`,
  `>short\n${ref93.slice(1)}\n`,
  `>ambiguous\n${ref93.replace("S", "X")}\n`,
]) {
  assert.throws(() => parseSingleFasta(invalid, model));
}

const quotedCsv = (
  `\uFEFFcandidate_id,aligned_sequence\r\n` +
  `"candidate_1","${ref93.slice(0, 15)}\r\n${ref93.slice(15)}"\r\n` +
  `"candidate_""quoted","${ref11}"\r\n`
);
const quotedRecords = parseCandidateCsv(quotedCsv);
assert.equal(quotedRecords.length, 2);
assert.equal(quotedRecords[0].candidateId, "candidate_1");
assert.equal(quotedRecords[0].alignedSequence.replace(/\s/g, ""), ref93);
assert.equal(quotedRecords[1].candidateId, 'candidate_"quoted');

for (const invalid of [
  "",
  "aligned_sequence,candidate_id\n",
  "candidate_id,aligned_sequence,extra\na,b,c\n",
  "candidate_id,aligned_sequence\n",
  `candidate_id,aligned_sequence\na,${ref93}\na,${ref11}\n`,
  `candidate_id,aligned_sequence\n"unterminated,${ref93}\n`,
  `candidate_id,aligned_sequence\n"a"x,${ref93}\n`,
  `candidate_id,aligned_sequence\na,${ref93},extra\n`,
]) {
  assert.throws(() => parseCandidateCsv(invalid));
}
const tooManyRows = [
  "candidate_id,aligned_sequence",
  ...Array.from({ length: MAX_BROWSER_ROWS + 1 }, (_, index) => `c${index},${ref93}`),
].join("\n");
assert.throws(() => parseCandidateCsv(tooManyRows), /browser limit/);
assert.throws(
  () => parseCandidateCsv(`candidate_id,aligned_sequence\n${"x".repeat(MAX_BROWSER_BYTES)}`),
  /browser limit/,
);

const records = [
  { candidateId: "copy_a", alignedSequence: ref93 },
  { candidateId: "copy_b", alignedSequence: ref93 },
  { candidateId: "other", alignedSequence: ref11 },
  { candidateId: "outside", alignedSequence: outside },
  { candidateId: "bad_sequence", alignedSequence: "TOO-SHORT" },
  { candidateId: "=FORMULA", alignedSequence: ref93 },
  { candidateId: "leading_gap", alignedSequence: leadingGap },
];
assert.throws(() => screenCandidates(records, "", model, sha256), /Choose one/);
assert.throws(
  () => screenCandidates([records[0], { ...records[0] }], "dual", model, sha256),
  /must be unique/,
);
const screening = screenCandidates(records, "dual", model, sha256);
assert.equal(screening.counts.total_rows, records.length);
assert.equal(screening.counts.input_error_rows, 2);
assert.equal(screening.counts.out_of_scope_rows, 1);
assert.equal(screening.status, "completed_with_row_errors");
assert.equal(screening.exitCode, 1);
const copies = screening.rows.filter((row) => row.candidate_id.startsWith("copy_"));
assert.deepEqual(new Set(copies.map((row) => row.rank)), new Set(["1"]));
assert.deepEqual(new Set(copies.map((row) => row.duplicate_sequence_count)), new Set(["2"]));
assert.ok(screening.rows.some((row) => row.status === "not_ranked_out_of_scope"));
assert.ok(screening.rows.some((row) => row.error_code === "invalid_aligned_sequence"));
assert.ok(screening.rows.some((row) => row.error_code === "invalid_candidate_id"));

assert.equal(spreadsheetSafeText("=SUM(A1:A2)"), "'=SUM(A1:A2)");
assert.equal(spreadsheetSafeText("+cmd"), "'+cmd");
assert.equal(spreadsheetSafeText("-HQ"), "'-HQ");
assert.equal(spreadsheetSafeText("@formula"), "'@formula");
const screeningCsv = renderScreeningCsv(screening.rows);
assert.match(screeningCsv, /'=FORMULA/);
assert.match(screeningCsv, /'-HQGTFTSDYSKYLDSRRASEFVQWLISE-/);
assert.ok(screeningCsv.endsWith("\n"));

const prediction = predictFromModel(ref93, model);
const document = buildSingleResultDocument(prediction, model, sha256);
assert.equal(document.schema_version, 1);
assert.equal(document.input.aligned_sequence, ref93);
assert.equal(document.model.artifact_sha256, sha256);
assert.equal(document.predictions.gcgr.endpoint, "cAMP accumulation EC50");
assert.equal(document.applicability.tier, "close_analogue");
assert.ok(document.warnings.some((warning) => warning.includes("not binding affinity")));
const singleJson = renderSingleResultJson(prediction, model, sha256);
assert.equal(JSON.parse(singleJson).input.aligned_sequence, ref93);
assert.ok(singleJson.endsWith("\n"));
const singleCsv = renderSingleResultCsv(prediction, model, sha256);
assert.match(singleCsv, /^aligned_sequence,glp1r_log10_ec50_pm/);
assert.match(singleCsv, new RegExp(ref93));
assert.doesNotMatch(singleCsv, /,'-[0-9]/);
assert.ok(singleCsv.endsWith("\n"));

const batchInput = (
  "candidate_id,aligned_sequence\n" +
  `copy_a,${ref93}\n` +
  `copy_b,${ref93}\n` +
  `outside,${outside}\n`
);
const artifacts = await buildBatchArtifacts(batchInput, "glp1r", model, {
  artifactSha256: sha256,
  inputFilename: "shortlist.csv",
  outputFilename: "screened.csv",
});
assert.equal(artifacts.receipt.input.filename, "shortlist.csv");
assert.equal(artifacts.receipt.output.filename, "screened.csv");
assert.match(artifacts.receipt.input.sha256, /^[0-9a-f]{64}$/);
assert.match(artifacts.receipt.output.sha256, /^[0-9a-f]{64}$/);
assert.equal(artifacts.receipt.counts.total_rows, 3);
assert.equal(artifacts.receipt.scientific_boundaries.structure_inference_run, false);
assert.equal(artifacts.receipt.scientific_boundaries.holdout_labels_accessed, false);
assert.equal(JSON.parse(artifacts.receiptJson).objective.name, "glp1r");

process.stdout.write("static demo I/O unit checks passed\n");
