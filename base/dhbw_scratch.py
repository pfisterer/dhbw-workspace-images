"""DHBW local storage (aiaas-deployment docs/todo.md scratch_limit, docs/architektur.md "Lokaler Speicher je Workspace"): what a workspace or a GPU kernel writes outside the home is Kubernetes' ephemeral-storage, and above the limit the kubelet evicts the pod. This module measures it the way the kubelet counts it, so that JupyterLab and VS Code warn before: once from 80 %, again from 95 %.

What the kubelet counts for a pod: each container's writable layer (containerd: du of the overlay's upper directory), the containers' logs and the emptyDir volumes on disk. From inside, only the merged view of the overlay is visible, not its upper directory. But everything in the upper layer was written after the container was created, and everything of the image was unpacked before, and the kernel sets an entry's ctime on every change (a new file, a file copied up for writing, a chmod; utime cannot set it back). So an entry is in the upper layer when its ctime is not older than the container. The anchor is the container's termination log (/dev/termination-log, a file the kubelet creates for each container after pulling the image and before creating the container), else the start of PID 1. A directory of the upper layer gets a new ctime whenever an entry is created in it (also when a file below it is copied up), so the walk skips every directory older than the anchor: it touches only what was written, not the image, a few milliseconds in a fresh container, about a second per 100,000 written files. Sizes are allocated blocks with hard links once, as containerd's du counts them. emptyDirs on disk (not tmpfs, which is memory) are added whole, among them a home without project storage. Not seen are the container's logs (the kubelet keeps at most 5 × 10 MiB) and what was written since the last measurement.

The limit is DHBW_SCRATCH_GB (GiB, the container's ephemeral-storage limit: set by the hub for the server, by the AI service for a GPU kernel pod).

Server side (dhbw_gpu): Scratch measures the server's container every TICK seconds in a thread and keeps the warning level for it and for each GPU kernel. Kernel side (dhbw_kernel_usage): kernel_usage() adds the GPU kernel pod's numbers to its usage_reply; the measurement itself runs as a separate process (python -m dhbw_scratch), so that its CPU time is no activity of the kernel for the release times.
"""
import asyncio
import json
import os
import stat
import subprocess
import sys
import time

TICK = int(os.environ.get("DHBW_SCRATCH_TICK", "60"))  # seconds between two measurements
LEVELS = (95, 80)  # percent of the limit at which a warning appears, highest first
HYSTERESIS = 5  # percent below a level before its warning is over (no new warning for every few megabytes deleted and written again)
GIB = 1 << 30
KERNEL_FILE = "/tmp/.dhbw-scratch.json"  # the GPU kernel pod's last measurement, written by python -m dhbw_scratch
EMPTY_DIR = "kubernetes.io~empty-dir"
HOME = os.path.expanduser("~").rstrip("/") or "/"


def limit_bytes():
    """The container's ephemeral-storage limit in bytes from DHBW_SCRATCH_GB, 0 without one."""
    try:
        return max(0, int(float(os.environ.get("DHBW_SCRATCH_GB") or 0) * GIB))
    except ValueError:
        return 0


def _unescape(path):
    """Mount points in mountinfo escape space, tab, newline and backslash as octal (\\040)."""
    if "\\" not in path:
        return path
    out, i = [], 0
    while i < len(path):
        if path[i] == "\\" and path[i + 1:i + 4].isdigit():
            out.append(chr(int(path[i + 1:i + 4], 8)))
            i += 4
        else:
            out.append(path[i])
            i += 1
    return "".join(out)


def mounts(mountinfo="/proc/self/mountinfo"):
    """[(mount point, root in its filesystem, filesystem type)] of this container."""
    result = []
    try:
        with open(mountinfo) as f:
            for line in f:
                fields = line.split()
                if " - " not in line or len(fields) < 7:
                    continue
                sep = fields.index("-")
                result.append((_unescape(fields[4]), _unescape(fields[3]), fields[sep + 1]))
    except OSError:
        pass
    return result


def anchor_ns():
    """When the container was created, in ns of the node's clock (ctime): the termination log's ctime, else the start of PID 1; None without either."""
    try:
        return os.stat("/dev/termination-log").st_ctime_ns
    except OSError:
        pass
    try:
        import psutil

        return int(psutil.Process(1).create_time() * 1e9)
    except Exception:  # noqa: BLE001 - without an anchor there is no measurement
        return None


