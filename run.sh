#!/bin/sh
set -eu

trap 'exit 130' INT
cd "$(dirname "$0")"
SOURCE_ROOT=$PWD
storage_mode=central
if [ -n "${HEBREW_LIVE_HOME:-}" ]; then
    storage_mode=custom
elif [ -e "$SOURCE_ROOT/.venv" ] || [ -e "$SOURCE_ROOT/.cache" ] || [ -e "$SOURCE_ROOT/models" ] || [ -e "$SOURCE_ROOT/logs" ] || [ -e "$SOURCE_ROOT/.local-settings" ]; then
    # Existing source installs keep their paths.  Moving recordings, models,
    # or a working environment implicitly would risk data loss and break an
    # offline-ready checkout.
    HEBREW_LIVE_HOME=$SOURCE_ROOT
    storage_mode=legacy-source
else
    HEBREW_LIVE_HOME="$HOME/Library/Application Support/Hebrew Live CLI"
fi
export HEBREW_LIVE_HOME
if [ "$storage_mode" = legacy-source ]; then
    HEBREW_LIVE_ENV="$SOURCE_ROOT/.venv"
    UV_CACHE_DIR="$SOURCE_ROOT/.cache/uv"
    HF_HOME="$SOURCE_ROOT/.cache/huggingface"
else
    HEBREW_LIVE_ENV="$HEBREW_LIVE_HOME/runtime/.venv"
    UV_CACHE_DIR="$HEBREW_LIVE_HOME/cache/uv"
    HF_HOME="$HEBREW_LIVE_HOME/cache/huggingface"
    export UV_PYTHON_INSTALL_DIR="$HEBREW_LIVE_HOME/runtime/python"
fi
export HEBREW_LIVE_ENV UV_PROJECT_ENVIRONMENT="$HEBREW_LIVE_ENV" UV_CACHE_DIR HF_HOME
export HF_HUB_DISABLE_TELEMETRY=1
export ORT_DISABLE_TELEMETRY=1

fail() {
    code="$1"
    shift
    printf '%s\n' "$*" >&2
    exit "$code"
}

preview_command=
preview_has_override=0
preview_skip_value=0
for argument in "$@"; do
    if [ "$preview_skip_value" -eq 1 ]; then
        preview_skip_value=0
        continue
    fi
    case "$argument" in
        --models|--log-dir)
            preview_has_override=1
            preview_skip_value=1
            ;;
        --models=*|--log-dir=*) preview_has_override=1 ;;
        storage|uninstall) [ -n "$preview_command" ] || preview_command=$argument ;;
    esac
done
if [ -n "$preview_command" ] && [ "$preview_has_override" -eq 1 ]; then
    preview_usage=$preview_command
    if [ "$preview_command" = uninstall ]; then preview_usage="uninstall --dry-run"; fi
    fail 64 "./run.sh $preview_command does not accept --models or --log-dir overrides because its preview runs before Python. Use HEBREW_LIVE_HOME for one managed root, or use the installed command form: he-ru --models PATH --log-dir PATH $preview_usage."
fi

show_storage() {
    printf '%s\n' \
        "Storage mode: $storage_mode" \
        "Managed data root: $HEBREW_LIVE_HOME" \
        "  models: $HEBREW_LIVE_HOME/models" \
        "  recordings and session logs: $HEBREW_LIVE_HOME/logs" \
        "  preferences: $HEBREW_LIVE_HOME/.local-settings" \
        "  uv cache: $UV_CACHE_DIR" \
        "  Hugging Face cache: $HF_HOME" \
        "  project environment: $HEBREW_LIVE_ENV" \
        "Source checkout: $SOURCE_ROOT" \
        "uv executable: $(command -v "${UV_BIN:-uv}" 2>/dev/null || printf 'not found')" \
        "Compatible --asr-model, --translation-model, and --vad-model paths are external user data and are never included in managed deletion."
    if [ "$storage_mode" = legacy-source ]; then
        printf '%s\n' "This existing source install remains in place. No automatic migration was attempted."
    fi
}

