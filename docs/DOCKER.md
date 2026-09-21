# Docker feasibility and native-runtime decision

Status: **native macOS selected**, checked 2026-09-20.

The public-alpha workflow is `./run.sh` on a native Apple Silicon Mac. Microphone input,
MLX/Metal ASR and translation, the loopback API, and the embedded browser UI stay on
macOS. Docker is not a supported runtime and the distribution intentionally has no
`Dockerfile` or Compose file. A container that only renders the UI or passes synthetic
tests is not a working Hebrew Live CLI translator.

## Why the current application cannot simply move into Docker Desktop on macOS

The supported product runs on Apple Silicon macOS. It records the microphone through
`sounddevice`, performs ASR with MLX Whisper, performs translation with MLX-LM, and
serves an authenticated loopback UI. These parts cross two host boundaries in Docker
Desktop:

1. Docker Desktop runs Linux containers in a Linux virtual machine. It does not expose
   the Mac's Metal device to those containers. Docker's documented local GPU support
   is limited to NVIDIA GPU paravirtualization on Windows with WSL2.
2. PortAudio uses Core Audio on macOS and ALSA or OSS on Linux. The Mac microphone is
   therefore not an automatic Linux `/dev/snd` device inside the Docker VM.

MLX now publishes separate CPU-only and CUDA backends for Linux. That makes a Linux
port possible to investigate, but it does not preserve the current Metal runtime or
establish that the two selected models can translate live at an acceptable latency.
The current lock also installs `mlx-metal` only on Darwin; it does not select
`mlx-cpu` for Linux. A Linux container would be a new inference target with its own
dependency declaration, lock resolution, compatibility checks, benchmarks, and
support statement.

The HTTP boundary also needs design work. `BrowserUI` currently binds to
`127.0.0.1` on a random port, creates a random URL token, and opens the browser from
the same host process. A Docker-published port cannot reach a service bound only to
the container's loopback interface, and a browser opened inside the Linux container
is not the Mac browser. Expanding the bind address without preserving the Host,
Origin, token, and local-only guarantees would be a security regression.

Primary references:

- [Docker Desktop virtual machine managers](https://docs.docker.com/desktop/features/vmm/)
- [Docker Desktop GPU support](https://docs.docker.com/desktop/features/gpu/)
- [Docker Desktop for Mac security boundary](https://docs.docker.com/desktop/setup/install/mac-permission-requirements/)
- [MLX installation and Linux backends](https://ml-explore.github.io/mlx/build/html/install.html)
- [PortAudio host APIs](https://portaudio.com/docs/v19-doxydocs/api_overview.html)

## Architecture choices

| Choice | What runs on macOS | What runs in Docker | Main consequence |
| --- | --- | --- | --- |
| **Native one-command launcher — selected** | Microphone, MLX/Metal inference, API, and UI | Nothing required for runtime | Preserves the qualified product boundary and provides `./run.sh`; this is not a Docker runtime. |
| Hybrid | Microphone and MLX/Metal inference runner | UI/control service, and possibly packaging helpers | Needs a new authenticated host-to-container protocol, lifecycle handling, and privacy review. A shell launcher can start both sides; `docker compose up` alone cannot start the native runner. |
| Full Linux backend | Nothing except the browser and Docker Desktop | Microphone input or file input, MLX CPU/CUDA inference, API, and UI | Requires a new Linux backend target. On a Mac there is no supported local Metal or NVIDIA path, and live microphone capture still needs a separate bridge. |

The full Linux option can be useful on a native Linux host with an actual audio device
and a qualified CPU or NVIDIA configuration. That is a different support target from
Docker Desktop on the current Mac.

## Accepted native workflow

The launcher includes dependency bootstrap after an explicit network prompt, then
requires a second explicit confirmation after printing the model inventory and linked
terms. `./run.sh --accept-model-terms` is the documented noninteractive one-command
form for a user who has already reviewed those links. Model weights remain separate
user downloads and are never part of the code archive, sdist, wheel, or an image.

Prepared dependencies must pass `uv sync --frozen --offline --check`; a partial `.venv`
from an interrupted sync does not qualify. Repair requires a new interactive response
or `--bootstrap`, which covers dependencies only and does not acknowledge model terms.

The launcher rejects non-macOS, Intel, and Rosetta execution before bootstrap or model
download. After the frozen MLX dependencies are present, it evaluates a small MLX array
to prove that Metal is usable before model setup or inference. ASR and translation have
no CPU, CUDA, Linux, or cloud fallback. Silero VAD and orchestration still use the CPU.

Models, settings, sessions, audio, transcripts, and logs remain in the documented
native data root. Compatible explicit MLX Whisper, MLX-LM, and Silero VAD paths remain
available and skip managed model download without changing the supported platform.

## Requirements if Docker support is reconsidered

## Requirements for any accepted Docker design

The runtime must publish only a high, unprivileged port on host `127.0.0.1`. It must
not mount the Docker socket, host home directory, SSH directory, cloud credentials,
or unrelated secrets. The container must run as a non-root user with dropped
capabilities and `no-new-privileges`; privileged mode is out of scope. Only explicit
model and application-data volumes may persist.

Runtime inference must remain offline. A separate, explicit model-setup command may
use the network after it prints the pinned model sources and terms and receives
`--accept-model-terms`. Compatible bring-your-own paths must remain read-only inputs
outside the managed model directory, with `doctor` performing the same layout and
warmup checks as the native workflow.

Any future Docker runbook must cover:

- Docker Desktop and resource prerequisites;
- model terms, initial setup, disk use, and compatible bring-your-own paths;
- explicit model and private-data volume locations;
- local port and tokenized browser URL;
- microphone selection or the approved host audio bridge;
- start, stop, status, and bounded log inspection commands;
- updates, recovery after an interrupted setup, and data removal as separate actions.

## Future Docker verification gate

A Docker workflow is supportable only after all of these checks pass on the selected
target:

1. Compose configuration validation and a reproducible image build from the public
   source export.
2. Dependency resolution from the frozen lock for the selected OS, architecture, and
   MLX backend.
3. `model-info` without downloads, followed by explicit setup with the original model
   terms and integrity manifest.
4. `doctor` with real model loading, inference warmup, and Silero VAD. File existence
   or synthetic fixtures do not satisfy this check.
5. A real same-audio benchmark compared with the native baseline, including output
   quality, first-caption latency, sustained lag, peak memory, and shutdown behavior.
6. Live microphone capture through the approved path, if `listen` is in scope.
7. Browser access from macOS through host `127.0.0.1`, including Host, Origin, token,
   action, archive, reconnect, and shutdown checks.
8. Restart and persistence checks proving that models and private session data use
   only the documented volumes.
9. A clean public-export scan proving that the Docker assets are present while models,
   secrets, audio, transcripts, logs, caches, and local paths are absent.
10. The existing backend and frontend suites plus an installed-package smoke test in
    the final image.

At the time of the feasibility check, Docker CLI 29.8.0 and Docker Compose 5.5.1 were
installed on the development Mac, but the Docker daemon was not running. No image
build, container smoke test, Linux model warmup, inference, or microphone test was
performed, and none is claimed by the selected native implementation.
