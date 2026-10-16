# DHBW workspaces: notebook image, one Dockerfile for all variants (images.yaml sets BASE and XGBOOST). Adds VS Code in the browser (code-server behind jupyter-vscode-proxy, Launcher tile "VS Code"), nbgitpuller (course material via link), jupyterlab-git and XGBoost to a Jupyter Docker Stacks image. Built in the DHBW GPU cluster from a release tag of this repository and pushed to Harbor (project platform).
ARG BASE
FROM ${BASE}

ARG CODE_SERVER_VERSION=4.141.0
ARG XGBOOST=xgboost
# Set by BuildKit per platform (amd64, arm64); code-server ships a tarball for each.
ARG TARGETARCH=amd64

USER root

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl git-lfs openssh-client rsync htop \
 && rm -rf /var/lib/apt/lists/*

# code-server as a standalone release under /opt/code-server. The Python and Jupyter extensions (Open VSX) go into its built-in extension directory: they are there for everyone, and extensions a person installs land in ~/.local/share/code-server in the persistent home.
RUN curl -fsSL "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-${TARGETARCH}.tar.gz" | tar -xz -C /opt \
 && mv "/opt/code-server-${CODE_SERVER_VERSION}-linux-${TARGETARCH}" /opt/code-server \
 && ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server \
 && HOME=/tmp/cs code-server --extensions-dir /opt/code-server/lib/vscode/extensions --install-extension ms-python.python --install-extension ms-toolsai.jupyter \
 && rm -rf /tmp/cs

# Without Workspace Trust: the server belongs to one person and only holds their own files, so the "Restricted Mode" question on every start protects nothing. jupyter-vscode-proxy runs "code-server" from PATH and has no setting for extra flags, hence a wrapper in place of the link.
RUN rm /usr/local/bin/code-server \
 && printf '#!/bin/sh\nexec /opt/code-server/bin/code-server --disable-workspace-trust "$@"\n' > /usr/local/bin/code-server \
 && chmod 755 /usr/local/bin/code-server

USER ${NB_UID}

# PyTorch for another CUDA (TORCH_CUDA, e.g. cu130): the same version as the upstream image's, from PyTorch's wheels for that CUDA, with torchvision and torchaudio to match; the CUDA 12 libraries only torch needed go. CUDA 13 brings kernels for the GB10 (sm_110/sm_120 builds), about six times the bf16 throughput of the cu128 wheels there (probe 16.10.2026), and runs with the 595 drivers of all GPU nodes.
ARG TORCH_CUDA=
RUN if [ -n "${TORCH_CUDA}" ]; then \
      v="$(python -c 'import torch; print(torch.__version__.split("+")[0])')" \
   && pip install --no-cache-dir --index-url "https://download.pytorch.org/whl/${TORCH_CUDA}" "torch==${v}+${TORCH_CUDA}" torchvision torchaudio \
   && old="$(pip list --format freeze | grep -E '^nvidia-[a-z0-9-]+-cu12==' | cut -d= -f1)" \
   && if [ -n "${old}" ]; then pip uninstall -y ${old}; fi \
   && python -c 'import torch, torchvision; print(torch.__version__, torch.version.cuda, torchvision.__version__)' \
   && fix-permissions "${CONDA_DIR}"; \
    fi

# jupyter-server-proxy explicitly: jupyter-vscode-proxy 0.7 no longer depends on it, and without it there is no VS Code tile.
RUN pip install --no-cache-dir nbgitpuller jupyter-server-proxy jupyter-vscode-proxy jupyterlab-git "${XGBOOST}" \
 && fix-permissions "${CONDA_DIR}" \
 && fix-permissions "/home/${NB_USER}"
