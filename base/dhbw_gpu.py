"""DHBW GPU kernels (aiaas-deployment docs/bauplan.md 6.2): jupyter_server extension in the bases, active in the profile "CPU + GPU-Kernel".

- The kernel pods are created by the AI service (llm-management-api), not by this server: gateway_provisioners' KubernetesProvisioner asks it to start, poll and stop the kernel (DHBW_GPU_API, authenticated with this server's own hub token). The server has no rights in Kubernetes; the AI service builds the pod from this server's pod (image, home, project) and checks the project's limits and budgets (one GPU per person and the like) before it starts one. A refusal comes back as the reason JupyterLab shows.
- Starts remote GPU kernels in the notebook's directory (jupyter_server passes it as cwd).
- One session per notebook while its kernel starts (_patch_sessions).
- GET <base>/dhbw-gpu/status: state of the person's GPU kernels (waiting with position in the queue and the latest time a GPU frees up, being prepared, running), for the JupyterLab extension dhbw-gpu-status.
- POST <base>/dhbw-gpu/cancel/<kernel_id>: stop waiting (deletes the kernel pod; the start then fails).
- Release times (dhbw_release.py, every profile): idle kernels and the idle server end by the project's times; the status tells what is left (server, each kernel) for the warning in the bar, POST <base>/dhbw-gpu/keepalive is "Weiterarbeiten".
"""
import asyncio
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from tornado import web

API = os.environ.get("DHBW_GPU_API", "").rstrip("/")  # the AI service's listener for the hub and the servers, e.g. http://llm-management-api-gpu-hub.default.svc:8091
LAUNCH_TIMEOUT = int(os.environ.get("GP_LAUNCH_TIMEOUT", "600"))
LOCAL_TZ = ZoneInfo("Europe/Berlin")

HOME = os.path.expanduser("~").rstrip("/")
_kernel_dirs = {}  # kernel_id -> directory the kernel was started in (pending kernels have no session yet)
_cancelled = set()  # kernel ids whose wait was stopped through /dhbw-gpu/cancel
_stop_reasons = {}  # kernel_id -> why it is ended (idle, cancel, timeout), sent with the deletion for the AI service's research log; a kernel without one was ended by the person
_server_stopping = False  # the server ends all its kernels on its way down (hub, culler, release times): the deletion goes without a reason


class GpuKernelError(web.HTTPError):
    """Refused or stopped GPU kernel start. JupyterLab shows the text in its "Error Starting Kernel" dialog: the sessions API wraps the error as str(e), so str() is the bare message (no "HTTP 409: Conflict (...)"), and the dialog renders it preformatted — as one line, quoted — so a message is a single sentence or two without line breaks (dhbw-branding wraps the dialog text)."""

    def __init__(self, message):
        super().__init__(409, message)

    def __str__(self):
        return self.log_message


def _api(method, path, body=None, timeout=20):
    """Call the AI service; returns (status, JSON body or None). 404 is an answer, not an error."""
    headers = {"Authorization": "token " + os.environ.get("JUPYTERHUB_API_TOKEN", "")}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"null")
        except ValueError:
            payload = None
        if e.code in (404, 409):
            return e.code, payload
        message = (payload or {}).get("message") if isinstance(payload, dict) else None
        raise GpuKernelError(message or f"Der KI-Dienst antwortet mit Fehler {e.code}.")
    except OSError:
        raise GpuKernelError("Der KI-Dienst ist gerade nicht erreichbar; bitte gleich noch einmal versuchen.")


def _fmt_time(dt):
    return dt.astimezone(LOCAL_TZ).strftime("%H:%M")


