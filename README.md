# DHBW Workspace-Images

Die Basis-Images der DHBW-Workspaces (JupyterHub auf dem GPU-Cluster der DHBW): Jupyter Docker Stacks mit JupyterLab, VS Code im Browser (code-server), nbgitpuller, jupyterlab-git und XGBoost.

| Image | Basis | Wofür |
| --- | --- | --- |
| `registry.gpu.services.dhbw.cloud/platform/notebook-cpu` | `quay.io/jupyter/scipy-notebook` | Python mit NumPy, pandas, scikit-learn, ohne GPU |
| `registry.gpu.services.dhbw.cloud/platform/notebook-pytorch` | `quay.io/jupyter/pytorch-notebook` (CUDA 12) | PyTorch auf der GPU |
| `registry.gpu.services.dhbw.cloud/platform/notebook-tensorflow` | `quay.io/jupyter/tensorflow-notebook` (CUDA) | TensorFlow und Keras auf der GPU |

## Eigene Umgebung darauf aufbauen

Jede Version ist ein Git-Tag (`v1.0.0`) und in Harbor ein Tag gleichen Namens, der nicht aufgeräumt wird:

```dockerfile
FROM registry.gpu.services.dhbw.cloud/platform/notebook-pytorch:v1.0.0
RUN pip install --no-cache-dir transformers
```

Was sich zwischen den Versionen ändert, steht in [CHANGELOG.md](CHANGELOG.md).

## Aufbau

- `images.yaml` – die Images: Name in Harbor, Verzeichnis mit dem Dockerfile, Build-Argumente.
- `notebook/Dockerfile` – ein Dockerfile für alle drei Varianten; `BASE` wählt das Jupyter-Image, `XGBOOST` das passende Paket.

## Release

1. Änderung per Pull Request nach `main`, Eintrag in `CHANGELOG.md`.
2. Tag setzen: `git tag v1.1.0 && git push origin v1.1.0`.
3. In `aiaas-deployment` die Version in `ansible/vars/images.yaml` (`workspace_images.version`) hochsetzen und die Images bauen (`--tags images`), danach den Hub ausrollen (`--tags jupyterhub`).

Gebaut wird im Cluster mit BuildKit, nicht in GitHub: Die GPU-Images sind über 10 GB groß, und so braucht GitHub keine Zugangsdaten zu Harbor. Der Build legt das Image unter einem Hash des Inhalts ab (unverändert = kein Neubau) und gibt ihm den Versions-Tag dazu.
