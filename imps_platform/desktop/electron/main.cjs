"use strict";

const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");


// The product name decides the window title and, through app.setName, the
// %APPDATA% folder for logs and PCAP jobs. It comes from the package.json that
// electron-builder bakes into the asar (extraMetadata), so an edition built
// under another name keeps its own data and can be installed side by side.
const APP_NAME = (() => {
  try {
    const meta = require(path.join(__dirname, "..", "..", "package.json"));
    if (typeof meta.productName === "string" && meta.productName.trim()) return meta.productName.trim();
  } catch {}
  return "iMPS Fault Detection";
})();
const LOOPBACK = "127.0.0.1";
const isSmokeTest = process.argv.includes("--smoke-test");
app.setName(APP_NAME);
let mainWindow = null;
let nextProcess = null;
let runtimeProcess = null;
let runtimeLogStream = null;
let shuttingDown = false;


function getRuntimePaths() {
  const projectRoot = path.resolve(__dirname, "../..");
  if (app.isPackaged) {
    return {
      nextRoot: path.join(process.resourcesPath, "app"),
      summaryPath: path.join(process.resourcesPath, "data", "summary.json"),
      runtimeExecutable: path.join(process.resourcesPath, "runtime", "imps-fault-runtime.exe"),
      modelDir: path.join(process.resourcesPath, "models"),
      tsharkPath: path.join(process.resourcesPath, "runtime", "wireshark", "tshark.exe"),
      iconPath: path.join(process.resourcesPath, "icon.png"),
    };
  }
  return {
    nextRoot: path.join(projectRoot, ".next-desktop", "standalone"),
    summaryPath: path.join(projectRoot, ".desktop-build", "summary.json"),
    runtimeExecutable: path.join(projectRoot, ".desktop-build", "runtime", "imps-fault-runtime.exe"),
    modelDir: path.join(projectRoot, ".desktop-build", "models"),
    tsharkPath: path.join(projectRoot, ".desktop-build", "runtime", "wireshark", "tshark.exe"),
    iconPath: path.join(projectRoot, "public", "img", "AI-icon.png"),
  };
}


function findFile(root, filename, depth = 0) {
  const direct = path.join(root, filename);
  if (fs.existsSync(direct)) return direct;
  if (depth >= 3 || !fs.existsSync(root)) return null;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === "node_modules") continue;
    const found = findFile(path.join(root, entry.name), filename, depth + 1);
    if (found) return found;
  }
  return null;
}


function appendLog(stream, prefix, chunk) {
  stream.write(`${new Date().toISOString()} ${prefix} ${String(chunk)}`);
}


function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, LOOPBACK, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}


function assertRuntimeFiles(runtime) {
  const required = [
    runtime.summaryPath,
    runtime.runtimeExecutable,
    path.join(runtime.modelDir, "lstm_ae.npz"),
    path.join(runtime.modelDir, "gru_fore.npz"),
    path.join(runtime.modelDir, "manifest.json"),
    runtime.tsharkPath,
  ];
  const missing = required.filter((candidate) => !fs.existsSync(candidate));
  if (missing.length) {
    throw new Error(`The full PCAP runtime is incomplete:\n${missing.join("\n")}`);
  }
}


function startInferenceRuntime(runtime, apiPort, webOrigin, jobsRoot, logStream) {
  assertRuntimeFiles(runtime);
  fs.mkdirSync(jobsRoot, { recursive: true });
  const child = spawn(runtime.runtimeExecutable, [
    "serve",
    "--host", LOOPBACK,
    "--port", String(apiPort),
    "--origin", webOrigin,
    "--summary", runtime.summaryPath,
    "--model-dir", runtime.modelDir,
    "--tshark", runtime.tsharkPath,
    "--jobs-root", jobsRoot,
  ], {
    cwd: path.dirname(runtime.runtimeExecutable),
    env: {
      ...process.env,
      // Reported on /health so the dashboard header can name this edition.
      // Passed through the environment (not argv) so a sidecar built before
      // these fields existed still starts.
      IMPS_PRODUCT_NAME: APP_NAME,
      IMPS_APP_VERSION: app.getVersion(),
      OMP_NUM_THREADS: "1",
      MKL_NUM_THREADS: "1",
      OPENBLAS_NUM_THREADS: "1",
      NUMEXPR_NUM_THREADS: "1",
    },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => appendLog(logStream, "API", chunk));
  child.stderr.on("data", (chunk) => appendLog(logStream, "API-ERR", chunk));
  child.once("error", (error) => appendLog(logStream, "API-SPAWN", `${error.stack ?? error}\n`));
  return child;
}


function waitForHttp(url, child, timeoutMs = 60000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      if (child.exitCode != null) {
        reject(new Error(`The embedded web server exited with code ${child.exitCode}`));
        return;
      }
      const request = http.get(url, (response) => {
        response.resume();
        if (response.statusCode === 200) {
          resolve();
          return;
        }
        retry();
      });
      request.setTimeout(1500, () => request.destroy());
      request.once("error", retry);
    };
    const retry = () => {
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(check, 350);
    };
    check();
  });
}


