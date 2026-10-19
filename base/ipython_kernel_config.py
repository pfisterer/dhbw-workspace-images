# The kernel launcher puts its own script directory first on sys.path; a local kernel has the working directory there, so that "import mymodule" finds files next to the notebook. Restore that.
c.InteractiveShellApp.exec_lines = ["import sys as _dhbw_sys; _dhbw_sys.path[:] = [''] + [p for p in _dhbw_sys.path if 'kernel-launchers' not in p]; del _dhbw_sys"]
# Release times (dhbw_kernel_usage.py): the kernel's usage reply also tells its GPU's utilisation, so a training in a background thread counts as activity; a failure here never stops the kernel.
try:
    import dhbw_kernel_usage as _dhbw_usage

    _dhbw_usage.install()
    del _dhbw_usage
except Exception:  # noqa: BLE001
    pass
