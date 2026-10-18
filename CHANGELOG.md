# Changelog

## v2.5.0 – 2026-10-18

- Sicherheitsupdates: Die Notebook-Images bauen auf den Jupyter-Docker-Stacks-Images vom 12.10.2026 (Datums-Tag statt `hub-5.5.1`, das seit 01.09. nicht mehr neu gebaut wird): Ubuntu 26.04, JupyterHub 6.0.1 (Single-User, läuft mit dem Hub 5.5), JupyterLab 4.6.4, Notebook 7.6.3, Python 3.13; PyTorch 2.11 und TensorFlow 2.21 wie bisher.
- Beim Bau werden die Ubuntu-Pakete aktualisiert (`apt-get upgrade`), `/usr/bin/pebble` aus dem Ubuntu-Basis-Image entfällt.
- code-server: die mitgelieferten Node-Module `basic-ftp` (6.2.3) und `shell-quote` (1.12.0) durch korrigierte Versionen ersetzt.
- `nbclassic` (klassische Notebook-Oberfläche) entfällt; `/tree` liefert Notebook 7.
- Trivy in Harbor (nur Funde mit verfügbarer Korrektur): `base-python` von 8 kritisch / 169 hoch auf 0 kritisch / 4 hoch, `base-pytorch` 0 / 7, `base-tensorflow` 0 / 5 (beide vorher nicht gescannt); die verbleibenden stecken in den von pip und setuptools mitgelieferten Kopien (urllib3, msgpack, setuptools, wheel, jaraco.context).

## v2.2.1 – 2026-10-14

- Die Quelle der JupyterLab-Erweiterung liegt wieder flach in `base/` (`tsconfig.json` darauf eingestellt): Der Build im Cluster bekommt seinen Kontext ohne Unterordner, v2.2.0 ließ sich dort nicht bauen.

## v2.2.0 – 2026-10-14

- GPU-Kernel: Neben dem GPU-Status in der Leiste steht „Jetzt freigeben“; der Knopf beendet die GPU-Kernel sofort, ohne Rückfrage, und gibt die GPU frei. Ein Klick auf den Text fragt wie bisher nach.
- `tsconfig.json` mit `moduleResolution: bundler`.

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
