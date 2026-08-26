import { readFile } from "node:fs/promises";
import { predictFromModel } from "../docs/app.mjs";

let body = "";
for await (const chunk of process.stdin) body += chunk;
const request = JSON.parse(body);
const model = JSON.parse(await readFile(request.model_path, "utf8"));
const results = request.sequences.map((sequence) => predictFromModel(sequence, model));
process.stdout.write(`${JSON.stringify(results)}\n`);
