#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$ROOT_DIR/.runtime/venv/bin/python"

cd "$ROOT_DIR"
export PYTHONUTF8=1

NEEDS_SETUP=0
if [ ! -x "$PYTHON_BIN" ]; then
  NEEDS_SETUP=1
fi

# The yt-dlp check is deliberate: an outdated copy still imports fine but
# fails every download, which used to look like a broken app to the user.
if [ "$NEEDS_SETUP" = "0" ]; then
  if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
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
) >= (2026, 5, 1)
PY
  then
    NEEDS_SETUP=1
  fi
fi

if [ "$NEEDS_SETUP" = "1" ]; then
  echo "Required tools are missing. Starting the automatic setup..."
  bash "$ROOT_DIR/setup_macos.sh"
fi

FFMPEG_DIR="$("$PYTHON_BIN" - <<'PY'
import os
import imageio_ffmpeg
print(os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe()))
PY
)"
export PATH="$ROOT_DIR/.runtime/deno:$FFMPEG_DIR:$PATH"

( sleep 3; open "http://localhost:8501" >/dev/null 2>&1 ) &

"$PYTHON_BIN" -m streamlit run "$ROOT_DIR/app.py" \
  --server.headless=true \
  --server.address=127.0.0.1 \
  --server.port=8501 \
  --browser.gatherUsageStats=false
