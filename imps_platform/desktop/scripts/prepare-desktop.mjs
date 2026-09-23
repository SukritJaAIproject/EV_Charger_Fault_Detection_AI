import { cp, mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const desktopBuildRoot = path.join(projectRoot, ".desktop-build");
const nextBuildRoot = path.join(projectRoot, ".next-desktop");


function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      env: { ...process.env, ...options.env },
      stdio: "inherit",
      windowsHide: true,
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} exited with ${signal ?? `code ${code}`}`));
    });
  });
}


async function runWithRetry(command, args, options = {}, attempts = 2) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await run(command, args, options);
      return;
    } catch (error) {
      lastError = error;
      if (attempt === attempts) break;
      process.stderr.write(
        `${command} failed on attempt ${attempt}/${attempts}; retrying once after a short delay.\n`,
      );
      await new Promise((resolve) => setTimeout(resolve, 2_000));
    }
  }
  throw lastError;
}


async function exists(candidate) {
  try {
    await stat(candidate);
    return true;
  } catch {
    return false;
  }
}


function powershellExecutable() {
  const systemRoot = process.env.SystemRoot ?? "C:\\Windows";
  return path.join(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
}


async function preparePortableRuntime() {
  const powershell = powershellExecutable();
  const runtimeScript = path.join(projectRoot, "desktop", "runtime", "build_runtime.ps1");
  const tsharkScript = path.join(projectRoot, "desktop", "scripts", "bundle-tshark.ps1");

  const runtimeArgs = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", runtimeScript];
  if (process.env.IMPS_MODEL_PYTHON) runtimeArgs.push("-ModelPython", process.env.IMPS_MODEL_PYTHON);
  if (process.env.IMPS_MODEL_SOURCE) runtimeArgs.push("-ModelSource", process.env.IMPS_MODEL_SOURCE);
  if (process.env.PYTHON) runtimeArgs.push("-Python", process.env.PYTHON);
  await run(powershell, runtimeArgs);

  const tsharkArgs = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tsharkScript];
  if (process.env.IMPS_WIRESHARK_SOURCE) {
    tsharkArgs.push("-SourceDirectory", process.env.IMPS_WIRESHARK_SOURCE);
  }
  if (process.env.IMPS_VC_RUNTIME_SOURCE) {
    tsharkArgs.push("-VCRuntimeDirectory", process.env.IMPS_VC_RUNTIME_SOURCE);
  }
  if (process.env.IMPS_GOLDEN_PCAP) tsharkArgs.push("-GoldenPcap", process.env.IMPS_GOLDEN_PCAP);
  if (process.env.IMPS_SKIP_TSHARK_SMOKE === "1") tsharkArgs.push("-SkipSmokeTest");
  await run(powershell, tsharkArgs);

  const required = [
    path.join(desktopBuildRoot, "runtime", "imps-fault-runtime.exe"),
    path.join(desktopBuildRoot, "runtime", "wireshark", "tshark.exe"),
    path.join(desktopBuildRoot, "runtime", "wireshark", "imps-tshark-bundle.json"),
    path.join(desktopBuildRoot, "models", "lstm_ae.npz"),
    path.join(desktopBuildRoot, "models", "gru_fore.npz"),
    path.join(desktopBuildRoot, "models", "manifest.json"),
  ];
  for (const artifact of required) {
    if (!(await exists(artifact)) || (await stat(artifact)).size === 0) {
      throw new Error(`Required full desktop artifact is missing or empty: ${artifact}`);
    }
  }
}


async function smokePortableRuntime() {
  if (process.env.IMPS_SKIP_RUNTIME_SMOKE === "1") return;
  const smokeScript = path.join(projectRoot, "desktop", "runtime", "smoke_runtime.ps1");
  const args = [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    smokeScript,
    "-SkipHealthy",
  ];
  if (process.env.IMPS_GOLDEN_PCAP) args.push("-GoldenPcap", process.env.IMPS_GOLDEN_PCAP);
  await run(powershellExecutable(), args);
}


async function exportSummary() {
  const exporter = path.join(projectRoot, "desktop", "export_summary.py");
  const output = path.join(desktopBuildRoot, "summary.json");
  const configured = process.env.PYTHON ? [{ command: process.env.PYTHON, prefix: [] }] : [];
  const candidates = [
    ...configured,
    { command: "python", prefix: [] },
    { command: "py", prefix: ["-3"] },
  ];
  let lastError;
  for (const candidate of candidates) {
    try {
      await run(candidate.command, [
        ...candidate.prefix,
        exporter,
        "--output",
        output,
        ...(process.env.IMPS_FAULT_DATA_ROOT
          ? ["--data-root", process.env.IMPS_FAULT_DATA_ROOT]
          : []),
        // the current line bundles the in-sample training-station rows
        ...(process.env.IMPS_FAULT_TRAIN_RECORDS
          ? ["--train-records", process.env.IMPS_FAULT_TRAIN_RECORDS]
          : []),
      ]);
      return output;
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(`Unable to export the desktop summary: ${lastError?.message ?? "Python was not found"}`);
}


async function findServerEntry(root, depth = 0) {
  const direct = path.join(root, "server.js");
  if (await exists(direct)) return direct;
  if (depth >= 3) return null;
  const { readdir } = await import("node:fs/promises");
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === "node_modules") continue;
    const found = await findServerEntry(path.join(root, entry.name), depth + 1);
    if (found) return found;
  }
  return null;
}


async function main() {
  await mkdir(desktopBuildRoot, { recursive: true });
  await preparePortableRuntime();
  const summaryPath = await exportSummary();
  await smokePortableRuntime();

  const nextCli = path.join(projectRoot, "node_modules", "next", "dist", "bin", "next");
  if (!(await exists(nextCli))) {
    throw new Error("Next.js is not installed. Run npm install first.");
  }

  if (await exists(nextBuildRoot)) {
    const resolved = path.resolve(nextBuildRoot);
    if (path.dirname(resolved) !== projectRoot || path.basename(resolved) !== ".next-desktop") {
      throw new Error(`Refusing to remove unexpected build directory: ${resolved}`);
    }
    await rm(resolved, { recursive: true, force: true });
  }

  // On Windows, endpoint protection can terminate a short-lived Next build
  // worker without a JavaScript stack while newly generated binaries are being
  // scanned. A clean one-time retry recovered that exact transient failure;
  // deterministic build errors still fail on the second attempt.
  await runWithRetry(process.execPath, [nextCli, "build"], {
    env: {
      IMPS_DESKTOP_BUILD: "1",
      NEXT_PUBLIC_FAULT_PCAP_ENABLED: "true",
      NEXT_TELEMETRY_DISABLED: "1",
    },
  }, 2);

  const standaloneRoot = path.join(nextBuildRoot, "standalone");
  const serverEntry = await findServerEntry(standaloneRoot);
  if (!serverEntry) {
    throw new Error(`Next.js standalone server was not generated under ${standaloneRoot}`);
  }
  const serverRoot = path.dirname(serverEntry);
  const staticSource = path.join(nextBuildRoot, "static");
  const staticTarget = path.join(serverRoot, ".next-desktop", "static");
  await mkdir(path.dirname(staticTarget), { recursive: true });
  await cp(staticSource, staticTarget, { recursive: true, force: true });

  const publicSource = path.join(projectRoot, "public");
  if (await exists(publicSource)) {
    await cp(publicSource, path.join(serverRoot, "public"), { recursive: true, force: true });
  }

  // electron-builder intentionally filters directories named node_modules from
  // extraResources. Keep Next's traced production dependencies under a neutral
  // name and point the embedded Node runtime at it with NODE_PATH.
  const nodeModulesSource = path.join(serverRoot, "node_modules");
  const serverModulesTarget = path.join(serverRoot, "server_modules");
  if (!(await exists(nodeModulesSource))) {
    throw new Error(`Next.js standalone dependencies were not generated under ${serverRoot}`);
  }
  await rename(nodeModulesSource, serverModulesTarget);

  const summary = JSON.parse(await readFile(summaryPath, "utf8"));
  const manifest = {
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    appVersion: JSON.parse(await readFile(path.join(projectRoot, "package.json"), "utf8")).version,
    snapshotAt: summary.snapshotAt,
    sessions: summary.dataset?.sessions ?? null,
    stations: summary.analysis?.byStation?.length ?? 0,
    trainStations: summary.analysis?.byStationTrain?.length ?? 0,
    detectionPolicy: summary.detectionPolicy?.id ?? "baseline",
    models: summary.leaderboard?.length ?? 0,
    nextServerRelativePath: path.relative(standaloneRoot, serverEntry).replaceAll("\\", "/"),
    moduleDirectory: "server_modules",
  };
  await writeFile(
    path.join(desktopBuildRoot, "manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(`Desktop bundle prepared: ${JSON.stringify(manifest)}\n`);
}


main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
