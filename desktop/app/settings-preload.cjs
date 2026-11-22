const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('argusSettings', {
  status: () => ipcRenderer.invoke('settings:status'),
  changeKey: (key) => ipcRenderer.invoke('settings:change-key', key),
});
