# Changelog

## v1.1.1 – 2026-10-14

- `notebook-base`: Kommen zwei Anfragen für dasselbe Notebook, während sein Kernel noch startet (z. B. JupyterLab stellt seine Tabs wieder her), startet nur ein Kernel. Vorher startete ein zweiter GPU-Kernel, den die Kontingent-Prüfung ablehnte, und das Notebook blieb ohne Kernel.

## v1.1.0 – 2026-10-13

- Neues Image `notebook-base` (auf `notebook-pytorch`): Notebook und GPU-Kernel in einem Image, Basis für Kursimages im Profil „CPU + GPU-Kernel“. Label `cloud.dhbw.base=notebook-v1`.
- Der GPU-Kernel startet über `/usr/local/bin/bootstrap-kernel.sh`, unabhängig vom `CMD` eines abgeleiteten Images.

## v1.0.0 – 2026-10-13

- Erste Version aus `aiaas-deployment/images/notebook`: Jupyter Docker Stacks `hub-5.5.1`, code-server 4.141.0 mit den Erweiterungen für Python und Jupyter, nbgitpuller, jupyter-server-proxy, jupyter-vscode-proxy, jupyterlab-git, XGBoost.
- VS Code startet ohne Workspace Trust (keine Abfrage „Restricted Mode“).