show_uninstall_preview() {
    show_storage
    printf '%s\n' \
        "" \
        "Dry run only; nothing was deleted."
    if [ "$storage_mode" = central ]; then
        printf '%s\n' \
            "Quit Hebrew Live CLI, verify that the dedicated managed data root contains no custom files, then move it to Trash in Finder." \
            "Review the source checkout separately and move it to Trash only if it contains no custom or untracked data you need."
    elif [ "$storage_mode" = custom ]; then
        printf '%s\n' \
            "Quit Hebrew Live CLI and review each listed app-owned subdirectory. The custom root may contain unrelated data; do not move the root as a whole unless you verified that it is dedicated to this app." \
            "Review the source checkout separately and move it to Trash only if it contains no custom or untracked data you need."
    else
        printf '%s\n' \
            "This legacy checkout mixes source and app-owned data. Review .venv, .cache, models, logs, and .local-settings individually, and preserve any custom or untracked files you need." \
            "Move the source checkout to Trash only after that review; doing so also removes every remaining file inside it."
    fi
    printf '%s\n' \
        "If the command was installed with 'uv tool install', run 'uv tool uninstall hebrew-live-cli' to remove that tool environment." \
        "Do not remove uv itself unless no other application uses it. Shared uv caches and Python installs outside the paths above are not owned by Hebrew Live CLI." \
        "External BYO model files are intentionally excluded and must be reviewed separately."
}

confirm() {
    prompt="$1"
    [ -t 0 ] && [ -t 1 ] || return 1
    printf '%s [y/N] ' "$prompt" >&2
    IFS= read -r answer || return 1
    case "$answer" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

require_native_apple_silicon() {
    system=$(uname -s 2>/dev/null || printf unknown)
    machine=$(uname -m 2>/dev/null || printf unknown)
    if [ "$system" != Darwin ]; then
        fail 64 "Hebrew Live CLI runtime requires macOS on Apple Silicon; detected $system/$machine. Linux, Windows, and Docker are not supported runtime targets."
    fi
    if [ "$machine" != arm64 ]; then
        if [ "$machine" = x86_64 ] && command -v sysctl >/dev/null 2>&1 && [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = 1 ]; then
            fail 64 "Hebrew Live CLI must run as native arm64. This terminal is running under Rosetta; reopen a native Apple Silicon terminal."
        fi
        fail 64 "Hebrew Live CLI runtime requires an Apple Silicon arm64 Mac; detected $machine. Intel Macs are not supported."
    fi
}

automatic=0
launcher_accepts_model_download=0
bootstrap_authorized=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --bootstrap)
            bootstrap_authorized=1
            shift
            ;;
        --accept-model-terms)
            launcher_accepts_model_download=1
            bootstrap_authorized=1
            shift
            ;;
        *) break ;;
    esac
done
if [ "$#" -eq 0 ]; then
    automatic=1
    set -- listen
fi

command_name=$1
if [ "$command_name" = storage ]; then
    [ "$#" -eq 1 ] || fail 64 "Usage: ./run.sh storage"
    show_storage
    exit 0
fi
if [ "$command_name" = uninstall ]; then
    [ "$#" -eq 2 ] && [ "$2" = --dry-run ] || fail 64 "Only a non-destructive preview is supported: ./run.sh uninstall --dry-run"
    show_uninstall_preview
    exit 0
fi
case "$command_name" in
    model-info|languages|report|-h|--help) ;;
    *) require_native_apple_silicon ;;
esac

UV_COMMAND=${UV_BIN:-uv}
if ! command -v "$UV_COMMAND" >/dev/null 2>&1; then
    fail 69 "uv is required. Install uv from https://docs.astral.sh/uv/, then run ./run.sh again. The launcher never pipes a remote installer into a shell or installs system software."
fi

accepted_setup=0
for argument in "$@"; do
    if [ "$argument" = --accept-model-terms ]; then accepted_setup=1; fi
