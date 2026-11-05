# Changelog

## v2.7.6 – 2026-11-05

- `dhbw-cloud` 0.2.73: im Workspace ohne eigenes Token angemeldet (es nimmt das Token des Workspace-Servers; ein gesetztes `DHBW_CLOUD_TOKEN` geht vor), `dhbw-cloud logout`, `dhbw-cloud job files` und `dhbw-cloud job get` holen die Dateien eines Jobs, `--llm-project` wählt das LLM-Projekt eines Jobs.

## v2.7.5 – 2026-11-05

- Warnung vor vollem lokalem Speicher: Hat der Workspace oder ein GPU-Kernel 80 % seines lokalen Speichers außerhalb des Homes belegt (Limit `ephemeral-storage`, je Budget einstellbar, Standard 10 GB), sagen JupyterLab und VS Code, wie viel belegt ist, wo die Grenze liegt und wie Platz frei wird; ab 95 % erneut als Fehlermeldung, bevor Kubernetes den Pod räumt. Gemessen wird wie beim Kubelet: die beschreibbare Schicht des Containers (`/tmp`, mit pip oder conda in die Umgebung installierte Pakete) und `emptyDir`-Volumes, ein Home ohne Workspace-Speicher eingeschlossen; im Server jede Minute, im GPU-Kernel-Pod in einem eigenen Prozess, der nicht als Aktivität des Kernels zählt (neues Modul `dhbw_scratch`). Das Limit kommt aus `DHBW_SCRATCH_GB` (Hub, KI-Dienst); ohne die Variable bleibt der Server ohne Warnung, ein GPU-Kernel nutzt dann das Limit des Servers. Ein GPU-Kernel wird dafür auch während einer Rechnung nach seiner `usage_reply` gefragt. JupyterLab-Erweiterung `dhbw-gpu-status` 0.5.0, VS-Code-Erweiterung `dhbw.activity` 1.2.0.

## v2.7.4 – 2026-11-05

- Endet ein GPU-Kernel von selbst, nennt JupyterLab den Grund in einer Meldung (und beim Start im Fehlerdialog): geräumt, weil er außerhalb des Homes mehr lokalen Speicher belegt hat als erlaubt (mit Hinweis, dass große Pakete in die Umgebung des Projekts gehören), weil auf dem Knoten Speicher knapp wurde, oder weil die Obergrenze des Projekts erreicht war. Braucht den KI-Dienst, der für einen beendeten Kernel-Pod dessen Grund liefert.
- `claude` sagt in einem Workspace ohne LLM-Schlüssel (ohne LLM gestartet oder kein LLM-Projekt), warum die DHBW-Modelle fehlen, und wie es mit einem LLM-Projekt oder dem eigenen Abo weitergeht.

## v2.7.3 – 2026-11-02

- Batch-Jobs: papermill (Notebooks als Job) und `dhbw-cloud` (`dhbw-cloud job submit -- …`; Projekt und Adresse setzt der Hub über `DHBW_PROJECT` und `DHBW_CLOUD_URL`).

## v2.7.2 – 2026-11-01

- Die Probe von OpenCode beim Bau schreibt nicht mehr als root ins Home von jovyan; v2.7.1 scheiterte daran bei `fix-permissions`.

## v2.7.1 – 2026-11-01

- Die Dateien der VS-Code-Erweiterung `dhbw.activity` liegen flach in `notebook/`: Der Build im Cluster bekommt seinen Kontext ohne Unterordner, v2.7.0 ließ sich dort nicht bauen.

## v2.7.0 – 2026-11-01

- VS Code zählt für die Rückgabezeiten: Tippen, Cursor, Scrollen, Speichern und Befehle im Terminal gelten als Aktivität (eingebaute Erweiterung `dhbw.activity`), und ein offener VS-Code-Tab gilt als offener Tab. Vorher zählte in VS Code nur CPU-Last, und es galt die kürzere Zeit ohne Tab. Die Warnung vor der Rückgabe mit „Weiterarbeiten“ erscheint jetzt auch in VS Code.
- Der Verkehr einer App hinter jupyter-server-proxy ist keine Aktivität mehr, nur noch ein Zeichen für den offenen Tab; Apps melden Eingaben über eine Datei in `DHBW_ACTIVITY_DIR`.
- Coding-Agenten im Terminal: OpenCode ist im Notebook-Image, Claude Code wird beim ersten Aufruf von `claude` geladen. Beide nutzen die Sprachmodelle des Projekts; Claude Code kann nach `/login` (erstes Mal mit `DHBW_CLAUDE=abo claude`) auch ein eigenes Claude-Abo nutzen, `/logout` schaltet zurück.