def _parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def collect_status(labels):
    """State of this person's GPU kernels. labels: kernel_id -> notebook name. A running GPU kernel without a notebook session was started through the REST API, which only the VS Code proxy does (dhbw_kernel_launch.py), so it is called "VS Code"."""
    _, overview = _api("GET", "/gpu/kernels")
    overview = overview or {}
    ends = [_parse_time(t) for t in overview.get("ends") or []]
    now = datetime.now(timezone.utc)
    result = []
    for k in overview.get("kernels") or []:
        kid = k.get("kernel_id", "")
        waited = int((now - _parse_time(k["created"])).total_seconds()) if k.get("created") else 0
        label = labels.get(kid)
        if not label:
            # No notebook session: a waiting kernel of JupyterLab has none yet (its folder then), a running one is the VS Code proxy's.
            if k.get("phase") == "running":
                label = "VS Code"
            else:
                folder = _kernel_dirs.get(kid, "")
                label = "Ordner ~" if folder.rstrip("/") in ("", HOME) else f"Ordner {os.path.basename(folder.rstrip('/'))}"
        entry = {"kernel_id": kid, "label": label, "waited": waited}
        if k.get("ends_at"):
            # The kernel pod's upper bound (the project's release times; none = no entry).
            entry["ends_at"] = k["ends_at"]
        if k.get("phase") == "running":
            entry.update(state="running", message="GPU-Kernel läuft")
        elif not k.get("admitted"):
            pos = k.get("position") or None
            msg = "wartet auf eine freie GPU"
            if pos:
                msg += f", Platz {pos} in der Warteschlange"
                if pos <= len(ends):
                    msg += f", spätestens frei um {_fmt_time(ends[pos - 1])}"
            msg += f" (Abbruch nach {LAUNCH_TIMEOUT // 60} min Wartezeit)"
            entry.update(state="waiting", position=pos, message=msg)
        else:
            entry.update(state="preparing", message="GPU zugeteilt, wird freigemacht und der Kernel gestartet (bis etwa 1 min)")
        result.append(entry)
    return result


def mark_stop(kernel_id, reason):
    """Remember why the kernel is about to end (idle, cancel, timeout); the deletion that follows sends it."""
    _stop_reasons[kernel_id] = reason


def unmark_stop(kernel_id):
    """The kernel did not end after all."""
    _stop_reasons.pop(kernel_id, None)


def _delete_kernel(kernel_id):
    """Delete the kernel pod, saying why: the marked reason, none while the server goes down, else the person ended it (shut down, restart, "Jetzt freigeben", VS Code)."""
    reason = _stop_reasons.pop(kernel_id, None if _server_stopping else "person")
    _api("DELETE", f"/gpu/kernels/{kernel_id}" + (f"?reason={reason}" if reason else ""))


def cancel_kernel(kernel_id):
    _cancelled.add(kernel_id)
    mark_stop(kernel_id, "cancel")
    _delete_kernel(kernel_id)


async def _session_labels(serverapp):
    labels = {}
    try:
        for s in await serverapp.session_manager.list_sessions():
            labels[s["kernel"]["id"]] = os.path.basename(s["path"])
    except Exception:  # noqa: BLE001 - labels are cosmetic
        pass
    return labels


_release = None  # dhbw_release.Release while DHBW_RELEASE is set


class StatusHandler(APIHandler):
    @web.authenticated
    async def get(self):
        # release: what is left until the server and each kernel go back (dhbw_release), for the warning in the bar; null without release times.
        release = _release.state if _release is not None else None
        if os.environ.get("DHBW_KERNELS", "split") != "split":
            # Only the local kernel (profiles "CPU" and "GPU"): no kernel pods to report.
            self.finish(json.dumps({"idle_timeout": 0, "kernels": [], "release": release}))
            return
        labels = await _session_labels(self.serverapp)
        kernels = await asyncio.get_running_loop().run_in_executor(None, collect_status, labels)
        for k in kernels:
            left = ((release or {}).get("kernels") or {}).get(k["kernel_id"])
            if left:
                k.update(idle_left=left["idle_left"], idle_warn=left["warn"])
        # idle_timeout: after how many seconds without execution a kernel is ended (MappingKernelManager.cull_idle_timeout) — the bar counts down to it where the release times give no idle_left (a hub from before).
        idle = int(getattr(self.serverapp.kernel_manager, "cull_idle_timeout", 0) or 0)
        self.finish(json.dumps({"idle_timeout": idle, "kernels": kernels, "release": release}))


