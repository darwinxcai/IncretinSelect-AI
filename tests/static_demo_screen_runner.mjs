import { readFile } from "node:fs/promises";
import { screenCandidates } from "../docs/io.mjs";

let body = "";
for await (const chunk of process.stdin) body += chunk;
const request = JSON.parse(body);
const model = JSON.parse(await readFile(request.model_path, "utf8"));
const result = screenCandidates(
  request.records,
  request.objective,
  model,
  request.artifact_sha256,
);
process.stdout.write(`${JSON.stringify(result)}\n`);
