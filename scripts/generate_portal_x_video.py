#!/usr/bin/env python3
"""Generate a PORTAL-X style video with Seedance 2.5 and poll the async task.

Adapted on 2026-09-16 from the user's twist-video-continuation Seedance helper.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_MODEL_ID = "doubao-seedance-2-5-260628"
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
TERMINAL_STATES = {"succeeded", "failed", "expired", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a PORTAL-X effect video with Seedance 2.5")
    parser.add_argument("--input-type", choices=("image", "video"), required=True)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-url", help="Publicly accessible source image/video URL")
    input_group.add_argument("--input-file", help="Local source image; videos must use --input-url")
    parser.add_argument(
        "--reference-video-url",
        default=os.environ.get("PORTAL_X_REFERENCE_VIDEO_URL"),
        help="Public URL of assets/reference-video-1.mp4; may also use PORTAL_X_REFERENCE_VIDEO_URL",
    )
    parser.add_argument(
        "--duration",
        type=int,
        choices=range(4, 31),
        metavar="4-30",
        help="Explicit output duration. Defaults to 5s for images or the source video duration for videos.",
    )
    parser.add_argument(
        "--source-video-file",
        help="Local copy of --input-url used only to probe source duration with ffprobe",
    )
    parser.add_argument(
        "--source-duration",
        type=float,
        help="Source video duration in seconds when no local copy is available",
    )
    parser.add_argument("--resolution", default="720p", choices=("480p", "720p", "1080p"))
    parser.add_argument("--ratio", default="adaptive")
    parser.add_argument("--model-id", default=os.environ.get("ARK_SEEDANCE_MODEL_ID", DEFAULT_MODEL_ID))
    parser.add_argument("--base-url", default=os.environ.get("ARK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--watermark", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output-json", default="temp_data/result.json")
    parser.add_argument("--output-video", default="temp_data/portal-x-video.mp4")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the request without calling Seedance")
    return parser.parse_args()


def is_public_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def image_data_url(path_value: str) -> str:
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"Input image does not exist: {path}")
    if path.stat().st_size >= 30 * 1024 * 1024:
        raise ValueError("Local input image must be smaller than 30 MB")
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "image/gif",
        "image/heic",
        "image/heif",
    }:
        raise ValueError(f"Unsupported local image type: {mime_type or 'unknown'}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def resolve_input(args: argparse.Namespace) -> str:
    if args.input_url:
        if not is_public_url(args.input_url):
            raise ValueError("--input-url must be a public HTTP(S) URL")
        return args.input_url
    if args.input_type != "image":
        raise ValueError("Local video input is not supported; upload it first and use --input-url")
    return image_data_url(args.input_file)


def probe_video_duration(path_value: str) -> float:
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"Source video does not exist: {path}")
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError("ffprobe is required to inherit source video duration") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "unknown ffprobe error"
        raise ValueError(f"Cannot read source video duration: {detail}") from exc
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise ValueError("ffprobe returned an invalid source video duration") from exc
    if duration <= 0:
        raise ValueError("Source video duration must be greater than 0")
    return duration


def resolve_duration(args: argparse.Namespace) -> int:
    if args.duration is not None:
        return args.duration
    if args.input_type == "image":
        return 5
    source_duration = args.source_duration
    if source_duration is None and args.source_video_file:
        source_duration = probe_video_duration(args.source_video_file)
    if source_duration is None:
        raise ValueError(
            "Video input must include --source-video-file or --source-duration so output can inherit its duration"
        )
    rounded = int(source_duration + 0.5)
    if not 4 <= rounded <= 30:
        raise ValueError(
            f"Source video is {source_duration:.3f}s; Seedance output duration must round to 4-30 seconds"
        )
    return rounded


def format_timestamp(seconds: float) -> str:
    return f"{seconds:.1f}".rstrip("0").rstrip(".")


def build_prompt(input_type: str, duration: int) -> str:
    source = "@图1" if input_type == "image" else "@视频1"
    reference = "@视频1" if input_type == "image" else "@视频2"
    phase_1_end = format_timestamp(duration * 0.2)
    phase_2_end = format_timestamp(duration * 0.7)
    phase_end = format_timestamp(float(duration))
    return f"""理解并根据{source}为基础，模仿{reference}的动态特效、镜头运镜、镜头语言、特殊风格但不允许参考{reference}的画面主体与物体：
