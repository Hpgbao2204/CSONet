"use strict";

const fs = require("fs");
const path = require("path");
const solc = require("solc");

const root = path.resolve(__dirname, "..");
const manifestPath = process.argv[2] || path.join(root, ".cache", "compile_manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

const sources = {};
for (const item of manifest.sources) {
  sources[item.path] = { content: fs.readFileSync(path.join(root, item.path), "utf8") };
}

const input = {
  language: "Solidity",
  sources,
  settings: {
    optimizer: { enabled: false, runs: 200 },
    outputSelection: {
      "*": {
        "": ["ast"],
        "*": ["abi", "evm.bytecode.object", "storageLayout"]
      }
    }
  }
};

const started = process.hrtime.bigint();
const output = JSON.parse(solc.compile(JSON.stringify(input)));
const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
const errors = (output.errors || []).filter((entry) => entry.severity === "error");
const warnings = (output.errors || []).filter((entry) => entry.severity !== "error");

const result = {
  compiler_long_version: solc.version(),
  source_count: manifest.sources.length,
  elapsed_ms: elapsedMs,
  error_count: errors.length,
  warning_count: warnings.length,
  errors: errors.map((entry) => entry.formattedMessage),
  warnings: warnings.map((entry) => entry.formattedMessage)
};

if (errors.length > 0) {
  fs.mkdirSync(path.dirname(manifest.result_path), { recursive: true });
  fs.writeFileSync(manifest.result_path, JSON.stringify(result, null, 2));
  process.stderr.write(errors.map((entry) => entry.formattedMessage).join("\n"));
  process.exit(1);
}

const artifactRoot = path.join(root, "dataset", "artifacts");
const kinds = ["abi", "ast", "bytecode", "storage_layout"];
for (const kind of kinds) {
  fs.mkdirSync(path.join(artifactRoot, kind), { recursive: true });
}

const index = {};
for (const item of manifest.sources) {
  const contracts = output.contracts[item.path] || {};
  const contract = contracts[item.contract_name];
  if (!contract) {
    throw new Error(`Contract ${item.contract_name} missing from ${item.path}`);
  }
  const stem = item.path.replace(/^dataset\//, "").replace(/[\\/:.]/g, "__");
  const relative = {};
  const outputs = {
    abi: contract.abi,
    ast: output.sources[item.path].ast,
    bytecode: {
      object: contract.evm.bytecode.object,
      bytes: contract.evm.bytecode.object.length / 2
    },
    storage_layout: contract.storageLayout
  };
  for (const kind of kinds) {
    const target = path.join(artifactRoot, kind, `${stem}.json`);
    fs.writeFileSync(target, JSON.stringify(outputs[kind], null, 2));
    relative[kind] = path.relative(root, target).replace(/\\/g, "/");
  }
  index[item.path] = {
    contract_name: item.contract_name,
    ...relative
  };
}

const indexPath = path.join(artifactRoot, "index.json");
fs.writeFileSync(indexPath, JSON.stringify(index, null, 2));
result.artifact_index = path.relative(root, indexPath).replace(/\\/g, "/");
result.artifact_count = Object.keys(index).length;
fs.mkdirSync(path.dirname(manifest.result_path), { recursive: true });
fs.writeFileSync(manifest.result_path, JSON.stringify(result, null, 2));
process.stdout.write(JSON.stringify(result, null, 2));
