const fs = require("node:fs");
const path = require("node:path");
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

// Code signing is opt-in: set IMPS_SIGN_CERT_SHA1 to the thumbprint of a code-signing
// certificate in the current user's store and electron-builder signs the app
// executable, the uninstaller and both installers with it (SHA-256, RFC 3161
// timestamp so the signature outlives the certificate). Nothing is signed when
// the variable is unset, so team builds keep working without a certificate.
const signCertSha1 = process.env.IMPS_SIGN_CERT_SHA1?.trim();
const signtoolOptions = signCertSha1
  ? {
      certificateSha1: signCertSha1,
      signingHashAlgorithms: ["sha256"],
      rfc3161TimeStampServer:
        process.env.IMPS_SIGN_TIMESTAMP_URL ?? "http://timestamp.digicert.com",
    }
  : undefined;

// Product identity is overridable so a second, independently installable
// edition can be built from the same tree (the 2026-09-12 snapshot lives next
// to the current line as its own app: different appId, install folder,
// shortcuts and %APPDATA%). Defaults reproduce the published 'iMPS Fault
// Detection'. IMPS_RESOURCES_ROOT points the bundled app/data/runtime/models
// at a previously prepared resources directory instead of .desktop-build.
const productName = process.env.IMPS_PRODUCT_NAME?.trim() || packageMetadata.build.productName;
const appId = process.env.IMPS_APP_ID?.trim() || packageMetadata.build.appId;
// IMPS_APP_VERSION lets an edition carry its own version (e.g. 1.1.1 for the
// snapshot) without editing package.json; electron-builder writes it into the
// asar's package.json, so app.getVersion() reports it too.
const version = process.env.IMPS_APP_VERSION?.trim() || packageMetadata.version;
const productSlug = productName.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "");
const resourcesRoot = process.env.IMPS_RESOURCES_ROOT?.trim();

// IMPS_ICON_DIR gives an edition its own artwork (desktop/icons/<edition>):
// icon.ico becomes win.icon, which electron-builder applies to the exe before
// signing (no post-build rcedit) and NSIS reuses for both installers, the
// uninstaller, Apps & Features and the shortcuts; icon.png is the BrowserWindow
// icon (resources/icon.png), which
// is what the taskbar and alt-tab show. The browser-tab favicon lives inside
// the Next app that all editions share, so it is swapped in the staged
// resources instead (desktop/scripts/stage-edition-resources.ps1).
const iconDir = process.env.IMPS_ICON_DIR?.trim();
const iconIco = iconDir ? path.resolve(__dirname, "..", iconDir, "icon.ico") : null;
const iconPng = iconDir ? path.resolve(__dirname, "..", iconDir, "icon.png") : null;
for (const iconFile of [iconIco, iconPng]) {
  if (iconFile && !fs.existsSync(iconFile)) throw new Error(`IMPS_ICON_DIR is missing ${iconFile}`);
}

const remapResource = (entry) => {
  if (iconPng && entry.from === "public/img/AI-icon.png") return { ...entry, from: iconPng };
  if (!resourcesRoot) return entry;
  const map = {
    ".next-desktop/standalone": "app",
    ".desktop-build/summary.json": "data/summary.json",
    ".desktop-build/runtime": "runtime",
    ".desktop-build/models": "models",
  };
  return map[entry.from] ? { ...entry, from: `${resourcesRoot}/${map[entry.from]}` } : entry;
};

// Third-party executables bundled as extra resources (Wireshark's tools) ship
// with their vendor's Authenticode signature. When signing is on, electron-builder
// re-signs every .exe it copies, which would replace the Wireshark Foundation
// signature with ours; a "!name" entry in win.signExts excludes a file (matched
// on the end of its path), so every executable anywhere under the bundled
// Wireshark directory (including extcap\) is listed here and kept as shipped.
const runtimeDir = resourcesRoot ? path.join(resourcesRoot, "runtime") : ".desktop-build/runtime";
const wiresharkDir = path.resolve(__dirname, "..", runtimeDir, "wireshark");
const listExecutables = (dir) =>
  fs.existsSync(dir)
    ? fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
        entry.isDirectory()
          ? listExecutables(path.join(dir, entry.name))
          : entry.name.toLowerCase().endsWith(".exe")
            ? [entry.name]
            : [],
      )
    : [];
const signExts = [...new Set(listExecutables(wiresharkDir))].map((name) => `!${name}`);

const base = packageMetadata.build;
const { artifactName: _unusedArtifactName, ...baseWindowsOptions } = base.win;
const targets = [];
if (includesOffline) targets.push({ target: "nsis", arch: ["x64"] });
if (includesOnline) targets.push({ target: "nsis-web", arch: ["x64"] });

module.exports = {
  ...base,
  appId,
  productName,
  extraMetadata: { ...(base.extraMetadata ?? {}), productName, version },
  extraResources: (base.extraResources ?? []).map(remapResource),
  directories: {
    ...base.directories,
    output: process.env.IMPS_INSTALLER_OUTPUT ?? "dist-desktop/release",
  },
  win: {
    ...baseWindowsOptions,
    ...(iconIco ? { icon: iconIco } : {}),
    target: targets,
    ...(signtoolOptions ? { signtoolOptions, signExts } : {}),
  },
  nsis: {
    ...base.nsis,
    shortcutName: productName,
    artifactName: `${productSlug}-Offline-Setup-\${version}.\${ext}`,
  },
  ...(includesOnline
    ? {
        nsisWeb: {
          artifactName: `${productSlug}-Online-Setup-\${version}.\${ext}`,
          appPackageUrl: onlinePackageUrl,
        },
      }
    : {}),
};