done
if [ "$command_name" = setup ] && [ "$accepted_setup" -ne 1 ]; then
    fail 64 "setup requires --accept-model-terms after ./run.sh model-info. No dependencies or model weights were downloaded."
fi

environment_ready=0
if [ -x "$HEBREW_LIVE_ENV/bin/python" ] && "$UV_COMMAND" sync --frozen --offline --check >/dev/null 2>&1; then
    environment_ready=1
fi
if [ "$environment_ready" -ne 1 ]; then
    if [ -x "$HEBREW_LIVE_ENV/bin/python" ]; then
        environment_prompt="The existing .venv is incomplete or no longer matches pyproject.toml and uv.lock. Let uv repair the frozen Python 3.12 environment? This may use the network but does not download model weights."
        environment_error="The existing .venv is incomplete or stale. Run ./run.sh interactively, or add --bootstrap to authorize a frozen dependency repair."
        environment_action="Repairing the frozen Python 3.12 environment with uv. Network access may be used for packages; model weights are still separate."
    else
        environment_prompt="First run: let uv acquire Python 3.12 if needed and install the frozen dependencies? This uses the network but does not download model weights."
        environment_error="The locked Python environment is not prepared. Run ./run.sh interactively, or add --bootstrap to authorize dependency setup."
        environment_action="Preparing the frozen Python 3.12 environment with uv. Network access may be used for Python and packages; model weights are still separate."
    fi
    if [ "$bootstrap_authorized" -ne 1 ] && [ "$accepted_setup" -ne 1 ]; then
        if ! confirm "$environment_prompt"; then fail 69 "$environment_error"; fi
    fi
    printf '%s\n' "$environment_action" >&2
    if "$UV_COMMAND" sync --frozen --python 3.12; then :; else
        sync_code=$?
        printf '%s\n' "uv could not prepare the frozen environment. Fix the reported network, disk, Python, or package error and rerun with the same explicit bootstrap choice." >&2
        exit "$sync_code"
    fi
    if ! "$UV_COMMAND" sync --frozen --offline --check >/dev/null 2>&1; then
        fail 70 "uv finished but the environment still does not match the frozen project. No model download will be attempted."
    fi
fi

case "$command_name" in
    setup|doctor|listen|benchmark)
        if ! "$UV_COMMAND" run --offline --frozen --no-sync python -c 'import mlx.core as mx; print(mx.__file__)' >/dev/null; then
            fail 69 "The frozen environment passed uv's check, but the MLX package cannot be imported. Inspect the import error and recreate the local environment as described in Troubleshooting; Metal was not tested."
        fi
        if ! "$UV_COMMAND" run --offline --frozen --no-sync python -c 'import mlx.core as mx; assert mx.metal.is_available(); mx.set_default_device(mx.gpu); value=mx.array([0],dtype=mx.int32); mx.eval(value)' >/dev/null; then
            fail 69 "Apple Metal is unavailable to MLX. Run from a native arm64 macOS terminal with an Apple GPU; no model download or CPU/CUDA fallback will be attempted."
        fi
        ;;
esac

if [ "$automatic" -eq 1 ] && [ ! -f "$HEBREW_LIVE_HOME/models/manifest.json" ]; then
    "$UV_COMMAND" run --offline --frozen --no-sync he-ru model-info
    if [ "$launcher_accepts_model_download" -ne 1 ]; then
        if ! confirm "After reviewing the sources and linked model terms above, download the pinned default models (about 5.1 GB)?"; then
            fail 130 "Model setup cancelled. No model weights were downloaded. To use compatible local models instead, pass all three paths to ./run.sh listen."
        fi
    fi
    "$UV_COMMAND" run --frozen --no-sync he-ru setup --accept-model-terms
fi

if [ "$command_name" = setup ]; then
    exec "$UV_COMMAND" run --frozen --no-sync he-ru "$@"
fi
exec "$UV_COMMAND" run --offline --frozen --no-sync he-ru "$@"