function waitForRuntimeHealth(url, child, timeoutMs = 180000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const retry = () => {
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error(`Timed out waiting for the PCAP runtime at ${url}`));
        return;
      }
      setTimeout(check, 350);
    };
    const check = () => {
      if (child.exitCode != null) {
        reject(new Error(`The PCAP runtime exited with code ${child.exitCode}`));
        return;
      }
      const request = http.get(url, (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          if (body.length < 65536) body += chunk;
        });
        response.on("end", () => {
          try {
            const health = JSON.parse(body);
            if (response.statusCode === 200 && health.status === "ok" && health.inferenceReady === true) {
              resolve(health);
              return;
            }
          } catch {
            // The runtime may still be starting and not serving JSON yet.
          }
          retry();
        });
      });
      request.setTimeout(1500, () => request.destroy());
      request.once("error", retry);
    };
    check();
  });
}


async function startNextServer(nextRoot, webPort, logStream) {
  const serverEntry = findFile(nextRoot, "server.js");
  if (!serverEntry) throw new Error(`Embedded Next.js server not found under ${nextRoot}`);
  const child = spawn(process.execPath, [serverEntry], {
    cwd: path.dirname(serverEntry),
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      NODE_ENV: "production",
      HOSTNAME: LOOPBACK,
      PORT: String(webPort),
      NEXT_TELEMETRY_DISABLED: "1",
      NODE_PATH: path.join(path.dirname(serverEntry), "server_modules"),
    },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => appendLog(logStream, "WEB", chunk));
  child.stderr.on("data", (chunk) => appendLog(logStream, "WEB-ERR", chunk));
  child.once("error", (error) => appendLog(logStream, "WEB-SPAWN", `${error.stack ?? error}\n`));
  try {
    await waitForHttp(`http://${LOOPBACK}:${webPort}/dashboard/ai/fault-detection?desktop=1`, child);
    return child;
  } catch (error) {
    terminateProcessTree(child);
    throw error;
  }
}


function terminateProcessTree(child) {
  if (!child || child.exitCode != null) return;
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    return;
  }
  child.kill();
}


function stopServices() {
  terminateProcessTree(nextProcess);
  nextProcess = null;
  terminateProcessTree(runtimeProcess);
  runtimeProcess = null;
  if (runtimeLogStream) {
    runtimeLogStream.end();
    runtimeLogStream = null;
  }
}


async function launch() {
  const runtime = getRuntimePaths();
  const webPort = await getFreePort();
  let apiPort = await getFreePort();
  while (apiPort === webPort) apiPort = await getFreePort();
  const webOrigin = `http://${LOOPBACK}:${webPort}`;

  const logDir = path.join(app.getPath("userData"), "logs");
  fs.mkdirSync(logDir, { recursive: true });
  runtimeLogStream = fs.createWriteStream(path.join(logDir, "desktop-runtime.log"), { flags: "a" });
  const jobsRoot = path.join(app.getPath("userData"), "pcap-jobs");
  appendLog(
    runtimeLogStream,
    "RUNTIME",
    `web=${webOrigin} api=http://${LOOPBACK}:${apiPort} next=${runtime.nextRoot} jobs=${jobsRoot}\n`,
  );
  runtimeProcess = startInferenceRuntime(runtime, apiPort, webOrigin, jobsRoot, runtimeLogStream);
  await waitForRuntimeHealth(`http://${LOOPBACK}:${apiPort}/health`, runtimeProcess);
  nextProcess = await startNextServer(runtime.nextRoot, webPort, runtimeLogStream);

  if (isSmokeTest) {
    appendLog(runtimeLogStream, "SMOKE", "PASS runtime=ready web=ready\n");
    app.quit();
    return;
  }

  const dashboardUrl = `${webOrigin}/dashboard/ai/fault-detection?desktop=1&desktopApiPort=${apiPort}&packaged=1`;
  mainWindow = new BrowserWindow({
    title: APP_NAME,
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    show: false,
    backgroundColor: "#f8fafc",
    autoHideMenuBar: true,
    icon: fs.existsSync(runtime.iconPath) ? runtime.iconPath : undefined,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
    },
  });
  Menu.setApplicationMenu(null);
  mainWindow.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    let isInternal = false;
    try {
      isInternal = new URL(url).origin === webOrigin;
    } catch {
      isInternal = false;
    }
    if (!isInternal) {
      event.preventDefault();
      if (/^https?:/i.test(url)) void shell.openExternal(url);
    }
  });
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  // The dashboard's <title> is the generic "iMPS"; keep the edition's product
  // name in the title bar so two installed editions can be told apart. The
  // event is emitted by the BrowserWindow, not by its webContents.
  mainWindow.on("page-title-updated", (event) => {
    event.preventDefault();
    mainWindow?.setTitle(APP_NAME);
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  await mainWindow.loadURL(dashboardUrl);
}


const hasLock = app.requestSingleInstanceLock();
if (!hasLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.whenReady().then(launch).catch((error) => {
    dialog.showErrorBox(
      `${APP_NAME} could not start`,
      `${error.message}\n\nLogs: ${path.join(app.getPath("userData"), "logs")}`,
    );
    stopServices();
    app.quit();
  });
}


app.on("before-quit", () => {
  if (shuttingDown) return;
  shuttingDown = true;
  stopServices();
});


app.on("window-all-closed", () => app.quit());
