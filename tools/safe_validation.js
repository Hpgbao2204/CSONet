"use strict";

const fs = require("fs");
const { spawn } = require("child_process");
const {
  ContractFactory,
  JsonRpcProvider,
  concat,
  keccak256,
  toBeHex,
  zeroPadValue
} = require("ethers");

const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const port = manifest.port || 8587;
const provider = new JsonRpcProvider(`http://127.0.0.1:${port}`);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function withTimeout(promise, label, timeoutMs = 20000) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label} timed out after ${timeoutMs} ms`)),
          timeoutMs
        );
      })
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function rpc(method, params = []) {
  return withTimeout(provider.send(method, params), method);
}

function word(value) {
  return zeroPadValue(toBeHex(BigInt(value)), 32);
}

function normalize(value) {
  if (typeof value === "bigint") return value.toString();
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !/^\d+$/.test(key))
        .map(([key, item]) => [key, normalize(item)])
    );
  }
  return value;
}

function mappingLocation(address, slot) {
  return keccak256(
    concat([zeroPadValue(address, 32), zeroPadValue(toBeHex(BigInt(slot)), 32)])
  );
}

async function waitForRpc() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      await provider.getBlockNumber();
      return;
    } catch {
      await sleep(100);
    }
  }
  throw new Error("Anvil did not become ready");
}

async function deploy(artifact, owner) {
  const abi = JSON.parse(fs.readFileSync(artifact.abi, "utf8"));
  const bytecode = JSON.parse(fs.readFileSync(artifact.bytecode, "utf8")).object;
  const layout = JSON.parse(fs.readFileSync(artifact.storage_layout, "utf8"));
  const factory = new ContractFactory(abi, `0x${bytecode}`, owner);
  const contract = await factory.deploy();
  await contract.waitForDeployment();
  return { contract, layout };
}

async function setState(contract, layout, state, account, guardian) {
  const address = await contract.getAddress();
  const byLabel = Object.fromEntries(layout.storage.map((item) => [item.label, item]));
  if (byLabel.guardian) {
    const shifted = BigInt(guardian) << BigInt(Number(byLabel.guardian.offset) * 8);
    await rpc("anvil_setStorageAt", [
      address,
      toBeHex(BigInt(byLabel.guardian.slot)),
      word(shifted)
    ]);
  }
  await rpc("anvil_setStorageAt", [
    address,
    toBeHex(BigInt(byLabel.total.slot)),
    word(state.total)
  ]);
  const packed =
    (BigInt(state.limit) << BigInt(Number(byLabel.limit.offset) * 8)) |
    ((state.active ? 1n : 0n) << BigInt(Number(byLabel.active.offset) * 8));
  await rpc("anvil_setStorageAt", [
    address,
    toBeHex(BigInt(byLabel.limit.slot)),
    word(packed)
  ]);
  const mappingEntry = layout.storage.find((item) =>
    layout.types[item.type].label.startsWith("mapping(")
  );
  const key = mappingLocation(account, mappingEntry.slot);
  await rpc("anvil_setStorageAt", [address, key, word(state.balance)]);
  if (byLabel.history) {
    await rpc("anvil_setStorageAt", [
      address,
      toBeHex(BigInt(byLabel.history.slot)),
      word(0)
    ]);
  }
  await rpc("anvil_setBalance", [address, toBeHex(10n ** 24n)]);
  await rpc("evm_mine", []);
  return key;
}

async function staticObservation(contract, signer, functionName, args) {
  try {
    const result = await withTimeout(
      contract.connect(signer).getFunction(functionName).staticCall(...args),
      `${functionName}.staticCall`
    );
    return { success: true, data: normalize(result) };
  } catch (error) {
    return {
      success: false,
      data: error.data || (error.info && error.info.error && error.info.error.data) || ""
    };
  }
}

async function transact(contract, signer, functionName, args) {
  try {
    const tx = await withTimeout(
      contract.connect(signer).getFunction(functionName)(
        ...args,
        { gasLimit: 5_000_000, value: 0 }
      ),
      `${functionName}.send`
    );
    const receipt = await withTimeout(tx.wait(), `${functionName}.wait`);
    return { hash: tx.hash, receipt };
  } catch (error) {
    const receipt = error.receipt || null;
    return {
      hash: (receipt && receipt.hash) || error.transactionHash || "",
      receipt
    };
  }
}

async function externalCalls(hash) {
  if (!hash) return [];
  const trace = await provider.send("debug_traceTransaction", [
    hash,
    { disableMemory: true, disableStorage: true, disableStack: true }
  ]);
  return (trace.structLogs || [])
    .filter((entry) => ["CALL", "STATICCALL", "DELEGATECALL", "CALLCODE"].includes(entry.op))
    .map((entry) => ({ op: entry.op }));
}

async function storageProjection(contract, slots, mappingKey) {
  const address = await contract.getAddress();
  const projection = {};
  for (const slot of slots) {
    projection[`slot:${slot}`] = await withTimeout(
      provider.getStorage(address, BigInt(slot)),
      `getStorage(${slot})`
    );
  }
  projection.mapping = await withTimeout(
    provider.getStorage(address, mappingKey),
    "getStorage(mapping)"
  );
  return projection;
}

async function execute(
  deployed,
  signer,
  functionName,
  state,
  account,
  guardian,
  slots,
  traceExternalCalls
) {
  const mappingKey = await setState(
    deployed.contract,
    deployed.layout,
    state,
    account,
    guardian
  );
  const args = [BigInt(state.amount)];
  const call = await staticObservation(deployed.contract, signer, functionName, args);
  const tx = await transact(deployed.contract, signer, functionName, args);
  const receipt = tx.receipt;
  return {
    call,
    transaction_status: receipt ? Number(receipt.status) : 0,
    events: receipt
      ? receipt.logs.map((log) => ({ topics: log.topics, data: log.data }))
      : [],
    storage: await storageProjection(deployed.contract, slots, mappingKey),
    external_calls: traceExternalCalls ? await externalCalls(tx.hash) : []
  };
}

function compare(first, second) {
  const dimensions = {
    status: first.call.success !== second.call.success ||
      first.transaction_status !== second.transaction_status,
    return_or_revert: JSON.stringify(first.call.data) !== JSON.stringify(second.call.data),
    events: JSON.stringify(first.events) !== JSON.stringify(second.events),
    storage: JSON.stringify(first.storage) !== JSON.stringify(second.storage),
    external_calls: JSON.stringify(first.external_calls) !== JSON.stringify(second.external_calls)
  };
  return { dimensions, mismatch: Object.values(dimensions).some(Boolean) };
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
  try {
    await waitForRpc();
    const owner = await provider.getSigner(0);
    const other = await provider.getSigner(1);
    const guardianSigner = await provider.getSigner(2);
    const ownerAddress = await owner.getAddress();
    const otherAddress = await other.getAddress();
    const guardianAddress = await guardianSigner.getAddress();
    const allowedCases = new Set(
      manifest.pairs.flatMap((pair) =>
        pair.cases.map(
          (_, caseIndex) =>
            `${pair.pair_id}:${(pair.case_offset || 0) + caseIndex + 1}`
        )
      )
    );
    const traceCases = new Set(
      manifest.pairs.map(
        (pair) => `${pair.pair_id}:${(pair.case_offset || 0) + 1}`
      )
    );
    const rows = fs.existsSync(manifest.result_path)
      ? JSON.parse(fs.readFileSync(manifest.result_path, "utf8"))
          .filter(
            (row) =>
              allowedCases.has(`${row.pair_id}:${row.case_id}`) &&
              !row.error &&
              (
                !traceCases.has(`${row.pair_id}:${row.case_id}`) ||
                row.external_calls_checked
              )
          )
      : [];
    for (const [pairIndex, pair] of manifest.pairs.entries()) {
      await rpc("anvil_reset", []);
      const first = await deploy(pair.v1, owner);
      const second = await deploy(pair.v2, owner);
      await (await first.contract.initialize(ownerAddress, 2n)).wait();
      await (await second.contract.initialize(ownerAddress, 2n)).wait();
      const slots = [...new Set(
        first.layout.storage
          .filter((entry) => entry.label !== "__gap")
          .map((entry) => BigInt(entry.slot).toString())
      )].sort((a, b) => Number(a) - Number(b));
      for (const [caseIndex, state] of pair.cases.entries()) {
        const caseId = (pair.case_offset || 0) + caseIndex + 1;
        if (rows.some(
          (row) => row.pair_id === pair.pair_id && row.case_id === caseId
        )) {
          continue;
        }
        const started = process.hrtime.bigint();
        try {
          const signer = state.sender_owner ? owner : other;
          const account = await signer.getAddress();
          const traceExternalCalls = caseIndex === 0;
          const v1 = await execute(
            first,
            signer,
            pair.changed_function,
            state,
            account,
            guardianAddress,
            slots,
            traceExternalCalls
          );
          const v2 = await execute(
            second,
            signer,
            pair.changed_function,
            state,
            account,
            guardianAddress,
            slots,
            traceExternalCalls
          );
          const result = compare(v1, v2);
          rows.push({
            pair_id: pair.pair_id,
            case_id: caseId,
            state,
            ...result,
            external_calls_checked: traceExternalCalls,
            model_evm_agree: !result.mismatch,
            runtime_ms: Number(process.hrtime.bigint() - started) / 1e6,
            observations: result.mismatch ? { v1, v2 } : {},
            error: ""
          });
          fs.writeFileSync(manifest.result_path, JSON.stringify(rows, null, 2));
          process.stdout.write(
            `safe validation ${pairIndex + 1}/${manifest.pairs.length} ` +
            `case ${caseIndex + 1}/${pair.cases.length}\n`
          );
        } catch (error) {
          rows.push({
            pair_id: pair.pair_id,
            case_id: caseId,
            state,
            dimensions: {},
            mismatch: true,
            model_evm_agree: false,
            runtime_ms: Number(process.hrtime.bigint() - started) / 1e6,
            observations: {},
            error: String(error.stack || error)
          });
          fs.writeFileSync(manifest.result_path, JSON.stringify(rows, null, 2));
        }
      }
      fs.writeFileSync(manifest.result_path, JSON.stringify(rows, null, 2));
      process.stdout.write(
        `safe validation ${pairIndex + 1}/${manifest.pairs.length} ${pair.pair_id}\n`
      );
    }
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
