const { app, BrowserWindow, Menu, dialog, ipcMain, session } = require('electron');
const { mkdirSync } = require('node:fs');
const { writeFile } = require('node:fs/promises');
const { dirname, join, resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const { changeKey, launch } = require('./sidecar.cjs');

const smokeArg = process.argv.find((arg) => arg.startsWith('--smoke-test='));
const smokeFile = smokeArg && resolve(smokeArg.slice('--smoke-test='.length));
const smokeVisible = process.argv.includes('--smoke-visible');
const mac = process.platform === 'darwin';
if (smokeFile) {
  const profile = join(dirname(smokeFile), 'profile');
  mkdirSync(profile, { recursive: true });
  app.setPath('userData', profile);
}
const data = app.getPath('userData');
const settingsPath = join(__dirname, 'settings.html');
const settingsUrl = pathToFileURL(settingsPath).href;
const binary = process.platform === 'win32' ? 'argus-sidecar.exe' : 'argus-sidecar';
const executable = join(process.resourcesPath, 'sidecar', binary);

let workspace;
let settings;
let service;
let info;
let quitting = false;
let allowQuit = false;
let recoveryUntil = 0;
let switching = false;
let lifecycle = Promise.resolve();
const shutdown = new AbortController();

function transition(operation) {
  const result = lifecycle.then(operation);
  lifecycle = result.catch(() => {});
  return result;
}

function permissions(partition) {
  partition.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  partition.setPermissionCheckHandler(() => false);
}

function lockNavigation(win, accepts) {
  win.webContents.on('will-frame-navigate', (event) => {
    if (!accepts(event.url)) event.preventDefault();
  });
  win.webContents.on('will-redirect', (event) => {
    if (!accepts(event.url)) event.preventDefault();
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
}

function isWorkspaceUrl(url) {
  return info !== undefined && new URL(url).origin === info.origin;
}

async function createWorkspace() {
  const partition = session.fromPartition('argus-workspace');
  permissions(partition);
  await partition.setProxy({ mode: 'direct' });
  partition.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !isWorkspaceUrl(details.url) }));
  partition.webRequest.onBeforeSendHeaders((details, callback) => {
    const requestHeaders = details.webContentsId === workspace?.webContents.id && isWorkspaceUrl(details.url)
      ? { ...details.requestHeaders, ...service.headers }
      : details.requestHeaders;
    callback({ requestHeaders });
  });

  const win = new BrowserWindow({
    width: 1440,
    height: 940,
    title: 'Argus',
    show: false,
    webPreferences: {
      session: partition,
      sandbox: true,
      contextIsolation: true,
      backgroundThrottling: !smokeFile,
    },
  });
  lockNavigation(win, isWorkspaceUrl);
  win.on('page-title-updated', (event) => event.preventDefault());
  win.on('closed', () => { workspace = undefined; });
  return win;
}

function windowTitle() {
  return info?.mode === 'replay' ? 'Argus · Simulated shop · Sealed replay' : 'Argus · Mission Control';
}

async function startWorkspace() {
  if (quitting) return;
  const next = launch(executable, {
    data,
    replayOnly: Boolean(smokeFile),
  });
  service = next;
  try {
    info = await next.ready;
    if (quitting) return;
    workspace ??= await createWorkspace();
    workspace.setTitle(windowTitle());
    const query = info.mode === 'replay' ? '?agentdemo=s4' : '?view=overview';
    await workspace.loadURL(`${info.origin}/${query}`);
    if (!smokeFile || smokeVisible) workspace.show();
  } catch (error) {
    await next.stop();
    if (service === next) info = undefined;
    throw error;
  }

  void next.done.then(() => transition(async () => {
    if (quitting || next.stopping || next !== service || smokeFile) return;
    info = undefined;
    if (Date.now() < recoveryUntil) throw new Error('The local API stopped repeatedly');
    recoveryUntil = Date.now() + 30_000;
    await startWorkspace();
  })).catch(startupError);
}

function startupError() {
  if (quitting) return;
  dialog.showErrorBox('Argus could not start', 'The local Argus API could not start. Close and reopen Argus to try again.');
  app.quit();
}

async function openSettings(visible = true) {
  if (settings) {
    settings.focus();
    return settings;
  }
  const partition = session.fromPartition('argus-settings');
  permissions(partition);
  const win = new BrowserWindow({
    parent: workspace,
    title: 'Argus Settings',
    width: 500,
    height: 320,
    resizable: false,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      session: partition,
      preload: join(__dirname, 'settings-preload.cjs'),
      sandbox: true,
      contextIsolation: true,
    },
  });
  settings = win;
  lockNavigation(win, (url) => url === settingsUrl);
  win.on('closed', () => { settings = undefined; });
  await win.loadFile(settingsPath);
  if (visible) win.show();
  return win;
}

function menu() {
  const settingsItem = {
    label: 'Settings…',
    accelerator: 'CmdOrCtrl+,',
    click: () => void openSettings().catch(() => {
      dialog.showErrorBox('Argus Settings', 'Settings could not open.');
    }),
  };
  const argus = { label: 'Argus', submenu: [settingsItem, { type: 'separator' }, { role: 'quit' }] };
  const file = { label: 'File', submenu: [settingsItem, { type: 'separator' }, { role: 'quit' }] };
  Menu.setApplicationMenu(Menu.buildFromTemplate([mac ? argus : file, { role: 'editMenu' }, { role: 'windowMenu' }]));
}

function settingsSender(event) {
  return settings && event.sender === settings.webContents && event.senderFrame === settings.webContents.mainFrame &&
    event.senderFrame?.url === settingsUrl;
}

function status() {
  return { mode: info?.mode ?? 'starting', keychainUnavailable: info?.keychainUnavailable === true };
}

ipcMain.handle('settings:status', (event) => settingsSender(event) ? status() : null);
ipcMain.handle('settings:change-key', async (event, key) => {
  if (!settingsSender(event) || smokeFile || switching || quitting || !info) return null;
  if (key !== null && (typeof key !== 'string' || !/^[!-~]{1,512}$/.test(key))) return null;
  switching = true;
  try {
    return await transition(async () => {
      if (quitting) return null;
      if (!await changeKey(executable, key, shutdown.signal)) {
        return { error: 'The system credential store could not be updated.' };
      }
      if (quitting) return null;
      info = undefined;
      await service.stop();
      await startWorkspace();
      return status();
    });
  } catch {
    startupError();
    return null;
  } finally {
    switching = false;
  }
});

app.on('before-quit', (event) => {
  if (allowQuit) return;
  event.preventDefault();
  if (quitting) return;
  quitting = true;
  shutdown.abort();
  void Promise.resolve(service?.stop()).finally(() => {
    allowQuit = true;
    app.quit();
  });
});
app.on('window-all-closed', () => app.quit());

if (!smokeFile && !app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (workspace?.isMinimized()) workspace.restore();
    workspace?.focus();
  });
  void app.whenReady().then(async () => {
    if (quitting) return;
    menu();
    if (smokeFile) {
      let report;
      try {
        await startWorkspace();
        const { verify } = require('./smoke.cjs');
        report = await verify(workspace, service, info, await openSettings(false));
      } catch (error) {
        report = { ok: false, error: error.message };
      } finally {
        await service?.stop();
      }
      await writeFile(smokeFile, JSON.stringify(report));
      app.exit(report.ok ? 0 : 1);
    } else {
      await transition(startWorkspace);
    }
  }).catch(startupError);
}
