#!/bin/bash
# Docker Stacks start hook (before-notebook.d, also run by start-singleuser.py): with DHBW_LOCAL_GPU=1 the server itself has the GPU (profile "Projekt-Image (GPU)"), so the local kernel is the GPU kernel and the remote one (a kernel pod) is not offered — in JupyterLab and in VS Code, which read the same kernel specs.
if [ "${DHBW_LOCAL_GPU:-}" = "1" ]; then
  K="${CONDA_DIR}/share/jupyter/kernels"
  rm -rf "${K}/python3-gpu"
  python -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['display_name']='Python 3 (GPU)'; json.dump(d, open(p, 'w'), indent=1)" "${K}/python3/kernel.json"
fi
