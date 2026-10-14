"""DHBW GPU kernels (aiaas-deployment docs/bauplan.md): jupyter_server extension in the notebook image of the profile "CPU + GPU-Kernel".

- Starts remote GPU kernels in the notebook's directory (jupyter_server passes it as cwd; gateway_provisioners only mirrors KERNEL_WORKING_DIR).
- One session per notebook while its kernel starts (_patch_sessions).
- Quota check before a GPU kernel starts: at most DHBW_GPU_KERNEL_LIMIT GPUs per person, GPU kernels and GPU servers (running or waiting) together, set by JupyterHub from its GpuQuotaSource (the hub checks the same when a GPU server starts). Over the limit the start fails at once with an explanation instead of waiting. This is a courtesy check inside the person's own pod; enforcing the quota belongs to whatever creates the kernel pods (later gpu-management-api).
- GET <base>/dhbw-gpu/status: state of the person's GPU kernels from Kubernetes and Kueue (waiting with position in the queue and the latest time a GPU frees up, being prepared, running), for the JupyterLab extension dhbw-gpu-status.
- POST <base>/dhbw-gpu/cancel/<kernel_id>: stop waiting (deletes the kernel pod; the start then fails).
"""
import asyncio
import json
import os
import ssl
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from kubernetes import client, config
from tornado import web

NAMESPACE = os.environ.get("GP_NAMESPACE", "jupyterhub")
USER_LABEL = os.environ.get("KERNEL_HUB_USER_LABEL", "")  # label hub.jupyter.org/username of this person's server pods; kernel pods carry it as dhbw.cloud/kernel-user
QUEUE = os.environ.get("DHBW_GPU_QUEUE", "notebooks")
LAUNCH_TIMEOUT = int(os.environ.get("GP_LAUNCH_TIMEOUT", "600"))
LOCAL_TZ = ZoneInfo("Europe/Berlin")

HOME = os.path.expanduser("~").rstrip("/")
_kernel_dirs = {}  # kernel_id -> directory the kernel was started in (pending kernels have no session yet)
_cancelled = set()  # kernel ids whose wait was stopped through /dhbw-gpu/cancel
_k8s_ready = False


def _k8s():
    global _k8s_ready
    if not _k8s_ready:
        config.load_incluster_config()
        _k8s_ready = True
    return client.CoreV1Api(), client.CustomObjectsApi()


class GpuKernelError(web.HTTPError):
    """Refused or stopped GPU kernel start. JupyterLab shows the text in its "Error Starting Kernel" dialog: the sessions API wraps the error as str(e), so str() is the bare message (no "HTTP 409: Conflict (...)"), and the dialog renders it preformatted — as one line, quoted — so a message is a single sentence or two without line breaks (dhbw-branding wraps the dialog text)."""

    def __init__(self, message):
        super().__init__(409, message)

    def __str__(self):
        return self.log_message


