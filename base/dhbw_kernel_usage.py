"""Kernel side of the DHBW release times (dhbw_release.py, aiaas-deployment docs/todo.md idle_release): the kernel's usage_reply (control channel, which ipykernel answers while a cell computes) also tells the utilisation of the GPU the kernel's pod holds, so that a training in a background thread counts as activity although the kernel shows "idle". Installed from /etc/ipython/ipython_kernel_config.py, for every kernel; a kernel without a GPU answers as before.

The GPU's utilisation comes from nvidia-smi in the kernel's own container, not from DCGM: it works on every GPU the pod gets (vGPU guests, passthrough, GB10, nvproxy under gVisor), needs no metrics pipeline (Prometheus in the AI cluster only forwards) and no network, and the pod has its GPU to itself.
"""
import shutil
import subprocess

_NVIDIA_SMI = shutil.which("nvidia-smi")


def gpu_usage():
    """{"gpu_util": percent (highest of the pod's GPUs)} or {} without nvidia-smi or GPU."""
    global _NVIDIA_SMI
    if not _NVIDIA_SMI:
        return {}
    try:
        out = subprocess.run([_NVIDIA_SMI, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        # No GPU in this container (the CPU kernel of a server whose image has nvidia-smi): not asked again.
        _NVIDIA_SMI = None
        return {}
    values = []
    for line in out.stdout.split():
        try:
            values.append(float(line))
        except ValueError:
            pass
    return {"gpu_util": max(values)} if values else {}


def install():
    """Wraps ipykernel's usage_request: the reply it sends gets gpu_util added. Only the usage_reply is touched, whichever thread sends what else at the same time."""
    from ipykernel.kernelbase import Kernel

    original = getattr(Kernel, "usage_request", None)
    if original is None or getattr(original, "_dhbw", False):
        return

    async def usage_request(self, stream, ident, parent):
        session = self.session
        send = session.send

        def send_with_gpu(stream_, msg_or_type, content=None, *args, **kwargs):
            if msg_or_type == "usage_reply" and isinstance(content, dict):
                content = {**content, **gpu_usage()}
            return send(stream_, msg_or_type, content, *args, **kwargs)

        session.send = send_with_gpu
        try:
            return await original(self, stream, ident, parent)
        finally:
            try:
                del session.send
            except AttributeError:
                pass

    usage_request._dhbw = True
    Kernel.usage_request = usage_request
