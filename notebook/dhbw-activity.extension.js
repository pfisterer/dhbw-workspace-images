// DHBW workspaces: the menu "DHBW" in the status bar, the counterpart of JupyterLab's menu "DHBW" (dhbw-branding in aiaas-deployment), with the same links read from the page config the hub mounts into every workspace. And (aiaas-deployment docs/todo.md app_idle): VS Code's traffic through jupyter-server-proxy tells the server only that its tab is open, not that anyone works (an open tab sends keepalives all the time). This extension reports the person's input instead: typing, moving the cursor, scrolling, switching editors, saving and running a command in a terminal touch a file in DHBW_ACTIVITY_DIR, at most every 30 seconds, which the server's release times count (dhbw_release.py of the bases). It also shows their warning with "Weiterarbeiten", like JupyterLab's status bar. And it warns, like JupyterLab, when the workspace or one of its GPU kernels has filled 80 % (again at 95 %) of its local storage outside the home (dhbw_scratch of the bases), with the text the server gives.
"use strict";
const vscode = require("vscode");
const fs = require("fs");
const http = require("http");
const path = require("path");

const DIR = process.env.DHBW_ACTIVITY_DIR || "/tmp/dhbw-activity";
const FILE = path.join(DIR, "vscode");
const TOUCH_EVERY = 30 * 1000;
const POLL_EVERY = 60 * 1000;
const PAGE_CONFIG = "/etc/jupyter/labconfig/page_config.json";

let touched = 0;

function touch() {
  const now = Date.now();
  if (now - touched < TOUCH_EVERY) return;
  touched = now;
  try {
    fs.mkdirSync(DIR, { recursive: true });
    const t = new Date(now);
    try {
      fs.utimesSync(FILE, t, t);
    } catch {
      fs.writeFileSync(FILE, "");
    }
  } catch {
    // Without the file the release times see no input from VS Code; nothing to bother the person with.
  }
}

// The Jupyter server this VS Code runs behind, with the server's own token (JupyterHub sets both in its environment, which jupyter-server-proxy passes on).
function server() {
  const token = process.env.JUPYTERHUB_API_TOKEN;
  const prefix = process.env.JUPYTERHUB_SERVICE_PREFIX;
  if (!token || !prefix) return null;
  let port = 8888;
  try {
    port = Number(new URL(process.env.JUPYTERHUB_SERVICE_URL).port) || port;
  } catch {
    // keep the default
  }
  return { token, prefix: prefix.endsWith("/") ? prefix : prefix + "/", port };
}

function call(s, method, route) {
  // no_track_activity: our own polling is neither activity nor an open tab (VS Code's extension host outlives a closed tab for a while).
  const options = { host: "127.0.0.1", port: s.port, method, path: s.prefix + route + "?no_track_activity=1", headers: { Authorization: "token " + s.token }, timeout: 10000 };
  return new Promise((resolve) => {
    const req = http.request(options, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try {
          resolve(res.statusCode < 300 && body ? JSON.parse(body) : null);
        } catch {
          resolve(null);
        }
      });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => req.destroy());
    req.end();
  });
}

function minutes(seconds) {
  const m = Math.max(1, Math.ceil(seconds / 60));
  return m === 1 ? "1 Minute" : `${m} Minuten`;
}

