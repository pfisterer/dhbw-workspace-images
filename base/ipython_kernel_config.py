# The kernel launcher puts its own script directory first on sys.path; a local kernel has the working directory there, so that "import mymodule" finds files next to the notebook. Restore that.
c.InteractiveShellApp.exec_lines = ["import sys as _dhbw_sys; _dhbw_sys.path[:] = [''] + [p for p in _dhbw_sys.path if 'kernel-launchers' not in p]; del _dhbw_sys"]
