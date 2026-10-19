// DHBW GPU platform: makes GPU kernels visible, and warns before the project's release times end the workspace or a GPU kernel (dhbw_release in the server extension). Polls the server extension dhbw_gpu (<base>/dhbw-gpu/status) every 5 s; a waiting or starting GPU kernel gets a notification with its position in the queue and a button to stop waiting. While a GPU kernel holds the GPU, the top bar shows a pulsing red dot with the time until an idle kernel is ended and a button „Jetzt freigeben“ that ends it without asking, which frees the GPU at once; a click on the text ends it after asking. A start refused by the quota is reported by JupyterLab itself (error dialog with the server's message). Release times: shortly before the workspace or a GPU kernel goes back for lack of activity, a warning with „Weiterarbeiten“ (counts as activity); shortly before the project's upper bound ends the workspace or a GPU kernel, a notice with the time.
import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { Dialog, Notification, showDialog } from '@jupyterlab/apputils';
import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import { Widget } from '@lumino/widgets';

interface IKernelStatus {
  kernel_id: string;
  label: string;
  state: 'waiting' | 'preparing' | 'running';
  message: string;
  // Release times (dhbw_release): seconds left without activity at the last check, whether that is within the warning, and the kernel pod's upper bound.
  idle_left?: number;
  idle_warn?: boolean;
  ends_at?: string;
}

interface IServerRelease {
  idle_left: number;
  idle_limit: number;
  tab_open: boolean;
  warn: boolean;
  ends_at?: string | null;
  ends_soon?: boolean;
}

interface IStatus {
  idle_timeout?: number;
  kernels: IKernelStatus[];
  release?: { server: IServerRelease } | null;
}

const STYLE = `
.dhbw-gpu-item { display: flex; align-items: center; gap: 6px; height: var(--jp-private-menubar-height, 28px); padding: 0 10px; font-size: var(--jp-ui-font-size1); cursor: pointer; }
.dhbw-gpu-item.dhbw-gpu-idle { display: none; }
.dhbw-gpu-dot { width: 8px; height: 8px; border-radius: 50%; background: #CF2C29; animation: dhbw-gpu-pulse 1.4s ease-in-out infinite; }
.dhbw-gpu-dot.dhbw-gpu-waiting { background: #E8A33A; }
.dhbw-gpu-item:hover .dhbw-gpu-label { text-decoration: underline; }
.dhbw-gpu-release { margin-left: 6px; padding: 0 8px; height: 20px; border: 1px solid #CF2C29; border-radius: 3px; background: transparent; color: #CF2C29; font-size: var(--jp-ui-font-size0); cursor: pointer; }
.dhbw-gpu-release:hover { background: #CF2C29; color: #fff; }
@keyframes dhbw-gpu-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(207, 44, 41, 0.6); } 50% { opacity: 0.55; box-shadow: 0 0 0 4px rgba(207, 44, 41, 0); } }
`;

// "4:32" or "1:04:32".
function clock(seconds: number): string {
  const left = Math.max(0, Math.floor(seconds));
  const h = Math.floor(left / 3600);
  const m = Math.floor((left % 3600) / 60);
  const sec = left % 60;
  const mm = h ? m.toString().padStart(2, '0') : m.toString();
  return `${h ? `${h}:` : ''}${mm}:${sec.toString().padStart(2, '0')}`;
}

// "4:32": what is left of the idle time, from the kernel's last activity (a server without release times).
function remaining(lastActivity: string | undefined, idleTimeout: number): string {
  if (!lastActivity || !idleTimeout) {
    return '';
  }
  return clock(idleTimeout - (Date.now() - Date.parse(lastActivity)) / 1000);
}

