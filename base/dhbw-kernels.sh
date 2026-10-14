#!/bin/bash
# Docker Stacks start hook (before-notebook.d, also run by start-singleuser.py): which kernels the server offers, set by the hub's profile in DHBW_KERNELS — in JupyterLab and in VS Code, which read the same kernel specs.
#   split (or unset): "Python 3 (CPU)" here and "Python 3 (GPU)" as a kernel pod on a GPU node (profile "CPU + GPU-Kernel")
#   cpu: only the local kernel, "Python 3" (profile "CPU")
#   gpu: only the local kernel, "Python 3 (GPU)": the server itself has the GPU (profile "GPU")
K="${CONDA_DIR}/share/jupyter/kernels"
dhbw_local_kernel() {
  rm -rf "${K}/python3-gpu"
  python -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['display_name']=sys.argv[2]; json.dump(d, open(p, 'w'), indent=1)" "${K}/python3/kernel.json" "$1"
}
case "${DHBW_KERNELS:-split}" in
  cpu) dhbw_local_kernel "Python 3" ;;
  gpu) dhbw_local_kernel "Python 3 (GPU)" ;;
esac
