// DHBW GPU platform: makes GPU kernels visible. Polls the server extension dhbw_gpu (<base>/dhbw-gpu/status) every 5 s; a waiting or starting GPU kernel gets a notification with its position in the queue and a button to stop waiting. While a GPU kernel holds the GPU, the top bar shows a pulsing red dot with the time until an idle kernel is ended; a click ends it (after asking), which frees the GPU at once. A start refused by the quota is reported by JupyterLab itself (error dialog with the server's message).
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
}

interface IStatus {
  idle_timeout?: number;
  kernels: IKernelStatus[];
}

const STYLE = `
.dhbw-gpu-item { display: flex; align-items: center; gap: 6px; height: var(--jp-private-menubar-height, 28px); padding: 0 10px; font-size: var(--jp-ui-font-size1); cursor: pointer; }
.dhbw-gpu-item.dhbw-gpu-idle { display: none; }
.dhbw-gpu-dot { width: 8px; height: 8px; border-radius: 50%; background: #CF2C29; animation: dhbw-gpu-pulse 1.4s ease-in-out infinite; }
.dhbw-gpu-dot.dhbw-gpu-waiting { background: #E8A33A; }
.dhbw-gpu-item:hover .dhbw-gpu-label { text-decoration: underline; }
@keyframes dhbw-gpu-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(207, 44, 41, 0.6); } 50% { opacity: 0.55; box-shadow: 0 0 0 4px rgba(207, 44, 41, 0); } }
`;

// "4:32": what is left of the idle time, from the kernel's last activity.
function remaining(lastActivity: string | undefined, idleTimeout: number): string {
  if (!lastActivity || !idleTimeout) {
    return '';
  }
  const left = Math.max(0, idleTimeout - (Date.now() - Date.parse(lastActivity)) / 1000);
  const m = Math.floor(left / 60);
  const sec = Math.floor(left % 60);
  return `${m}:${sec.toString().padStart(2, '0')}`;
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
    app.shell.add(item, 'top', { rank: 1100 });

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
      render();
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
          const left = remaining(m?.last_activity, status.idle_timeout ?? 0);
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
    window.setInterval(render, 1000);
  }
};

export default plugin;