class KeepaliveHandler(APIHandler):
    """ "Weiterarbeiten" in the warning: counts as activity of the server and its kernels."""

    @web.authenticated
    async def post(self):
        if _release is not None:
            _release.keepalive()
        self.finish(json.dumps({"ok": True}))


class CancelHandler(APIHandler):
    @web.authenticated
    async def post(self, kernel_id):
        await asyncio.get_running_loop().run_in_executor(None, cancel_kernel, kernel_id)
        self.finish(json.dumps({"cancelled": kernel_id}))


def _launch_args(cmd):
    """The launch parameters gateway_provisioners filled into the kernel spec's argv (--kernel-id, --response-address, ...)."""
    flags = {"--kernel-id": "kernel_id", "--response-address": "response_address", "--public-key": "public_key", "--port-range": "port_range", "--kernel-class-name": "kernel_class_name", "--transport-encryption": "transport_encryption"}
    out = {}
    for i, arg in enumerate(cmd[:-1]):
        if arg in flags and not cmd[i + 1].startswith("--") and not cmd[i + 1].startswith("{"):
            out[flags[arg]] = cmd[i + 1]
    return out


def _patch_provisioner(serverapp):
    """KubernetesProvisioner without Kubernetes: the launch, the polling and the deletion go to the AI service; everything else (waiting for the kernel's connection info, interrupts, timeouts) stays gateway_provisioners'."""
    # gateway_provisioners.k8s loads a Kubernetes configuration when imported, and this server has none (no service account token): import it once here with an empty one that is never used.
    import tempfile

    saved = {k: os.environ.get(k) for k in ("GP_USE_INCLUSTER_CONFIG", "KUBECONFIG")}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"apiVersion": "v1", "kind": "Config", "clusters": [{"name": "none", "cluster": {"server": "https://127.0.0.1:9"}}], "users": [{"name": "none", "user": {}}], "contexts": [{"name": "none", "context": {"cluster": "none", "user": "none"}}], "current-context": "none"}, f)
    os.environ.update(GP_USE_INCLUSTER_CONFIG="false", KUBECONFIG=f.name)
    try:
        from gateway_provisioners.k8s import KubernetesProvisioner
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    from gateway_provisioners.remote_provisioner import RemoteProvisionerBase, local_ip, poll_interval

    original_pre_launch = KubernetesProvisioner.pre_launch

    async def pre_launch(self, **kwargs):
        self._dhbw_pod_seen = False  # see get_container_status; reset for restarts
        self._dhbw_cwd = kwargs.get("cwd") or ""
        if self._dhbw_cwd:
            _kernel_dirs[self.kernel_id] = self._dhbw_cwd
        return await original_pre_launch(self, **kwargs)

    async def launch_kernel(self, cmd, **kwargs):
        body = _launch_args(cmd)
        body["kernel_id"] = self.kernel_id
        body["working_dir"] = self._dhbw_cwd if getattr(self, "_dhbw_cwd", "") else ""
        status, answer = await asyncio.get_running_loop().run_in_executor(None, lambda: _api("POST", "/gpu/kernels", body, timeout=60))
        if status == 409:
            raise GpuKernelError((answer or {}).get("message") or "Der GPU-Kernel wurde abgelehnt.")
        if status == 404:
            raise GpuKernelError("Der KI-Dienst kennt GPU-Kernel nicht; bitte den Server neu starten.")
        self.local_proc = None
        self.pid = 0
        self.ip = local_ip
        self.container_name = (answer or {}).get("name")
        self.log_kernel_launch(cmd)
        await self.confirm_remote_startup()
        return self.connection_info

    def get_container_status(self, iteration):
        # While a kernel starts, gateway_provisioners keeps waiting (up to GP_LAUNCH_TIMEOUT) when its pod is gone. End the start at once instead, with a message JupyterLab shows: the wait was stopped, or the pod vanished (deleted, evicted).
        code, pod = _api("GET", f"/gpu/kernels/{self.kernel_id}")
        status = ""
        if code == 200 and pod:
            self.container_name = pod.get("name") or self.container_name
            status = pod.get("phase") or ""
            if status == "running" and not self.assigned_host and pod.get("pod_ip"):
                self.assigned_ip = pod["pod_ip"]
                self.assigned_host = self.container_name
                self.assigned_node_ip = pod.get("host_ip")
        if status:
            self._dhbw_pod_seen = True
        elif iteration:
            if self.kernel_id in _cancelled:
                _cancelled.discard(self.kernel_id)
                raise GpuKernelError("Warten auf eine GPU abgebrochen.")
            if getattr(self, "_dhbw_pod_seen", False):
                raise GpuKernelError("Der GPU-Kernel ist beim Warten verschwunden (gelöscht oder verdrängt). Bitte den Kernel neu starten.")
        return status

    def delete_managed_object(self, termination_stati):
        _delete_kernel(self.kernel_id)
        return True

    # gateway_provisioners 0.5.0's own check, with the reason marked before its kill(): the start waited longer than GP_LAUNCH_TIMEOUT.
    async def handle_launch_timeout(self):
        await asyncio.sleep(poll_interval)
        if RemoteProvisionerBase.get_time_diff(self.start_time) > self.launch_timeout:
            mark_stop(self.kernel_id, "timeout")
            await self.kill()
            self.log_and_raise(TimeoutError(f"KernelID: '{self.kernel_id}' launch timeout due to: Waited too long ({self.launch_timeout}s) to get connection file"))

    KubernetesProvisioner.pre_launch = pre_launch
    KubernetesProvisioner.handle_launch_timeout = handle_launch_timeout
    KubernetesProvisioner.launch_kernel = launch_kernel
    KubernetesProvisioner.get_container_status = get_container_status
    KubernetesProvisioner.delete_managed_object = delete_managed_object