// "18:05": a time of day.
function timeOfDay(iso: string): string {
  return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'dhbw-gpu-status:plugin',
  description: 'Shows waiting and running GPU kernels.',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    const settings = ServerConnection.makeSettings();
    const url = (...parts: string[]) => URLExt.join(settings.baseUrl, 'dhbw-gpu', ...parts);

    const style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    // In the top bar, right of the DHBW links (dhbw-branding, rank 1000): where people look, not down in the status bar.
    const item = new Widget();
    item.id = 'dhbw-gpu-status';
    item.addClass('dhbw-gpu-item');
    item.addClass('dhbw-gpu-idle');
    let last: IStatus = { kernels: [] };
    let polledAt = Date.now();
    app.shell.add(item, 'top', { rank: 1100 });

    // The workspace's release: shown only shortly before it goes back or ends.
    const releaseItem = new Widget();
    releaseItem.id = 'dhbw-release-status';
    releaseItem.addClass('dhbw-gpu-item');
    releaseItem.addClass('dhbw-gpu-idle');
    app.shell.add(releaseItem, 'top', { rank: 1090 });
    const warned = new Map<string, string>(); // what was warned about (server, kernel id, "ends:" …) -> notification id

    const keepalive = async () => {
      await ServerConnection.makeRequest(url('keepalive'), { method: 'POST' }, settings);
      for (const id of warned.values()) {
        Notification.dismiss(id);
      }
      warned.clear();
      void poll();
    };
    const keepAction = { label: 'Weiterarbeiten', callback: () => void keepalive(), displayType: 'accent' as const };

    // One notification per episode: shown when it starts, dismissed when it is over.
    const notify = (key: string, active: boolean, text: string, withKeep: boolean) => {
      const id = warned.get(key);
      if (active && !id) {
        warned.set(key, Notification.warning(text, { autoClose: false, actions: withKeep ? [keepAction] : [] }));
      } else if (!active && id) {
        Notification.dismiss(id);
        warned.delete(key);
      }
    };

    const warnings = (status: IStatus) => {
      const server = status.release?.server;
      notify('server', !!server?.warn, `Ohne Aktivität wird dieser Workspace in etwa ${clock(server?.idle_left ?? 0)} zurückgegeben${server?.tab_open ? '' : ' (kein offener Tab)'}. Gespeicherte Dateien bleiben, Variablen gehen verloren.`, true);
      notify('server-ends', !!server?.ends_soon && !!server?.ends_at, server?.ends_at ? `Dieser Workspace endet um ${timeOfDay(server.ends_at)}, die Obergrenze des Projekts. Bis dahin speichern; danach neu starten.` : '', false);
      const running = status.kernels.filter(k => k.state === 'running');
      for (const k of running) {
        notify(`kernel:${k.kernel_id}`, !!k.idle_warn, `${k.label}: Ohne Aktivität wird der GPU-Kernel in etwa ${clock(k.idle_left ?? 0)} freigegeben, seine Variablen gehen verloren.`, true);
        const endsSoon = !!k.ends_at && Date.parse(k.ends_at) - Date.now() <= 15 * 60 * 1000;
        notify(`ends:${k.kernel_id}`, endsSoon, k.ends_at ? `${k.label}: Der GPU-Kernel endet um ${timeOfDay(k.ends_at)}, die Obergrenze des Projekts. Lange Rechnungen gehören in einen GPU-Job.` : '', false);
      }
      for (const key of [...warned.keys()]) {
        const kid = key.startsWith('kernel:') ? key.slice(7) : key.startsWith('ends:') ? key.slice(5) : '';
        if (kid && !running.some(k => k.kernel_id === kid)) {
          notify(key, false, '', false);
        }
      }
    };

    const notifications = new Map<string, string>(); // kernel id -> notification id
    const shown = new Map<string, string>(); // kernel id -> last message shown

    const cancel = async (kernelId: string) => {
      await ServerConnection.makeRequest(url('cancel', kernelId), { method: 'POST' }, settings);
    };

    const poll = async () => {
      let status: IStatus;
      try {
        const response = await ServerConnection.makeRequest(url('status'), {}, settings);
        if (!response.ok) {
          return;
        }
        status = (await response.json()) as IStatus;
      } catch {
        return;
      }

      const current = new Set<string>();
      for (const k of status.kernels) {
        current.add(k.kernel_id);
        const text = `${k.label}: ${k.message}`;
        const id = notifications.get(k.kernel_id);
        if (k.state === 'running') {
          if (id) {
            Notification.update({ id, message: text, type: 'success', autoClose: 5000, actions: [] });
            notifications.delete(k.kernel_id);
          }
        } else if (shown.get(k.kernel_id) !== text) {
          const actions = [{ label: 'Warten abbrechen', callback: () => void cancel(k.kernel_id), displayType: 'warn' as const }];
          if (id) {
            Notification.update({ id, message: text, type: 'info', autoClose: false, actions });
          } else {
            notifications.set(k.kernel_id, Notification.info(text, { autoClose: false, actions }));
          }
        }
        shown.set(k.kernel_id, text);
      }
      for (const [kernelId, id] of notifications) {
        if (!current.has(kernelId)) {
          Notification.dismiss(id);
          notifications.delete(kernelId);
        }
      }
      for (const kernelId of [...shown.keys()]) {
        if (!current.has(kernelId)) {
          shown.delete(kernelId);
        }
      }

      last = status;
      polledAt = Date.now();
      warnings(status);
      render();
    };

    // The workspace's own release, next to the GPU status: only while a warning is due.
    const renderRelease = () => {
      const server = last.release?.server;
      const since = (Date.now() - polledAt) / 1000;
      releaseItem.node.textContent = '';
      const show = !!server && (server.warn || !!server.ends_soon);
      releaseItem.toggleClass('dhbw-gpu-idle', !show);
      if (!server || !show) {
        return;
      }
      const dot = document.createElement('span');
      dot.className = 'dhbw-gpu-dot dhbw-gpu-waiting';
      const label = document.createElement('span');
      label.className = 'dhbw-gpu-label';
      label.textContent = server.warn ? `Rückgabe ohne Aktivität in ${clock(server.idle_left - since)}` : `Workspace endet um ${timeOfDay(server.ends_at as string)}`;
      releaseItem.node.title = server.warn ? 'Der Workspace wird nach den Rückgabezeiten des Projekts zurückgegeben, wenn nichts mehr rechnet. „Weiterarbeiten“ zählt als Aktivität.' : 'Die Obergrenze des Projekts für diesen Workspace.';
      releaseItem.node.appendChild(dot);
      releaseItem.node.appendChild(label);
      if (server.warn) {
        const keep = document.createElement('button');
        keep.className = 'dhbw-gpu-release';
        keep.textContent = 'Weiterarbeiten';
        keep.addEventListener('click', event => {
          event.stopPropagation();
          keep.disabled = true;
          void keepalive();
        });
        releaseItem.node.appendChild(keep);
      }
    };

    // The dot and the text: red and pulsing while a GPU kernel holds the GPU, amber while one waits for it.
    const render = () => {
      const status = last;
      const pending = status.kernels.filter(k => k.state !== 'running');
      const running = status.kernels.filter(k => k.state === 'running');
      item.node.textContent = '';
      item.toggleClass('dhbw-gpu-idle', !status.kernels.length);
      if (!status.kernels.length) {
        item.node.title = '';
        return;
      }
      const dot = document.createElement('span');
      dot.className = 'dhbw-gpu-dot' + (running.length ? '' : ' dhbw-gpu-waiting');
      const label = document.createElement('span');
      label.className = 'dhbw-gpu-label';
      if (running.length) {
        const models = [...app.serviceManager.kernels.running()];
        const parts = running.map(k => {
          const m = models.find(x => x.id === k.kernel_id);
          if (m?.execution_state === 'busy') {
            return `${k.label} rechnet`;
          }
          // The server's count (release times: CPU and GPU load count as activity), else JupyterLab's own from the last output.
          const left = k.idle_left !== undefined ? clock(k.idle_left - (Date.now() - polledAt) / 1000) : remaining(m?.last_activity, status.idle_timeout ?? 0);
          return left ? `${k.label}, wird ohne Aktivität freigegeben in ${left}` : k.label;
        });
        label.textContent = `GPU zugeteilt: ${parts.join(' · ')}`;
        item.node.title = 'Diesem GPU-Kernel ist eine GPU zugeteilt. Klicken, um ihn zu beenden und die GPU freizugeben (Variablen gehen verloren, Dateien bleiben).';
      } else {
        label.textContent = pending[0].message;
        item.node.title = 'Klicken, um das Warten abzubrechen.';
      }
      item.node.appendChild(dot);
      item.node.appendChild(label);
      if (running.length) {
        // Ends the GPU kernels at once, without asking: whoever presses it knows what it does.
        const release = document.createElement('button');
        release.className = 'dhbw-gpu-release';
        release.textContent = 'Jetzt freigeben';
        release.title = 'GPU-Kernel sofort beenden und die GPU freigeben (Variablen gehen verloren, Dateien bleiben).';
        release.addEventListener('click', event => {
          event.stopPropagation();
          release.disabled = true;
          void Promise.all(running.map(k => app.serviceManager.kernels.shutdown(k.kernel_id).catch(() => undefined))).then(() => poll());
        });
        item.node.appendChild(release);
      }
    };

    // A click ends what the dot stands for: the running GPU kernels (after asking), or the wait for one.
    item.node.addEventListener('click', async () => {
      const running = last.kernels.filter(k => k.state === 'running');
      const pending = last.kernels.filter(k => k.state !== 'running');
      if (running.length) {
        const names = running.map(k => k.label).join(', ');
        const result = await showDialog({
          title: 'GPU-Kernel beenden?',
          body: `${names} ist eine GPU zugeteilt. Beim Beenden gehen die Variablen dieses Kernels verloren, die Dateien bleiben. Die GPU ist danach sofort für andere frei.`,
          buttons: [Dialog.cancelButton({ label: 'Abbrechen' }), Dialog.warnButton({ label: 'Beenden' })]
        });
        if (result.button.accept) {
          await Promise.all(running.map(k => app.serviceManager.kernels.shutdown(k.kernel_id).catch(() => undefined)));
          void poll();
        }
      } else if (pending.length) {
        await Promise.all(pending.map(k => cancel(k.kernel_id)));
        void poll();
      }
    });

    void poll();
    window.setInterval(() => void poll(), 5000);
    // The countdown runs between polls too.
    window.setInterval(() => {
      render();
      renderRelease();
    }, 1000);
  }
};

export default plugin;
