# DHBW Workspace-Images

Die Basis-Images der DHBW-Workspaces (JupyterHub auf dem GPU-Cluster der DHBW): Jupyter Docker Stacks mit JupyterLab, VS Code im Browser (code-server), nbgitpuller, jupyterlab-git und XGBoost.

| Image | Basis | Wofür |
| --- | --- | --- |
| `registry.gpu.services.dhbw.cloud/platform/notebook-cpu` | `quay.io/jupyter/scipy-notebook` | Python mit NumPy, pandas, scikit-learn, ohne GPU |
| `registry.gpu.services.dhbw.cloud/platform/notebook-pytorch` | `quay.io/jupyter/pytorch-notebook` (CUDA 12) | PyTorch auf der GPU |
| `registry.gpu.services.dhbw.cloud/platform/notebook-tensorflow` | `quay.io/jupyter/tensorflow-notebook` (CUDA) | TensorFlow und Keras auf der GPU |
| `registry.gpu.services.dhbw.cloud/platform/notebook-base` | `notebook-pytorch` | Notebook auf der CPU mit GPU-Kernel; Basis für Projekt-Images |

## Eigene Umgebung darauf aufbauen

Jede Version ist ein Git-Tag (`v1.0.0`) und in Harbor ein Tag gleichen Namens, der nicht aufgeräumt wird:

```dockerfile
FROM registry.gpu.services.dhbw.cloud/platform/notebook-pytorch:v1.0.0
RUN pip install --no-cache-dir transformers
```

## Projekt-Image für „CPU + GPU-Kernel“ und „Projekt-Image (GPU)“

Im Profil „CPU + GPU-Kernel“ läuft das Notebook auf einem CPU-Knoten, der Kernel „Python 3 (GPU)“ startet bei Bedarf als eigener Pod auf einem GPU-Knoten; „Projekt-Image (GPU)“ ist dasselbe Image als ganzer Server auf der GPU. Ein Projekt kann dafür ein eigenes Projekt-Image festlegen (Self-Service, Projekt bearbeiten, Reiter „Workspaces“), aus Git gebaut oder als fertiges Image. Ein fertiges Image muss von `notebook-base` abgeleitet sein, dann läuft dasselbe Image für Notebook, Terminal, VS Code, den CPU- und den GPU-Kernel:

```dockerfile
FROM registry.gpu.services.dhbw.cloud/platform/notebook-base:v1.2.0
RUN pip install --no-cache-dir transformers datasets
```

Einfacher geht es ohne Dockerfile: Am Projekt „Aus Git bauen“ wählen und ein öffentliches Repository angeben. Gebaut wird wie bei Binder aus `requirements.txt`, `environment.yml`, `apt.txt` und `postBuild` (im Hauptverzeichnis, `binder/` oder `.binder/`), aber auf `notebook-base`. Erscheint eine neue Version von `notebook-base`, wird das Projekt-Image von selbst neu gebaut; das Repository landet beim Start als Kursmaterial unter `~/projekte`.

Geprüft wird beim Speichern am Label `cloud.dhbw.base`, das `notebook-base` setzt und abgeleitete Images erben. Das Image muss öffentlich abrufbar sein (z. B. auf ghcr.io oder aus einem Build in Harbor `envs/`), läuft als Benutzer 1000 ohne root-Rechte und hat auf der GPU 3 GB Speicher.

Was sich zwischen den Versionen ändert, steht in [CHANGELOG.md](CHANGELOG.md).

## Aufbau

- `images.yaml` – die Images: Name in Harbor, Verzeichnis mit dem Dockerfile, Build-Argumente.
- `notebook/Dockerfile` – ein Dockerfile für alle drei Varianten; `BASE` wählt das Jupyter-Image, `XGBOOST` das passende Paket.
- `base/` – `notebook-base`: Kernel-Spec „Python 3 (GPU)“ mit gateway_provisioners, Pod-Vorlage des GPU-Kernels, Server-Erweiterung `dhbw_gpu` und JupyterLab-Erweiterung `dhbw-gpu-status`.

## Release

1. Änderung per Pull Request nach `main`, Eintrag in `CHANGELOG.md`.
2. Tag setzen: `git tag v1.1.0 && git push origin v1.1.0`.
3. In `aiaas-deployment` die Version in `ansible/vars/images.yaml` (`workspace_images.version`) hochsetzen und die Images bauen (`--tags images`), danach den Hub ausrollen (`--tags jupyterhub`).

Gebaut wird im Cluster mit BuildKit, nicht in GitHub: Die GPU-Images sind über 10 GB groß, und so braucht GitHub keine Zugangsdaten zu Harbor. Der Build legt das Image unter einem Hash des Inhalts ab (unverändert = kein Neubau) und gibt ihm den Versions-Tag dazu.