def _du(top, skip, seen, newer_than=None):
    """Allocated bytes below top (without top itself), not crossing into the paths in skip; with newer_than (ns) only entries whose ctime is not older, and only directories that are not older are entered. seen: (st_dev, st_ino) already counted."""
    total = 0
    stack = [top]
    while stack:
        path = stack.pop()
        try:
            entries = os.scandir(path)
        except OSError:
            continue
        with entries:
            for e in entries:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if newer_than is not None and st.st_ctime_ns < newer_than:
                    continue
                if e.path in skip:
                    continue
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                total += st.st_blocks * 512
                if stat.S_ISDIR(st.st_mode):
                    stack.append(e.path)
    return total


def measure(mountinfo="/proc/self/mountinfo", root="/", anchor=None):
    """{"used": bytes, "home_counts": bool, "took": seconds} for this container, None without an anchor. used: the upper layer of the overlay below root plus the emptyDirs on disk; home_counts: the home is no volume of its own or an emptyDir (a project without workspace storage), so it counts as well."""
    started = time.monotonic()
    anchor = anchor_ns() if anchor is None else anchor
    if anchor is None:
        return None
    ms = mounts(mountinfo)
    points = {p for p, _, _ in ms if p != root}
    seen = set()
    used = _du(root, points, seen, newer_than=anchor)
    home_mount = None
    for point, src, fstype in ms:
        if EMPTY_DIR in src and fstype not in ("tmpfs", "ramfs"):
            try:
                st = os.stat(point)
            except OSError:
                continue
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                used += st.st_blocks * 512
                if stat.S_ISDIR(st.st_mode):
                    used += _du(point, points - {point}, seen)
        if point == HOME:
            home_mount = (src, fstype)
    home_counts = home_mount is None or (EMPTY_DIR in home_mount[0] and home_mount[1] not in ("tmpfs", "ramfs"))
    return {"used": used, "home_counts": home_counts, "took": round(time.monotonic() - started, 3)}


def gb(n):
    """Bytes as "8,3 GB" (GiB, as the self-service shows the limit), a whole number without decimals."""
    v = n / GIB
    return (f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}".replace(".", ",")) + " GB"


def next_level(prev, used, limit):
    """The warning level (95, 80 or 0) for used of limit bytes; a level stays until use drops HYSTERESIS percent below it."""
    if not limit:
        return 0
    pct = 100 * used / limit
    new = next((lv for lv in LEVELS if pct >= lv), 0)
    if new < prev and pct >= prev - HYSTERESIS:
        return prev
    return new


def text(kind, used, limit, home_counts):
    """The warning for people, the same in JupyterLab and VS Code (without the notebook's name, which JupyterLab puts before a kernel's). kind: "server" or "kernel"."""
    pct = min(100, int(100 * used / limit))
    what = "des Workspaces" if kind == "server" else "des GPU-Kernels"
    ends = "beendet Kubernetes den Workspace; Variablen und nicht gespeicherte Änderungen gehen verloren" if kind == "server" else "beendet Kubernetes den GPU-Kernel; seine Variablen gehen verloren"
    head = f"Lokaler Speicher {what} zu {pct} % belegt: {gb(used)} von {gb(limit)} außerhalb des Homes"
    if home_counts:
        head = f"Lokaler Speicher {what} zu {pct} % belegt: {gb(used)} von {gb(limit)}, das Home eingeschlossen (das Projekt hat keinen Workspace-Speicher)"
        advice = "Platz schaffen: nicht mehr benötigte Dateien löschen, auch in /tmp, große Pakete in die Umgebung des Projekts aufnehmen; „conda clean --all“ leert den Paket-Cache."
    else:
        advice = "Platz schaffen: Dateien in /tmp löschen, Daten ins Home legen, Pakete mit „pip install --user“ ins Home installieren oder in die Umgebung des Projekts aufnehmen; „conda clean --all“ leert den Paket-Cache."
    return f"{head}. Bei {gb(limit)} {ends}. {advice}"


def entry(kind, level, used, limit, home_counts):
    """What the status says about one container: its numbers, the level, and the text while there is a warning."""
    out = {"used": used, "limit": limit, "level": level}
    if level:
        out["message"] = text(kind, used, limit, home_counts)
    return out


