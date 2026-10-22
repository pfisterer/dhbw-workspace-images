# DHBW workspaces: notebook image, one Dockerfile for all variants (images.yaml sets BASE and XGBOOST). Adds VS Code in the browser (code-server behind jupyter-vscode-proxy, Launcher tile "VS Code"), nbgitpuller (course material via link), jupyterlab-git and XGBoost to a Jupyter Docker Stacks image. Built in the DHBW GPU cluster from a release tag of this repository and pushed to Harbor (project platform).
ARG BASE
FROM ${BASE}

ARG CODE_SERVER_VERSION=4.141.0
ARG XGBOOST=xgboost
# Set by BuildKit per platform (amd64, arm64); code-server ships a tarball for each. No default: one would override BuildKit's value.
ARG TARGETARCH

USER root

# Security updates of the OS packages on top of the upstream image (Trivy in Harbor). /usr/bin/pebble comes with Ubuntu's base image outside any package, is not used here and carries an old Go runtime.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends curl git-lfs openssh-client rsync htop \
 && rm -rf /var/lib/apt/lists/* /usr/bin/pebble

# code-server as a standalone release under /opt/code-server. The Python and Jupyter extensions (Open VSX) go into its built-in extension directory: they are there for everyone, and extensions a person installs land in ~/.local/share/code-server in the persistent home.
RUN curl -fsSL "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-${TARGETARCH}.tar.gz" | tar -xz -C /opt \
 && mv "/opt/code-server-${CODE_SERVER_VERSION}-linux-${TARGETARCH}" /opt/code-server \
 && ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server \
 && HOME=/tmp/cs code-server --extensions-dir /opt/code-server/lib/vscode/extensions --install-extension ms-python.python --install-extension ms-toolsai.jupyter \
 && rm -rf /tmp/cs

# Node modules code-server bundles in versions with known vulnerabilities, replaced by fixed releases from npm (checked by SHA-256): basic-ftp (6.x only drops separate transfer hosts by default), shell-quote and follow-redirects. Remove an entry once a code-server release brings the version itself.
RUN set -e; for m in "node_modules/basic-ftp basic-ftp-6.2.3 3c2d91c437866ce6cfeeb0a0b1c28729b2951c7c01b3d12abb7eda87e1e9b132" \
                    "lib/vscode/node_modules/shell-quote shell-quote-1.12.0 3cdb295c8aa0565ff782e8e3e482a83caba67110857ac3b74aad4312407898a6" \
                    "node_modules/follow-redirects follow-redirects-1.16.1 6e075d999dc5ff568916954508397b11a537b18bde615986d7bd8b3d3fa1799f"; do \
      set -- $m; d="/opt/code-server/$1"; n="${2%-*}"; \
      curl -fsSL -o /tmp/m.tgz "https://registry.npmjs.org/${n}/-/$2.tgz"; \
      echo "$3  /tmp/m.tgz" | sha256sum -c -; \
      test -d "$d"; rm -rf "$d"; mkdir -p "$d"; tar -xzf /tmp/m.tgz -C "$d" --strip-components=1 --no-same-owner; rm /tmp/m.tgz; \
    done

# Without Workspace Trust: the server belongs to one person and only holds their own files, so the "Restricted Mode" question on every start protects nothing. jupyter-vscode-proxy runs "code-server" from PATH and has no setting for extra flags, hence a wrapper in place of the link.
RUN rm /usr/local/bin/code-server \
 && printf '#!/bin/sh\nexec /opt/code-server/bin/code-server --disable-workspace-trust "$@"\n' > /usr/local/bin/code-server \
 && chmod 755 /usr/local/bin/code-server

USER ${NB_UID}

# PyTorch for another CUDA (TORCH_CUDA, e.g. cu130): the same version as the upstream image's, from PyTorch's wheels for that CUDA, with torchvision and torchaudio to match. The CUDA 12 libraries go first: their packages and those for CUDA 13 share paths (nvidia/cudnn/lib/libcudnn.so.9), so removing them afterwards would remove the new ones. CUDA 13 brings kernels for the GB10 (sm_110/sm_120 builds), about ten times the bf16 throughput of the cu128 wheels there (probe 16.10.2026), and runs with the 595 drivers of all GPU nodes.
ARG TORCH_CUDA=
RUN if [ -n "${TORCH_CUDA}" ]; then \
      v="$(python -c 'import torch; print(torch.__version__.split("+")[0])')" \
   && old="$(pip list --format freeze | grep -E '^nvidia-[a-z0-9-]+-cu12==' | cut -d= -f1)" \
   && pip uninstall -y torch torchvision torchaudio ${old} \
   && pip install --no-cache-dir --index-url "https://download.pytorch.org/whl/${TORCH_CUDA}" "torch==${v}+${TORCH_CUDA}" torchvision torchaudio \
   && python -c 'import torch, torchvision; print(torch.__version__, torch.version.cuda, torchvision.__version__)' \
   && fix-permissions "${CONDA_DIR}"; \
    fi

# nbclassic (the classic notebook UI, nothing here depends on it; Notebook 7 serves /tree) ships an old underscore.js; removed alone (--force), so that its dependencies such as nest-asyncio stay; pip vendors its own copies of urllib3, msgpack and setuptools, which Trivy lists as well and only a pip release can update.
RUN if python -c 'import nbclassic' 2>/dev/null; then \
      mamba remove --force --yes --quiet --prefix "${CONDA_DIR}" nbclassic \
   && mamba clean --all -f -y \
   && fix-permissions "${CONDA_DIR}"; \
    fi

# certifi from the upstream image (2026.7.22) and the copy inside pip (2026.6.17) carry a revoked root (GHSA-6q48-6c7w-9gw2); pip 26.2.2 vendors 2026.10.19. Drop once the upstream image brings both.
RUN pip install --no-cache-dir --upgrade "pip>=26.2.2" "certifi>=2026.10.19" \
 && python -c 'import certifi, pip._vendor.certifi as v; print("certifi", certifi.__version__, "pip vendored", v.__version__)' \
 && fix-permissions "${CONDA_DIR}"

# jupyter-server-proxy explicitly: jupyter-vscode-proxy 0.7 no longer depends on it, and without it there is no VS Code tile.
RUN pip install --no-cache-dir nbgitpuller jupyter-server-proxy jupyter-vscode-proxy jupyterlab-git "${XGBOOST}" \
 && fix-permissions "${CONDA_DIR}" \
 && fix-permissions "/home/${NB_USER}"
