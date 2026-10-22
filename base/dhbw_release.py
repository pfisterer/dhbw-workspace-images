"""DHBW release times (aiaas-deployment docs/todo.md idle_release): ends idle kernels and the idle server by the project's release times, loaded by the server extension dhbw_gpu in every profile.

The hub passes the times in DHBW_RELEASE (seconds, from the AI service: the budget sets the most, the project chooses within): {"server": {"idle_open", "idle_closed", "max"}, "kernel": {...}}. "server" applies to the server and its local kernels, "kernel" to the GPU kernels of "CPU + GPU-Kernel" (kernel spec python3-gpu, their pods hold the GPU). Without DHBW_RELEASE (a hub from before) nothing changes: JupyterLab's own culler and shutdown work with the hub's arguments.

Counted is idle time, not runtime. Activity is:
- a kernel executing (execution_state busy) or sending output, as JupyterLab's own culler sees it;
- a kernel's CPU or GPU load, from its usage_reply on the control channel (answered while it computes; dhbw_kernel_usage adds the GPU's utilisation from nvidia-smi in the kernel's own pod): a training in a background thread shows "idle" but loads CPU or GPU;
- for the server also the load of the whole container (cgroup CPU, nvidia-smi where the server has the GPU itself), a terminal's input and output, and saving a file;
- "Weiterarbeiten" in the warning (POST <base>/dhbw-gpu/keepalive).
A tab counts as open while JupyterLab, VS Code or the status bar talk to the server (API requests in the last two minutes) or a notebook is connected to the kernel; then idle_open applies, else idle_closed. JupyterLab's own kernel culler is switched off (it would end a computing background thread); its shutdown_no_activity stays as the fallback, and the activity found here goes into the server's last activity (dhbw_last_activity), which JupyterHub's culler sees as well.
"""
import asyncio
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone

import dhbw_gpu  # loaded first anyway: dhbw_gpu's server extension imports this module

TICK = int(os.environ.get("DHBW_RELEASE_TICK", "30"))  # seconds between two checks (shorter only for tests)
TAB_WINDOW = 120  # seconds an API request counts as an open tab
WARN_BEFORE = 300  # seconds before a release the warning appears (at most half the idle time)
KERNEL_CPU_ACTIVE = float(os.environ.get("DHBW_ACTIVE_KERNEL_CPU", "10"))  # percent of a core, usage_reply kernel_cpu
SERVER_CPU_ACTIVE = float(os.environ.get("DHBW_ACTIVE_SERVER_CPU", "0.3"))  # cores of the container (JupyterLab, VS Code and the server itself use a few percent)
GPU_ACTIVE = float(os.environ.get("DHBW_ACTIVE_GPU", "5"))  # percent utilisation
GPU_KERNEL_SPEC = "python3-gpu"


def utcnow():
    return datetime.now(timezone.utc)


def parse_release(raw):
    """DHBW_RELEASE as {"server": {...}, "kernel": {...}} with whole seconds, or None when it is missing or broken (then nothing changes)."""
    try:
        release = json.loads(raw or "null")
        server = {k: int(release["server"][k]) for k in ("idle_open", "idle_closed", "max")}
        kernel = {k: int((release.get("kernel") or release["server"])[k]) for k in ("idle_open", "idle_closed", "max")}
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if min(server["idle_open"], server["idle_closed"], kernel["idle_open"], kernel["idle_closed"]) <= 0:
        return None
    return {"server": server, "kernel": kernel}


def idle_limit(times, tab_open):
    return times["idle_open"] if tab_open else times["idle_closed"]