class Scratch:
    """Server side: the server's own measurement and the warning levels of the server and its GPU kernels, for the status (dhbw_gpu)."""

    def __init__(self, log, limit=None, measure_fn=measure):
        self.log = log
        self.limit = limit_bytes() if limit is None else limit
        self.measure_fn = measure_fn
        self.server = None  # entry() of the server, None before the first measurement or without a limit
        self.kernels = {}  # kernel id -> entry() of a GPU kernel that reported its numbers
        self._levels = {}  # "server" or a kernel id -> level
        self._next = 0.0  # monotonic time of the next measurement
        self._busy = False

    def _update(self, key, kind, used, limit, home_counts):
        prev = self._levels.get(key, 0)
        level = next_level(prev, used, limit)
        if level != prev:
            self.log.info("dhbw_scratch: %s at %d %% of its local storage (%d of %d bytes)", key, int(100 * used / limit), used, limit)
        self._levels[key] = level
        return entry(kind, level, used, limit, home_counts)

    def measure_server(self):
        """One measurement of the server's container (blocking, run in a thread). A long walk (many written files) is repeated less often: at most a thirtieth of the time goes to it."""
        if not self.limit:
            return
        result = self.measure_fn()
        if result is None:
            return
        self._next = time.monotonic() + max(TICK, 30 * result.get("took", 0))
        self.server = self._update("server", "server", result["used"], self.limit, result.get("home_counts", False))

    async def tick(self):
        if self._busy or time.monotonic() < self._next:
            return
        self._busy = True
        try:
            await asyncio.get_running_loop().run_in_executor(None, self.measure_server)
        except Exception as e:  # noqa: BLE001 - one failed measurement must not end the measurements
            self.log.warning("dhbw_scratch: measurement failed: %s", e)
        finally:
            self._busy = False

    def kernel_usage(self, kernel_id, usage):
        """A GPU kernel's usage_reply (dhbw_release asks every check): scratch_used, scratch_limit (its pod's limit; the server's own when an AI service from before set none), scratch_home."""
        used = usage.get("scratch_used")
        limit = usage.get("scratch_limit") or self.limit
        if not isinstance(used, int) or not limit:
            return
        self.kernels[kernel_id] = self._update(kernel_id, "kernel", used, limit, bool(usage.get("scratch_home")))

    def forget(self, alive):
        """Drop the kernels that are gone."""
        for kid in [k for k in self.kernels if k not in alive]:
            del self.kernels[kid]
            self._levels.pop(kid, None)


# Kernel side, in the GPU kernel's process.

_spawned = 0.0  # monotonic time the last measurement process was started


def _in_kernel_pod():
    """A GPU kernel pod: the AI service passes the launcher's parameters (RESPONSE_ADDRESS) only there. A local kernel shares the server's container, which the server measures itself."""
    return bool(os.environ.get("RESPONSE_ADDRESS"))


def kernel_usage(path=KERNEL_FILE):
    """{"scratch_used", "scratch_limit", "scratch_home"} for the GPU kernel's usage_reply from the last measurement, {} outside a kernel pod or before the first one. A measurement older than TICK starts the next one as a process of its own, detached from the kernel (its parent exits at once), so that its CPU time does not count as the kernel's."""
    global _spawned
    if not _in_kernel_pod():
        return {}
    try:
        with open(path) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = None
    age = time.time() - last.get("at", 0) if isinstance(last, dict) else None
    if (age is None or age >= TICK) and time.monotonic() - _spawned >= TICK:
        _spawned = time.monotonic()
        try:
            # -I: neither the working directory (the notebook's folder) nor the person's site-packages on the path.
            subprocess.Popen(["/bin/sh", "-c", 'nice -n 19 "$0" -I -m dhbw_scratch "$1" </dev/null >/dev/null 2>&1 &', sys.executable, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
    if not isinstance(last, dict) or not isinstance(last.get("used"), int):
        return {}
    out = {"scratch_used": last["used"], "scratch_home": bool(last.get("home_counts"))}
    if limit_bytes():
        out["scratch_limit"] = limit_bytes()
    return out


def _write(path):
    result = measure()
    if result is None:
        return
    result["at"] = time.time()
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(result, f)
    os.replace(tmp, path)


if __name__ == "__main__":
    # The GPU kernel pod's measurement process (kernel_usage), at most one at a time.
    target = sys.argv[1] if len(sys.argv) > 1 else KERNEL_FILE
    lock = target + ".lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - os.stat(lock).st_mtime < 10 * TICK:
                sys.exit(0)
            os.unlink(lock)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            sys.exit(0)
    try:
        _write(target)
    finally:
        os.close(fd)
        os.unlink(lock)
