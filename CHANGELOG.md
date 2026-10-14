# Changelog

## v2.1.0 – 2026-10-14

- GPU-Kernel: Den Kernel-Pod legt der KI-Dienst an, nicht mehr der Notebook-Server. Der Server braucht dafür keine Rechte in Kubernetes mehr; der Kernel-Pod bekommt Image und Home des Servers und nur noch die nötigen Umgebungsvariablen. Das Pod-Template `kernel-pod.yaml.j2` entfällt.
- Das Kontingent für GPU-Kernel prüft der KI-Dienst (Grenzen und Budgets des Projekts) statt der Server selbst.

## v2.0.0 – 2026-10-14

- Drei Basen statt `notebook-base`: `base-python`, `base-pytorch` (Standard) und `base-tensorflow`, aus einem Dockerfile. Sie sind die Umgebungen der Projekte für alle Server-Arten.
- `DHBW_KERNELS` (cpu, split, gpu) statt `DHBW_LOCAL_GPU`: welche Kernel ein Server anbietet.
- `notebook-base` gibt es nicht mehr; Images darauf (Label `notebook-v1`) laufen weiter.

## v1.2.0 – 2026-10-14

- `notebook-base` als ganzer GPU-Server (Profil „Projekt-Image (GPU)“, `DHBW_LOCAL_GPU=1`): Der lokale Kernel heißt dann „Python 3 (GPU)“, der Kernel-Pod-Eintrag entfällt (JupyterLab und VS Code).
- Kursimages heißen jetzt Projekt-Images: am Projekt im Self-Service, aus Git gebaut oder als fertiges Image.

## v1.1.1 – 2026-10-14

- `notebook-base`: Kommen zwei Anfragen für dasselbe Notebook, während sein Kernel noch startet (z. B. JupyterLab stellt seine Tabs wieder her), startet nur ein Kernel. Vorher startete ein zweiter GPU-Kernel, den die Kontingent-Prüfung ablehnte, und das Notebook blieb ohne Kernel.

## v1.1.0 – 2026-10-13

- Neues Image `notebook-base` (auf `notebook-pytorch`): Notebook und GPU-Kernel in einem Image, Basis für Kursimages im Profil „CPU + GPU-Kernel“. Label `cloud.dhbw.base=notebook-v1`.
- Der GPU-Kernel startet über `/usr/local/bin/bootstrap-kernel.sh`, unabhängig vom `CMD` eines abgeleiteten Images.

## v1.0.0 – 2026-10-13

- Erste Version aus `aiaas-deployment/images/notebook`: Jupyter Docker Stacks `hub-5.5.1`, code-server 4.141.0 mit den Erweiterungen für Python und Jupyter, nbgitpuller, jupyter-server-proxy, jupyter-vscode-proxy, jupyterlab-git, XGBoost.
- VS Code startet ohne Workspace Trust (keine Abfrage „Restricted Mode“).
