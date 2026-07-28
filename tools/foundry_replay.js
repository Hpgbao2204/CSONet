"use strict";

const fs = require("fs");
const { spawn } = require("child_process");
const {
  ContractFactory,
  JsonRpcProvider,
  concat,
  getAddress,
  keccak256,
  toBeHex,
  zeroPadValue
} = require("ethers");

const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const port = manifest.port || 8547;
const rpcUrl = `http://127.0.0.1:${port}`;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function word(value) {
  return zeroPadValue(toBeHex(BigInt(value)), 32);
}

function mappingLocation(address, slot) {
  return keccak256(
    concat([zeroPadValue(address, 32), zeroPadValue(toBeHex(BigInt(slot)), 32)])
  );
}

function normalize(value) {
  if (typeof value === "bigint") return value.toString();
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value)) result[key] = normalize(item);
    return result;
  }
  return value;
}

async function waitForRpc(provider) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      await provider.getBlockNumber();
      return;
    } catch {
      await sleep(100);
    }
  }
  throw new Error("Anvil did not become ready");
}

async function setState(provider, contract, layout, model, account, guardian) {
  const address = await contract.getAddress();
  const byLabel = Object.fromEntries(layout.storage.map((item) => [item.label, item]));
  const guardianEntry = byLabel.guardian;
  if (guardianEntry) {
    const shifted = BigInt(guardian) << BigInt(Number(guardianEntry.offset) * 8);
    await provider.send("anvil_setStorageAt", [
      address,
      toBeHex(BigInt(guardianEntry.slot)),
      word(shifted)
    ]);
  }
  const totalEntry = byLabel.total;
  await provider.send("anvil_setStorageAt", [
    address,
    toBeHex(BigInt(totalEntry.slot)),
    word(model.total)
  ]);
  const limitEntry = byLabel.limit;
  const activeEntry = byLabel.active;
  const packed =
    (BigInt(model.limit) << BigInt(Number(limitEntry.offset) * 8)) |
    ((model.active ? 1n : 0n) << BigInt(Number(activeEntry.offset) * 8));
  await provider.send("anvil_setStorageAt", [
    address,
    toBeHex(BigInt(limitEntry.slot)),
    word(packed)
  ]);
  const mappingEntry = layout.storage.find((item) =>
    layout.types[item.type].label.startsWith("mapping(")
  );
  const mappingKey = mappingLocation(account, mappingEntry.slot);
  await provider.send("anvil_setStorageAt", [
    address,
    mappingKey,
    word(model.balance)
  ]);
  await provider.send("anvil_setBalance", [address, toBeHex(10n ** 24n)]);
  await provider.send("evm_mine", []);
  return { mappingKey };
}

async function staticObservation(contract, signer, functionName, args) {
  try {
    const result = await contract
      .connect(signer)
      .getFunction(functionName)
      .staticCall(...args);
    return { success: true, return_data: normalize(result) };
  } catch (error) {
    return {
      success: false,
      revert_data: error.data || (error.info && error.info.error && error.info.error.data) || ""
    };
  }
}

async function sendTransaction(contract, signer, functionName, args) {
  let hash = "";
  let receipt = null;
  try {
    const tx = await contract.connect(signer).getFunction(functionName)(
      ...args,
      { gasLimit: 5_000_000 }
    );
    hash = tx.hash;
    receipt = await tx.wait();
  } catch (error) {
    receipt = error.receipt || null;
    hash = (receipt && receipt.hash) || error.transactionHash || "";
  }
  return { hash, receipt };
}

async function traceObservation(provider, hash) {
  if (!hash) return [];
  try {
    const trace = await provider.send("debug_traceTransaction", [
      hash,
      { disableMemory: true, disableStorage: true, disableStack: false }
    ]);
    const logs = trace.structLogs || trace.struct_logs || trace.structlogs || [];
    if (!logs.length) {
      return [{ op: "TRACE_EMPTY", keys: Object.keys(trace || {}) }];
    }
    return logs
      .filter((entry) =>
        entry.op === "SSTORE" ||
        entry.op === "CALL" ||
        entry.op.startsWith("LOG") ||
        entry.op === "REVERT" ||
        entry.op === "RETURN"
      )
      .map((entry) => {
        const observation = { op: entry.op };
        if (entry.op === "CALL" && entry.stack && entry.stack.length >= 3) {
          observation.to = getAddress(
            `0x${entry.stack[entry.stack.length - 2].slice(-40)}`
          );
          const rawValue = entry.stack[entry.stack.length - 3];
          observation.value = BigInt(
            rawValue.startsWith("0x") ? rawValue : `0x${rawValue}`
          ).toString();
        }
        return observation;
      });
  } catch (error) {
    return [{ op: "TRACE_UNAVAILABLE", error: String(error.message || error) }];
  }
}

async function postStorage(provider, address, layout, mappingKey) {
  const slots = new Set(layout.storage.map((entry) => BigInt(entry.slot).toString()));
  const result = {};
  for (const slot of [...slots].sort((a, b) => Number(a) - Number(b))) {
    result[`slot:${slot}`] = await provider.getStorage(address, BigInt(slot));
  }
  result[`mapping:${mappingKey}`] = await provider.getStorage(address, mappingKey);
  return result;
}