def _patch_sessions(serverapp):
    """One session per notebook, also while its kernel starts. jupyter_server records a session only once its kernel is up, so a second request for the same notebook in the meantime (JupyterLab restoring its tabs, a second browser tab) starts a second kernel. Locally that window is a fraction of a second; for a GPU kernel it is the whole pod start, and the second kernel is refused by the quota above, leaving the notebook without a kernel. Requests for the same path now wait for the first and get its session."""
    manager = type(serverapp.session_manager)
    original = manager.create_session
    locks = {}

    async def create_session(self, path=None, *args, **kwargs):
        if not path:
            return await original(self, path, *args, **kwargs)
        lock = locks.setdefault(path, asyncio.Lock())
        try:
            async with lock:
                if await self.session_exists(path=path):
                    return await self.get_session(path=path)
                return await original(self, path, *args, **kwargs)
        finally:
            if not lock.locked() and locks.get(path) is lock:
                del locks[path]

    manager.create_session = create_session


def _patch_cleanup(serverapp):
    """Kernels the server ends on its way down (stopped by the hub, its culler or the release times) were not ended by the person: their deletions go without a reason."""
    original = serverapp.cleanup_kernels

    async def cleanup_kernels():
        global _server_stopping
        _server_stopping = True
        await original()

    serverapp.cleanup_kernels = cleanup_kernels


def _jupyter_server_extension_points():
    return [{"module": "dhbw_gpu"}]


def _load_jupyter_server_extension(serverapp):
    global _release
    _patch_provisioner(serverapp)
    _patch_sessions(serverapp)
    _patch_cleanup(serverapp)
    try:
        import dhbw_release

        _release = dhbw_release.setup(serverapp)
    except Exception as e:  # noqa: BLE001 - without it JupyterLab's own culler and shutdown remain
        serverapp.log.warning("dhbw_gpu: release times not active: %s", e)
    base = serverapp.web_app.settings["base_url"]
    serverapp.web_app.add_handlers(".*$", [
        (url_path_join(base, "dhbw-gpu", "status"), StatusHandler),
        (url_path_join(base, "dhbw-gpu", "cancel", r"([^/]+)"), CancelHandler),
        (url_path_join(base, "dhbw-gpu", "keepalive"), KeepaliveHandler),
    ])
    serverapp.log.info("dhbw_gpu: GPU kernels through %s, status at %s", API or "(DHBW_GPU_API not set)", url_path_join(base, "dhbw-gpu", "status"))