- 特效1：[00:00 - 00:{phase_1_end}]，白色半透明动态马赛克方块，呈像素化闪烁消散效果。
- 特效2：[00:{phase_1_end} - 00:{phase_2_end}]，全屏叠加密集的三维立体白色点线拓扑结构网络，各节点附带白色小字体标签（内容含\"[id: 1YtL8 SUBJ: It's a Portal]\"、\"T: 2026/7/29 11:36:22 L: 51.5445 N -0.062 E\"等坐标信息），连线随时间动态增密。
- 特效3：[00:{phase_2_end} - 00:{phase_end}]，画面转为多组垂直白色贯穿线条与UI瞄准矩形框，框体内外标注白色文字\"PORTAL-X\"与\"2026 ich hill\"；同时出现周期性爆发、扩散并消隐的高亮度白色马赛克方块阵列。
完全参考{reference}中的特效效果生成一个类似的视频，总时长 {duration} 秒。
保持{source}的主体身份、主体数量、服装或材质、场景布局和主要构图稳定；不要复制{reference}中的人物或物体。不要生成额外主体、异常肢体、身份漂移、背景融化、无动机跳切、乱码、水印或 logo。"""


def build_content(input_type: str, input_url: str, reference_video_url: str, prompt: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if input_type == "image":
        content.append({"type": "image_url", "image_url": {"url": input_url}, "role": "first_frame"})
    else:
        content.append({"type": "video_url", "video_url": {"url": input_url}, "role": "reference_video"})
    content.append(
        {"type": "video_url", "video_url": {"url": reference_video_url}, "role": "reference_video"}
    )
    return content


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    duration = resolve_duration(args)
    prompt = build_prompt(args.input_type, duration)
    input_value = resolve_input(args)
    request: dict[str, Any] = {
        "model": args.model_id,
        "content": build_content(args.input_type, input_value, args.reference_video_url, prompt),
        "duration": duration,
        "ratio": args.ratio,
        "resolution": args.resolution,
        "generate_audio": not args.no_audio,
        "return_last_frame": True,
        "watermark": args.watermark,
    }
    if args.seed is not None:
        request["seed"] = args.seed
    return request


def to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {"raw": str(value)}


def find_first_url(data: Any, key_hints: tuple[str, ...]) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            lowered = key.lower()
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                if any(hint in lowered for hint in key_hints):
                    return value
        for value in data.values():
            found = find_first_url(value, key_hints)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_first_url(value, key_hints)
            if found:
                return found
    return None


def write_json(path: str, result: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def download_video(url: str, output_path: str) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Aime-PORTAL-X-Skill/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, output.open("wb") as target:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
    if output.stat().st_size == 0:
        raise RuntimeError("Downloaded video is empty")
    return str(output)


def validate_args(args: argparse.Namespace) -> None:
    if not is_public_url(args.reference_video_url):
        raise ValueError(
            "Provide --reference-video-url or PORTAL_X_REFERENCE_VIDEO_URL with a public HTTP(S) URL"
        )
    if args.poll_interval <= 0:
        raise ValueError("--poll-interval must be greater than 0")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than 0")


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        request = build_request(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0

    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        print("Missing ARK_API_KEY environment variable", file=sys.stderr)
        return 2

    try:
        from volcenginesdkarkruntime import Ark
    except ImportError:
        print("Missing dependency: pip install 'volcengine-python-sdk[ark]'", file=sys.stderr)
        return 2

    client = Ark(base_url=args.base_url, api_key=api_key)
    task_id: str | None = None
    try:
        created = client.content_generation.tasks.create(**request)
        latest = to_dict(created)
        task_id = latest.get("id") or getattr(created, "id", None)
        if not task_id:
            raise RuntimeError("Create response has no task id")

        deadline = time.monotonic() + args.timeout
        status = str(latest.get("status", "queued")).lower()
        while status not in TERMINAL_STATES and time.monotonic() < deadline:
            time.sleep(args.poll_interval)
            latest = to_dict(client.content_generation.tasks.get(task_id=task_id))
            status = str(latest.get("status", "running")).lower()

        if status not in TERMINAL_STATES:
            result = {
                "status": "timeout",
                "task_id": task_id,
                "model": args.model_id,
                "video_url": None,
                "video_file": None,
                "last_frame_url": None,
                "duration_seconds": request["duration"],
                "warnings": ["Polling timed out; query the retained task_id later."],
            }
            write_json(args.output_json, result)
            print(json.dumps(result, ensure_ascii=False))
            return 3

        video_url = find_first_url(latest, ("video", "output"))
        last_frame_url = find_first_url(latest, ("last_frame", "lastframe"))
        warnings: list[str] = []
        video_file: str | None = None
        if status == "succeeded" and video_url:
            try:
                video_file = download_video(video_url, args.output_video)
            except Exception as exc:
                warnings.append(f"Video succeeded but download failed: {type(exc).__name__}: {exc}")
        elif status == "succeeded":
            warnings.append("Task succeeded but no video URL was found in the response")
        else:
            warnings.append(str(latest.get("error", "Generation failed")))

        result = {
            "status": status,
            "task_id": task_id,
            "model": args.model_id,
            "video_url": video_url,
            "video_file": video_file,
            "last_frame_url": last_frame_url,
            "duration_seconds": request["duration"],
            "warnings": warnings,
        }
        write_json(args.output_json, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if status == "succeeded" and video_url else 1
    except Exception as exc:
        result = {
            "status": "failed",
            "task_id": task_id,
            "model": args.model_id,
            "video_url": None,
            "video_file": None,
            "last_frame_url": None,
            "duration_seconds": request["duration"],
            "warnings": [f"{type(exc).__name__}: {exc}"],
        }
        write_json(args.output_json, result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
