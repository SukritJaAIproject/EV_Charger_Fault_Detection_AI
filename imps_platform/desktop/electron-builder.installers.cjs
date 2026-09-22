const packageMetadata = require("../package.json");


const installerKind = process.env.IMPS_INSTALLER_KIND ?? "both";
const supportedKinds = new Set(["offline", "online", "both"]);

if (!supportedKinds.has(installerKind)) {
  throw new Error(
    `IMPS_INSTALLER_KIND must be offline, online, or both (received ${installerKind})`,
  );
}

const includesOffline = installerKind === "offline" || installerKind === "both";
const includesOnline = installerKind === "online" || installerKind === "both";
const onlinePackageUrl = process.env.IMPS_ONLINE_PACKAGE_URL;

if (includesOnline) {
  if (!onlinePackageUrl) {
    throw new Error(
      "IMPS_ONLINE_PACKAGE_URL must be the full HTTPS URL of the generated x64 .nsis.7z payload",
    );
  }

  const parsed = new URL(onlinePackageUrl);
  const permitsLocalHttp =
    process.env.IMPS_ALLOW_INSECURE_INSTALLER_URL === "1" &&
    (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost");
  if (parsed.protocol !== "https:" && !permitsLocalHttp) {
    throw new Error(
      "IMPS_ONLINE_PACKAGE_URL must use HTTPS (HTTP is allowed only for an explicit localhost smoke test)",
    );
  }
}

const base = packageMetadata.build;
const { artifactName: _unusedArtifactName, ...baseWindowsOptions } = base.win;
const targets = [];
if (includesOffline) targets.push({ target: "nsis", arch: ["x64"] });
if (includesOnline) targets.push({ target: "nsis-web", arch: ["x64"] });

module.exports = {
  ...base,
  directories: {
    ...base.directories,
    output: process.env.IMPS_INSTALLER_OUTPUT ?? "dist-desktop/release",
  },
  win: {
    ...baseWindowsOptions,
    target: targets,
  },
  nsis: {
    ...base.nsis,
    artifactName: "iMPS-Fault-Detection-Offline-Setup-${version}.${ext}",
  },
  ...(includesOnline
    ? {
        nsisWeb: {
          artifactName: "iMPS-Fault-Detection-Online-Setup-${version}.${ext}",
          appPackageUrl: onlinePackageUrl,
        },
      }
    : {}),
};
