import { readFile } from "node:fs/promises";
import { prepareRawSequence, predictRawFromModel, validateAlignmentAdapter,
  validateModelArtifact } from "../docs/model.mjs";

const request = JSON.parse(await new Promise((resolve) => {
  let input = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { input += chunk; });
  process.stdin.on("end", () => resolve(input));
}));

const model = validateModelArtifact(JSON.parse(await readFile(request.model_path, "utf8")));
model.raw_alignment_adapter = validateAlignmentAdapter(
  JSON.parse(await readFile(request.adapter_path, "utf8")),
);
model.raw_alignment_adapter_sha256 = request.adapter_sha256;

const results = request.sequences.map((sequence) => {
  try {
    const prepared = prepareRawSequence(sequence, model);
    const prediction = predictRawFromModel(sequence, model);
    return { ok: true, prepared, prediction };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
});
process.stdout.write(JSON.stringify(results));
