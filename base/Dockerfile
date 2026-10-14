# DHBW workspaces: base image for course environments with the notebook on a CPU node and the kernel "Python 3 (GPU)" in its own pod on a GPU node (profile "CPU + GPU-Kernel"). The same image runs both: the notebook pod (JupyterLab, VS Code, terminal and the local kernel "Python 3 (CPU)") and the GPU kernel pod, so a course image derived from it has one environment everywhere. Built on notebook-pytorch (CUDA 12); adds gateway_provisioners (KubernetesProvisioner in the notebook, kernel launcher in the kernel pod), the server extension dhbw_gpu (quota check, GPU status, working directory) and the JupyterLab extension dhbw-gpu-status (waiting kernels visible). The label cloud.dhbw.base marks the image and everything derived from it; a project's course image must carry it.
ARG BASE

# JupyterLab extension, built with Node in a separate stage.
FROM ${BASE} AS labext
RUN mamba install --yes --quiet nodejs=22 && mkdir -p /tmp/ext/src
COPY --chown=${NB_UID}:${NB_GID} package.json tsconfig.json /tmp/ext/
COPY --chown=${NB_UID}:${NB_GID} index.ts /tmp/ext/src/index.ts
WORKDIR /tmp/ext
# node_modules instead of Yarn Plug'n'Play, so that tsc finds the packages (as in the JupyterLab extension template).
RUN echo 'nodeLinker: node-modules' > .yarnrc.yml && jlpm install && jlpm build

FROM ${BASE}

LABEL cloud.dhbw.base="notebook-v1"

RUN pip install --no-cache-dir "gateway_provisioners[k8s]==0.5.0" \
 && fix-permissions "${CONDA_DIR}"

USER root
COPY --from=labext /tmp/ext/labextension ${CONDA_DIR}/share/jupyter/labextensions/dhbw-gpu-status
COPY dhbw_gpu.py /tmp/dhbw_gpu.py
COPY dhbw_gpu.json /etc/jupyter/jupyter_server_config.d/dhbw_gpu.json
COPY kernel-pod.yaml.j2 /tmp/kernel-pod.yaml.j2
COPY dhbw_kernel_launch.py /tmp/dhbw_kernel_launch.py
COPY ipython_kernel_config.py /etc/ipython/ipython_kernel_config.py
COPY dhbw-local-gpu.sh /usr/local/bin/before-notebook.d/20-dhbw-local-gpu.sh
# Kernel side: the launcher the kernel pod runs (bootstrap-kernel.sh, launch_ipykernel.py); image-bootstrap copies the script without the execute bit.
# Notebook side: kernel spec in the environment; our pod template replaces the default one; its entry point is dhbw_kernel_launch.py, which hands over to launch_kubernetes.py when the Jupyter server starts the kernel and is a proxy to the server when VS Code starts the spec on its own (--connection-file, only filled by VS Code); image name and launch timeout are removed from the spec so that GP_IMAGE_NAME and GP_LAUNCH_TIMEOUT (set by JupyterHub) decide; the spec's 30 s are too short when a kernel waits for a GPU. The local kernel is named "Python 3 (CPU)" next to it instead of "Python 3 (ipykernel)".
RUN jupyter image-bootstrap install --languages=Python \
 && chmod 0755 /usr/local/bin/bootstrap-kernel.sh \
 && mv /tmp/dhbw_gpu.py "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/dhbw_gpu.py" \
 && jupyter k8s-spec install --sys-prefix --kernel-name=python3-gpu --display-name="Python 3 (GPU)" \
 && K="${CONDA_DIR}/share/jupyter/kernels/python3-gpu" \
 && mv /tmp/kernel-pod.yaml.j2 "${K}/scripts/kernel-pod.yaml.j2" \
 && mv /tmp/dhbw_kernel_launch.py "${K}/scripts/dhbw_kernel_launch.py" \
 && python -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); c=d['metadata']['kernel_provisioner']['config']; [c.pop(k, None) for k in ('image_name', 'executor_image_name', 'launch_timeout')]; d['argv'][1]=d['argv'][1].replace('launch_kubernetes.py', 'dhbw_kernel_launch.py'); d['argv'] += ['--connection-file', '{connection_file}']; json.dump(d, open(p, 'w'), indent=2)" "${K}/kernel.json" \
 && python -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['display_name']='Python 3 (CPU)'; json.dump(d, open(p, 'w'), indent=1)" "${CONDA_DIR}/share/jupyter/kernels/python3/kernel.json" \
 && chmod 0755 /usr/local/bin/before-notebook.d/20-dhbw-local-gpu.sh \
 && fix-permissions "${CONDA_DIR}"
USER ${NB_UID}
