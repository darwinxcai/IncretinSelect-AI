import { readFile } from "node:fs/promises";

import { renderSingleResultCsv } from "../docs/io.mjs";
import { SOFTWARE_VERSION, predictFromModel } from "../docs/model.mjs";

let body = "";
for await (const chunk of process.stdin) body += chunk;
const request = JSON.parse(body);
const model = JSON.parse(await readFile(request.model_path, "utf8"));
model.software_version = SOFTWARE_VERSION;
const results = request.sequences.map((sequence) => renderSingleResultCsv(
  predictFromModel(sequence, model),
  model,
  request.artifact_sha256,
));
process.stdout.write(`${JSON.stringify(results)}\n`);
