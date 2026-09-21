from __future__ import annotations

import hashlib
import html
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tomllib
import urllib.request
import base64
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import streamlit as st
import yt_dlp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


# All settings/credential paths are resolved against the folder that holds
# app.py, not the process working directory. Launching the app from another
# folder used to point the app at a different (empty) .streamlit folder, which
# showed up to users as "keys were saved but the app says they are not set".
APP_ROOT = Path(__file__).resolve().parent

# Platform-appropriate re-setup instruction for user-facing error messages;
# telling macOS users to run setup.ps1 was a dead end.
SETUP_COMMAND_HINT = (
    "setup.ps1 または start_app.bat"
    if os.name == "nt"
    else "setup_macos.sh"
)


def _ensure_runtime_tools_on_path() -> None:
    # The launchers (start_app.bat / start_app_macos.command) put the bundled
    # ffmpeg and Deno on PATH, but yt-dlp locates Deno via PATH lookup, so a
    # direct `streamlit run app.py` used to lose Deno and fail some videos
    # with HTTP 403. Injecting the folders here makes every launch method work.
    candidates = [
        APP_ROOT / ".runtime" / "ffmpeg" / "bin",
        APP_ROOT / ".runtime" / "deno",
    ]
    existing = os.environ.get("PATH", "")
    parts = existing.split(os.pathsep) if existing else []
    prepend = [
        str(candidate)
        for candidate in candidates
        if candidate.is_dir() and str(candidate) not in parts
    ]
    if prepend:
        os.environ["PATH"] = os.pathsep.join([*prepend, existing])


_ensure_runtime_tools_on_path()

MODE_OPTIONS = {
    "再生回数順": "viewCount",
    "人気順（関連度）": "relevance",
    "バズり度順": "buzzRatio",
}
MODE_SETTINGS = {
    "viewCount": {"order": "viewCount", "limit": 100},
    "relevance": {"order": "relevance", "limit": 100},
    "buzzRatio": {"order": "viewCount", "limit": 300},
}
MIN_VIDEO_DURATION_SECONDS = 3 * 60
YOUTUBE_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
SUBTITLE_LANGUAGE_OPTIONS = {
    "日本語のみ": "ja",
    "日本語 → 英語": "ja,en",
    "英語のみ": "en",
}
VIDEO_LANGUAGE_OPTIONS = ["日本語動画", "英語動画"]
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-transcribe-diarize"
AUDIO_CHUNK_SECONDS = 10 * 60
TIMECODE_RE = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s+-->\s+"
    r"\d{1,2}:\d{2}:\d{2}[.,]\d{3}"
)
TIMED_SUBTITLE_LINE_RE = re.compile(
    r"^\s*(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})(?:\s+.*)?$"
)
VTT_TIMESTAMP_TAG_RE = re.compile(r"<\d{1,2}:\d{2}:\d{2}\.\d{3}>")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HTML_TAG_RE = re.compile(r"<[^>]+>")
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
VIDEO_ID_IN_FILENAME_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
DOWNLOADED_VIDEO_IDS_FILE = ".downloaded_video_ids.json"
UPLOAD_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
YOUTUBE_UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube"]
# yt-dlp must be kept close to current: YouTube changes its player often and an
# outdated copy fails every download with 403 / "format not available".
MIN_RECOMMENDED_YTDLP = "2026.05.01"
DEFAULT_UPLOAD_CLIENT_SECRETS = ".streamlit/client_secret.json"
DEFAULT_UPLOAD_TOKEN = ".streamlit/youtube_upload_token.json"
SETTINGS_PROFILES_FILE = ".streamlit/settings_profiles.json"
SETTINGS_PROFILES_DIR = ".streamlit/profiles"
PRIVACY_OPTIONS = {
    "非公開": "private",
    "限定公開": "unlisted",
    "公開": "public",
}
SCHEDULE_PRIVACY_LABEL = "予約公開"
SCHEDULE_TIMEZONE_OPTIONS = {
    "日本時間": 9,
    "世界標準時": 0,
    "米国東部時間": -5,
    "米国太平洋時間": -8,
    "中央ヨーロッパ時間": 1,
}
APP_PAGES = [
    "アカウント設定",
    "YouTube検索＆ダウンロード",
    "YouTubeアップロード",
]
APP_PAGE_SLUGS = {
    "アカウント設定": "settings",
    "YouTube検索＆ダウンロード": "search",
    "YouTubeアップロード": "upload",
}
APP_PAGE_BY_SLUG = {slug: page for page, slug in APP_PAGE_SLUGS.items()}


def streamlit_config_dir() -> Path:
    return APP_ROOT / ".streamlit"


def secrets_file_path() -> Path:
    return streamlit_config_dir() / "secrets.toml"


def default_client_secret_path() -> Path:
    return APP_ROOT / DEFAULT_UPLOAD_CLIENT_SECRETS


def default_upload_token_path() -> Path:
    return APP_ROOT / DEFAULT_UPLOAD_TOKEN


def settings_profiles_file_path() -> Path:
    return APP_ROOT / SETTINGS_PROFILES_FILE


def settings_profiles_dir() -> Path:
    return APP_ROOT / SETTINGS_PROFILES_DIR


def mask_secret(value: str) -> str:
    value = value.strip()
    if not value:
        return "未設定"
    if len(value) <= 8:
        return "設定済み"
    return f"{value[:4]}...{value[-4:]}"


def toml_quote(value: str) -> str:
    return json.dumps(value.strip(), ensure_ascii=False)


def read_local_secret_value(key: str) -> str:
    path = secrets_file_path()
    if not path.is_file():
        return ""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    value = data.get(key, "")
    return str(value).strip() if value is not None else ""


def write_local_secret_value(key: str, value: str) -> None:
    streamlit_config_dir().mkdir(parents=True, exist_ok=True)
    path = secrets_file_path()
    line = f"{key} = {toml_quote(value)}"
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replaced = False
    updated_lines: list[str] = []
    for existing_line in lines:
        if pattern.match(existing_line):
            updated_lines.append(line)
            replaced = True
        else:
            updated_lines.append(existing_line)
    if not replaced:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(line)
    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def make_profile_id(name: str) -> str:
    cleaned = INVALID_FILENAME_CHARS_RE.sub("_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    if not cleaned:
        cleaned = "profile"
    digest = hashlib.md5(name.strip().encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:40]}_{digest}"


def profile_client_secret_path(profile_id: str) -> Path:
    return settings_profiles_dir() / profile_id / "client_secret.json"


def profile_token_path(profile_id: str) -> Path:
    return settings_profiles_dir() / profile_id / "youtube_upload_token.json"


def legacy_default_profile() -> dict[str, Any]:
    return {
        "active_profile": "default",
        "profiles": {
            "default": {
                "name": "既定",
                "youtube_api_key": read_local_secret_value("YOUTUBE_API_KEY"),
                "openai_api_key": read_local_secret_value("OPENAI_API_KEY"),
                "client_secret_path": DEFAULT_UPLOAD_CLIENT_SECRETS,
                "token_path": DEFAULT_UPLOAD_TOKEN,
            }
        },
    }


def load_settings_profiles() -> dict[str, Any]:
    path = settings_profiles_file_path()
    if not path.is_file():
        return legacy_default_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return legacy_default_profile()
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return legacy_default_profile()
    active_profile = str(data.get("active_profile") or next(iter(profiles)))
    if active_profile not in profiles:
        active_profile = next(iter(profiles))
    return {"active_profile": active_profile, "profiles": profiles}


def save_settings_profiles(config: dict[str, Any]) -> None:
    streamlit_config_dir().mkdir(parents=True, exist_ok=True)
    settings_profiles_dir().mkdir(parents=True, exist_ok=True)
    settings_profiles_file_path().write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def current_settings_profile() -> tuple[str, dict[str, Any], dict[str, Any]]:
    config = load_settings_profiles()
    profile_id = str(config["active_profile"])
    profile = dict(config["profiles"][profile_id])
    return profile_id, profile, config


def configured_profile_value(key: str) -> tuple[str, str]:
    profile_id, profile, _config = current_settings_profile()
    value = str(profile.get(key, "")).strip()
    if value:
        return value, f"設定プロファイル: {profile.get('name', profile_id)}"
    return "", ""


def profile_path_value(profile: dict[str, Any], key: str, fallback: str) -> str:
    return str(profile.get(key) or fallback)


def resolve_profile_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = APP_ROOT / path
    return path


