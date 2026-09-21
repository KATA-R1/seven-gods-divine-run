#!/usr/bin/env bash
set -euo pipefail

NO_SHORTCUT="${1:-}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
VENV_DIR="$RUNTIME_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python"

cd "$ROOT_DIR"
mkdir -p "$RUNTIME_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 が見つかりません。"
  echo "先に https://www.python.org/downloads/macos/ からPython 3をインストールしてください。"
  echo "Homebrewを使っている場合は brew install python でも構いません。"
  exit 1
fi

# The app uses tomllib, which requires Python 3.11+. An older python3 would
# install everything fine and then crash at first launch.
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11以上が必要です（現在: $(python3 --version)）。"
  echo "https://www.python.org/downloads/macos/ から新しいPythonをインストールしてください。"
  exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Creating Python virtual environment ..."
  python3 -m venv "$VENV_DIR"
fi

echo "Python: $("$PYTHON_BIN" --version)"

echo "Installing Python packages ..."
"$PYTHON_BIN" -m pip install \
  --disable-pip-version-check \
  --quiet \
  --upgrade pip
# No blanket --upgrade here: only yt-dlp needs to chase upstream (below).
# Upgrading streamlit/pandas/openai wholesale would risk breaking the UI on
# every setup run; requirements.txt floors pull them up only when needed.
"$PYTHON_BIN" -m pip install \
  --disable-pip-version-check \
  --quiet \
  -r "$ROOT_DIR/requirements.txt"

# YouTube changes its player frequently, so always pull the newest yt-dlp
# instead of leaving an already-satisfied requirement pin in place.
echo "Updating yt-dlp ..."
"$PYTHON_BIN" -m pip install \
  --disable-pip-version-check \
  --quiet \
  --upgrade \
  yt-dlp || echo "Warning: could not update yt-dlp. Downloads may fail."

# The Windows setup installs Deno, which yt-dlp uses to solve YouTube's
# JavaScript challenge. Without it macOS users hit HTTP 403 on some videos.
DENO_DIR="$RUNTIME_DIR/deno"
DENO_BIN="$DENO_DIR/deno"
if [ ! -x "$DENO_BIN" ]; then
  case "$(uname -m)" in
    arm64) DENO_TARGET="aarch64-apple-darwin" ;;
    *) DENO_TARGET="x86_64-apple-darwin" ;;
  esac
  DENO_URL="https://github.com/denoland/deno/releases/latest/download/deno-$DENO_TARGET.zip"
  echo "Downloading portable Deno ..."
  mkdir -p "$DENO_DIR"
  if curl -fsSL "$DENO_URL" -o "$DENO_DIR/deno.zip"; then
    unzip -oq "$DENO_DIR/deno.zip" -d "$DENO_DIR"
    rm -f "$DENO_DIR/deno.zip"
    chmod +x "$DENO_BIN" 2>/dev/null || true
  else
    echo "Warning: could not download Deno. Some videos may fail with HTTP 403."
  fi
fi

echo "Verifying dependencies ..."
"$PYTHON_BIN" - <<'PY'
import imageio_ffmpeg
import streamlit
import pandas
import yt_dlp
import googleapiclient
import google_auth_oauthlib
import openai
assert tuple(map(int, openai.__version__.split('.')[:2])) >= (2, 44)
assert tuple(
    int(''.join(filter(str.isdigit, part)) or 0)
    for part in yt_dlp.version.__version__.split('.')[:3]
) >= (2026, 5, 1), f"yt-dlp is outdated: {yt_dlp.version.__version__}"

print("ffmpeg:", imageio_ffmpeg.get_ffmpeg_exe())
print("yt-dlp:", yt_dlp.version.__version__)
PY

if [ "$NO_SHORTCUT" != "--no-shortcut" ]; then
  DESKTOP_DIR="$HOME/Desktop"
  if [ -d "$DESKTOP_DIR" ]; then
    SHORTCUT_PATH="$DESKTOP_DIR/YouTube Search Downloader.command"
    cat > "$SHORTCUT_PATH" <<EOF
#!/usr/bin/env bash
cd "$ROOT_DIR"
exec "$ROOT_DIR/start_app_macos.command"
EOF
    chmod +x "$SHORTCUT_PATH"
    echo "Desktop launcher created: $SHORTCUT_PATH"
  fi
fi

echo ""
echo "Setup completed successfully."