def _get_raw(path):
    """GET on the Kubernetes API with the pod's service account, for paths the generated client does not cover (Kueue's pendingworkloads subresource)."""
    sa = "/var/run/secrets/kubernetes.io/serviceaccount"
    token = open(f"{sa}/token").read().strip()
    request = urllib.request.Request(f"https://kubernetes.default.svc{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=f"{sa}/ca.crt"), timeout=10) as response:
        return json.load(response)


def gpu_kernel_limit():
    return int(os.environ.get("DHBW_GPU_KERNEL_LIMIT", "1"))


def _gpu_request(pod):
    for c in pod.spec.containers:
        req = (c.resources.requests or {}) if c.resources else {}
        if req.get("nvidia.com/gpu"):
            return True
    return False


def _live(pods):
    return [p for p in pods if p.status.phase in ("Pending", "Running") and not p.metadata.deletion_timestamp]


def _active_kernel_pods():
    """GPU kernel pods of this person that are waiting or running (not finished, not being deleted)."""
    v1, _ = _k8s()
    return _live(v1.list_namespaced_pod(NAMESPACE, label_selector=f"component=kernel,dhbw.cloud/kernel-user={USER_LABEL}").items)


def _active_gpu_pods():
    """Everything of this person that holds or waits for a GPU: GPU kernels and GPU servers (named servers of the GPU profiles)."""
    v1, _ = _k8s()
    servers = v1.list_namespaced_pod(NAMESPACE, label_selector=f"component=singleuser-server,hub.jupyter.org/username={USER_LABEL}").items
    return _active_kernel_pods() + [p for p in _live(servers) if _gpu_request(p)]


def _fmt_time(dt):
    return dt.astimezone(LOCAL_TZ).strftime("%H:%M")


def collect_status(labels):
    """State of this person's GPU kernels. labels: kernel_id -> notebook name. A running GPU kernel without a notebook session was started through the REST API, which only the VS Code proxy does (dhbw_kernel_launch.py), so it is called "VS Code"."""
    v1, co = _k8s()
    pods = _active_kernel_pods()
    if not pods:
        return []
    workloads = co.list_namespaced_custom_object("kueue.x-k8s.io", "v1beta2", NAMESPACE, "workloads")["items"]
    wl_by_pod = {ref["name"]: w for w in workloads for ref in w["metadata"].get("ownerReferences", []) if ref.get("kind") == "Pod"}
    pending = _get_raw(f"/apis/visibility.kueue.x-k8s.io/v1beta2/namespaces/{NAMESPACE}/localqueues/{QUEUE}/pendingworkloads")
    position = {w["metadata"]["name"]: w.get("positionInClusterQueue", 0) + 1 for w in (pending or {}).get("items", [])}
    # When GPUs free up at the latest: running GPU pods anywhere in the cluster end at their deadline; pods with negative priority (gap-filling inference) do not count, Kueue evicts them for a waiting kernel.
    now = datetime.now(timezone.utc)
    ends = sorted(
        p.status.start_time.timestamp() + p.spec.active_deadline_seconds
        for p in v1.list_pod_for_all_namespaces(field_selector="status.phase=Running").items
        if p.status.start_time and p.spec.active_deadline_seconds and (p.spec.priority or 0) >= 0 and _gpu_request(p)
    )
    result = []
    for p in pods:
        kid = p.metadata.labels.get("kernel_id", "")
        wl = wl_by_pod.get(p.metadata.name)
        admitted = bool(wl and (wl.get("status", {}).get("admission")))
        waited = int((now - p.metadata.creation_timestamp).total_seconds())
        label = labels.get(kid)
        if not label:
            # No notebook session: a waiting kernel of JupyterLab has none yet (its folder then), a running one is the VS Code proxy's.
            if p.status.phase == "Running":
                label = "VS Code"
            else:
                folder = _kernel_dirs.get(kid, "")
                label = "Ordner ~" if folder.rstrip("/") in ("", HOME) else f"Ordner {os.path.basename(folder.rstrip('/'))}"
        entry = {"kernel_id": kid, "label": label, "waited": waited}
        if p.status.phase == "Running":
            entry.update(state="running", message="GPU-Kernel läuft")
        elif not admitted:
            pos = position.get(wl["metadata"]["name"]) if wl else None
            msg = "wartet auf eine freie GPU"
            if pos:
                msg += f", Platz {pos} in der Warteschlange"
                if pos <= len(ends):
                    msg += f", spätestens frei um {_fmt_time(datetime.fromtimestamp(ends[pos - 1], timezone.utc))}"
            msg += f" (Abbruch nach {LAUNCH_TIMEOUT // 60} min Wartezeit)"
            entry.update(state="waiting", position=pos, message=msg)
        else:
            entry.update(state="preparing", message="GPU zugeteilt, wird freigemacht und der Kernel gestartet (bis etwa 1 min)")
        result.append(entry)
    return result


def cancel_kernel(kernel_id):
    _cancelled.add(kernel_id)
    v1, _ = _k8s()
    v1.delete_collection_namespaced_pod(NAMESPACE, label_selector=f"component=kernel,dhbw.cloud/kernel-user={USER_LABEL},kernel_id={kernel_id}")


async def _session_labels(serverapp):
    labels = {}
    try:
        for s in await serverapp.session_manager.list_sessions():
            labels[s["kernel"]["id"]] = os.path.basename(s["path"])
    except Exception:  # noqa: BLE001 - labels are cosmetic
        pass
    return labels


class StatusHandler(APIHandler):
    @web.authenticated
    async def get(self):
        labels = await _session_labels(self.serverapp)
        kernels = await asyncio.get_running_loop().run_in_executor(None, collect_status, labels)
        # idle_timeout: after how many seconds without execution a kernel is ended (MappingKernelManager.cull_idle_timeout) — the status bar counts down to it.
        idle = int(getattr(self.serverapp.kernel_manager, "cull_idle_timeout", 0) or 0)
        self.finish(json.dumps({"limit": gpu_kernel_limit(), "idle_timeout": idle, "kernels": kernels}))


class CancelHandler(APIHandler):
    @web.authenticated
    async def post(self, kernel_id):
        await asyncio.get_running_loop().run_in_executor(None, cancel_kernel, kernel_id)
        self.finish(json.dumps({"cancelled": kernel_id}))


def _patch_provisioner(serverapp):
    from gateway_provisioners.k8s import KubernetesProvisioner

    original = KubernetesProvisioner.pre_launch

    async def pre_launch(self, **kwargs):
        self._dhbw_pod_seen = False  # see get_container_status; reset for restarts
        # Quota: count this person's GPU kernels and GPU servers that are waiting or running, except this kernel (a restart keeps the kernel id).
        others = [p for p in await asyncio.get_running_loop().run_in_executor(None, _active_gpu_pods) if p.metadata.labels.get("kernel_id") != self.kernel_id]
        limit = gpu_kernel_limit()
        if len(others) >= limit:
            labels = await _session_labels(serverapp)

            def describe(p):
                if p.metadata.labels.get("component") == "singleuser-server":
                    return f"GPU-Server „{p.metadata.labels.get('hub.jupyter.org/servername') or 'Standard'}“"
                kid = p.metadata.labels.get("kernel_id")
                if labels.get(kid):
                    return labels[kid]
                return f"Ordner {os.path.basename(_kernel_dirs[kid]) or '~'}" if kid in _kernel_dirs else "ein anderes Notebook"

            where = ", ".join(describe(p) for p in others)
            waiting = any(p.status.phase == "Pending" for p in others)
            raise GpuKernelError(
                f"Die GPU ist schon belegt ({where}{', wartet noch' if waiting else ''}), möglich {'ist 1 GPU' if limit == 1 else f'sind {limit} GPUs'} gleichzeitig. "
                "Den anderen Kernel bzw. Server beenden oder hier „Python 3 (CPU)“ ohne GPU wählen."
            )
        if kwargs.get("cwd"):
            kwargs["env"] = dict(kwargs.get("env") or os.environ)
            kwargs["env"]["KERNEL_WORKING_DIR"] = kwargs["cwd"]
            _kernel_dirs[self.kernel_id] = kwargs["cwd"]
        return await original(self, **kwargs)

    KubernetesProvisioner.pre_launch = pre_launch

    original_status = KubernetesProvisioner.get_container_status

    def get_container_status(self, iteration):
        # While a kernel starts, gateway_provisioners keeps waiting (up to GP_LAUNCH_TIMEOUT) when its pod is gone. End the start at once instead, with a message JupyterLab shows: the wait was stopped, or the pod vanished (deleted, evicted).
        status = original_status(self, iteration)
        if status:
            self._dhbw_pod_seen = True
        elif iteration:
            if self.kernel_id in _cancelled:
                _cancelled.discard(self.kernel_id)
                raise GpuKernelError("Warten auf eine GPU abgebrochen.")
            if getattr(self, "_dhbw_pod_seen", False):
                raise GpuKernelError("Der GPU-Kernel ist beim Warten verschwunden (gelöscht oder verdrängt). Bitte den Kernel neu starten.")
        return status

    KubernetesProvisioner.get_container_status = get_container_status


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


def _jupyter_server_extension_points():
    return [{"module": "dhbw_gpu"}]


def _load_jupyter_server_extension(serverapp):
    _patch_provisioner(serverapp)
    _patch_sessions(serverapp)
    base = serverapp.web_app.settings["base_url"]
    serverapp.web_app.add_handlers(".*$", [
        (url_path_join(base, "dhbw-gpu", "status"), StatusHandler),
        (url_path_join(base, "dhbw-gpu", "cancel", r"([^/]+)"), CancelHandler),
    ])
    serverapp.log.info("dhbw_gpu: GPU kernel quota %s, status at %s", gpu_kernel_limit(), url_path_join(base, "dhbw-gpu", "status"))