def save_oauth_client_secret(uploaded_bytes: bytes, target_path: Path | None = None) -> None:
    try:
        data = json.loads(uploaded_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("OAuthクライアントJSONを読み取れませんでした。") from exc
    if not isinstance(data, dict) or not any(
        key in data for key in ("installed", "web")
    ):
        raise ValueError(
            "Google Cloudで作成したOAuthクライアントJSONではない可能性があります。"
        )
    # Login uses InstalledAppFlow.run_local_server(), which only works with a
    # "desktop app" client. A "web application" client saved fine but then
    # failed every login with redirect_uri_mismatch, so reject it up front.
    if "installed" not in data and "web" in data:
        raise ValueError(
            "これは「ウェブアプリケーション」用のJSONのため、このツールでは使えません。\n"
            "Google Cloud Console → APIとサービス → 認証情報 → OAuthクライアントIDを作成 で、"
            "アプリケーションの種類を「デスクトップアプリ」にして作り直し、"
            "そのJSONをアップロードしてください。"
        )
    target = target_path or default_client_secret_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(uploaded_bytes)


def describe_oauth_login_error(exc: Exception) -> str:
    detail = str(exc)
    lowered = detail.lower()
    if "redirect_uri_mismatch" in lowered:
        return (
            "OAuthクライアントの種類が「デスクトップアプリ」になっているか確認してください。"
            "「ウェブアプリケーション」では認証できません。"
        )
    if "access_denied" in lowered or "has not completed" in lowered:
        return (
            "OAuth同意画面が「テスト中」で、テストユーザーに未登録の可能性があります。"
            "Google Cloud Console → OAuth同意画面 → テストユーザー に、"
            "投稿に使うGoogleアカウントを追加してください。"
        )
    if "youtube.googleapis.com" in lowered or "has not been used" in lowered:
        return (
            "そのGoogle Cloudプロジェクトで YouTube Data API v3 が有効化されていません。"
            "APIとサービス → ライブラリ から有効化してください。"
        )
    if "address already in use" in lowered or "winerror 10013" in lowered:
        return (
            "認証用のローカルサーバーを起動できませんでした。"
            "セキュリティソフトやファイアウォールの設定を確認してください。"
        )
    return (
        "ブラウザが開かない場合は、既定のブラウザ設定とセキュリティソフトを確認してください。"
    )


def chunks(values: list[str], size: int = 50) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def describe_api_error(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    details = f"{exc} {content}"
    if status == 403 or "quotaExceeded" in details or "dailyLimitExceeded" in details:
        return (
            "YouTube Data API が HTTP 403 を返しました。本日のAPI利用枠を"
            "使い切った可能性があります。"
        )
    return f"YouTube Data API エラー: {exc}"


def best_thumbnail(snippet: dict[str, Any]) -> str:
    thumbnails = snippet.get("thumbnails", {})
    for name in ("maxres", "standard", "high", "medium", "default"):
        url = thumbnails.get(name, {}).get("url")
        if url:
            return str(url)
    return ""


def format_published_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y/%m/%d %H:%M")
    except (TypeError, ValueError):
        return value


def parse_youtube_duration(value: str) -> int:
    match = YOUTUBE_DURATION_RE.match(value)
    if not match:
        return 0
    parts = {
        name: int(match.group(name) or 0)
        for name in ("days", "hours", "minutes", "seconds")
    }
    return (
        parts["days"] * 24 * 60 * 60
        + parts["hours"] * 60 * 60
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def safe_file_stem(value: str, limit: int = 120) -> str:
    cleaned = INVALID_FILENAME_CHARS_RE.sub("_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "video")[:limit].rstrip(" .")


def resolve_output_dir(output_dir_value: str) -> Path:
    output_dir = Path(output_dir_value).expanduser()
    if not output_dir.is_absolute():
        output_dir = APP_ROOT / output_dir
    return output_dir


def video_workspace_dir(output_dir: Path, video: dict[str, Any]) -> Path:
    return output_dir / f"{safe_file_stem(str(video['title']))} [{video['videoId']}]"


def write_upload_metadata(
    video_dir: Path,
    video: dict[str, Any],
    *,
    status: str = "downloaded",
) -> None:
    metadata_path = video_dir / "upload_metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            metadata = {}
    metadata.update(
        {
            "sourceVideoId": str(video.get("videoId", "")),
            "sourceUrl": str(video.get("url", "")),
            "sourceTitle": str(video.get("title", "")),
            "channelTitle": str(video.get("channelTitle", "")),
            "publishedAt": str(video.get("publishedAt", "")),
            "durationText": str(video.get("durationText", "")),
            "status": status,
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
        }
    )
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_downloaded_video_ids(output_dir: Path) -> set[str]:
    video_ids: set[str] = set()
    index_path = output_dir / DOWNLOADED_VIDEO_IDS_FILE
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                video_ids.update(str(video_id) for video_id in data)
            elif isinstance(data, list):
                video_ids.update(str(video_id) for video_id in data)
        except (OSError, json.JSONDecodeError):
            pass
    if output_dir.exists():
        for file_path in output_dir.rglob("*"):
            if not file_path.is_file() and not file_path.is_dir():
                continue
            match = VIDEO_ID_IN_FILENAME_RE.search(file_path.name)
            if match:
                video_ids.add(match.group(1))
            if file_path.name == "upload_metadata.json":
                try:
                    metadata = json.loads(file_path.read_text(encoding="utf-8"))
                    video_id = str(metadata.get("sourceVideoId", "")).strip()
                    if video_id:
                        video_ids.add(video_id)
                except (OSError, json.JSONDecodeError, AttributeError):
                    pass
    return video_ids


def record_downloaded_video(output_dir: Path, video: dict[str, Any]) -> None:
    index_path = output_dir / DOWNLOADED_VIDEO_IDS_FILE
    data: dict[str, Any] = {}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
            elif isinstance(loaded, list):
                data = {str(video_id): {} for video_id in loaded}
        except (OSError, json.JSONDecodeError):
            data = {}
    video_id = str(video.get("videoId", "")).strip()
    if not video_id:
        return
    data[video_id] = {
        "title": str(video.get("title", "")),
        "url": str(video.get("url", "")),
        "folder": video_workspace_dir(output_dir, video).name,
        "downloadedAt": datetime.now().isoformat(timespec="seconds"),
    }
    index_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="replace")


def markdown_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in markdown.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def clean_markdown_list_item(line: str) -> str:
    cleaned = re.sub(r"^\s*(?:[-*]\s+|\d+[\).\s]+)", "", line).strip()
    cleaned = cleaned.strip("「」\"'` ")
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    return cleaned.strip()


def extract_title_candidates(summary_text: str) -> list[str]:
    sections = markdown_sections(summary_text)
    title_section = ""
    for heading, content in sections.items():
        if "タイトル" in heading:
            title_section = content
            break
    candidates: list[str] = []
    for line in title_section.splitlines():
        candidate = clean_markdown_list_item(line)
        if not candidate:
            continue
        if len(candidate) > 100:
            candidate = candidate[:100].rstrip()
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates[:20]


def extract_summary_description(summary_text: str) -> str:
    sections = markdown_sections(summary_text)
    parts: list[str] = []
    for heading in ("3行要約", "詳細要約", "重要ポイント"):
        content = sections.get(heading, "").strip()
        if content:
            parts.append(f"■ {heading}\n{content}")
    if not parts and summary_text.strip():
        parts.append(summary_text.strip()[:2500])
    return "\n\n".join(parts).strip()


def extract_hashtags(summary_text: str, title: str) -> str:
    source = f"{title}\n{summary_text}"
    hashtags = re.findall(r"#[\wぁ-んァ-ヶ一-龥ー]+", source)
    if hashtags:
        unique = []
        for tag in hashtags:
            if tag not in unique:
                unique.append(tag)
        return " ".join(unique[:12])
    keyword_map = {
        "FX": "#FX",
        "トレード": "#トレード",
        "スキャルピング": "#スキャルピング",
        "投資": "#投資",
        "株": "#株式投資",
        "YouTube": "#YouTube",
    }
    inferred = [
        tag for keyword, tag in keyword_map.items() if keyword.lower() in source.lower()
    ]
    return " ".join(dict.fromkeys(inferred))


def extract_video_id_from_path(path: Path) -> str:
    match = VIDEO_ID_IN_FILENAME_RE.search(path.name)
    return match.group(1) if match else ""


def detect_upload_items(output_dir: Path) -> list[dict[str, Any]]:
    if not output_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for folder in sorted([path for path in output_dir.iterdir() if path.is_dir()]):
        video_files = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in UPLOAD_VIDEO_EXTENSIONS
        ]
        if not video_files:
            continue
        metadata_path = folder / "upload_metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    metadata = loaded
            except (OSError, json.JSONDecodeError):
                metadata = {}
        video_id = str(metadata.get("sourceVideoId") or extract_video_id_from_path(folder))
        title = str(metadata.get("sourceTitle") or folder.name)
        preferred_video = next(
            (path for path in video_files if path.name == "video_ja_subtitled.mp4"),
            None,
        ) or next(
            (path for path in video_files if path.name == "video.mkv"),
            video_files[0],
        )
        item = {
            "key": str(folder.resolve()),
            "kind": "folder",
            "folder": folder,
            "video_path": preferred_video,
            "summary_path": folder / "summary.md",
            "thumbnail_path": folder / "thumbnail.png",
            "transcript_path": folder / "transcript.txt",
            "metadata_path": metadata_path,
            "source_video_id": video_id,
            "title": title,
            "uploaded_video_id": str(metadata.get("uploadedVideoId", "")),
        }
        items.append(item)
        seen_keys.add(item["key"])

    id_files: dict[str, dict[str, Path]] = {}
    for file_path in output_dir.iterdir():
        if not file_path.is_file():
            continue
        video_id = extract_video_id_from_path(file_path)
        if not video_id:
            continue
        slot = id_files.setdefault(video_id, {})
        suffixes = "".join(file_path.suffixes).lower()
        if file_path.suffix.lower() in UPLOAD_VIDEO_EXTENSIONS:
            slot["video"] = file_path
        elif suffixes.endswith(".summary.md"):
            slot["summary"] = file_path
        elif suffixes.endswith(".thumbnail.png") or suffixes.endswith(".thumbnail.jpg"):
            slot["thumbnail"] = file_path
        elif suffixes.endswith(".transcript.txt"):
            slot["transcript"] = file_path

    root_videos = [
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix.lower() in UPLOAD_VIDEO_EXTENSIONS
    ]
    for video_id, files in id_files.items():
        video_path = files.get("video")
        if video_path is None:
            summary_path = files.get("summary")
            if summary_path:
                base = summary_path.name.split(f" [{video_id}]")[0]
                matches = [
                    path
                    for path in root_videos
                    if path.stem == base or path.stem.startswith(base)
                ]
                if matches:
                    video_path = matches[0]
        if video_path is None:
            continue
        key = str(video_path.resolve())
        if key in seen_keys:
            continue
        # Missing companion files default to their would-be path (which does
        # not exist yet). The old sentinel `output_dir / ""` collapsed to the
        # output directory itself, which "exists", so missing thumbnails were
        # treated as real files and crashed uploads and regeneration.
        legacy_base = (
            video_path.stem
            if f"[{video_id}]" in video_path.stem
            else f"{video_path.stem} [{video_id}]"
        )
        items.append(
            {
                "key": key,
                "kind": "legacy",
                "folder": output_dir,
                "video_path": video_path,
                "summary_path": files.get(
                    "summary", output_dir / f"{legacy_base}.summary.md"
                ),
                "thumbnail_path": files.get(
                    "thumbnail", output_dir / f"{legacy_base}.thumbnail.png"
                ),
                "transcript_path": files.get(
                    "transcript", output_dir / f"{legacy_base}.transcript.txt"
                ),
                "metadata_path": output_dir / f"{video_path.stem} [{video_id}].upload_metadata.json",
                "source_video_id": video_id,
                "title": video_path.stem,
                "uploaded_video_id": "",
            }
        )
    return items


def save_upload_metadata_for_item(
    item: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    metadata_path = Path(item["metadata_path"])
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            metadata = {}
    metadata.update(updates)
    metadata["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def upload_template_path() -> Path:
    return APP_ROOT / ".streamlit" / "upload_description_template.txt"


def load_upload_template() -> str:
    path = upload_template_path()
    if not path.exists():
        return ""
    return read_text_file(path)


def save_upload_template(text: str) -> None:
    path = upload_template_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_description(
    generated_summary: str,
    fixed_text: str,
    hashtags: str,
    *,
    include_summary: bool = True,
) -> str:
    parts = []
    if fixed_text.strip():
        parts.append(fixed_text.strip())
    if include_summary and generated_summary.strip():
        parts.append(generated_summary.strip())
    if hashtags.strip():
        parts.append(hashtags.strip())
    return "\n\n".join(parts).strip()[:5000]


def scheduled_publish_iso(
    schedule_date: date,
    schedule_time: time,
    timezone_label: str,
) -> str:
    offset_hours = SCHEDULE_TIMEZONE_OPTIONS.get(timezone_label, 9)
    local_timezone = timezone(timedelta(hours=offset_hours))
    scheduled_local = datetime.combine(schedule_date, schedule_time).replace(
        tzinfo=local_timezone
    )
    return scheduled_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_future_publish_time(publish_at_iso: str) -> bool:
    publish_at = datetime.fromisoformat(publish_at_iso.replace("Z", "+00:00"))
    return publish_at > datetime.now(timezone.utc) + timedelta(minutes=2)


def parse_tags(value: str) -> list[str]:
    tags = [
        tag.strip().lstrip("#")
        for tag in re.split(r"[,、\n]", value)
        if tag.strip()
    ]
    unique: list[str] = []
    for tag in tags:
        if tag and tag not in unique:
            unique.append(tag[:500])
    return unique[:30]


def youtube_upload_service(client_secret_path: Path, token_path: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            f"YouTubeアップロード用パッケージが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    credentials = None
    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(token_path),
                YOUTUBE_UPLOAD_SCOPES,
            )
        except Exception:
            # Corrupt or hand-edited token file: treat as not logged in.
            credentials = None
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:
            # Refresh tokens get revoked or expire (consent screens in
            # "testing" mode expire them after 7 days). Fall through to a
            # fresh browser login instead of crashing every upload until
            # the user manually deletes the token file.
            credentials = None
    if not credentials or not credentials.valid:
        if not client_secret_path.exists():
            raise FileNotFoundError(
                f"OAuthクライアントJSONが見つかりません: {client_secret_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_path),
            YOUTUBE_UPLOAD_SCOPES,
        )
        credentials = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def prepare_thumbnail_for_upload(thumbnail_path: Path) -> Path | None:
    # is_file (not exists) so a directory can never be picked up as an image.
    if not thumbnail_path.is_file():
        return None
    if thumbnail_path.stat().st_size <= 2_000_000:
        return thumbnail_path
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            f"サムネイル圧縮用のPillowが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    compressed_path = thumbnail_path.with_name("thumbnail_upload.jpg")
    with Image.open(thumbnail_path) as image:
        image = image.convert("RGB")
        for quality in (92, 86, 80, 74, 68, 62, 56, 50):
            image.save(
                compressed_path,
                format="JPEG",
                quality=quality,
                optimize=True,
            )
            if compressed_path.stat().st_size <= 2_000_000:
                return compressed_path
    raise RuntimeError("サムネイルを2MB以下に圧縮できませんでした。")


def upload_video_to_youtube(
    item: dict[str, Any],
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    publish_at: str | None,
    client_secret_path: Path,
    token_path: Path,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    youtube = youtube_upload_service(client_secret_path, token_path)
    video_path = Path(item["video_path"])
    if not video_path.exists():
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

    mimetype = mimetypes.guess_type(video_path.name)[0] or "video/*"
    status_body: dict[str, Any] = {
        "privacyStatus": "private" if publish_at else privacy_status,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        status_body["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title.strip()[:100],
            "description": description.strip()[:5000],
            "tags": tags,
            "categoryId": "22",
        },
        "status": status_body,
    }
    media = MediaFileUpload(
        str(video_path),
        mimetype=mimetype,
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            progress_callback(float(status.progress()), "動画をアップロード中...")
    uploaded_video_id = response["id"]
    uploaded_url = f"https://www.youtube.com/watch?v={uploaded_video_id}"

    # The video exists on YouTube from this point on. Persist the ID before
    # doing anything else so a later step (e.g. thumbnail) failing can never
    # lose it — that used to make users re-upload the same video twice.
    save_upload_metadata_for_item(
        item,
        {
            "uploadedVideoId": uploaded_video_id,
            "uploadedUrl": uploaded_url,
            "uploadedAt": datetime.now().isoformat(timespec="seconds"),
        },
    )

    thumbnail_detail = "サムネイルなし"
    thumbnail_error = ""
    try:
        thumbnail_path = prepare_thumbnail_for_upload(Path(item["thumbnail_path"]))
        if thumbnail_path:
            youtube.thumbnails().set(
                videoId=uploaded_video_id,
                media_body=MediaFileUpload(
                    str(thumbnail_path),
                    mimetype=mimetypes.guess_type(thumbnail_path.name)[0]
                    or "image/jpeg",
                ),
            ).execute()
            thumbnail_detail = f"サムネイル設定済み: {thumbnail_path.name}"
    except Exception as exc:
        # The upload itself succeeded; degrade to a warning instead of
        # reporting the whole upload as failed.
        thumbnail_detail = "サムネイル設定に失敗"
        thumbnail_error = str(exc)

    result = {
        "uploadedVideoId": uploaded_video_id,
        "uploadedUrl": uploaded_url,
        "uploadedAt": datetime.now().isoformat(timespec="seconds"),
        "selectedTitle": title.strip(),
        "description": description.strip(),
        "tags": tags,
        "privacyStatus": status_body["privacyStatus"],
        "scheduledPublishAt": publish_at or "",
        "thumbnailDetail": thumbnail_detail,
        "thumbnailError": thumbnail_error,
    }
    save_upload_metadata_for_item(item, result)
    return result


def parse_language_codes(value: str) -> list[str]:
    codes = [
        code.strip().lower()
        for code in value.replace("、", ",").split(",")
        if code.strip()
    ]
    return codes or ["ja"]


def pick_caption_track(
    tracks_by_language: dict[str, Any],
    language_codes: list[str],
) -> tuple[str, dict[str, Any]] | None:
    normalized_keys = {
        str(language).lower(): str(language)
        for language in tracks_by_language
    }
    for language_code in language_codes:
        matching_keys = [
            original
            for normalized, original in normalized_keys.items()
            if normalized == language_code
            or normalized.startswith(f"{language_code}-")
            or normalized.startswith(f"{language_code}.")
        ]
        for language_key in matching_keys:
            tracks = tracks_by_language.get(language_key) or []
            preferred_tracks = sorted(
                tracks,
                key=lambda track: {
                    "vtt": 0,
                    "srt": 1,
                    "ttml": 2,
                    "srv3": 3,
                    "json3": 4,
                }.get(str(track.get("ext", "")).lower(), 99),
            )
            for track in preferred_tracks:
                if track.get("url"):
                    return language_key, track
    return None


def download_text_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def subtitle_to_transcript(subtitle_text: str) -> str:
    lines: list[str] = []
    previous = ""
    skip_block = False
    for raw_line in subtitle_text.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line:
            skip_block = False
            continue
        upper_line = line.upper()
        if upper_line.startswith(("WEBVTT", "KIND:", "LANGUAGE:")):
            continue
        if upper_line.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue
        if skip_block:
            continue
        if TIMECODE_RE.match(line):
            continue
        if line.isdigit():
            continue
        line = VTT_TIMESTAMP_TAG_RE.sub("", line)
        line = HTML_TAG_RE.sub("", line)
        line = html.unescape(line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()


def fetch_subtitle_transcript(
    video: dict[str, Any],
    output_dir: Path,
    language_codes: list[str],
) -> dict[str, Any]:
    logger = DownloadLogger()
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "logger": logger,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video["url"], download=False)

    manual_choice = pick_caption_track(info.get("subtitles") or {}, language_codes)
    auto_choice = pick_caption_track(
        info.get("automatic_captions") or {},
        language_codes,
    )
    source = "manual"
    choice = manual_choice
    if choice is None:
        source = "auto"
        choice = auto_choice
    if choice is None:
        return {
            "status": "skipped",
            "detail": "指定言語の字幕・自動字幕が見つかりませんでした。",
        }

    language, track = choice
    ext = str(track.get("ext") or "vtt").lower()
    if ext not in {"vtt", "srt", "ttml", "srv3", "json3"}:
        ext = "vtt"
    subtitle_text = download_text_url(str(track["url"]))
    transcript = subtitle_to_transcript(subtitle_text)
    if not transcript:
        return {
            "status": "failed",
            "detail": "字幕は取得できましたが、本文を抽出できませんでした。",
        }

    source_label = "manual" if source == "manual" else "auto"
    subtitle_path = output_dir / f"subtitle.{language}.{source_label}.{ext}"
    transcript_path = output_dir / "transcript.txt"
    subtitle_path.write_text(subtitle_text, encoding="utf-8")
    transcript_path.write_text(transcript + "\n", encoding="utf-8")

    return {
        "status": "success",
        "detail": (
            f"{'手動字幕' if source == 'manual' else '自動字幕'}"
            f"（{language}）を保存しました。"
        ),
        "subtitle_path": str(subtitle_path),
        "transcript_path": str(transcript_path),
        "transcript": transcript,
        "source": source,
        "language": language,
    }


def parse_subtitle_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"字幕の時刻形式を解釈できません: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def clean_caption_text(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = VTT_TIMESTAMP_TAG_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_timed_caption_blocks(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for block in blocks:
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        current = {
            "start": float(block["start"]),
            "end": max(float(block["end"]), float(block["start"]) + 0.1),
            "text": text,
        }
        if normalized:
            previous = normalized[-1]
            close_in_time = current["start"] <= previous["end"] + 0.5
            if close_in_time and current["text"] == previous["text"]:
                previous["end"] = max(previous["end"], current["end"])
                continue
            if close_in_time and current["text"].startswith(previous["text"]):
                previous["text"] = current["text"]
                previous["end"] = max(previous["end"], current["end"])
                continue
            if close_in_time and previous["text"].startswith(current["text"]):
                previous["end"] = max(previous["end"], current["end"])
                continue
        normalized.append(current)
    for index, block in enumerate(normalized, start=1):
        block["id"] = index
    return normalized


def parse_timed_subtitle_blocks(subtitle_text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = subtitle_text.replace("\ufeff", "").splitlines()
    index = 0
    while index < len(lines):
        match = TIMED_SUBTITLE_LINE_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        start = parse_subtitle_timestamp(match.group("start"))
        end = parse_subtitle_timestamp(match.group("end"))
        index += 1
        text_lines: list[str] = []
        while index < len(lines):
            if TIMED_SUBTITLE_LINE_RE.match(lines[index]):
                break
            if not lines[index].strip():
                index += 1
                break
            text_lines.append(lines[index])
            index += 1
        text = clean_caption_text(text_lines)
        if text:
            blocks.append({"start": start, "end": end, "text": text})
    return normalize_timed_caption_blocks(blocks)


def timed_blocks_to_transcript(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        if lines and text == lines[-1]:
            continue
        if lines and text.startswith(lines[-1]):
            lines[-1] = text
            continue
        if lines and lines[-1].endswith(text):
            continue
        lines.append(text)
    return "\n".join(lines).strip()


def wrap_japanese_caption(text: str, preferred_line_length: int = 24) -> str:
    cleaned = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if len(cleaned) <= preferred_line_length:
        return cleaned
    lines = split_caption_text_balanced(
        cleaned,
        2,
        max_characters=preferred_line_length,
    )
    return "\n".join(lines) if len(lines) == 2 else cleaned


def wrap_english_caption(text: str, preferred_line_length: int = 42) -> str:
    cleaned = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if len(cleaned) <= preferred_line_length:
        return cleaned
    midpoint = len(cleaned) // 2
    spaces = [
        position
        for position, character in enumerate(cleaned)
        if character == " " and 8 <= position <= len(cleaned) - 8
    ]
    split_at = min(spaces, key=lambda position: abs(position - midpoint)) if spaces else midpoint
    first = cleaned[:split_at].strip()
    second = cleaned[split_at:].strip()
    return f"{first}\n{second}" if first and second else cleaned


def split_caption_text_balanced(
    text: str,
    part_count: int,
    max_characters: int | None = None,
) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if part_count <= 1 or len(cleaned) <= 1:
        return [cleaned] if cleaned else []

    parts: list[str] = []
    remaining = cleaned
    has_japanese = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", cleaned))
    strong_boundaries = "。！？!?"
    weak_boundaries = "、，,；;：:"
    opening_characters = "([{「『【〈《〔（［｛“‘"
    closing_characters = "、。，．・：；？！!?)]}」』】〉》〕）］｝”’"
    conjunctions = (
        "そして",
        "しかし",
        "ただし",
        "だから",
        "そのため",
        "また",
        "つまり",
        "一方",
        "でも",
        "たとえば",
    )
    phrase_endings = (
        "でした",
        "ました",
        "ません",
        "では",
        "には",
        "とは",
        "から",
        "まで",
        "より",
        "ので",
        "のに",
        "けれど",
        "けど",
        "なら",
        "ても",
        "ては",
        "ために",
        "ように",
        "です",
        "ます",
        "ない",
        "たい",
    )
    single_particle_endings = "はがをにでとへも"
    for parts_left in range(part_count, 1, -1):
        ideal = max(1, round(len(remaining) / parts_left))
        lower = max(1, round(ideal * 0.6))
        upper = min(len(remaining) - (parts_left - 1), round(ideal * 1.4))
        if max_characters is not None:
            lower = max(
                lower,
                len(remaining) - (parts_left - 1) * max_characters,
            )
            upper = min(upper, max_characters)
        candidates: list[tuple[int, int, int]] = []
        for position in range(lower, upper + 1):
            previous_character = remaining[position - 1]
            next_character = remaining[position] if position < len(remaining) else ""
            previous_nonspace_index = position - 1
            while (
                previous_nonspace_index >= 0
                and remaining[previous_nonspace_index].isspace()
            ):
                previous_nonspace_index -= 1
            next_nonspace_index = position
            while (
                next_nonspace_index < len(remaining)
                and remaining[next_nonspace_index].isspace()
            ):
                next_nonspace_index += 1
            previous_nonspace = (
                remaining[previous_nonspace_index]
                if previous_nonspace_index >= 0
                else ""
            )
            next_nonspace = (
                remaining[next_nonspace_index]
                if next_nonspace_index < len(remaining)
                else ""
            )
            if previous_character in opening_characters:
                continue
            if next_character in closing_characters:
                continue
            if (
                re.fullmatch(r"[A-Za-z0-9._+\-]", previous_character)
                and re.fullmatch(r"[A-Za-z0-9._+\-]", next_character)
            ):
                continue
            if (
                has_japanese
                and (previous_character.isspace() or next_character.isspace())
                and re.fullmatch(r"[A-Za-z0-9._+\-]", previous_nonspace)
                and re.fullmatch(r"[A-Za-z0-9._+\-]", next_nonspace)
            ):
                continue
            if previous_character in strong_boundaries:
                priority = 0
            elif any(remaining[position:].startswith(word) for word in conjunctions):
                priority = 1
            elif previous_character in weak_boundaries:
                priority = 2
            elif any(remaining[:position].endswith(ending) for ending in phrase_endings):
                priority = 3
            elif previous_character in single_particle_endings:
                priority = 4
            elif previous_character.isspace():
                priority = 5 if has_japanese else 0
            else:
                continue
            candidates.append((priority, abs(position - ideal), position))
        split_at = min(candidates)[2] if candidates else ideal
        if 0 < split_at < len(remaining):
            left_nonspace = split_at - 1
            while left_nonspace >= 0 and remaining[left_nonspace].isspace():
                left_nonspace -= 1
            right_nonspace = split_at
            while (
                right_nonspace < len(remaining)
                and remaining[right_nonspace].isspace()
            ):
                right_nonspace += 1
            if (
                left_nonspace >= 0
                and right_nonspace < len(remaining)
                and re.fullmatch(
                    r"[A-Za-z0-9._+\-]", remaining[left_nonspace]
                )
                and re.fullmatch(
                    r"[A-Za-z0-9._+\-]", remaining[right_nonspace]
                )
            ):
                left = left_nonspace + 1
                while left > 0 and re.fullmatch(
                    r"[A-Za-z0-9._+\-]", remaining[left - 1]
                ):
                    left -= 1
                right = right_nonspace
                while right < len(remaining) and re.fullmatch(
                    r"[A-Za-z0-9._+\-]", remaining[right]
                ):
                    right += 1
                if has_japanese:
                    next_token = right
                    while (
                        next_token < len(remaining)
                        and remaining[next_token].isspace()
                    ):
                        next_token += 1
                    if (
                        next_token > right
                        and next_token < len(remaining)
                        and re.fullmatch(
                            r"[A-Za-z0-9._+\-]", remaining[next_token]
                        )
                    ):
                        right = next_token
                        while right < len(remaining) and re.fullmatch(
                            r"[A-Za-z0-9._+\-]", remaining[right]
                        ):
                            right += 1
                    previous_token = left - 1
                    while previous_token >= 0 and remaining[previous_token].isspace():
                        previous_token -= 1
                    if (
                        previous_token < left - 1
                        and previous_token >= 0
                        and re.fullmatch(
                            r"[A-Za-z0-9._+\-]", remaining[previous_token]
                        )
                    ):
                        left = previous_token + 1
                        while left > 0 and re.fullmatch(
                            r"[A-Za-z0-9._+\-]", remaining[left - 1]
                        ):
                            left -= 1
                valid_positions = [
                    position
                    for position in (left, right)
                    if lower <= position <= upper
                    and (
                        max_characters is None
                        or position <= max_characters
                    )
                ]
                if not valid_positions and max_characters is not None:
                    protected_limit = math.ceil(max_characters * 1.25)
                    valid_positions = [
                        position
                        for position in (left, right)
                        if 1 <= position < len(remaining)
                        and position <= protected_limit
                        and len(remaining) - position
                        <= (parts_left - 1) * protected_limit
                    ]
                if valid_positions:
                    split_at = min(
                        valid_positions,
                        key=lambda position: abs(position - ideal),
                    )
        piece = remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()
        if piece:
            parts.append(piece)
    if remaining:
        parts.append(remaining)
    return parts


def split_long_timed_caption_blocks(
    blocks: list[dict[str, Any]],
    *,
    max_duration: float = 6.0,
    max_characters: int = 88,
    minimum_part_duration: float = 1.2,
) -> list[dict[str, Any]]:
    split_blocks: list[dict[str, Any]] = []
    for block in blocks:
        start = float(block["start"])
        end = max(float(block["end"]), start + 0.1)
        text = re.sub(r"\s+", " ", str(block.get("text", ""))).strip()
        if not text:
            continue
        duration = end - start
        required_parts = max(
            1,
            math.ceil(duration / max_duration),
            math.ceil(len(text) / max_characters),
        )
        maximum_parts = max(1, int(duration / minimum_part_duration))
        part_count = min(required_parts, maximum_parts, len(text))
        while True:
            pieces = split_caption_text_balanced(
                text,
                part_count,
                max_characters=max_characters,
            )
            weights = [max(1, len(piece)) for piece in pieces]
            total_weight = sum(weights)
            longest_duration = max(
                (duration * weight / total_weight for weight in weights),
                default=duration,
            )
            if (
                longest_duration <= max_duration
                and all(len(piece) <= max_characters for piece in pieces)
            ):
                break
            if part_count >= maximum_parts or part_count >= len(text):
                break
            part_count += 1
        if len(pieces) <= 1:
            split_blocks.append({**block, "start": start, "end": end, "text": text})
            continue

        consumed_weight = 0
        for index, (piece, weight) in enumerate(zip(pieces, weights)):
            piece_start = start + duration * consumed_weight / total_weight
            consumed_weight += weight
            piece_end = (
                end
                if index == len(pieces) - 1
                else start + duration * consumed_weight / total_weight
            )
            split_blocks.append(
                {
                    **block,
                    "start": piece_start,
                    "end": piece_end,
                    "text": piece,
                }
            )
    for index, block in enumerate(split_blocks, start=1):
        block["id"] = index
    return split_blocks


def join_caption_texts(first: str, second: str) -> str:
    first = first.strip()
    second = second.strip()
    if not first:
        return second
    if not second:
        return first
    japanese_pattern = r"[\u3040-\u30ff\u3400-\u9fff]"
    separator = "" if re.search(japanese_pattern, first + second) else " "
    return first + separator + second


def stabilize_short_caption_blocks(
    blocks: list[dict[str, Any]],
    *,
    minimum_duration: float = 1.2,
    max_characters: int = 42,
) -> list[dict[str, Any]]:
    working = [{**block} for block in blocks]
    index = 0
    while index < len(working):
        current = working[index]
        duration = float(current["end"]) - float(current["start"])
        if duration >= minimum_duration:
            index += 1
            continue

        candidates: list[tuple[int, int, str]] = []
        if index > 0:
            previous = working[index - 1]
            gap = float(current["start"]) - float(previous["end"])
            combined = join_caption_texts(
                str(previous["text"]), str(current["text"])
            )
            if gap <= 0.6 and len(combined) <= max_characters:
                candidates.append((len(combined), -1, combined))
        if index + 1 < len(working):
            following = working[index + 1]
            gap = float(following["start"]) - float(current["end"])
            combined = join_caption_texts(
                str(current["text"]), str(following["text"])
            )
            if gap <= 0.6 and len(combined) <= max_characters:
                candidates.append((len(combined), 1, combined))

        if candidates:
            _, direction, combined_text = min(candidates)
            if direction < 0:
                previous = working[index - 1]
                previous["end"] = max(
                    float(previous["end"]), float(current["end"])
                )
                previous["text"] = combined_text
                working.pop(index)
                index = max(0, index - 1)
            else:
                following = working[index + 1]
                following["start"] = min(
                    float(current["start"]), float(following["start"])
                )
                following["text"] = combined_text
                working.pop(index)
            continue

        earliest_start = (
            max(0.0, float(working[index - 1]["end"]) + 0.05)
            if index > 0
            else 0.0
        )
        latest_end = (
            float(working[index + 1]["start"]) - 0.05
            if index + 1 < len(working)
            else max(
                float(current["end"]),
                float(current["start"]) + minimum_duration,
            )
        )
        if latest_end - earliest_start >= minimum_duration:
            latest_start = latest_end - minimum_duration
            adjusted_start = min(
                max(float(current["start"]), earliest_start),
                latest_start,
            )
            current["start"] = adjusted_start
            current["end"] = adjusted_start + minimum_duration
        elif latest_end > float(current["end"]):
            current["end"] = latest_end
        index += 1

    for index, block in enumerate(working, start=1):
        block["id"] = index
    return working


def prepare_japanese_caption_blocks(
    blocks: list[dict[str, Any]],
    caption_texts: list[str],
) -> list[dict[str, Any]]:
    if len(blocks) != len(caption_texts):
        raise ValueError("字幕数と字幕テキストの数が一致しません。")
    translated_blocks = [
        {**block, "text": caption_text}
        for block, caption_text in zip(blocks, caption_texts)
    ]
    split_blocks = split_long_timed_caption_blocks(
        translated_blocks,
        max_duration=6.0,
        max_characters=42,
        minimum_part_duration=1.2,
    )
    merged_blocks = stabilize_short_caption_blocks(
        split_blocks,
        minimum_duration=1.2,
        max_characters=84,
    )
    resplit_blocks = split_long_timed_caption_blocks(
        merged_blocks,
        max_duration=6.0,
        max_characters=42,
        minimum_part_duration=1.2,
    )
    return stabilize_short_caption_blocks(
        resplit_blocks,
        minimum_duration=1.2,
        max_characters=42,
    )


def caption_blocks_to_srt(
    blocks: list[dict[str, Any]],
    caption_texts: list[str],
    formatter: Callable[[str], str],
) -> str:
    if len(blocks) != len(caption_texts):
        raise ValueError("字幕数と字幕テキストの数が一致しません。")
    entries: list[str] = []
    for index, (block, caption_text) in enumerate(
        zip(blocks, caption_texts),
        start=1,
    ):
        caption = formatter(caption_text)
        entries.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(float(block['start']))} --> "
                    f"{format_srt_timestamp(float(block['end']))}",
                    caption,
                ]
            )
        )
    return "\n\n".join(entries).strip() + "\n"


def translated_blocks_to_srt(
    blocks: list[dict[str, Any]],
    translated_texts: list[str],
) -> str:
    prepared_blocks = prepare_japanese_caption_blocks(blocks, translated_texts)
    return caption_blocks_to_srt(
        prepared_blocks,
        [str(block["text"]) for block in prepared_blocks],
        wrap_japanese_caption,
    )


SUBTITLE_LAYOUT_VERSION = 1


def subtitle_layout_marker_path(subtitle_path: Path) -> Path:
    return subtitle_path.with_name(f"{subtitle_path.stem}.layout.json")


def subtitle_layout_is_current(subtitle_path: Path) -> bool:
    marker_path = subtitle_layout_marker_path(subtitle_path)
    if not subtitle_path.is_file() or not marker_path.is_file():
        return False
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    stat = subtitle_path.stat()
    return (
        payload.get("version") == SUBTITLE_LAYOUT_VERSION
        and payload.get("subtitleMtimeNs") == stat.st_mtime_ns
        and payload.get("subtitleSize") == stat.st_size
    )


def write_subtitle_layout_marker(subtitle_path: Path) -> None:
    stat = subtitle_path.stat()
    subtitle_layout_marker_path(subtitle_path).write_text(
        json.dumps(
            {
                "version": SUBTITLE_LAYOUT_VERSION,
                "subtitleMtimeNs": stat.st_mtime_ns,
                "subtitleSize": stat.st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def reflow_japanese_subtitle_file(
    subtitle_path: Path,
    source_path: Path | None = None,
) -> bool:
    if source_path is None and subtitle_layout_is_current(subtitle_path):
        return False
    current_text = subtitle_path.read_text(encoding="utf-8")
    source_text = (source_path or subtitle_path).read_text(encoding="utf-8")
    blocks = parse_timed_subtitle_blocks(source_text)
    if not blocks:
        raise RuntimeError("日本語字幕のタイムコードを読み取れませんでした。")
    prepared_blocks = prepare_japanese_caption_blocks(
        blocks,
        [str(block["text"]) for block in blocks],
    )
    rewritten_text = caption_blocks_to_srt(
        prepared_blocks,
        [str(block["text"]) for block in prepared_blocks],
        wrap_japanese_caption,
    )
    if rewritten_text == current_text:
        write_subtitle_layout_marker(subtitle_path)
        return False
    backup_path = subtitle_path.with_name("subtitles_ja.before_reflow.srt")
    if source_path is None and not backup_path.exists():
        shutil.copy2(subtitle_path, backup_path)
    subtitle_path.write_text(rewritten_text, encoding="utf-8")
    write_subtitle_layout_marker(subtitle_path)
    return True


def parse_translation_response(output_text: str) -> dict[int, str]:
    cleaned = output_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start < 0 or end <= start:
            raise RuntimeError("字幕翻訳の応答をJSONとして読み取れませんでした。")
        payload = json.loads(cleaned[start : end + 1])
    if isinstance(payload, dict):
        payload = payload.get("translations")
    if not isinstance(payload, list):
        raise RuntimeError("字幕翻訳の応答形式が正しくありません。")
    translations: dict[int, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        translated = str(item.get("ja") or item.get("text") or "").strip()
        if translated:
            translations[item_id] = translated
    return translations


def caption_translation_chunks(
    blocks: list[dict[str, Any]],
    *,
    max_items: int = 60,
    max_characters: int = 7000,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_characters = 0
    for block in blocks:
        text_length = len(str(block.get("text", "")))
        if current and (
            len(current) >= max_items
            or current_characters + text_length > max_characters
        ):
            chunks.append(current)
            current = []
            current_characters = 0
        current.append(block)
        current_characters += text_length
    if current:
        chunks.append(current)
    return chunks


def translate_caption_blocks_to_japanese(
    blocks: list[dict[str, Any]],
    video: dict[str, Any],
    openai_api_key: str,
    model: str,
    progress_callback: Callable[[str], None] | None = None,
) -> list[str]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            f"OpenAI Pythonパッケージが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    client = OpenAI(api_key=openai_api_key)
    translations: dict[int, str] = {}
    chunks = caption_translation_chunks(blocks)
    for chunk_index, chunk in enumerate(chunks, start=1):
        if progress_callback:
            progress_callback(
                f"日本語へ翻訳しています（{chunk_index}/{len(chunks)}）..."
            )
        first_id = int(chunk[0]["id"])
        last_id = int(chunk[-1]["id"])
        previous_context = next(
            (
                str(block["text"])
                for block in blocks
                if int(block["id"]) == first_id - 1
            ),
            "",
        )
        next_context = next(
            (
                str(block["text"])
                for block in blocks
                if int(block["id"]) == last_id + 1
            ),
            "",
        )
        source_items = [
            {"id": int(block["id"]), "text": str(block["text"])}
            for block in chunk
        ]
        prompt = f"""
次の英語字幕を、YouTube動画に表示する自然で簡潔な日本語字幕へ翻訳してください。

動画タイトル: {video.get('title', '')}
直前の文脈（翻訳対象外）: {previous_context}
直後の文脈（翻訳対象外）: {next_context}

ルール:
- 前後の流れを踏まえ、直訳調ではなく意味の通る自然な日本語にする
- 字幕として一読できる簡潔さを優先する
- 意味、固有名詞、数値、否定表現を変えない
- 各IDを結合・分割・省略せず、入力と同じIDを1回ずつ返す
- 改行、番号、解説、Markdownを ja の文章内へ入れない
- 出力は必ずJSON配列だけにする
- 形式: [{{"id": 1, "ja": "日本語字幕"}}]

翻訳対象:
{json.dumps(source_items, ensure_ascii=False)}
""".strip()
        response = client.responses.create(
            model=model.strip() or DEFAULT_OPENAI_MODEL,
            max_output_tokens=8000,
            input=[
                {
                    "role": "system",
                    "content": (
                        "あなたは映像字幕の英日翻訳者です。前後の文脈を読み、"
                        "短く自然で正確な日本語字幕をJSONだけで返します。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise RuntimeError("OpenAI APIから字幕翻訳を取得できませんでした。")
        chunk_translations = parse_translation_response(output_text)
        missing_ids = [
            int(block["id"])
            for block in chunk
            if int(block["id"]) not in chunk_translations
        ]
        if missing_ids:
            raise RuntimeError(
                "字幕翻訳の一部が不足しています: "
                + ", ".join(str(item_id) for item_id in missing_ids[:10])
            )
        translations.update(chunk_translations)
    return [translations[int(block["id"])] for block in blocks]


def pick_timed_caption_track(
    tracks_by_language: dict[str, Any],
    language_codes: list[str],
) -> tuple[str, dict[str, Any]] | None:
    timed_tracks = {
        language: [
            track
            for track in (tracks or [])
            if str(track.get("ext", "")).lower() in {"vtt", "srt"}
        ]
        for language, tracks in tracks_by_language.items()
    }
    return pick_caption_track(timed_tracks, language_codes)


def existing_english_caption_source(output_dir: Path) -> Path | None:
    candidates = [
        path
        for path in output_dir.glob("subtitles_en*")
        if path.is_file()
        and path.suffix.lower() in {".vtt", ".srt"}
        and any(
            marker in path.name
            for marker in (".manual.", ".auto.", "_corrected.")
        )
    ]
    candidates.sort(
        key=lambda path: (
            0
            if ".manual." in path.name
            else 1
            if ".auto." in path.name
            else 2,
            path.name,
        )
    )
    return next((path for path in candidates if path.stat().st_size > 0), None)


def fetch_english_caption_assets(
    video: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    existing_source = existing_english_caption_source(output_dir)
    if existing_source is not None:
        subtitle_text = existing_source.read_text(encoding="utf-8")
        blocks = parse_timed_subtitle_blocks(subtitle_text)
        if blocks:
            transcript_path = output_dir / "transcript_en.txt"
            transcript = (
                transcript_path.read_text(encoding="utf-8").strip()
                if transcript_path.exists() and transcript_path.stat().st_size > 0
                else timed_blocks_to_transcript(blocks)
            )
            if not transcript_path.exists() or transcript_path.stat().st_size == 0:
                transcript_path.write_text(transcript + "\n", encoding="utf-8")
            return {
                "status": "success",
                "detail": f"保存済み英語字幕を再利用しました（{existing_source.name}）。",
                "subtitle_path": existing_source,
                "transcript_path": transcript_path,
                "transcript": transcript,
                "blocks": blocks,
                "reused": True,
            }

    logger = DownloadLogger()
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "logger": logger,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video["url"], download=False)
    manual_choice = pick_timed_caption_track(info.get("subtitles") or {}, ["en"])
    auto_choice = pick_timed_caption_track(
        info.get("automatic_captions") or {},
        ["en"],
    )
    source = "manual"
    choice = manual_choice
    if choice is None:
        source = "auto"
        choice = auto_choice
    if choice is None:
        return {
            "status": "skipped",
            "detail": "英語の手動字幕・自動字幕が見つかりませんでした。",
        }

    language, track = choice
    ext = str(track.get("ext") or "vtt").lower()
    subtitle_text = download_text_url(str(track["url"]))
    blocks = parse_timed_subtitle_blocks(subtitle_text)
    if not blocks:
        return {
            "status": "failed",
            "detail": "英語字幕は取得できましたが、タイムコードを読み取れませんでした。",
        }
    transcript = timed_blocks_to_transcript(blocks)
    source_path = output_dir / f"subtitles_en.{source}.{ext}"
    transcript_path = output_dir / "transcript_en.txt"
    source_path.write_text(subtitle_text, encoding="utf-8")
    transcript_path.write_text(transcript + "\n", encoding="utf-8")
    return {
        "status": "success",
        "detail": (
            f"{'手動字幕' if source == 'manual' else '自動字幕'}"
            f"（{language}）と英語文字起こしを保存しました。"
        ),
        "subtitle_path": source_path,
        "transcript_path": transcript_path,
        "transcript": transcript,
        "blocks": blocks,
        "source": source,
        "language": language,
        "reused": False,
    }


def find_downloaded_source_video(output_dir: Path) -> Path:
    preferred_extensions = [".mkv", ".mp4", ".webm", ".mov", ".m4v", ".avi"]
    for extension in preferred_extensions:
        candidate = output_dir / f"video{extension}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    raise FileNotFoundError("字幕を焼き込む元動画が見つかりません。")


def find_optional_ffmpeg_executable() -> str:
    local_candidates = [
        APP_ROOT / ".runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
        APP_ROOT / ".runtime" / "ffmpeg" / "bin" / "ffmpeg",
    ]
    for candidate in local_candidates:
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        executable = ""
    if executable and Path(executable).is_file():
        return executable
    return ""


def find_ffmpeg_executable() -> str:
    executable = find_optional_ffmpeg_executable()
    if executable:
        return executable
    raise FileNotFoundError(
        f"FFmpegが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
    )


def find_ffprobe_executable() -> str:
    ffmpeg_path = Path(find_ffmpeg_executable())
    ffprobe_name = "ffprobe.exe" if ffmpeg_path.suffix.lower() == ".exe" else "ffprobe"
    adjacent = ffmpeg_path.with_name(ffprobe_name)
    if adjacent.is_file():
        return str(adjacent)
    executable = shutil.which("ffprobe")
    if executable:
        return executable
    raise FileNotFoundError("動画の長さを確認するFFprobeが見つかりません。")


def probe_media_duration(source_path: Path) -> float:
    completed = subprocess.run(
        [
            find_ffprobe_executable(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source_path.resolve()),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("動画の長さを確認できませんでした。") from exc
    if completed.returncode != 0 or duration <= 0:
        raise RuntimeError("動画の長さを確認できませんでした。")
    return duration


def extract_audio_chunks(
    source_video: Path,
    output_dir: Path,
    duration_seconds: float,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    duration = duration_seconds if duration_seconds > 0 else probe_media_duration(source_video)
    audio_dir = output_dir / "audio_chunks"
    audio_dir.mkdir(parents=True, exist_ok=True)
    chunk_count = max(1, math.ceil(duration / AUDIO_CHUNK_SECONDS))
    ffmpeg = find_ffmpeg_executable()
    chunks: list[dict[str, Any]] = []
    for index in range(chunk_count):
        start = float(index * AUDIO_CHUNK_SECONDS)
        chunk_duration = min(float(AUDIO_CHUNK_SECONDS), duration - start)
        chunk_path = audio_dir / f"chunk_{index:04d}.mp3"
        if not chunk_path.is_file() or chunk_path.stat().st_size == 0:
            if progress_callback:
                progress_callback(
                    f"音声を準備しています（{index + 1}/{chunk_count}）..."
                )
            temporary_path = chunk_path.with_name(f".{chunk_path.stem}.partial.mp3")
            if temporary_path.exists():
                temporary_path.unlink()
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-i",
                    str(source_video.resolve()),
                    "-t",
                    f"{chunk_duration:.3f}",
                    "-vn",
                    "-map",
                    "0:a:0",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "48k",
                    str(temporary_path.resolve()),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if completed.returncode != 0 or not temporary_path.is_file():
                if temporary_path.exists():
                    temporary_path.unlink()
                error_detail = completed.stderr.strip().splitlines()[-8:]
                raise RuntimeError(
                    "動画から音声を取り出せませんでした。 " + " / ".join(error_detail)
                )
            temporary_path.replace(chunk_path)
        if chunk_path.stat().st_size >= 25 * 1024 * 1024:
            raise RuntimeError(
                f"音声ファイルが25MB以上になりました: {chunk_path.name}"
            )
        chunks.append(
            {
                "path": chunk_path,
                "name": chunk_path.name,
                "start": start,
                "end": start + chunk_duration,
            }
        )
    return chunks


def object_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def load_transcription_progress(progress_path: Path) -> dict[str, Any]:
    if not progress_path.is_file():
        return {}
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_transcription_progress(
    progress_path: Path,
    model: str,
    completed_chunks: set[str],
    blocks: list[dict[str, Any]],
) -> None:
    payload = {
        "model": model,
        "completedChunks": sorted(completed_chunks),
        "blocks": [
            {
                "start": float(block["start"]),
                "end": float(block["end"]),
                "text": str(block["text"]),
                "speaker": str(block.get("speaker", "")),
            }
            for block in blocks
        ],
    }
    progress_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def transcribe_audio_chunks(
    video: dict[str, Any],
    output_dir: Path,
    openai_api_key: str,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    raw_srt_path = output_dir / "subtitles_en_raw.srt"
    if raw_srt_path.is_file() and raw_srt_path.stat().st_size > 0:
        reused_blocks = parse_timed_subtitle_blocks(
            raw_srt_path.read_text(encoding="utf-8")
        )
        if reused_blocks:
            reused_blocks = split_long_timed_caption_blocks(reused_blocks)
            raw_srt_path.write_text(
                caption_blocks_to_srt(
                    reused_blocks,
                    [str(block["text"]) for block in reused_blocks],
                    wrap_english_caption,
                ),
                encoding="utf-8",
            )
            raw_transcript_path = output_dir / "transcript_en_raw.txt"
            if not raw_transcript_path.is_file() or raw_transcript_path.stat().st_size == 0:
                raw_transcript_path.write_text(
                    timed_blocks_to_transcript(reused_blocks) + "\n",
                    encoding="utf-8",
                )
            if progress_callback:
                progress_callback("保存済みの未修正文字起こしを再利用しました。")
            return reused_blocks

    source_video = find_downloaded_source_video(output_dir)
    try:
        duration_seconds = float(video.get("durationSeconds") or 0)
    except (TypeError, ValueError):
        duration_seconds = 0
    audio_chunks = extract_audio_chunks(
        source_video,
        output_dir,
        duration_seconds,
        progress_callback,
    )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            f"OpenAI Pythonパッケージが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    progress_path = output_dir / "transcription_en_raw.json"
    saved_progress = load_transcription_progress(progress_path)
    completed_chunks = {
        str(name) for name in saved_progress.get("completedChunks", []) if name
    }
    raw_blocks = [
        {
            "start": float(block.get("start", 0)),
            "end": float(block.get("end", 0)),
            "text": str(block.get("text", "")),
            "speaker": str(block.get("speaker", "")),
        }
        for block in saved_progress.get("blocks", [])
        if isinstance(block, dict) and str(block.get("text", "")).strip()
    ]
    client = OpenAI(api_key=openai_api_key)
    for index, audio_chunk in enumerate(audio_chunks, start=1):
        chunk_name = str(audio_chunk["name"])
        if chunk_name in completed_chunks:
            continue
        if progress_callback:
            progress_callback(
                f"音声を英語で文字起こししています（{index}/{len(audio_chunks)}）..."
            )
        with Path(audio_chunk["path"]).open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=DEFAULT_TRANSCRIPTION_MODEL,
                file=audio_file,
                language="en",
                response_format="diarized_json",
                chunking_strategy="auto",
                timeout=1800,
            )
        segments = object_value(transcription, "segments", []) or []
        chunk_blocks: list[dict[str, Any]] = []
        for segment in segments:
            text = str(object_value(segment, "text", "") or "").strip()
            if not text:
                continue
            segment_start = float(object_value(segment, "start", 0) or 0)
            segment_end = float(object_value(segment, "end", segment_start + 0.1) or 0)
            chunk_blocks.append(
                {
                    "start": float(audio_chunk["start"]) + segment_start,
                    "end": float(audio_chunk["start"]) + segment_end,
                    "text": text,
                    "speaker": str(object_value(segment, "speaker", "") or ""),
                }
            )
        if not chunk_blocks:
            transcription_text = str(object_value(transcription, "text", "") or "").strip()
            if transcription_text:
                chunk_blocks.append(
                    {
                        "start": float(audio_chunk["start"]),
                        "end": float(audio_chunk["end"]),
                        "text": transcription_text,
                        "speaker": "",
                    }
                )
        if not chunk_blocks:
            raise RuntimeError(f"{chunk_name} から音声文字起こしを取得できませんでした。")
        raw_blocks.extend(chunk_blocks)
        completed_chunks.add(chunk_name)
        write_transcription_progress(
            progress_path,
            DEFAULT_TRANSCRIPTION_MODEL,
            completed_chunks,
            raw_blocks,
        )

    normalized_blocks = split_long_timed_caption_blocks(
        normalize_timed_caption_blocks(raw_blocks)
    )
    if not normalized_blocks:
        raise RuntimeError("音声から英語文字起こしを作成できませんでした。")
    raw_texts = [str(block["text"]) for block in normalized_blocks]
    raw_srt_path.write_text(
        caption_blocks_to_srt(normalized_blocks, raw_texts, wrap_english_caption),
        encoding="utf-8",
    )
    (output_dir / "transcript_en_raw.txt").write_text(
        timed_blocks_to_transcript(normalized_blocks) + "\n",
        encoding="utf-8",
    )
    return normalized_blocks


def correct_english_transcription_blocks(
    blocks: list[dict[str, Any]],
    video: dict[str, Any],
    output_dir: Path,
    openai_api_key: str,
    model: str,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    corrected_srt_path = output_dir / "subtitles_en_corrected.srt"
    if corrected_srt_path.is_file() and corrected_srt_path.stat().st_size > 0:
        corrected_blocks = parse_timed_subtitle_blocks(
            corrected_srt_path.read_text(encoding="utf-8")
        )
        if corrected_blocks:
            corrected_blocks = split_long_timed_caption_blocks(corrected_blocks)
            corrected_srt_path.write_text(
                caption_blocks_to_srt(
                    corrected_blocks,
                    [str(block["text"]) for block in corrected_blocks],
                    wrap_english_caption,
                ),
                encoding="utf-8",
            )
            corrected_transcript = timed_blocks_to_transcript(corrected_blocks)
            corrected_transcript_path = output_dir / "transcript_en_corrected.txt"
            canonical_transcript_path = output_dir / "transcript_en.txt"
            if (
                not corrected_transcript_path.is_file()
                or corrected_transcript_path.stat().st_size == 0
            ):
                corrected_transcript_path.write_text(
                    corrected_transcript + "\n",
                    encoding="utf-8",
                )
            if (
                not canonical_transcript_path.is_file()
                or canonical_transcript_path.stat().st_size == 0
            ):
                canonical_transcript_path.write_text(
                    corrected_transcript + "\n",
                    encoding="utf-8",
                )
            if progress_callback:
                progress_callback("保存済みの校正済み英語字幕を再利用しました。")
            return corrected_blocks

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            f"OpenAI Pythonパッケージが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    correction_progress_path = output_dir / "transcription_en_corrected.json"
    saved_progress = load_transcription_progress(correction_progress_path)
    saved_corrections = saved_progress.get("corrections", {})
    corrections: dict[int, str] = {}
    if isinstance(saved_corrections, dict):
        for item_id, text in saved_corrections.items():
            try:
                numeric_id = int(item_id)
            except (TypeError, ValueError):
                continue
            if str(text).strip():
                corrections[numeric_id] = str(text).strip()

    client = OpenAI(api_key=openai_api_key)
    chunks = caption_translation_chunks(blocks, max_items=50, max_characters=6000)
    for chunk_index, chunk in enumerate(chunks, start=1):
        pending_chunk = [
            block for block in chunk if int(block["id"]) not in corrections
        ]
        if not pending_chunk:
            continue
        if progress_callback:
            progress_callback(
                f"英語文字起こしを校正しています（{chunk_index}/{len(chunks)}）..."
            )
        first_id = int(chunk[0]["id"])
        last_id = int(chunk[-1]["id"])
        previous_context = next(
            (str(block["text"]) for block in blocks if int(block["id"]) == first_id - 1),
            "",
        )
        next_context = next(
            (str(block["text"]) for block in blocks if int(block["id"]) == last_id + 1),
            "",
        )
        source_items = [
            {"id": int(block["id"]), "text": str(block["text"])}
            for block in pending_chunk
        ]
        prompt = f"""
次の英語音声認識結果を、前後の文脈に基づいて校正してください。

動画タイトル: {video.get('title', '')}
直前の文脈（校正対象外）: {previous_context}
直後の文脈（校正対象外）: {next_context}

ルール:
- 誤認識、脱字、重複、不自然な文法や単語だけを修正する
- 人名、会社名、商品名、専門用語は文脈から合理的に判断できる場合だけ直す
- 数字、金額、日付、割合、否定表現の意味を変えない
- 音声にない情報を追加したり、内容を要約したりしない
- 判断できない語句は推測で創作せず [unclear] と記載する
- 英語のまま校正し、日本語へ翻訳しない
- IDの結合、分割、省略をせず、入力と同じIDを1回ずつ返す
- 出力は必ずJSON配列だけにする
- 形式: [{{"id": 1, "text": "Corrected English"}}]

校正対象:
{json.dumps(source_items, ensure_ascii=False)}
""".strip()
        response = client.responses.create(
            model=model.strip() or DEFAULT_OPENAI_MODEL,
            max_output_tokens=8000,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful English transcript editor. Correct only well-supported "
                        "speech-recognition errors and return valid JSON without commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise RuntimeError("OpenAI APIから英語校正結果を取得できませんでした。")
        chunk_corrections = parse_translation_response(output_text)
        missing_ids = [
            int(block["id"])
            for block in pending_chunk
            if int(block["id"]) not in chunk_corrections
        ]
        if missing_ids:
            raise RuntimeError(
                "英語校正結果の一部が不足しています: "
                + ", ".join(str(item_id) for item_id in missing_ids[:10])
            )
        corrections.update(chunk_corrections)
        correction_progress_path.write_text(
            json.dumps(
                {
                    "model": model.strip() or DEFAULT_OPENAI_MODEL,
                    "corrections": {
                        str(item_id): text for item_id, text in sorted(corrections.items())
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    corrected_blocks = [
        {
            **block,
            "text": corrections.get(int(block["id"]), str(block["text"])),
        }
        for block in blocks
    ]
    corrected_texts = [str(block["text"]) for block in corrected_blocks]
    corrected_srt_path.write_text(
        caption_blocks_to_srt(corrected_blocks, corrected_texts, wrap_english_caption),
        encoding="utf-8",
    )
    corrected_transcript = timed_blocks_to_transcript(corrected_blocks)
    (output_dir / "transcript_en_corrected.txt").write_text(
        corrected_transcript + "\n",
        encoding="utf-8",
    )
    (output_dir / "transcript_en.txt").write_text(
        corrected_transcript + "\n",
        encoding="utf-8",
    )
    return corrected_blocks


def transcribe_and_correct_english_audio(
    video: dict[str, Any],
    output_dir: Path,
    openai_api_key: str,
    model: str,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    raw_blocks = transcribe_audio_chunks(
        video,
        output_dir,
        openai_api_key,
        progress_callback,
    )
    corrected_blocks = correct_english_transcription_blocks(
        raw_blocks,
        video,
        output_dir,
        openai_api_key,
        model,
        progress_callback,
    )
    corrected_transcript_path = output_dir / "transcript_en_corrected.txt"
    corrected_srt_path = output_dir / "subtitles_en_corrected.srt"
    return {
        "status": "success",
        "detail": (
            "字幕がなかったため音声から英語を文字起こしし、"
            "AI校正済みの英語字幕を保存しました。"
        ),
        "subtitle_path": corrected_srt_path,
        "transcript_path": corrected_transcript_path,
        "transcript": corrected_transcript_path.read_text(encoding="utf-8").strip(),
        "blocks": corrected_blocks,
        "source": "speech",
        "language": "en",
        "reused": False,
    }


def burn_japanese_subtitles(
    source_video: Path,
    subtitle_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    newest_input_time = max(
        source_video.stat().st_mtime,
        subtitle_path.stat().st_mtime,
    )
    if (
        output_path.is_file()
        and output_path.stat().st_size > 0
        and output_path.stat().st_mtime >= newest_input_time
    ):
        return {
            "status": "success",
            "detail": "保存済みの日本語字幕付き動画を再利用しました。",
            "video_path": output_path,
            "reused": True,
        }
    ffmpeg = find_ffmpeg_executable()
    temporary_path = output_path.with_name(f".{output_path.stem}.partial.mp4")
    if temporary_path.exists():
        temporary_path.unlink()
    subtitle_filter = (
        "scale=w='min(1920,iw)':h='min(1080,ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"subtitles={subtitle_path.name}:charenc=UTF-8:"
        "force_style='FontSize=22,Outline=2,Shadow=1,Alignment=2,MarginV=40'"
    )
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video.resolve()),
        "-vf",
        subtitle_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temporary_path.resolve()),
    ]
    completed = subprocess.run(
        command,
        cwd=subtitle_path.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not temporary_path.exists():
        if temporary_path.exists():
            temporary_path.unlink()
        error_detail = completed.stderr.strip().splitlines()[-8:]
        raise RuntimeError(
            "FFmpegによる字幕焼き込みに失敗しました。 " + " / ".join(error_detail)
        )
    temporary_path.replace(output_path)
    return {
        "status": "success",
        "detail": "日本語字幕を焼き込んだMP4動画を保存しました。",
        "video_path": output_path,
        "reused": False,
    }


def process_english_video_subtitles(
    video: dict[str, Any],
    output_dir: Path,
    openai_api_key: str,
    model: str,
    progress_callback: Callable[[str], None] | None = None,
    force_audio_transcription: bool = False,
) -> dict[str, Any]:
    def report(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    if force_audio_transcription:
        report("テスト設定により、YouTube字幕を使わず音声認識へ進みます。")
        caption_result = {
            "status": "skipped",
            "detail": "音声認識を優先します。",
        }
    else:
        report("英語字幕を確認しています...")
        try:
            caption_result = fetch_english_caption_assets(video, output_dir)
        except Exception as exc:
            report(f"YouTube字幕を取得できなかったため音声認識へ進みます（{exc}）。")
            caption_result = {
                "status": "skipped",
                "detail": "YouTube字幕を取得できませんでした。",
            }
    if caption_result["status"] != "success":
        if not openai_api_key.strip():
            raise RuntimeError(
                "YouTube字幕がないため音声認識が必要ですが、設定プロファイルにOpenAI APIキーがありません。"
            )
        report("YouTube字幕がないため、動画の音声から文字起こしします。")
        caption_result = transcribe_and_correct_english_audio(
            video,
            output_dir,
            openai_api_key,
            model,
            progress_callback,
        )
    report(str(caption_result["detail"]))

    blocks = split_long_timed_caption_blocks(list(caption_result["blocks"]))
    japanese_srt_path = output_dir / "subtitles_ja.srt"
    if japanese_srt_path.is_file() and japanese_srt_path.stat().st_size > 0:
        changed = reflow_japanese_subtitle_file(japanese_srt_path)
        translation_detail = (
            "保存済みの日本語字幕を読みやすい長さと表示時間に調整しました。"
            if changed
            else "保存済みの日本語字幕を再利用しました。"
        )
        report(translation_detail)
    else:
        if not openai_api_key.strip():
            raise RuntimeError(
                "英語字幕は保存しましたが、日本語翻訳には設定プロファイルのOpenAI APIキーが必要です。"
            )
        translated_texts = translate_caption_blocks_to_japanese(
            blocks,
            video,
            openai_api_key,
            model,
            progress_callback=progress_callback,
        )
        japanese_srt_path.write_text(
            translated_blocks_to_srt(blocks, translated_texts),
            encoding="utf-8",
        )
        write_subtitle_layout_marker(japanese_srt_path)
        translation_detail = "日本語翻訳字幕（subtitles_ja.srt）を保存しました。"
        report(translation_detail)

    report("日本語字幕を動画へ焼き込んでいます...")
    source_video = find_downloaded_source_video(output_dir)
    subtitled_video_path = output_dir / "video_ja_subtitled.mp4"
    burn_result = burn_japanese_subtitles(
        source_video,
        japanese_srt_path,
        subtitled_video_path,
    )
    report(str(burn_result["detail"]))
    return {
        "status": "success",
        "detail": (
            f"{caption_result['detail']} "
            f"{translation_detail} {burn_result['detail']}"
        ),
        "transcript": str(caption_result.get("transcript", "")),
        "subtitle_source_path": str(caption_result["subtitle_path"]),
        "transcript_path": str(caption_result["transcript_path"]),
        "japanese_srt_path": str(japanese_srt_path),
        "subtitled_video_path": str(subtitled_video_path),
    }


def configured_openai_key() -> tuple[str, str]:
    profile_key, profile_source = configured_profile_value("openai_api_key")
    if profile_key:
        return profile_key, profile_source
    local_key = read_local_secret_value("OPENAI_API_KEY")
    if local_key:
        return local_key, ".streamlit/secrets.toml"
    try:
        secret_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        secret_key = ""
    if secret_key:
        return secret_key, ".streamlit/secrets.toml"
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key, "環境変数 OPENAI_API_KEY"
    return "", ""


def generate_summary_and_titles(
    video: dict[str, Any],
    transcript: str,
    output_dir: Path,
    openai_api_key: str,
    model: str,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            f"OpenAI Pythonパッケージが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    summary_path = summary_path or output_dir / "summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    clipped_transcript = transcript[:60_000]
    client = OpenAI(api_key=openai_api_key)
    prompt = f"""
次のYouTube動画の文字起こしを分析してください。
文字起こしは自動字幕由来の可能性があり、誤字、誤変換、不自然な文章、句読点の欠落、文脈に合わない単語が含まれることがあります。
内容の意味を変えない範囲で、必ず自然な日本語に補正・校正してから要約してください。
明らかな誤変換は文脈から推定して直してください。ただし、根拠のない情報追加や事実の捏造はしないでください。

動画タイトル:
{video['title']}

出力は日本語Markdownで、以下の見出しを必ず含めてください。

## 3行要約
## 詳細要約
## 重要ポイント
## 文字起こし補正メモ
- 要約時に補正した主な誤変換や不自然表現があれば短く記録
## 新しい動画タイトル案
- YouTube向けに10個
- 少し尖らせて、人の興味を引く表現にする
- 文字起こし内に具体的な数値、金額、年数、回数、割合、期間、順位がある場合は優先的に活かす
- 数字は強調するが、文字起こしにない数字や成果を捏造しない
- 不安・損失・意外性・希少性・Before/Afterのどれかを自然に入れる
- 煽りすぎず、内容と一致する範囲でクリックしたくなる表現
## サムネイル文言案
- 12文字以内を中心に5個
- 数字や金額がある場合は短く強調する
- 画像に載せても読めるよう、短く、強く、具体的にする

文字起こし:
{clipped_transcript}
""".strip()
    response = client.responses.create(
        model=model.strip() or DEFAULT_OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "あなたは日本語YouTube動画の編集者です。"
                    "自動字幕の誤字、誤変換、不自然な区切り、文脈に合わない単語を見抜き、意味を変えない範囲で校正してから分析します。"
                    "内容を誇張しすぎず、ただし少し尖らせて、視聴者の興味を引く要約・タイトル案・サムネイル文言を作ります。"
                    "具体的な数字や金額がある場合は強いフックとして活かしますが、根拠のない数字は作りません。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    output_text = getattr(response, "output_text", "").strip()
    if not output_text:
        raise RuntimeError("OpenAI APIから要約テキストを取得できませんでした。")
    summary_path.write_text(output_text + "\n", encoding="utf-8")
    return {
        "status": "success",
        "detail": "要約・タイトル案を保存しました。",
        "summary_path": str(summary_path),
        "summary": output_text,
    }


def generate_thumbnail_image(
    video: dict[str, Any],
    transcript: str,
    summary: str,
    output_dir: Path,
    openai_api_key: str,
    model: str,
    thumbnail_path: Path | None = None,
    prompt_path: Path | None = None,
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            f"OpenAI Pythonパッケージが見つかりません。{SETUP_COMMAND_HINT} を再実行してください。"
        ) from exc

    thumbnail_path = thumbnail_path or output_dir / "thumbnail.png"
    prompt_path = prompt_path or output_dir / "thumbnail_prompt.txt"
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    source_text = summary.strip() or transcript[:12_000]
    prompt = f"""
YouTubeサムネイル用の16:9横長画像を生成してください。

元動画タイトル:
{video['title']}

内容メモ:
{source_text[:12_000]}

制作ルール:
- クリックされやすい、少し尖ったビジュアルにする
- 具体的な数字、金額、年数、回数、割合、期間が内容内にある場合は、それを中心フックとして視覚的に強調する
- ただし、内容にない数字・成果・人物・事実は捏造しない
- 不安、驚き、ギャップ、Before/After、希少性のどれかが伝わる構図にする
- YouTubeサムネイルとして強いコントラスト、大きな余白、視線誘導、印象的な被写体を使う
- 図、チャート、比較表、矢印、ステップ図、伸びるグラフなど、視覚的に内容を理解しやすく興味付けできる要素が有効なら積極的に入れる
- 数値の伸び、金額の変化、ランキング、手順、原因と結果、Before/Afterが読み取れる内容なら、それを簡潔な図解として表現する
- 日本語の細かい文字は崩れやすいので、画像内テキストは最小限にする。入れる場合は短い数字や短語だけにする
- 実在人物の顔写真風、既存ロゴ、著名人そっくりの顔、元動画サムネイルのコピーは避ける
- 仕上がりは1280x720のサムネイルに使いやすい構図にする
""".strip()
    client = OpenAI(api_key=openai_api_key)
    response = client.responses.create(
        model=model.strip() or DEFAULT_OPENAI_MODEL,
        input=prompt,
        tools=[{"type": "image_generation"}],
    )
    image_data = [
        getattr(output, "result", None)
        for output in getattr(response, "output", [])
        if getattr(output, "type", "") == "image_generation_call"
    ]
    image_base64 = next((value for value in image_data if value), None)
    if not image_base64:
        raise RuntimeError("OpenAI APIからサムネイル画像を取得できませんでした。")
    thumbnail_path.write_bytes(base64.b64decode(image_base64))
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    return {
        "status": "success",
        "detail": "サムネイル画像を保存しました。",
        "thumbnail_path": str(thumbnail_path),
        "prompt_path": str(prompt_path),
    }


def thumbnail_regeneration_paths(item: dict[str, Any]) -> tuple[Path, Path, Path]:
    folder = Path(item["folder"])
    existing_thumbnail = Path(item["thumbnail_path"])
    if str(item.get("kind")) == "folder":
        output_dir = folder
        thumbnail_path = output_dir / "thumbnail.png"
        prompt_path = output_dir / "thumbnail_prompt.txt"
        return output_dir, thumbnail_path, prompt_path

    video_path = Path(item["video_path"])
    output_dir = folder
    if existing_thumbnail.name:
        thumbnail_path = existing_thumbnail
    else:
        thumbnail_path = output_dir / f"{video_path.stem}.thumbnail.png"
    prompt_path = thumbnail_path.with_name(
        thumbnail_path.name.replace(".thumbnail.", ".thumbnail_prompt.").rsplit(".", 1)[0]
        + ".txt"
    )
    return output_dir, thumbnail_path, prompt_path


def search_youtube(
    api_key: str,
    keyword: str,
    mode: str,
    start_year: int,
    end_year: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run the GAS-compatible one-request-per-year search."""
    settings = MODE_SETTINGS[mode]
    youtube = build(
        "youtube",
        "v3",
        developerKey=api_key,
        cache_discovery=False,
    )
    video_ids: list[str] = []
    seen_video_ids: set[str] = set()
    channel_ids: list[str] = []
    seen_channel_ids: set[str] = set()
    warnings: list[str] = []

    for year in range(start_year, end_year + 1):
        try:
            response = (
                youtube.search()
                .list(
                    part="id,snippet",
                    q=keyword,
                    type="video",
                    order=settings["order"],
                    maxResults=50,
                    publishedAfter=f"{year}-01-01T00:00:00Z",
                    publishedBefore=f"{year}-12-31T23:59:59Z",
                )
                .execute()
            )
        except HttpError as exc:
            warnings.append(
                f"{year}年の取得中に処理を打ち切りました。"
                f"{describe_api_error(exc)} それ以前の取得結果だけを表示します。"
            )
            break

        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            channel_id = item.get("snippet", {}).get("channelId")
            if video_id and video_id not in seen_video_ids:
                seen_video_ids.add(video_id)
                video_ids.append(video_id)
            if channel_id and channel_id not in seen_channel_ids:
                seen_channel_ids.add(channel_id)
                channel_ids.append(channel_id)

    if not video_ids:
        return [], warnings

    subscriber_counts: dict[str, int] = {}
    for batch in chunks(channel_ids):
        try:
            response = (
                youtube.channels()
                .list(part="statistics", id=",".join(batch), maxResults=50)
                .execute()
            )
        except HttpError as exc:
            warnings.append(
                f"チャンネル統計の一部を取得できませんでした: {describe_api_error(exc)}"
            )
            continue
        for item in response.get("items", []):
            statistics = item.get("statistics", {})
            hidden = statistics.get("hiddenSubscriberCount", False)
            raw_count = statistics.get("subscriberCount", 0)
            try:
                count = 0 if hidden else int(raw_count)
            except (TypeError, ValueError):
                count = 0
            subscriber_counts[item.get("id", "")] = count

    details_by_id: dict[str, dict[str, Any]] = {}
    for batch in chunks(video_ids):
        try:
            response = (
                youtube.videos()
                .list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(batch),
                    maxResults=50,
                )
                .execute()
            )
        except HttpError as exc:
            warnings.append(
                f"動画詳細の一部を取得できませんでした: {describe_api_error(exc)}"
            )
            continue
        for item in response.get("items", []):
            video_id = item.get("id")
            if video_id:
                details_by_id[video_id] = item

    results: list[dict[str, Any]] = []
    # Iterate in search order so relevance mode keeps the API response order.
    for video_id in video_ids:
        item = details_by_id.get(video_id)
        if not item:
            continue
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        duration_seconds = parse_youtube_duration(
            str(content_details.get("duration", ""))
        )
        if duration_seconds < MIN_VIDEO_DURATION_SECONDS:
            continue
        channel_id = snippet.get("channelId", "")
        subscriber_count = subscriber_counts.get(channel_id, 0)
        # Only buzzRatio needs a real subscriber count (it is the ratio's
        # denominator). Applying this floor in every mode made hidden-count
        # channels — and whole searches when channels.list failed — vanish
        # with a misleading "no results" message.
        if mode == "buzzRatio" and subscriber_count < 10:
            continue
        try:
            view_count = int(statistics.get("viewCount", 0))
        except (TypeError, ValueError):
            view_count = 0

        result: dict[str, Any] = {
            "videoId": video_id,
            "title": html.unescape(str(snippet.get("title", ""))),
            "viewCount": view_count,
            "channelTitle": html.unescape(str(snippet.get("channelTitle", ""))),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "publishedAt": format_published_at(str(snippet.get("publishedAt", ""))),
            "thumbnailUrl": best_thumbnail(snippet),
            "durationSeconds": duration_seconds,
            "durationText": format_duration(duration_seconds),
        }
        if mode == "buzzRatio":
            ratio = view_count / subscriber_count
            if ratio <= 3:
                continue
            result["subCount"] = subscriber_count
            result["ratio"] = round(ratio, 2)
        results.append(result)

    if mode == "viewCount":
        results.sort(key=lambda row: row["viewCount"], reverse=True)
    elif mode == "buzzRatio":
        results.sort(
            key=lambda row: (row["ratio"], row["subCount"]),
            reverse=True,
        )

    return results[: int(settings["limit"])], warnings


class DownloadLogger:
    def __init__(self) -> None:
        self.skipped = False
        # yt-dlp's own messages used to be discarded here, so a failed download
        # only ever surfaced as "exit code 1". Keep them so the UI can show the
        # real reason (403, format unavailable, bot check, missing ffmpeg, ...).
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def debug(self, message: str) -> None:
        lowered = message.lower()
        if (
            "has already been downloaded" in lowered
            or "has already been recorded in the archive" in lowered
        ):
            self.skipped = True

    def info(self, _message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self._record(self.warnings, message)

    def error(self, message: str) -> None:
        self._record(self.errors, message)

    @staticmethod
    def _record(target: list[str], message: str) -> None:
        cleaned = ANSI_ESCAPE_RE.sub("", str(message)).strip()
        if cleaned and cleaned not in target:
            target.append(cleaned[:500])

    def failure_detail(self) -> str:
        messages = self.errors or self.warnings
        return " / ".join(messages[:3])


def explain_download_failure(detail: str) -> str:
    lowered = detail.lower()
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        return (
            "YouTubeがボット判定をしています。時間をおいて試すか、VPN・社内プロキシを"
            "切って自宅回線などで実行してください。"
        )
    if "requested format is not available" in lowered:
        return (
            "yt-dlp が古い可能性があります。アプリを閉じてから "
            "`.runtime\\python312\\python.exe -m pip install -U yt-dlp` を実行してください。"
        )
    if "http error 403" in lowered or "forbidden" in lowered:
        return (
            "YouTubeに接続を拒否されました。yt-dlp の更新（pip install -U yt-dlp）と、"
            "Denoが同梱されているか（環境チェック）を確認してください。"
        )
    if "ffmpeg" in lowered or "ffprobe" in lowered:
        return (
            "ffmpeg が見つかりません。いつもの起動方法（デスクトップのショートカット）で"
            f"起動し直すか、{SETUP_COMMAND_HINT} を再実行してください。"
        )
    if "private video" in lowered or "members-only" in lowered:
        return "非公開・メンバー限定の動画のため、このツールでは取得できません。"
    if "age" in lowered and "confirm" in lowered:
        return "年齢制限付き動画のため、このツールでは取得できません。"
    if "unavailable" in lowered or "removed" in lowered:
        return "この動画は削除済み、または地域制限で視聴できません。"
    if "no space left" in lowered or "errno 28" in lowered:
        return "保存先の空き容量が不足しています。"
    if "filename too long" in lowered or ("path" in lowered and "too long" in lowered):
        return (
            "保存先のパスが長すぎます。ツール本体を C:\\ytool のような浅いフォルダへ"
            "移動してください。"
        )
    return ""


def download_one(
    url: str,
    out_dir: str | Path,
    hook: Callable[[dict[str, Any]], None],
    force_redownload: bool = False,
) -> str:
    logger = DownloadLogger()
    ydl_opts = {
        # Download YouTube's ready-made 1080p-or-lower stream instead of
        # downloading 4K and shrinking it locally. The final fallback keeps
        # downloads working for unusual videos that expose no <=1080p format.
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "merge_output_format": "mkv",
        "outtmpl": str(Path(out_dir) / "video.%(ext)s"),
        "progress_hooks": [hook],
        "logger": logger,
        # overwrites=True makes yt-dlp fetch the video again even when the
        # file already exists; used by the re-download checkbox in the UI.
        "overwrites": force_redownload,
        "noplaylist": True,
    }
    # The merge step needs ffmpeg. Relying on PATH broke downloads whenever the
    # app was started without start_app.bat, so point yt-dlp at it directly.
    bundled_ffmpeg = find_optional_ffmpeg_executable()
    if bundled_ffmpeg:
        ydl_opts["ffmpeg_location"] = bundled_ffmpeg
    # Without ignoreerrors, yt-dlp raises DownloadError instead of returning a
    # nonzero code, so the friendly-hint path must live in an except block.
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return_code = ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(
            download_failure_message(logger, str(exc))
        ) from exc
    if return_code:
        raise RuntimeError(
            download_failure_message(logger, f"終了コード {return_code}")
        )
    return "skipped" if logger.skipped else "success"


def download_failure_message(logger: DownloadLogger, fallback_detail: str) -> str:
    detail = logger.failure_detail() or ANSI_ESCAPE_RE.sub(
        "", fallback_detail
    ).strip()
    hint = explain_download_failure(detail)
    message = "ダウンロードに失敗しました。"
    if hint:
        message += f"\n\n{hint}"
    if detail:
        message += f"\n\nyt-dlp のメッセージ: {detail}"
    return message


def configured_api_key() -> tuple[str, str]:
    profile_key, profile_source = configured_profile_value("youtube_api_key")
    if profile_key:
        return profile_key, profile_source
    local_key = read_local_secret_value("YOUTUBE_API_KEY")
    if local_key:
        return local_key, ".streamlit/secrets.toml"
    try:
        secret_key = str(st.secrets.get("YOUTUBE_API_KEY", "")).strip()
    # Streamlit raises a version-dependent exception when no secrets file exists.
    # In that normal case, continue to the environment variable and UI fallbacks.
    except Exception:
        secret_key = ""
    if secret_key:
        return secret_key, ".streamlit/secrets.toml"
    env_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if env_key:
        return env_key, "環境変数 YOUTUBE_API_KEY"
    return "", ""


def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "search_results": [],
        "search_mode": "",
        "search_warnings": [],
        "selections": {},
        "download_results": [],
        "search_cache": {},
        "editor_revision": 0,
        "api_key_input": "",
        "openai_api_key_input": "",
        "active_page": "YouTube検索＆ダウンロード",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_initial_settings(expanded: bool = False) -> None:
    with st.expander("初期設定（APIキー / OpenAIキー / OAuth）", expanded=expanded):
        config = load_settings_profiles()
        profiles: dict[str, Any] = config["profiles"]
        profile_ids = list(profiles)
        active_profile_id = str(config["active_profile"])
        labels = [
            f"{profiles[profile_id].get('name', profile_id)} ({profile_id})"
            for profile_id in profile_ids
        ]
        selected_label = st.selectbox(
            "使用する設定プロファイル",
            labels,
            index=profile_ids.index(active_profile_id),
            help="複数のGoogleアカウント・ブランドチャンネルを使う場合は、プロファイルを分けると安全です。",
        )
        selected_profile_id = profile_ids[labels.index(selected_label)]
        if selected_profile_id != active_profile_id:
            config["active_profile"] = selected_profile_id
            save_settings_profiles(config)
            st.rerun()

        profile = dict(profiles[selected_profile_id])
        client_secret_value = profile_path_value(
            profile, "client_secret_path", DEFAULT_UPLOAD_CLIENT_SECRETS
        )
        token_value = profile_path_value(profile, "token_path", DEFAULT_UPLOAD_TOKEN)
        client_secret_path = resolve_profile_path(client_secret_value)
        token_path = resolve_profile_path(token_value)

        st.caption(
            "ここで保存した設定はプロファイルごとに `.streamlit` フォルダへ自動保存されます。"
            "空欄の項目は既存設定を上書きしません。"
        )
        status_cols = st.columns(4)
        status_cols[0].metric(
            "YouTube Data API v3",
            mask_secret(str(profile.get("youtube_api_key", ""))),
        )
        status_cols[1].metric(
            "OpenAI API",
            mask_secret(str(profile.get("openai_api_key", ""))),
        )
        status_cols[2].metric(
            "認証ファイル",
            "設定済み" if client_secret_path.is_file() else "未設定",
        )
        status_cols[3].metric(
            "ログイン状態",
            "認証済み" if token_path.is_file() else "未認証",
        )
        if not token_path.is_file():
            st.info(
                "「未認証」は異常ではありません。認証ファイルを保存しただけでは"
                "Googleへのログインは完了しません。下の「今すぐGoogleにログイン」を押すか、"
                "初回のアップロードを実行すると認証されます。"
            )

        with st.form("create_settings_profile_form"):
            new_profile_name = st.text_input(
                "新しいプロファイル名",
                placeholder="例: ブランドch / 検証用 / abcアカウント",
            )
            create_profile = st.form_submit_button("プロファイルを追加")
        if create_profile:
            name = new_profile_name.strip()
            if not name:
                st.error("プロファイル名を入力してください。")
            else:
                new_profile_id = make_profile_id(name)
                if new_profile_id in profiles:
                    st.error("同じ名前のプロファイルが既にあります。")
                else:
                    config["profiles"][new_profile_id] = {
                        "name": name,
                        "youtube_api_key": "",
                        "openai_api_key": "",
                        "client_secret_path": str(
                            profile_client_secret_path(new_profile_id)
                            .relative_to(APP_ROOT)
                        ),
                        "token_path": str(
                            profile_token_path(new_profile_id).relative_to(APP_ROOT)
                        ),
                    }
                    config["active_profile"] = new_profile_id
                    save_settings_profiles(config)
                    st.success(f"プロファイルを追加しました: {name}")
                    st.rerun()

        with st.form("initial_settings_form"):
            profile_name_input = st.text_input(
                "プロファイル表示名",
                value=str(profile.get("name", selected_profile_id)),
            )
            youtube_api_key_input = st.text_input(
                "YouTube Data API v3 キー",
                type="password",
                help="検索に使うAPIキーです。空欄ならこのプロファイルの保存済みキーを変更しません。",
            )
            openai_api_key_input = st.text_input(
                "OpenAI APIキー",
                type="password",
                help="要約・タイトル案・サムネイル生成に使います。空欄ならこのプロファイルの保存済みキーを変更しません。",
            )
            oauth_json_file = st.file_uploader(
                "YouTubeアップロード用の認証ファイル",
                type=["json"],
                help="Google CloudでダウンロードしたJSONファイルを選択します。",
            )
            save_settings = st.form_submit_button("このプロファイルに設定を保存", type="primary")

        if save_settings:
            saved_messages: list[str] = []
            try:
                profile["name"] = profile_name_input.strip() or str(
                    profile.get("name", selected_profile_id)
                )
                if youtube_api_key_input.strip():
                    profile["youtube_api_key"] = youtube_api_key_input.strip()
                    saved_messages.append("YouTube Data API v3キー")
                if openai_api_key_input.strip():
                    profile["openai_api_key"] = openai_api_key_input.strip()
                    saved_messages.append("OpenAI APIキー")
                if oauth_json_file is not None:
                    target_path = client_secret_path
                    if selected_profile_id != "default":
                        target_path = profile_client_secret_path(selected_profile_id)
                        profile["client_secret_path"] = str(
                            target_path.relative_to(APP_ROOT)
                        )
                        profile["token_path"] = str(
                            profile_token_path(selected_profile_id).relative_to(APP_ROOT)
                        )
                    save_oauth_client_secret(oauth_json_file.getvalue(), target_path)
                    saved_messages.append("YouTubeアップロード用の認証ファイル")
                profiles[selected_profile_id] = profile
                config["profiles"] = profiles
                save_settings_profiles(config)
            except Exception as exc:
                st.error(f"設定保存に失敗しました: {exc}")
            else:
                if saved_messages:
                    st.success("保存しました: " + " / ".join(saved_messages))
                else:
                    st.success("プロファイル情報を保存しました。")
                st.rerun()

        st.write("このプロファイルの保存先")
        st.code(
            "\n".join(
                [
                    f"プロファイル設定: {settings_profiles_file_path()}",
                    f"認証ファイル: {client_secret_path}",
                    f"ログイン状態の保存先: {token_path}",
                ]
            )
        )
        if token_path.is_file():
            st.warning(
                "ログイン済みの情報があります。投稿先チャンネルを変えたい場合は、"
                "下のボタンで削除してから再認証してください。"
            )
            if st.button("ログインをやり直す"):
                token_path.unlink(missing_ok=True)
                st.success("ログイン情報を削除しました。次回アップロード時に再ログインします。")
                st.rerun()
        else:
            st.caption(
                "ボタンを押すとブラウザが開きます。Googleアカウントを選び、"
                "「許可」まで進めてください（アップロード前に済ませておけます）。"
            )
            if st.button(
                "今すぐGoogleにログイン",
                type="primary",
                disabled=not client_secret_path.is_file(),
            ):
                if not client_secret_path.is_file():
                    st.error("先に認証ファイル（OAuthクライアントJSON）を保存してください。")
                else:
                    with st.spinner("ブラウザで認証を完了してください..."):
                        try:
                            youtube_upload_service(client_secret_path, token_path)
                        except Exception as exc:
                            st.error(f"ログインに失敗しました: {exc}")
                            st.info(describe_oauth_login_error(exc))
                        else:
                            st.success("ログインしました。「認証済み」に変わります。")
                            st.rerun()

        st.divider()
        st.write("プロファイル削除")
        delete_files = st.checkbox(
            "認証ファイルとログイン情報も一緒に削除する",
            value=True,
            help="不要になったアカウント・チャンネル設定を残したくない場合はONにします。",
        )
        if len(profiles) <= 1:
            st.caption("プロファイルは最低1つ必要なため、最後の1件は削除できません。")
        if st.button(
            "選択中のプロファイルを削除",
            disabled=len(profiles) <= 1,
            type="secondary",
        ):
            if delete_files:
                client_secret_path.unlink(missing_ok=True)
                token_path.unlink(missing_ok=True)
                profile_dir = client_secret_path.parent
                try:
                    profile_dir.rmdir()
                except OSError:
                    pass
            deleted_name = str(profile.get("name", selected_profile_id))
            profiles.pop(selected_profile_id, None)
            config["profiles"] = profiles
            config["active_profile"] = next(iter(profiles))
            save_settings_profiles(config)
            st.success(f"プロファイルを削除しました: {deleted_name}")
            st.rerun()


DOWNLOADED_MARK = "🔴 ダウンロード済み"


def result_dataframe(
    results: list[dict[str, Any]],
    selected: dict[str, bool],
    mode: str,
    downloaded_ids: set[str],
) -> pd.DataFrame:
    rows = []
    for rank, result in enumerate(results, start=1):
        row = {
            "選択": bool(selected.get(result["videoId"], False)),
            "状態": (
                DOWNLOADED_MARK if result["videoId"] in downloaded_ids else ""
            ),
            "順位": rank,
            "サムネイル": result["thumbnailUrl"],
            "タイトル": result["title"],
            "再生時間": result["durationText"],
            "再生回数": result["viewCount"],
            "チャンネル名": result["channelTitle"],
            "URL": result["url"],
            "アップロード日": result["publishedAt"],
            "_videoId": result["videoId"],
        }
        if mode == "buzzRatio":
            row["登録者数"] = result["subCount"]
            row["倍率"] = result["ratio"]
        rows.append(row)
    return pd.DataFrame(rows)


def render_search_form(api_key: str) -> None:
    current_year = datetime.now().year
    with st.form("search_form"):
        keyword = st.text_input("検索キーワード")
        mode_label = st.radio(
            "取得モード",
            list(MODE_OPTIONS),
            horizontal=True,
        )
        year_columns = st.columns(2)
        start_year = int(
            year_columns[0].number_input(
                "開始年",
                min_value=2005,
                max_value=current_year,
                value=max(2005, current_year - 2),
                step=1,
            )
        )
        end_year = int(
            year_columns[1].number_input(
                "終了年",
                min_value=2005,
                max_value=current_year,
                value=current_year,
                step=1,
            )
        )
        submitted = st.form_submit_button("検索", type="primary")

    if not submitted:
        return
    keyword = keyword.strip()
    if not api_key:
        st.error("YouTube Data API キーを入力してください。")
        return
    if not keyword:
        st.error("検索キーワードを入力してください。")
        return
    if start_year > end_year:
        st.error("開始年は終了年以前にしてください。")
        return

    mode = MODE_OPTIONS[mode_label]
    key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
    cache_key = (keyword, mode, start_year, end_year, key_fingerprint)
    cached = st.session_state.search_cache.get(cache_key)
    if cached is not None:
        results, warnings = cached
        st.info("同じ検索条件の保存済み結果を再利用しました（API消費なし）。")
    else:
        with st.spinner(
            f"{end_year - start_year + 1}年分を検索しています"
            f"（推定 {100 * (end_year - start_year + 1):,} ユニット）..."
        ):
            try:
                results, warnings = search_youtube(
                    api_key,
                    keyword,
                    mode,
                    start_year,
                    end_year,
                )
            except HttpError as exc:
                st.error(describe_api_error(exc))
                return
            except Exception as exc:
                st.error(f"検索を開始できませんでした: {exc}")
                return
        st.session_state.search_cache[cache_key] = (results, warnings)

    st.session_state.search_results = results
    st.session_state.search_mode = mode
    st.session_state.search_warnings = warnings
    st.session_state.selections = {
        result["videoId"]: False for result in results
    }
    st.session_state.download_results = []
    st.session_state.editor_revision += 1


def render_results() -> None:
    all_results: list[dict[str, Any]] = st.session_state.search_results
    for warning in st.session_state.search_warnings:
        st.warning(warning)
    if not all_results:
        if st.session_state.search_mode:
            st.info("条件に一致する動画はありませんでした。")
        return

    output_dir = st.text_input("出力先フォルダ", value="./downloads")
    resolved_output_dir = resolve_output_dir(output_dir)
    downloaded_video_ids = load_downloaded_video_ids(resolved_output_dir)
    # Downloaded videos stay visible with a mark instead of being hidden, so
    # users can see what they already have and re-download when needed.
    results = all_results
    saved_result_count = sum(
        result["videoId"] in downloaded_video_ids for result in results
    )
    st.subheader(f"検索結果（{len(results)}件）")
    if saved_result_count:
        st.caption(
            f"{DOWNLOADED_MARK} の {saved_result_count}件はダウンロード済みです"
            f"（保存先: {resolved_output_dir}）。"
            "もう一度ダウンロードしたい場合は、選択してから下の"
            "「再ダウンロード」をオンにしてください。"
        )
    st.markdown("#### 動画の言語を選択")
    st.caption(
        "英語動画を選ぶと、英語音声・字幕を日本語へ翻訳し、"
        "読みやすく調整した日本語字幕を動画へ付けます。"
    )
    video_language_label = st.radio(
        "動画の言語",
        VIDEO_LANGUAGE_OPTIONS,
        index=0,
        horizontal=True,
        label_visibility="collapsed",
        help="英語動画を選ぶと、英語字幕を日本語へ翻訳して動画に表示します。",
    )
    is_english_video = video_language_label == "英語動画"
    with st.expander("ダウンロード後処理（字幕・要約・タイトル案・サムネイル）", expanded=False):
        if is_english_video:
            fetch_subtitles = True
            custom_language_value = "en"
            st.info(
                "英語の手動字幕を優先し、なければ英語の自動字幕を使います。"
                "字幕がない場合は音声から英語を文字起こしし、AIで校正してから日本語へ翻訳します。"
                "音声認識・校正・翻訳にはOpenAI APIキー、動画処理にはFFmpegを使います。"
            )
            force_audio_transcription = st.checkbox(
                "YouTube字幕があっても音声から文字起こしする（テスト用）",
                value=False,
                help=(
                    "音声認識APIの動作を確認したい場合だけオンにします。"
                    "通常よりOpenAI APIの処理と料金が増えます。"
                ),
            )
        else:
            fetch_subtitles = st.checkbox(
                "YouTube字幕・自動字幕を取得して transcript.txt を作成する",
                value=True,
                help="日本語字幕があれば優先して使い、なければ自動字幕を探します。",
            )
            language_label = st.selectbox(
                "字幕の優先言語",
                list(SUBTITLE_LANGUAGE_OPTIONS),
                index=0,
                disabled=not fetch_subtitles,
            )
            language_value = SUBTITLE_LANGUAGE_OPTIONS[language_label]
            custom_language_value = st.text_input(
                "字幕言語を直接指定（任意・例: ja,en）",
                value=language_value,
                disabled=not fetch_subtitles,
            )
            force_audio_transcription = False
        create_summary = st.checkbox(
            "取得した文字起こしから要約・タイトル案を作成する（OpenAI API使用）",
            value=True,
            disabled=not fetch_subtitles,
        )
        create_thumbnail = st.checkbox(
            "要約をもとにサムネイル画像PNGを生成する（OpenAI API使用）",
            value=True,
            disabled=not create_summary,
            help=(
                "動画内容、要約、数字・金額・比較ポイントをもとに、"
                "16:9のサムネイル用画像を作成します。"
            ),
        )
        openai_key, openai_source = configured_openai_key()
        if openai_source:
            st.caption(f"OpenAI APIキー: {openai_source} から読み込みます。")
        else:
            openai_key = st.text_input(
                "OpenAI APIキー",
                type="password",
                key="openai_api_key_input",
                disabled=not (create_summary or is_english_video),
                help="要約・タイトル案、英語字幕の日本語翻訳に使います。",
            ).strip()
        openai_model = st.text_input(
            "OpenAIモデル",
            value=DEFAULT_OPENAI_MODEL,
            disabled=not (create_summary or is_english_video),
        )
        st.caption(
            "既定では要約・タイトル案・サムネイルを作成します。"
            "OpenAI APIキーが未設定の場合、日本語動画では字幕取得と動画保存だけ行います。"
            "英語動画ではYouTube字幕があれば原文字幕まで保存しますが、"
            "字幕がない場合の音声認識と日本語翻訳は行いません。"
        )
    # Disabled (grayed-out) checkboxes still report their last value, so gate
    # each step on its prerequisite; otherwise turning subtitles off left
    # create_summary True and every download was reported as "一部失敗".
    effective_create_summary = create_summary and fetch_subtitles
    effective_create_thumbnail = create_thumbnail and effective_create_summary
    postprocess_options = {
        "video_language": "en" if is_english_video else "ja",
        "force_audio_transcription": force_audio_transcription,
        "fetch_subtitles": fetch_subtitles,
        "language_codes": parse_language_codes(custom_language_value),
        "create_summary": effective_create_summary,
        "create_thumbnail": effective_create_thumbnail,
        "openai_api_key": openai_key,
        "openai_model": openai_model,
    }
    select_col, clear_col, count_col = st.columns([1, 1, 4])
    if select_col.button("全選択"):
        st.session_state.selections = {
            result["videoId"]: True for result in results
        }
        st.session_state.editor_revision += 1
        st.rerun()
    if clear_col.button("全解除"):
        st.session_state.selections = {
            result["videoId"]: False for result in results
        }
        st.session_state.editor_revision += 1
        st.rerun()

    frame = result_dataframe(
        results,
        st.session_state.selections,
        st.session_state.search_mode,
        downloaded_video_ids,
    )
    column_config: dict[str, Any] = {
        "選択": st.column_config.CheckboxColumn("選択"),
        "状態": st.column_config.TextColumn("状態", width="small"),
        "順位": st.column_config.NumberColumn("順位", format="%d"),
        "サムネイル": st.column_config.ImageColumn("サムネイル"),
        "再生回数": st.column_config.NumberColumn("再生回数", format="%d"),
        "URL": st.column_config.LinkColumn("URL", display_text="YouTubeを開く"),
    }
    if st.session_state.search_mode == "buzzRatio":
        column_config["登録者数"] = st.column_config.NumberColumn(
            "登録者数", format="%d"
        )
        column_config["倍率"] = st.column_config.NumberColumn(
            "倍率", format="%.2f"
        )
    edited = st.data_editor(
        frame,
        key=f"result_editor_{st.session_state.editor_revision}",
        column_config=column_config,
        disabled=[column for column in frame.columns if column != "選択"],
        hide_index=True,
        width="stretch",
        row_height=90,
        column_order=[
            column for column in frame.columns if column != "_videoId"
        ],
    )
    st.session_state.selections = {
        str(row["_videoId"]): bool(row["選択"])
        for _, row in edited.iterrows()
    }
    selected_results = [
        result
        for result in results
        if st.session_state.selections.get(result["videoId"], False)
    ]
    count_col.caption(f"{len(selected_results)}件を選択中")

    selected_downloaded_count = sum(
        result["videoId"] in downloaded_video_ids for result in selected_results
    )
    force_redownload = False
    if selected_downloaded_count:
        force_redownload = st.checkbox(
            f"ダウンロード済みの{selected_downloaded_count}件を再ダウンロードする（動画ファイルを上書き）",
            value=False,
            help=(
                "オフのままだと、ダウンロード済みの動画はスキップされます"
                "（字幕・要約などの後処理だけやり直せます）。"
                "オンにすると動画ファイルを取り直して上書きします。"
            ),
        )

    if st.button(
        "選択した動画をダウンロード",
        type="primary",
        disabled=not selected_results,
    ):
        run_downloads(
            selected_results,
            output_dir,
            postprocess_options,
            force_redownload=force_redownload,
        )

    if st.session_state.download_results:
        st.subheader("ダウンロード結果")
        labels = {
            "success": "成功",
            "partial": "一部失敗",
            "failed": "失敗",
            "skipped": "スキップ",
        }
        display_results = [
            {
                "結果": labels.get(item["status"], item["status"]),
                "タイトル": item["title"],
                "詳細": item["detail"],
            }
            for item in st.session_state.download_results
        ]
        st.dataframe(display_results, hide_index=True, width="stretch")


def run_downloads(
    selected_results: list[dict[str, Any]],
    output_dir_value: str,
    postprocess_options: dict[str, Any],
    force_redownload: bool = False,
) -> None:
    if not output_dir_value.strip():
        st.error("出力先フォルダを入力してください。")
        return
    output_dir = Path(output_dir_value).expanduser()
    if not output_dir.is_absolute():
        output_dir = APP_ROOT / output_dir
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not output_dir.is_dir():
            raise NotADirectoryError(str(output_dir))
    except OSError as exc:
        st.error(f"出力先フォルダを作成できません: {exc}")
        return

    download_results: list[dict[str, str]] = []
    overall_progress = st.progress(0.0, text="ダウンロードを開始します...")
    with st.status("ダウンロード中...", expanded=True) as status_box:
        total = len(selected_results)
        for index, video in enumerate(selected_results, start=1):
            title = video["title"]
            video_dir = video_workspace_dir(output_dir, video)
            status_box.write(f"{index}/{total}: {title}")

            def hook(
                data: dict[str, Any],
                *,
                current=index,
                current_title=title,
            ) -> None:
                if data.get("status") != "downloading":
                    return
                downloaded = float(data.get("downloaded_bytes") or 0)
                expected = float(
                    data.get("total_bytes")
                    or data.get("total_bytes_estimate")
                    or 0
                )
                item_progress = min(downloaded / expected, 1.0) if expected else 0.0
                combined = ((current - 1) + item_progress) / total
                st.session_state.current_download_progress = combined
                overall_progress.progress(
                    combined,
                    text=f"{current}/{total}: {current_title}",
                )

            try:
                video_dir.mkdir(parents=True, exist_ok=True)
                write_upload_metadata(video_dir, video, status="downloading")
                outcome = download_one(
                    video["url"],
                    video_dir,
                    hook,
                    force_redownload=force_redownload,
                )
                record_downloaded_video(output_dir, video)
                write_upload_metadata(video_dir, video, status="downloaded")
                detail_parts = [
                    (
                        "動画は既に保存済みでした。"
                        if outcome == "skipped"
                        else "動画を保存しました。"
                    )
                ]
                row_status = "skipped" if outcome == "skipped" else "success"
                transcript = ""
                summary_text = ""
                video_language = str(
                    postprocess_options.get("video_language") or "ja"
                )
                if video_language == "en":
                    try:
                        english_result = process_english_video_subtitles(
                            video,
                            video_dir,
                            str(postprocess_options.get("openai_api_key") or ""),
                            str(postprocess_options.get("openai_model") or ""),
                            progress_callback=lambda message: status_box.write(
                                f"　{message}"
                            ),
                            force_audio_transcription=bool(
                                postprocess_options.get("force_audio_transcription")
                            ),
                        )
                        if english_result["status"] == "success":
                            transcript = str(english_result.get("transcript", ""))
                            detail_parts.append(
                                f"英語→日本語字幕: {english_result['detail']}"
                            )
                            row_status = "success"
                        else:
                            detail_parts.append(
                                f"英語→日本語字幕: {english_result['detail']}"
                            )
                            row_status = "partial"
                    except Exception as exc:
                        detail_parts.append(f"英語→日本語字幕: 失敗（{exc}）")
                        row_status = "partial"
                        transcript_path = video_dir / "transcript_en.txt"
                        if transcript_path.is_file():
                            transcript = transcript_path.read_text(
                                encoding="utf-8"
                            ).strip()
                elif postprocess_options.get("fetch_subtitles"):
                    try:
                        subtitle_result = fetch_subtitle_transcript(
                            video,
                            video_dir,
                            postprocess_options.get("language_codes") or ["ja"],
                        )
                        if subtitle_result["status"] == "success":
                            transcript = str(subtitle_result.get("transcript", ""))
                            detail_parts.append(
                                f"字幕: {subtitle_result['detail']}"
                            )
                            row_status = "success"
                        elif subtitle_result["status"] == "skipped":
                            detail_parts.append(
                                f"字幕: {subtitle_result['detail']}"
                            )
                        else:
                            detail_parts.append(
                                f"字幕: {subtitle_result['detail']}"
                            )
                            row_status = "partial"
                    except Exception as exc:
                        detail_parts.append(f"字幕: 失敗（{exc}）")
                        row_status = "partial"

                if postprocess_options.get("create_summary"):
                    openai_api_key = str(
                        postprocess_options.get("openai_api_key") or ""
                    ).strip()
                    if not transcript:
                        detail_parts.append(
                            "要約: 文字起こしがないため作成しませんでした。"
                        )
                        row_status = "partial"
                    elif not openai_api_key:
                        detail_parts.append(
                            "要約: OpenAI APIキーが未入力のため作成しませんでした。"
                        )
                        row_status = "partial"
                    else:
                        try:
                            summary_result = generate_summary_and_titles(
                                video,
                                transcript,
                                video_dir,
                                openai_api_key,
                                str(postprocess_options.get("openai_model") or ""),
                            )
                            detail_parts.append(
                                f"要約: {summary_result['detail']}"
                            )
                            summary_text = str(summary_result.get("summary", ""))
                        except Exception as exc:
                            detail_parts.append(f"要約: 失敗（{exc}）")
                            row_status = "partial"

                if postprocess_options.get("create_thumbnail"):
                    openai_api_key = str(
                        postprocess_options.get("openai_api_key") or ""
                    ).strip()
                    if not transcript:
                        detail_parts.append(
                            "サムネイル: 文字起こしがないため作成しませんでした。"
                        )
                        row_status = "partial"
                    elif not openai_api_key:
                        detail_parts.append(
                            "サムネイル: OpenAI APIキーが未入力のため作成しませんでした。"
                        )
                        row_status = "partial"
                    elif not summary_text:
                        detail_parts.append(
                            "サムネイル: 要約がないため作成しませんでした。"
                        )
                        row_status = "partial"
                    else:
                        try:
                            thumbnail_result = generate_thumbnail_image(
                                video,
                                transcript,
                                summary_text,
                                video_dir,
                                openai_api_key,
                                str(postprocess_options.get("openai_model") or ""),
                            )
                            detail_parts.append(
                                f"サムネイル: {thumbnail_result['detail']}"
                            )
                        except Exception as exc:
                            detail_parts.append(f"サムネイル: 失敗（{exc}）")
                            row_status = "partial"
                detail = " / ".join(detail_parts)
                download_results.append(
                    {"status": row_status, "title": title, "detail": detail}
                )
                status_box.write(
                    f"{'⚠️' if row_status == 'partial' else '✅'} {detail}"
                )
            except Exception as exc:
                download_results.append(
                    {
                        "status": "failed",
                        "title": title,
                        "detail": str(exc),
                    }
                )
                status_box.write(f"❌ 失敗: {exc}")
            overall_progress.progress(
                index / total,
                text=f"{index}/{total}件を処理しました。",
            )
            st.session_state.download_results = list(download_results)

        failures = sum(item["status"] == "failed" for item in download_results)
        if failures:
            status_box.update(
                label=f"完了（{failures}件失敗）",
                state="error",
                expanded=True,
            )
            status_box.write(
                "うまくいかない場合は「アカウント設定」ページの「環境チェック」を開いて、"
                "❌が付いている項目を先に解消してください。"
            )
        else:
            status_box.update(label="すべて完了しました。", state="complete")

    # Untick processed rows; the rows now stay visible (with the downloaded
    # mark) instead of disappearing, so a stale selection would otherwise
    # invite an accidental second download. Failed rows keep their tick so
    # the user can fix the cause and immediately retry.
    # download_results has exactly one row per selected video (in order).
    for video, row in zip(selected_results, download_results):
        if row["status"] != "failed":
            st.session_state.selections[video["videoId"]] = False
    st.session_state.editor_revision += 1
    # Without an immediate rerun the table (rendered before the downloads
    # started) kept showing the old ticks until the user's next click — which
    # read as "my checkboxes never clear" and risked accidental re-downloads.
    st.rerun()


def render_upload_section() -> None:
    st.subheader("YouTubeアップロード")
    st.caption(
        "自分の動画、許可済み素材、再利用可能な素材だけをアップロードしてください。"
        "初期設定は安全のため非公開です。"
    )
    _profile_id, active_profile, _config = current_settings_profile()
    profiles: dict[str, Any] = _config["profiles"]
    profile_ids = list(profiles)
    profile_labels = [
        f"{profiles[profile_id].get('name', profile_id)} ({profile_id})"
        for profile_id in profile_ids
    ]
    selected_profile_label = st.selectbox(
        "アップロードに使うアカウント / 設定プロファイル",
        profile_labels,
        index=profile_ids.index(_profile_id),
        key="upload_profile_selector",
        help=(
            "アカウント設定ページで登録したプロファイルから選びます。"
            "ここで選んだアカウント設定でアップロードします。"
        ),
    )
    selected_profile_id = profile_ids[profile_labels.index(selected_profile_label)]
    if selected_profile_id != _profile_id:
        _config["active_profile"] = selected_profile_id
        save_settings_profiles(_config)
        st.rerun()

    _profile_id = selected_profile_id
    active_profile = dict(profiles[_profile_id])
    upload_client_secret_default = profile_path_value(
        active_profile, "client_secret_path", DEFAULT_UPLOAD_CLIENT_SECRETS
    )
    upload_token_default = profile_path_value(
        active_profile, "token_path", DEFAULT_UPLOAD_TOKEN
    )
    upload_client_secret_path = resolve_profile_path(upload_client_secret_default)
    upload_token_path = resolve_profile_path(upload_token_default)
    status_cols = st.columns(3)
    status_cols[0].metric("使用プロファイル", str(active_profile.get("name", _profile_id)))
    status_cols[1].metric(
        "認証ファイル",
        "設定済み" if upload_client_secret_path.is_file() else "未設定",
    )
    status_cols[2].metric(
        "ログイン状態",
        "認証済み" if upload_token_path.is_file() else "未認証",
    )
    output_dir_value = st.text_input(
        "アップロード対象フォルダ",
        value="./downloads",
        key="upload_output_dir",
    )
    output_dir = resolve_output_dir(output_dir_value)
    items = detect_upload_items(output_dir)
    if not items:
        st.info("アップロード候補が見つかりません。まず動画をダウンロードして素材を作成してください。")
        return

    labels = []
    for index, item in enumerate(items, start=1):
        uploaded = " / 投稿済み" if item.get("uploaded_video_id") else ""
        labels.append(f"{index}. {item['title']}{uploaded}")
    selected_label = st.selectbox("投稿する動画セット", labels)
    selected_index = labels.index(selected_label)
    item = items[selected_index]

    video_path = Path(item["video_path"])
    summary_path = Path(item["summary_path"])
    thumbnail_path = Path(item["thumbnail_path"])
    summary_text = read_text_file(summary_path) if summary_path.is_file() else ""
    title_candidates = extract_title_candidates(summary_text)
    generated_description = extract_summary_description(summary_text)
    hashtags = extract_hashtags(summary_text, str(item["title"]))
    default_title = title_candidates[0] if title_candidates else str(item["title"])[:100]
    item_key = hashlib.md5(str(video_path).encode("utf-8")).hexdigest()[:12]
    preview_state_key = f"youtube_upload_preview_{item_key}"

    st.write(f"動画ファイル: `{video_path}`")
    cols = st.columns([1, 2])
    with cols[0]:
        if thumbnail_path.is_file():
            st.image(str(thumbnail_path), caption="サムネイル", width="stretch")
            st.caption(f"サイズ: {thumbnail_path.stat().st_size / 1024 / 1024:.2f} MB")
        else:
            st.warning("サムネイル画像が見つかりません。")
    with cols[1]:
        if summary_path.is_file():
            st.success(f"summary.md を読み込みました: {summary_path.name}")
        else:
            st.warning("summary.md が見つかりません。タイトル・説明欄は手動入力してください。")
        if item.get("uploaded_video_id"):
            st.info(
                "この素材は投稿済みです: "
                f"https://www.youtube.com/watch?v={item['uploaded_video_id']}"
            )

    transcript_path = Path(item["transcript_path"])
    transcript_text = read_text_file(transcript_path) if transcript_path.is_file() else ""

    with st.expander("要約・タイトル案を後から生成", expanded=not summary_path.is_file()):
        st.caption(
            "ダウンロード時に生成できなかった場合でも、文字起こしが保存されていれば後から作成できます。"
            "生成結果は summary.md に保存されます。"
        )
        st.write(f"保存先: `{summary_path}`")
        summary_openai_key, summary_openai_source = configured_openai_key()
        if summary_openai_source:
            st.caption(f"OpenAI APIキー: {summary_openai_source} から読み込みます。")
        else:
            summary_openai_key = st.text_input(
                "OpenAI APIキー（要約生成用）",
                type="password",
                key=f"late_summary_openai_key_{item_key}",
            ).strip()
        summary_model = st.text_input(
            "要約生成モデル",
            value=DEFAULT_OPENAI_MODEL,
            key=f"late_summary_model_{item_key}",
        )
        if summary_path.is_file():
            st.info("summary.md は既にあります。再生成すると上書きされます。")
        if not transcript_text.strip():
            st.warning("transcript.txt が必要です。字幕取得に失敗している場合は後から生成できません。")
        can_generate_summary_later = bool(summary_openai_key.strip() and transcript_text.strip())
        if st.button(
            "要約・タイトル案を生成する",
            disabled=not can_generate_summary_later,
            key=f"generate_summary_later_{item_key}",
        ):
            with st.spinner("要約・タイトル案を生成しています..."):
                try:
                    result = generate_summary_and_titles(
                        {"title": str(item["title"])},
                        transcript_text,
                        Path(item["folder"]),
                        summary_openai_key,
                        summary_model,
                        summary_path=summary_path,
                    )
                    save_upload_metadata_for_item(
                        item,
                        {
                            "summaryGeneratedAt": datetime.now().isoformat(
                                timespec="seconds"
                            ),
                            "summaryPath": result["summary_path"],
                        },
                    )
                except Exception as exc:
                    st.error(f"要約・タイトル案の生成に失敗しました: {exc}")
                else:
                    st.success("要約・タイトル案を生成しました。")
                    st.rerun()

    with st.expander("サムネイルだけ再生成", expanded=False):
        regen_output_dir, regen_thumbnail_path, regen_prompt_path = thumbnail_regeneration_paths(item)
        st.caption(
            "選択中の素材の summary.md / transcript.txt を使って、サムネイル画像だけを再生成します。"
            "既存のサムネイルは上書きされます。"
        )
        st.write(f"再生成先: `{regen_thumbnail_path}`")
        st.write(f"プロンプト保存先: `{regen_prompt_path}`")
        regen_openai_key, regen_openai_source = configured_openai_key()
        if regen_openai_source:
            st.caption(f"OpenAI APIキー: {regen_openai_source} から読み込みます。")
        else:
            regen_openai_key = st.text_input(
                "OpenAI APIキー（サムネイル再生成用）",
                type="password",
                key=f"regen_openai_key_{item_key}",
            ).strip()
        regen_model = st.text_input(
            "サムネイル再生成モデル",
            value=DEFAULT_OPENAI_MODEL,
            key=f"regen_openai_model_{item_key}",
        )
        can_regenerate_thumbnail = bool(
            regen_openai_key.strip() and (summary_text.strip() or transcript_text.strip())
        )
        if not summary_text.strip() and not transcript_text.strip():
            st.warning("summary.md または transcript.txt が必要です。")
        if st.button(
            "サムネイルを再生成する",
            disabled=not can_regenerate_thumbnail,
            key=f"regenerate_thumbnail_{item_key}",
        ):
            with st.spinner("サムネイルを再生成しています..."):
                try:
                    result = generate_thumbnail_image(
                        {"title": str(item["title"])},
                        transcript_text,
                        summary_text,
                        regen_output_dir,
                        regen_openai_key,
                        regen_model,
                        thumbnail_path=regen_thumbnail_path,
                        prompt_path=regen_prompt_path,
                    )
                    save_upload_metadata_for_item(
                        item,
                        {
                            "thumbnailRegeneratedAt": datetime.now().isoformat(
                                timespec="seconds"
                            ),
                            "thumbnailPath": result["thumbnail_path"],
                            "thumbnailPromptPath": result["prompt_path"],
                        },
                    )
                except Exception as exc:
                    st.error(f"サムネイル再生成に失敗しました: {exc}")
                else:
                    st.success("サムネイルを再生成しました。")
                    st.rerun()

    with st.form("youtube_upload_form"):
        if title_candidates:
            title_choice = st.selectbox("タイトル候補", title_candidates)
        else:
            title_choice = default_title
            st.caption("タイトル候補がないため、元タイトルを使います。")
        initial_title = default_title[:100]
        manual_title = st.text_input(
            "投稿タイトル（手動で上書きする場合）",
            value=initial_title,
            max_chars=100,
            help=(
                "この欄を初期値のままにしている場合は、上で選択したタイトル候補を使います。"
                "手動で編集した場合は、この欄の内容を優先します。"
            ),
        )
        manual_title_changed = manual_title.strip() != initial_title.strip()
        title = manual_title.strip() if manual_title_changed else str(title_choice).strip()[:100]
        st.caption(f"実際に使うタイトル: {title}")

        include_generated_summary = st.checkbox("説明欄に生成要約文を入れる", value=True)
        generated_summary_input = st.text_area(
            "生成要約文",
            value=generated_description,
            height=180,
        )
        fixed_text = st.text_area(
            "毎回入れたい固定文章（誘導リンク・注意書きなど）",
            value=load_upload_template(),
            height=160,
        )
        hashtags_input = st.text_input("説明欄ハッシュタグ", value=hashtags)
        description_preview = build_description(
            generated_summary_input,
            fixed_text,
            hashtags_input,
            include_summary=include_generated_summary,
        )

        tag_default = ", ".join(parse_tags(hashtags_input))
        tags_input = st.text_input("動画タグ（カンマ区切り）", value=tag_default)
        privacy_labels = list(PRIVACY_OPTIONS) + [SCHEDULE_PRIVACY_LABEL]
        privacy_label = st.selectbox("公開設定", privacy_labels, index=0)
        scheduled_publish_at = ""
        if privacy_label == SCHEDULE_PRIVACY_LABEL:
            schedule_cols = st.columns([1, 1, 1.4])
            schedule_date = schedule_cols[0].date_input(
                "予約公開日",
                value=(datetime.now() + timedelta(days=1)).date(),
                min_value=datetime.now().date(),
            )
            schedule_time = schedule_cols[1].time_input(
                "予約公開時刻",
                value=time(20, 0),
                step=900,
            )
            schedule_timezone = schedule_cols[2].selectbox(
                "タイムゾーン",
                list(SCHEDULE_TIMEZONE_OPTIONS),
                index=0,
            )
            scheduled_publish_at = scheduled_publish_iso(
                schedule_date,
                schedule_time,
                schedule_timezone,
            )
            st.caption(
                "指定した日時になると公開されます。アップロード直後は非公開で保存されます。"
            )
        effective_privacy_status = (
            "private"
            if privacy_label == SCHEDULE_PRIVACY_LABEL
            else PRIVACY_OPTIONS[privacy_label]
        )
        st.info(
            "コメント欄のON/OFF、収益化、終了画面、カード、字幕、詳細な年齢制限や"
            "視聴者設定など、このツールで設定できない項目はアップロード後に"
            "YouTube Studioで手動確認・設定してください。"
        )
        with st.expander("詳細設定（通常は変更不要）", expanded=False):
            client_secret_value = st.text_input(
                "認証ファイル",
                value=upload_client_secret_default,
                help="通常はアカウント設定で保存したものを自動で使います。",
            )
            token_value = st.text_input(
                "ログイン状態の保存先",
                value=upload_token_default,
                help="通常は変更しないでください。",
            )
        preview_submitted = st.form_submit_button("プレビュー表示")
        save_template = st.form_submit_button("固定文章テンプレートを保存")
        upload_submitted = st.form_submit_button("YouTubeに非公開/設定どおりアップロード", type="primary")

    if preview_submitted:
        st.session_state[preview_state_key] = {
            "title": title,
            "description": description_preview,
            "tags": parse_tags(tags_input),
            "privacyLabel": privacy_label,
            "privacyStatus": effective_privacy_status,
            "scheduledPublishAt": scheduled_publish_at,
        }

    preview_data = st.session_state.get(preview_state_key)
    if preview_data:
        st.markdown("#### アップロード内容プレビュー")
        st.text_input(
            "プレビュー: 投稿タイトル",
            value=preview_data["title"],
            disabled=True,
            key=f"preview_title_{item_key}",
        )
        st.text_area(
            "プレビュー: 最終説明欄",
            value=preview_data["description"],
            height=260,
            disabled=True,
            key=f"preview_description_{item_key}",
        )
        st.caption(
            " / ".join(
                part
                for part in [
                    f"公開設定: {preview_data['privacyLabel']}",
                    (
                        f"予約公開: {preview_data['scheduledPublishAt']}"
                        if preview_data.get("scheduledPublishAt")
                        else ""
                    ),
                    f"タグ: {', '.join(preview_data['tags']) or 'なし'}",
                ]
                if part
            )
        )
    else:
        st.info("入力内容を確認するには「プレビュー表示」を押してください。")

    if save_template:
        save_upload_template(fixed_text)
        st.success("固定文章テンプレートを保存しました。")

    if upload_submitted:
        client_secret_path = Path(client_secret_value)
        token_path = Path(token_value)
        if not client_secret_path.is_absolute():
            client_secret_path = APP_ROOT / client_secret_path
        if not token_path.is_absolute():
            token_path = APP_ROOT / token_path
        if not title.strip():
            st.error("投稿タイトルを入力してください。")
            return
        if not video_path.exists():
            st.error(f"動画ファイルが見つかりません: {video_path}")
            return
        if scheduled_publish_at and not is_future_publish_time(scheduled_publish_at):
            st.error("予約公開日時は、現在時刻より少し先の日時にしてください。")
            return
        save_upload_metadata_for_item(
            item,
            {
                "selectedTitle": title.strip(),
                "description": description_preview,
                "tags": parse_tags(tags_input),
                "privacyStatus": effective_privacy_status,
                "scheduledPublishAt": scheduled_publish_at,
            },
        )
        progress = st.progress(0.0, text="アップロード準備中...")
        try:
            result = upload_video_to_youtube(
                item,
                title,
                description_preview,
                parse_tags(tags_input),
                effective_privacy_status,
                scheduled_publish_at or None,
                client_secret_path,
                token_path,
                lambda value, text: progress.progress(value, text=text),
            )
            progress.progress(1.0, text="アップロード完了")
            st.success("YouTubeアップロードが完了しました。")
            if result.get("thumbnailError"):
                st.warning(
                    "動画は投稿できましたが、サムネイルの設定に失敗しました。"
                    "YouTube Studioで手動設定してください。"
                    f"（詳細: {result['thumbnailError']}）"
                )
            st.link_button("動画を開く", result["uploadedUrl"])
            st.code(result["uploadedUrl"])
        except Exception as exc:
            progress.empty()
            st.error(f"アップロードに失敗しました: {exc}")


def render_navigation() -> str:
    query_page = st.query_params.get("page", "")
    if isinstance(query_page, list):
        query_page = query_page[0] if query_page else ""
    active_page = APP_PAGE_BY_SLUG.get(
        str(query_page),
        str(st.session_state.get("active_page") or APP_PAGES[1]),
    )
    if active_page not in APP_PAGES:
        active_page = APP_PAGES[1]
        st.session_state.active_page = active_page
    else:
        st.session_state.active_page = active_page

    cols = st.columns(len(APP_PAGES))
    for index, page in enumerate(APP_PAGES):
        button_type = "primary" if page == active_page else "secondary"
        if cols[index].button(page, type=button_type, width="stretch"):
            st.session_state.active_page = page
            st.query_params["page"] = APP_PAGE_SLUGS[page]
            st.rerun()
    if not query_page:
        st.query_params["page"] = APP_PAGE_SLUGS[active_page]
    st.divider()
    return active_page


def find_deno_executable() -> str:
    local_candidates = [
        APP_ROOT / ".runtime" / "deno" / "deno.exe",
        APP_ROOT / ".runtime" / "deno" / "deno",
    ]
    for candidate in local_candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("deno") or ""


def parse_ytdlp_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in value.split(".")[:3]:
        digits = re.sub(r"\D", "", chunk)
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def collect_environment_checks() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    installed_version = str(getattr(yt_dlp.version, "__version__", "不明"))
    parsed = parse_ytdlp_version(installed_version)
    required = parse_ytdlp_version(MIN_RECOMMENDED_YTDLP)
    if not parsed:
        ytdlp_state, ytdlp_detail = "warn", "バージョンを判定できませんでした。"
    elif parsed < required:
        ytdlp_state = "error"
        ytdlp_detail = (
            f"古いバージョンです（推奨 {MIN_RECOMMENDED_YTDLP} 以降）。"
            "YouTube側の仕様変更でダウンロードが失敗します。下の更新手順を実行してください。"
        )
    else:
        ytdlp_state, ytdlp_detail = "ok", "最新に近いバージョンです。"
    checks.append(
        {
            "name": "yt-dlp（ダウンロード本体）",
            "state": ytdlp_state,
            "value": installed_version,
            "detail": ytdlp_detail,
        }
    )

    ffmpeg_path = find_optional_ffmpeg_executable()
    checks.append(
        {
            "name": "ffmpeg（映像と音声の結合）",
            "state": "ok" if ffmpeg_path else "error",
            "value": ffmpeg_path or "見つかりません",
            "detail": (
                ""
                if ffmpeg_path
                else f"これが無いとダウンロードは必ず失敗します。{SETUP_COMMAND_HINT} を再実行してください。"
            ),
        }
    )

    deno_path = find_deno_executable()
    checks.append(
        {
            "name": "Deno（YouTubeの再生制限の解除に使用）",
            "state": "ok" if deno_path else "warn",
            "value": deno_path or "見つかりません",
            "detail": (
                ""
                if deno_path
                else f"一部の動画で HTTP 403 になることがあります。{SETUP_COMMAND_HINT} を再実行してください。"
            ),
        }
    )

    root_text = str(APP_ROOT)
    if len(root_text) > 120:
        path_state = "error"
        path_detail = (
            "フォルダのパスが長すぎます。長いタイトルの動画で保存に失敗します。"
            "C:\\ytool のような浅いフォルダへ移動してください。"
        )
    elif len(root_text) > 80 or "OneDrive" in root_text:
        path_state = "warn"
        path_detail = (
            "パスが長い、またはOneDrive配下です。長いタイトルの動画で失敗することがあります。"
        )
    else:
        path_state, path_detail = "ok", ""
    checks.append(
        {
            "name": "ツールの場所",
            "state": path_state,
            "value": root_text,
            "detail": path_detail,
        }
    )

    downloads_dir = APP_ROOT / "downloads"
    try:
        downloads_dir.mkdir(parents=True, exist_ok=True)
        probe = downloads_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        write_state, write_detail = "ok", ""
    except OSError as exc:
        write_state = "error"
        write_detail = f"保存先に書き込めません: {exc}"
    checks.append(
        {
            "name": "保存先への書き込み",
            "state": write_state,
            "value": str(downloads_dir),
            "detail": write_detail,
        }
    )

    try:
        free_bytes = shutil.disk_usage(APP_ROOT).free
    except OSError:
        checks.append(
            {
                "name": "空き容量",
                "state": "warn",
                "value": "判定できませんでした",
                "detail": "",
            }
        )
    else:
        free_gb = free_bytes / (1024**3)
        checks.append(
            {
                "name": "空き容量",
                "state": "ok" if free_gb >= 5 else "error",
                "value": f"{free_gb:.1f} GB",
                "detail": "" if free_gb >= 5 else "空き容量が不足しています。",
            }
        )

    return checks


def render_environment_check() -> None:
    checks = collect_environment_checks()
    has_error = any(check["state"] == "error" for check in checks)
    has_warning = any(check["state"] == "warn" for check in checks)
    if has_error:
        label = "環境チェック（要対応の項目があります）"
    elif has_warning:
        label = "環境チェック（注意の項目があります）"
    else:
        label = "環境チェック（問題ありません）"

    with st.expander(label, expanded=has_error):
        st.caption(
            "ダウンロードがうまくいかないときは、まずここを確認してください。"
            "サポートに連絡するときは、この画面のスクリーンショットを添えると原因を特定しやすくなります。"
        )
        icons = {"ok": "✅", "warn": "⚠️", "error": "❌"}
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "状態": icons[check["state"]],
                        "項目": check["name"],
                        "内容": check["value"],
                        "対処": check["detail"],
                    }
                    for check in checks
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.write("yt-dlp が古い場合の更新手順（アプリを閉じてから実行してください）")
        st.code(
            f'cd /d "{APP_ROOT}"\n'
            ".runtime\\python312\\python.exe -m pip install -U yt-dlp",
            language="bat",
        )
        st.caption(
            "macOSの場合: `.runtime/venv/bin/python -m pip install -U yt-dlp`"
        )


def render_account_settings_page() -> None:
    st.header("アカウント設定")
    st.caption(
        "YouTube Data APIキー、OpenAI APIキー、OAuthクライアントJSON、"
        "複数アカウント用プロファイルを管理します。"
    )
    render_environment_check()
    render_initial_settings(expanded=True)


def render_search_download_page() -> None:
    st.header("YouTube検索＆ダウンロード")
    api_key, source = configured_api_key()
    if source:
        st.success(f"APIキーを {source} から読み込みました。")
    else:
        st.text_input(
            "YouTube Data API キー",
            type="password",
            key="api_key_input",
            help=(
                "一時入力です。毎回使う場合は「アカウント設定」ページで保存してください。"
            ),
        )
        api_key = st.session_state.api_key_input.strip()

    render_search_form(api_key)
    st.divider()
    render_results()


def render_upload_page() -> None:
    render_upload_section()


def main() -> None:
    st.set_page_config(
        page_title="YouTube 検索 & ダウンローダー",
        page_icon="▶️",
        layout="wide",
    )
    initialize_state()
    st.title("YouTube 検索 & ダウンローダー")
    st.caption(
        "YouTube Data API で候補を検索し、選択した動画だけを"
        "再エンコードせず MKV にダウンロードします。"
    )

    active_page = render_navigation()
    if active_page == "アカウント設定":
        render_account_settings_page()
    elif active_page == "YouTubeアップロード":
        render_upload_page()
    else:
        render_search_download_page()


if __name__ == "__main__":
    main()