async function executeVersion(provider, item, version, signerSet, model) {
  const artifact = item[version];
  const abi = JSON.parse(fs.readFileSync(artifact.abi, "utf8"));
  const bytecode = JSON.parse(fs.readFileSync(artifact.bytecode, "utf8")).object;
  const layout = JSON.parse(fs.readFileSync(artifact.storage_layout, "utf8"));
  const factory = new ContractFactory(abi, `0x${bytecode}`, signerSet.owner);
  const contract = await factory.deploy();
  await contract.waitForDeployment();
  const ownerAddress = await signerSet.owner.getAddress();
  const otherAddress = await signerSet.other.getAddress();
  const guardianAddress = await signerSet.guardian.getAddress();
  await (await contract.initialize(ownerAddress, BigInt(model.limit))).wait();
  const account = otherAddress;
  const stateInfo = await setState(
    provider,
    contract,
    layout,
    model,
    account,
    guardianAddress
  );
  const caller = model.sender_owner ? signerSet.owner : signerSet.other;
  const args =
    item.changed_function === "withdraw"
      ? [account, BigInt(model.amount)]
      : [BigInt(model.amount)];
  const call = await staticObservation(
    contract,
    caller,
    item.changed_function,
    args
  );
  const tx = await sendTransaction(
    contract,
    caller,
    item.changed_function,
    args
  );
  const receipt = tx.receipt;
  const logs = receipt
    ? receipt.logs.map((log) => ({ topics: log.topics, data: log.data }))
    : [];
  // Opcode traces are only needed for interaction-sensitive withdraw cases.
  // Avoiding full traces for arithmetic/state mutations keeps replay bounded.
  const trace =
    item.changed_function === "withdraw"
      ? await traceObservation(provider, tx.hash)
      : [];
  const storage = await postStorage(
    provider,
    await contract.getAddress(),
    layout,
    stateInfo.mappingKey
  );
  return {
    call,
    tx_status: receipt ? Number(receipt.status) : 0,
    logs,
    trace,
    storage
  };
}

function observedDifference(first, second) {
  const dimensions = {
    status_or_return: JSON.stringify(first.call) !== JSON.stringify(second.call),
    transaction_status: first.tx_status !== second.tx_status,
    events: JSON.stringify(first.logs) !== JSON.stringify(second.logs),
    storage: JSON.stringify(first.storage) !== JSON.stringify(second.storage),
    external_trace: JSON.stringify(first.trace) !== JSON.stringify(second.trace)
  };
  return { dimensions, valid: Object.values(dimensions).some(Boolean) };
}

async function main() {
  const anvil = spawn(
    manifest.anvil_path,
    ["--port", String(port), "--silent", "--steps-tracing", "--hardfork", "cancun"],
    { stdio: ["ignore", "pipe", "pipe"], windowsHide: true }
  );
  let stderr = "";
  anvil.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
  });
  const provider = new JsonRpcProvider(rpcUrl);
  try {
    await waitForRpc(provider);
    const signerSet = {
      owner: await provider.getSigner(0),
      other: await provider.getSigner(1),
      guardian: await provider.getSigner(2)
    };
    const results = [];
    for (const [index, item] of manifest.pairs.entries()) {
      await provider.send("anvil_reset", []);
      fs.writeFileSync(
        `${manifest.result_path}.progress`,
        JSON.stringify(
          { index: index + 1, total: manifest.pairs.length, pair_id: item.pair_id },
          null,
          2
        )
      );
      process.stdout.write(
        `replay ${index + 1}/${manifest.pairs.length} ${item.pair_id}\n`
      );
      const started = process.hrtime.bigint();
      try {
        const model = item.counterexample;
        const first = await executeVersion(provider, item, "v1", signerSet, model);
        const second = await executeVersion(provider, item, "v2", signerSet, model);
        const comparison = observedDifference(first, second);
        results.push({
          pair_id: item.pair_id,
          verdict: comparison.valid ? "Validated" : "Invalid",
          runtime_ms: Number(process.hrtime.bigint() - started) / 1e6,
          ...comparison,
          observations: comparison.valid ? {} : { v1: first, v2: second },
          error: ""
        });
      } catch (error) {
        results.push({
          pair_id: item.pair_id,
          verdict: "Error",
          runtime_ms: Number(process.hrtime.bigint() - started) / 1e6,
          dimensions: {},
          valid: false,
          error: String(error.stack || error)
        });
      }
      fs.writeFileSync(
        manifest.result_path,
        JSON.stringify(results, null, 2)
      );
    }
    fs.rmSync(`${manifest.result_path}.progress`, { force: true });
    process.stdout.write(
      JSON.stringify({
        pairs: results.length,
        valid: results.filter((entry) => entry.valid).length,
        errors: results.filter((entry) => entry.verdict === "Error").length,
        result_path: manifest.result_path
      })
    );
  } finally {
    anvil.kill();
    provider.destroy();
    if (stderr.trim()) process.stderr.write(stderr);
  }
}

main().catch((error) => {
  process.stderr.write(String(error.stack || error));
  process.exitCode = 1;
});