## v2.6.2 – 2026-10-22

- Sicherheitsupdates: Die Notebook-Images bauen auf den Jupyter-Docker-Stacks-Images vom 19.10.2026 (Pillow 13.0.0, urllib3 2.8.0, msgpack 1.2.3); certifi 2026.10.19 und pip 26.2.2 (dessen eigene Kopie von certifi ebenfalls 2026.10.19); in code-server `follow-redirects` 1.16.1. PyTorch bleibt 2.11 (cu130), TensorFlow 2.21, Pillow 13 mit Matplotlib und torchvision geprüft.
- Trivy in Harbor (nur Funde mit verfügbarer Korrektur): `base-python` 0 kritisch / 4 hoch, `base-pytorch` 0 / 7, `base-tensorflow` 0 / 5; die verbleibenden stecken in den von pip mitgelieferten Kopien (urllib3, msgpack, setuptools) und bei PyTorch und TensorFlow in Paketen des Upstream-Images (setuptools 78.1.0, wheel, jaraco.context, Brotli).

## v2.6.1 – 2026-10-22

- GPU-Kernel: Beim Beenden sagt der Server dem KI-Dienst, warum (für sein Forschungsprotokoll `research_workloads`): `idle` (Rückgabezeiten, auch wenn der ganze Workspace wegen Leerlauf endet), `cancel` („Warten abbrechen“), `timeout` (Start dauerte länger als `GP_LAUNCH_TIMEOUT`), `person` (Shut Down, Restart, „Jetzt freigeben“, VS Code); endet der Server selbst (Hub, Culler), geht der Aufruf ohne Grund. Vorher kam jedes Ende als „vom Server beendet“ an.
- Trivy in Harbor (nur Funde mit verfügbarer Korrektur): `base-python` 5 kritisch / 22 hoch, `base-pytorch` 5 / 25, `base-tensorflow` 5 / 23. Die Zunahme gegenüber v2.6.0 kommt aus seither veröffentlichten Meldungen, nicht aus dieser Änderung (der Scan von v2.6.0 ist vom 19.10.): Pillow 12.3.0 (3 kritisch, behoben in 13.0.0), certifi (kritisch, behoben in 2026.10.19), urllib3 2.7.0 (behoben in 2.8.0), msgpack, follow-redirects (code-server), setuptools.

## v2.6.0 – 2026-10-19

- Rückgabezeiten je Projekt (aiaas-deployment `idle_release`): Die Erweiterung `dhbw_gpu` beendet ruhende Kernel und den ruhenden Workspace nach den Zeiten, die der Hub in `DHBW_RELEASE` übergibt (Leerlauf mit offenem Tab, ohne Tab, Obergrenze; für den Workspace und seine lokalen Kernel die CPU-Zeiten, für GPU-Kernel die GPU-Zeiten). Gezählt wird Leerlauf: Ein Kernel gilt auch dann als aktiv, wenn er im Hintergrund-Thread rechnet (CPU- oder GPU-Last aus seiner `usage_reply`), der Workspace bei Last im Container, Terminal-Ein- und -Ausgaben und beim Speichern. JupyterLabs eigener Kernel-Culler ist dann aus; ohne `DHBW_RELEASE` (Hub von vorher) bleibt alles wie bisher.
- Neues Modul `dhbw_kernel_usage` (über `/etc/ipython/ipython_kernel_config.py`): Die `usage_reply` des Kernels enthält die GPU-Auslastung aus `nvidia-smi` im eigenen Pod.
- JupyterLab-Erweiterung `dhbw-gpu-status` 0.4.0: Kurz vor der Rückgabe warnt eine Meldung mit „Weiterarbeiten“ (zählt als Aktivität), kurz vor der Obergrenze eine Meldung mit der Uhrzeit; der Countdown eines GPU-Kernels kommt vom Server und berücksichtigt die Last.
- Trivy in Harbor (nur Funde mit verfügbarer Korrektur), unverändert zu v2.5.0: `base-python` 0 kritisch / 4 hoch, `base-pytorch` 0 / 7, `base-tensorflow` 0 / 5.

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
