import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { cp, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const packageMetadata = JSON.parse(
  await readFile(path.join(projectRoot, "package.json"), "utf8"),
);


function parseArguments(argv) {
  const options = {
    kind: "both",
    output: path.join(projectRoot, "dist-desktop", "release"),
    prepackaged: null,
    reuseOffline: null,
    reuseOnline: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    const value = argv[index + 1];
    if (argument === "--kind" && value) {
      options.kind = value;
      index += 1;
    } else if (argument === "--output" && value) {
      options.output = path.resolve(projectRoot, value);
      index += 1;
    } else if (argument === "--prepackaged" && value) {
      options.prepackaged = path.resolve(projectRoot, value);
      index += 1;
    } else if (argument === "--reuse-offline" && value) {
      options.reuseOffline = path.resolve(projectRoot, value);
      index += 1;
    } else if (argument === "--reuse-online" && value) {
      options.reuseOnline = path.resolve(projectRoot, value);
      index += 1;
    } else {
      throw new Error(`Unknown or incomplete argument: ${argument}`);
    }
  }

  if (!["offline", "online", "both"].includes(options.kind)) {
    throw new Error("--kind must be offline, online, or both");
  }
  return options;
}


function run(command, args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      env,
      stdio: "inherit",
      windowsHide: true,
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited with ${signal ?? `code ${code}`}`));
    });
  });
}


async function assertNonEmptyFile(candidate, label) {
  const details = await stat(candidate).catch(() => null);
  if (!details?.isFile() || details.size === 0) {
    throw new Error(`${label} is missing or empty: ${candidate}`);
  }
}


async function fileHashes(candidate) {
  const sha256 = createHash("sha256");
  const sha512 = createHash("sha512");
  await new Promise((resolve, reject) => {
    const input = createReadStream(candidate);
    input.on("data", (chunk) => {
      sha256.update(chunk);
      sha512.update(chunk);
    });
    input.once("error", reject);
    input.once("end", resolve);
  });
  return {
    sha256: sha256.digest("hex").toUpperCase(),
    sha512: sha512.digest("hex").toUpperCase(),
  };
}


async function copyOnlineArtifacts(source, output) {
  const onlineName = `iMPS-Fault-Detection-Online-Setup-${packageMetadata.version}.exe`;
  const onlineSource = path.join(source, onlineName);
  await assertNonEmptyFile(onlineSource, "Reusable online installer");
  await cp(onlineSource, path.join(output, onlineName), { force: true });

  const payloads = (await readdir(source)).filter((name) => name.endsWith(".nsis.7z"));
  if (payloads.length !== 1) {
    throw new Error(
      `Expected exactly one .nsis.7z payload in ${source}, found ${payloads.length}`,
    );
  }
  const payloadSource = path.join(source, payloads[0]);
  await assertNonEmptyFile(payloadSource, "Reusable online payload");
  await cp(payloadSource, path.join(output, payloads[0]), { force: true });
}


async function writeReleaseManifest(output, onlinePackageUrl) {
  const names = (await readdir(output)).sort((left, right) => left.localeCompare(right));
  const artifactNames = names.filter(
    (name) =>
      /^iMPS-Fault-Detection-.*\.(?:exe|blockmap)$/i.test(name) ||
      /\.nsis\.7z$/i.test(name) ||
      /^latest.*\.ya?ml$/i.test(name),
  );
  const artifacts = [];
  for (const name of artifactNames) {
    const candidate = path.join(output, name);
    const details = await stat(candidate);
    if (!details.isFile()) continue;
    const hashes = await fileHashes(candidate);
    artifacts.push({
      name,
      bytes: details.size,
      ...hashes,
    });
  }

  const manifest = {
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    appVersion: packageMetadata.version,
    platform: "win32",
    arch: "x64",
    onlinePackageUrl: onlinePackageUrl ?? null,
    artifacts,
  };
  await writeFile(
    path.join(output, "release-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
  await writeFile(
    path.join(output, "SHA256SUMS.txt"),
    `${artifacts.map((artifact) => `${artifact.sha256} *${artifact.name}`).join("\n")}\n`,
    "utf8",
  );
  return manifest;
}


async function main() {
  const options = parseArguments(process.argv.slice(2));
  const includesOffline = options.kind === "offline" || options.kind === "both";
  const includesOnline = options.kind === "online" || options.kind === "both";
  const onlinePackageUrl = process.env.IMPS_ONLINE_PACKAGE_URL;

  if (includesOnline && !onlinePackageUrl) {
    throw new Error(
      "Set IMPS_ONLINE_PACKAGE_URL to the full HTTPS URL where the generated .nsis.7z payload will be hosted",
    );
  }
  if (options.prepackaged) {
    await assertNonEmptyFile(
      path.join(options.prepackaged, "iMPS Fault Detection.exe"),
      "Prepackaged desktop executable",
    );
  }

  await mkdir(options.output, { recursive: true });
  let buildOffline = includesOffline;
  let buildOnline = includesOnline;

  if (includesOffline && options.reuseOffline) {
    await assertNonEmptyFile(options.reuseOffline, "Reusable offline installer");
    const offlineName = `iMPS-Fault-Detection-Offline-Setup-${packageMetadata.version}.exe`;
    await cp(options.reuseOffline, path.join(options.output, offlineName), { force: true });
    const reusableBlockmap = `${options.reuseOffline}.blockmap`;
    const blockmapDetails = await stat(reusableBlockmap).catch(() => null);
    if (blockmapDetails?.isFile() && blockmapDetails.size > 0) {
      await cp(reusableBlockmap, path.join(options.output, `${offlineName}.blockmap`), {
        force: true,
      });
    }
    buildOffline = false;
  }

  if (includesOnline && options.reuseOnline) {
    await copyOnlineArtifacts(options.reuseOnline, options.output);
    buildOnline = false;
  }

  const builderKind =
    buildOffline && buildOnline
      ? "both"
      : buildOffline
        ? "offline"
        : buildOnline
          ? "online"
          : null;
  if (builderKind) {
    const builderCli = path.join(
      projectRoot,
      "node_modules",
      "electron-builder",
      "out",
      "cli",
      "cli.js",
    );
    const args = [
      builderCli,
      "--config",
      path.join(projectRoot, "desktop", "electron-builder.installers.cjs"),
      "--win",
      "--x64",
    ];
    if (options.prepackaged) args.push("--prepackaged", options.prepackaged);
    await assertNonEmptyFile(builderCli, "electron-builder CLI");
    await run(process.execPath, args, {
      ...process.env,
      IMPS_INSTALLER_KIND: builderKind,
      IMPS_INSTALLER_OUTPUT: options.output,
    });

    if (builderKind === "online" || builderKind === "both") {
      const onlineName = `iMPS-Fault-Detection-Online-Setup-${packageMetadata.version}.exe`;
      const onlineAtRoot = await stat(path.join(options.output, onlineName)).catch(() => null);
      if (!onlineAtRoot?.isFile()) {
        await copyOnlineArtifacts(path.join(options.output, "nsis-web"), options.output);
      }
    }
  }

  const offlinePath = path.join(
    options.output,
    `iMPS-Fault-Detection-Offline-Setup-${packageMetadata.version}.exe`,
  );
  const onlinePath = path.join(
    options.output,
    `iMPS-Fault-Detection-Online-Setup-${packageMetadata.version}.exe`,
  );
  if (includesOffline) await assertNonEmptyFile(offlinePath, "Offline installer");
  if (includesOnline) await assertNonEmptyFile(onlinePath, "Online installer");

  const manifest = await writeReleaseManifest(options.output, onlinePackageUrl);
  process.stdout.write(
    `Installer release prepared with ${manifest.artifacts.length} checksummed artifacts at ${options.output}\n`,
  );
}


main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
