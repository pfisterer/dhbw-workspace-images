# DHBW Workspace-Images

Die Basis-Images der DHBW-Workspaces (JupyterHub auf dem GPU-Cluster der DHBW): Jupyter Docker Stacks mit JupyterLab, VS Code im Browser (code-server), nbgitpuller, jupyterlab-git und XGBoost.

| Image | Basis | Wofür |
| --- | --- | --- |
| `registry.gpu.services.dhbw.cloud/platform/base-python` | `notebook-cpu` (scipy) | Python mit NumPy, pandas, scikit-learn, ohne GPU-Bibliotheken |
| `registry.gpu.services.dhbw.cloud/platform/base-pytorch` | `notebook-pytorch` (CUDA 12) | PyTorch, Standard |
| `registry.gpu.services.dhbw.cloud/platform/base-tensorflow` | `notebook-tensorflow` (CUDA) | TensorFlow und Keras |

Die Basen sind die Umgebungen der Projekte: Jedes Projekt wählt im Self-Service eine Basis, optional mit Paketen aus einem Git-Repository darauf gebaut, oder ein vorhandenes Image. Alle Server-Arten des Projekts – „CPU“, „CPU + GPU-Kernel“ (Notebook auf der CPU, GPU-Kernel als eigener Pod) und „GPU“ – laufen mit dieser Umgebung. Die Basen bauen auf den Notebook-Images `notebook-cpu`, `notebook-pytorch` und `notebook-tensorflow` auf (Jupyter Docker Stacks mit VS Code, nbgitpuller, jupyterlab-git, XGBoost) und bringen dazu den GPU-Kernel, die DHBW-Erweiterungen und das Label `cloud.dhbw.base` mit.

## Eigene Umgebung darauf aufbauen

Jede Version ist ein Git-Tag (`v1.0.0`) und in Harbor ein Tag gleichen Namens, der nicht aufgeräumt wird:

```dockerfile
FROM registry.gpu.services.dhbw.cloud/platform/notebook-pytorch:v1.0.0
RUN pip install --no-cache-dir transformers
```

## Eigene Umgebung darauf aufbauen

Am einfachsten am Projekt „Basis + Git“ wählen und ein öffentliches Repository angeben. Gebaut wird wie bei Binder aus `requirements.txt`, `environment.yml`, `apt.txt` und `postBuild` (im Hauptverzeichnis, `binder/` oder `.binder/`) auf der gewählten Basis. Erscheint eine neue Version der Basis, wird von selbst neu gebaut; das Repository landet beim Start als Kursmaterial unter `~/projekte`.

Ein eigenes Image auf einer Basis, jede Version ist ein Git-Tag und in Harbor ein Tag gleichen Namens, der nicht aufgeräumt wird:

```dockerfile
FROM registry.gpu.services.dhbw.cloud/platform/base-pytorch:v2.0.0
RUN pip install --no-cache-dir transformers datasets
```

Am Projekt als „Vorhandenes Image“ eintragen. Beim Speichern wird das Label `cloud.dhbw.base` nachgesehen: Mit ihm läuft das Image mit allem; ein beliebiges anderes Image (es braucht `jupyterhub-singleuser`) läuft so, wie es ist, ohne „CPU + GPU-Kernel“. Das Image muss öffentlich abrufbar sein und läuft als Benutzer 1000 ohne root-Rechte; auf der GPU gibt es 3 GB Speicher.

Was sich zwischen den Versionen ändert, steht in [CHANGELOG.md](CHANGELOG.md).

## Aufbau

- `images.yaml` – die Images: Name in Harbor, Verzeichnis mit dem Dockerfile, Build-Argumente.
- `notebook/Dockerfile` – ein Dockerfile für alle drei Varianten; `BASE` wählt das Jupyter-Image, `XGBOOST` das passende Paket.
- `base/` – die Basen (`VARIANT` python, pytorch, tensorflow): Kernel-Spec „Python 3 (GPU)“ mit gateway_provisioners, Pod-Vorlage des GPU-Kernels, Start-Hook `dhbw-kernels.sh` (welche Kernel ein Server anbietet), Server-Erweiterung `dhbw_gpu` und JupyterLab-Erweiterung `dhbw-gpu-status`.

## Release

1. Änderung per Pull Request nach `main`, Eintrag in `CHANGELOG.md`.
2. Tag setzen: `git tag v1.1.0 && git push origin v1.1.0`.
3. In `aiaas-deployment` die Version in `ansible/vars/images.yaml` (`workspace_images.version`) hochsetzen und die Images bauen (`--tags images`), danach den Hub ausrollen (`--tags jupyterhub`).

Gebaut wird im Cluster mit BuildKit, nicht in GitHub: Die GPU-Images sind über 10 GB groß, und so braucht GitHub keine Zugangsdaten zu Harbor. Der Build legt das Image unter einem Hash des Inhalts ab (unverändert = kein Neubau) und gibt ihm den Versions-Tag dazu.