def warn_window(limit):
    return min(WARN_BEFORE, limit // 2)


def local_gpu_util():
    """Utilisation of the GPUs this container has (percent, the highest), None without nvidia-smi or GPU. The profile "GPU" has its GPU in the server's own container."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
        values = [float(x) for x in out.split() if x.replace(".", "", 1).isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return max(values) if values else None


class CgroupCPU:
    """CPU time of the whole container (cgroup v2 cpu.stat, v1 cpuacct.usage), as cores used since the last call."""

    def __init__(self):
        self.last = None

    @staticmethod
    def read():
        try:
            with open("/sys/fs/cgroup/cpu.stat") as f:
                for line in f:
                    if line.startswith("usage_usec "):
                        return int(line.split()[1]) / 1e6
        except OSError:
            pass
        try:
            with open("/sys/fs/cgroup/cpuacct/cpuacct.usage") as f:
                return int(f.read()) / 1e9
        except (OSError, ValueError):
            return None

    def cores(self):
        now, used = time.monotonic(), self.read()
        if used is None:
            return None
        last, self.last = self.last, (now, used)
        if last is None or now <= last[0]:
            return None
        return (used - last[1]) / (now - last[0])


def pod_started():
    """When the container started (its PID 1), for the time its upper bound ends; the pod's own start (activeDeadlineSeconds counts from there) is a few seconds earlier, before the init containers."""
    try:
        import psutil

        return datetime.fromtimestamp(psutil.Process(1).create_time(), timezone.utc)
    except Exception:  # noqa: BLE001 - only for showing the end
        return utcnow()


class Release:
    """The check every TICK seconds; the state for the status bar (snapshot)."""

    def __init__(self, serverapp, release):
        self.app = serverapp
        self.server = release["server"]
        self.kernel = release["kernel"]
        self.log = serverapp.log
        self.started = pod_started()
        self.server_active = utcnow()  # last activity of the server found here
        self.kernel_active = {}  # kernel id -> last activity found here (load), on top of the kernel's own last_activity
        self.clients = {}  # kernel id -> client with an open control channel, for usage_request
        self.cpu = CgroupCPU()
        self.keepalive_at = None
        self.state = {"server": {}, "kernels": {}}
        self._stopping = False
        self._busy = False

    # Activity sources, separate so that a test can replace them.

    def now(self):
        return utcnow()

    def tab_open(self, now):
        last = self.app.web_app.settings.get("api_last_activity")
        return bool(last) and (now - last).total_seconds() < TAB_WINDOW

    def server_load_active(self):
        cores = self.cpu.cores()
        gpu = local_gpu_util()
        return (cores is not None and cores >= SERVER_CPU_ACTIVE) or (gpu is not None and gpu >= GPU_ACTIVE)

    async def kernel_usage(self, kernel_id, kernel):
        """The kernel's usage_reply content ({kernel_cpu, gpu_util, ...}), None when it does not answer in time (an older kernel without usage_request, a kernel that is starting)."""
        client = self.clients.get(kernel_id)
        try:
            if client is None:
                client = kernel.client()
                client.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
                self.clients[kernel_id] = client
            msg = client.session.msg("usage_request", {})
            client.control_channel.send(msg)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                reply = await client.control_channel.get_msg(timeout=max(0.1, deadline - time.monotonic()))
                if reply.get("parent_header", {}).get("msg_id") == msg["header"]["msg_id"]:
                    return reply.get("content") or {}
        except Exception:  # noqa: BLE001 - no answer is no information, not an error
            self.drop_client(kernel_id)
        return None

    def drop_client(self, kernel_id):
        client = self.clients.pop(kernel_id, None)
        if client is not None:
            try:
                client.stop_channels()
            except Exception:  # noqa: BLE001
                pass

    def times_of(self, kernel):
        return self.kernel if getattr(kernel, "kernel_name", "") == GPU_KERNEL_SPEC else self.server

    def other_activity(self):
        """Terminals (input and output) and file saves, as the server records them."""
        settings = self.app.web_app.settings
        times = [t for t in (settings.get("terminal_last_activity"), settings.get("dhbw_save_activity"), self.keepalive_at) if t]
        return max(times) if times else None

    def mark_active(self, now):
        self.server_active = now
        # Counted by the server's last_activity(): its own shutdown_no_activity and JupyterHub's culler see the activity too.
        self.app.web_app.settings["dhbw_last_activity"] = now

    async def tick(self):
        now = self.now()
        tab = self.tab_open(now)
        km = self.app.kernel_manager
        kernels = {}
        latest = None  # the latest activity of any kernel
        for kid in list(km.list_kernel_ids()):
            try:
                kernel = km.get_kernel(kid)
            except KeyError:
                continue
            times = self.times_of(kernel)
            seen = [t for t in (getattr(kernel, "last_activity", None), self.kernel_active.get(kid), self.keepalive_at) if t is not None]
            last = max(seen) if seen else now
            reason = ""
            if getattr(kernel, "execution_state", "") == "busy":
                last, reason = now, "busy"
            else:
                usage = await self.kernel_usage(kid, kernel)
                if usage:
                    cpu, gpu = usage.get("kernel_cpu"), usage.get("gpu_util")
                    if isinstance(cpu, (int, float)) and cpu >= KERNEL_CPU_ACTIVE:
                        last, reason = now, f"cpu {cpu:.0f}%"
                    elif isinstance(gpu, (int, float)) and gpu >= GPU_ACTIVE:
                        last, reason = now, f"gpu {gpu:.0f}%"
            if reason:
                self.kernel_active[kid] = now
            connected = km._kernel_connections.get(kid, 0) > 0
            limit = idle_limit(times, tab or connected)
            idle = (now - last).total_seconds()
            if idle >= limit:
                self.log.info("dhbw_release: ending kernel %s (%s) after %d s without activity (limit %d s, %s)", kid, kernel.kernel_name, idle, limit, "tab open" if tab or connected else "no tab")
                self.drop_client(kid)
                self.kernel_active.pop(kid, None)
                try:
                    if kernel.kernel_name == GPU_KERNEL_SPEC:
                        dhbw_gpu.mark_stop(kid, "idle")
                    await km.shutdown_kernel(kid)
                except Exception as e:  # noqa: BLE001
                    self.log.warning("dhbw_release: kernel %s not ended: %s", kid, e)
                    if kernel.kernel_name == GPU_KERNEL_SPEC:
                        dhbw_gpu.unmark_stop(kid)
                continue
            kernels[kid] = {"idle_left": int(limit - idle), "idle_limit": limit, "warn": limit - idle <= warn_window(limit), "active": reason}
            latest = last if latest is None or last > latest else latest
        for kid in list(self.clients):
            if kid not in kernels:
                self.drop_client(kid)

        if self.server_load_active():
            self.mark_active(now)
        elif latest is not None and (now - latest).total_seconds() < TICK:
            self.mark_active(now)
        last = max(t for t in (self.server_active, latest, self.other_activity()) if t is not None)
        limit = idle_limit(self.server, tab)
        idle = (now - last).total_seconds()
        ends_at = self.started + timedelta(seconds=self.server["max"]) if self.server["max"] else None
        self.state = {
            "server": {"idle_left": int(limit - idle), "idle_limit": limit, "tab_open": tab, "warn": limit - idle <= warn_window(limit), "ends_at": ends_at.isoformat() if ends_at else None, "ends_soon": bool(ends_at) and (ends_at - now).total_seconds() <= 15 * 60},
            "kernels": kernels,
        }
        if idle >= limit and not self._stopping:
            self._stopping = True
            self.log.warning("dhbw_release: stopping the server after %d s without activity (limit %d s, %s)", idle, limit, "tab open" if tab else "no tab")
            # Its GPU kernels go down with it, and they were idle too.
            for kid in list(km.list_kernel_ids()):
                try:
                    if km.get_kernel(kid).kernel_name == GPU_KERNEL_SPEC:
                        dhbw_gpu.mark_stop(kid, "idle")
                except KeyError:
                    pass
            self.app.stop()

    def keepalive(self):
        """"Weiterarbeiten": the person is there; counts as activity of the server and of every kernel."""
        now = self.now()
        self.keepalive_at = now
        self.mark_active(now)

    async def safe_tick(self):
        if self._busy or self._stopping:
            return
        self._busy = True
        try:
            await self.tick()
        except Exception as e:  # noqa: BLE001 - one failed check must not end the checks
            self.log.warning("dhbw_release: check failed: %s", e)
        finally:
            self._busy = False


def _patch_saves(serverapp):
    """Saving a file (JupyterLab saves a changed notebook every two minutes) counts as activity of the server."""
    manager = serverapp.contents_manager
    original = manager.save

    def save(*args, **kwargs):
        serverapp.web_app.settings["dhbw_save_activity"] = utcnow()
        return original(*args, **kwargs)

    manager.save = save


def setup(serverapp):
    """Start the checks when DHBW_RELEASE is set; returns the Release or None."""
    release = parse_release(os.environ.get("DHBW_RELEASE"))
    if release is None:
        return None
    km = serverapp.kernel_manager
    # Our own usage requests are no user activity, and their status messages must not overwrite a computing kernel's execution_state.
    km.untracked_message_types = list(km.untracked_message_types) + [t for t in ("usage_request", "usage_reply") if t not in km.untracked_message_types]

    # JupyterLab's own culler counts only output and execution; it would end a kernel whose background thread computes. These checks take its place.
    async def no_cull(self, kernel_id):
        return None

    type(km).cull_kernel_if_idle = no_cull
    _patch_saves(serverapp)
    r = Release(serverapp, release)
    # Like the server's own shutdown_no_activity: a periodic callback on the server's loop, started while it initialises.
    from tornado.ioloop import PeriodicCallback

    PeriodicCallback(lambda: asyncio.ensure_future(r.safe_tick()), TICK * 1000).start()
    serverapp.log.info("dhbw_release: server %s, GPU kernels %s (seconds)", release["server"], release["kernel"])
    return r