function watchRelease(context) {
  const s = server();
  if (!s) return;
  let warned = false;
  let endsWarned = false;
  const scratchShown = new Map(); // "server" or kernel id -> level warned about
  // Local storage: one message per level reached (80 % a warning, 95 % an error); a level that is over may warn again later.
  const scratchWarnings = (status) => {
    const current = new Map();
    if (status.scratch) current.set("server", { scratch: status.scratch, label: "" });
    for (const k of status.kernels || []) {
      if (k.scratch) current.set(k.kernel_id, { scratch: k.scratch, label: `${k.label}: ` });
    }
    for (const [key, { scratch, label }] of current) {
      if ((scratchShown.get(key) || 0) === scratch.level) continue;
      scratchShown.set(key, scratch.level);
      if (!scratch.level || !scratch.message) continue;
      const text = label + scratch.message;
      if (scratch.level >= 95) vscode.window.showErrorMessage(text);
      else vscode.window.showWarningMessage(text);
    }
    for (const key of [...scratchShown.keys()]) {
      if (!current.has(key)) scratchShown.delete(key);
    }
  };
  const poll = async () => {
    const status = await call(s, "GET", "dhbw-gpu/status");
    if (status) scratchWarnings(status);
    const r = status && status.release && status.release.server;
    if (!r) return;
    if (r.warn && !warned) {
      warned = true;
      const choice = await vscode.window.showWarningMessage(`Ohne Aktivität wird der Workspace in etwa ${minutes(r.idle_left)} beendet und gibt seine Ressourcen zurück. Gespeicherte Dateien bleiben erhalten.`, "Weiterarbeiten");
      if (choice === "Weiterarbeiten") {
        await call(s, "POST", "dhbw-gpu/keepalive");
        touch();
      }
    } else if (!r.warn) {
      warned = false;
    }
    if (r.ends_soon && !endsWarned) {
      endsWarned = true;
      vscode.window.showWarningMessage("Die Höchstlaufzeit des Workspaces endet in weniger als 15 Minuten. Bitte Dateien speichern; danach kann der Workspace neu gestartet werden.");
    }
  };
  const timer = setInterval(poll, POLL_EVERY);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

// The links of the menu: dhbwSelfServiceUrl, dhbwDocsUrl and dhbwHubUrl from the hub's page config; an entry whose link is missing stays away.
function links() {
  let c = {};
  try {
    c = JSON.parse(fs.readFileSync(PAGE_CONFIG, "utf8"));
  } catch {
    // outside the DHBW setup: only what needs no link
  }
  const out = {};
  if (c.dhbwSelfServiceUrl) {
    out.projects = c.dhbwSelfServiceUrl;
    try {
      out.servers = new URL("/workspaces/servers", c.dhbwSelfServiceUrl).toString();
    } catch {
      // no servers link
    }
  }
  if (c.dhbwDocsUrl) out.docs = c.dhbwDocsUrl;
  const prefix = process.env.JUPYTERHUB_SERVICE_PREFIX;
  if (c.dhbwHubUrl && prefix) out.jupyterlab = c.dhbwHubUrl.replace(/\/$/, "") + (prefix.endsWith("/") ? prefix : prefix + "/") + "lab";
  return out;
}

function hasOpenCode() {
  return (process.env.PATH || "").split(":").some((d) => {
    try {
      fs.accessSync(path.join(d, "opencode"), fs.constants.X_OK);
      return true;
    } catch {
      return false;
    }
  });
}

function startAgent() {
  const t = vscode.window.createTerminal({ name: "OpenCode" });
  t.show();
  t.sendText("opencode");
}

function setupMenu(context) {
  const open = (key) => () => {
    const url = links()[key];
    if (url) vscode.env.openExternal(vscode.Uri.parse(url));
  };
  const entries = [
    { key: "jupyterlab", command: "dhbw.jupyterlab", label: "$(notebook) JupyterLab öffnen", run: open("jupyterlab") },
    { key: "servers", command: "dhbw.servers", label: "$(server) Aktive Workspaces (Self-Service)", run: open("servers") },
    { key: "projects", command: "dhbw.projects", label: "$(project) Workspace-Projekte (Self-Service)", run: open("projects") },
    { key: "docs", command: "dhbw.docs", label: "$(book) Anleitungen (dhbw.cloud)", run: open("docs") },
    { key: "agent", command: "dhbw.agent", label: "$(hubot) Coding-Agent im Terminal starten (OpenCode)", run: startAgent },
  ];
  for (const e of entries) context.subscriptions.push(vscode.commands.registerCommand(e.command, e.run));
  context.subscriptions.push(
    vscode.commands.registerCommand("dhbw.menu", async () => {
      const have = links();
      const items = entries.filter((e) => (e.key === "agent" ? hasOpenCode() : Boolean(have[e.key])));
      const pick = await vscode.window.showQuickPick(items, { title: "DHBW Workspaces" });
      if (pick) pick.run();
    }),
  );
  const item = vscode.window.createStatusBarItem("dhbw.menu", vscode.StatusBarAlignment.Left, 1000);
  item.name = "DHBW";
  item.text = "$(menu) DHBW";
  item.tooltip = "DHBW Workspaces: JupyterLab, Self-Service, Anleitungen, Coding-Agent";
  item.command = "dhbw.menu";
  item.show();
  context.subscriptions.push(item);
}

function activate(context) {
  const w = vscode.window;
  const events = [
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.contentChanges.length > 0) touch();
    }),
    vscode.workspace.onDidSaveTextDocument(touch),
    w.onDidChangeTextEditorSelection(touch),
    w.onDidChangeTextEditorVisibleRanges(touch),
    w.onDidChangeActiveTextEditor(touch),
    w.onDidChangeActiveTerminal(touch),
    w.onDidOpenTerminal(touch),
    w.onDidChangeWindowState((s) => {
      if (s.focused) touch();
    }),
  ];
  // Running a command in a terminal (shell integration, VS Code 1.93 and later).
  if (w.onDidStartTerminalShellExecution) events.push(w.onDidStartTerminalShellExecution(touch));
  if (vscode.window.onDidChangeNotebookEditorSelection) events.push(vscode.window.onDidChangeNotebookEditorSelection(touch));
  context.subscriptions.push(...events);
  touch();
  setupMenu(context);
  watchRelease(context);
}

function deactivate() {}

module.exports = { activate, deactivate };
