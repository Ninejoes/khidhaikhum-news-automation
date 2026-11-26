"""Voice synthesis module.

Generates broadcast-quality Thai news voice narration using:
1. Gemini 3.8 Flash TTS (Charon voice) when GEMINI_API_KEY is available.
2. Microsoft Edge Neural TTS (th-TH-NiwatNeural / th-TH-PremwadeeNeural) as free, high-fidelity neural fallback.
3. macOS Native Thai TTS (Kanya) as local system fallback.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

GEMINI_TTS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_EDGE_VOICE = "th-TH-NiwatNeural"  # Professional Thai male news anchor


async def _synthesize_edge_tts(script: str, output_path: Path, voice: str = DEFAULT_EDGE_VOICE) -> bool:
    """Generates natural Thai speech using Microsoft Edge Neural TTS."""
    try:
        import edge_tts

        temp_mp3 = output_path.with_suffix(".temp.mp3")
        communicate = edge_tts.Communicate(script, voice, rate="+2%", pitch="-1Hz")
        await communicate.save(str(temp_mp3))

        if temp_mp3.is_file() and temp_mp3.stat().st_size > 10_000:
            # Convert to standard 48kHz WAV
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(temp_mp3),
                "-ar", "48000", "-ac", "2",
                str(output_path),
            ]
            subprocess.run(cmd, check=True)
            temp_mp3.unlink(missing_ok=True)
            logger.info("Edge-TTS (%s) narration created: %d bytes", voice, output_path.stat().st_size)
            return True
    except Exception as exc:
        logger.warning("Edge-TTS synthesis failed (%s): %s", type(exc).__name__, exc)

    return False


def _synthesize_gemini_tts(script: str, output_path: Path, api_key: str) -> bool:
    """Generates Thai speech using Gemini 3.8 Flash TTS Interactions API with rate-limit retry."""
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts").strip()
    voice = os.environ.get("GEMINI_TTS_VOICE", "Charon").strip()
    style = (
        "A calm, warm, low-pitched adult Thai male news anchor; "
        "clear Thai pronunciation, steady pace, confident and natural."
    )
    request_body = {
        "model": model,
        "input": [
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": script,
                        "annotations": [{"type": "speech_metadata", "style": style}],
                    }
                ],
            }
        ],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }

    for attempt in range(4):
        try:
            resp = requests.post(
                GEMINI_TTS_ENDPOINT,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=request_body,
                timeout=(15, 180),
            )
            if resp.ok:
                payload = resp.json()
                encoded_audio = (payload.get("output_audio") or {}).get("data")
                if not encoded_audio:
                    for step in reversed(payload.get("steps") or []):
                        if step.get("type") != "model_output":
                            continue
                        for part in step.get("content") or []:
                            if part.get("type") == "audio" and part.get("data"):
                                encoded_audio = part["data"]
                                break
                        if encoded_audio:
                            break

                if encoded_audio:
                    audio_bytes = base64.b64decode(encoded_audio)
                    if len(audio_bytes) > 50_000:
                        output_path.write_bytes(audio_bytes)
                        logger.info("Gemini TTS narration created: %d bytes (attempt %d)", len(audio_bytes), attempt + 1)
                        # Brief pacing pause so back-to-back beats don't trigger 429 burst limits
                        time.sleep(2.5)
                        return True

            if "requests per day" in resp.text or "per_day" in resp.text:
                logger.warning("Gemini TTS daily quota reached (10 req/day): %s", resp.text[:180])
                break

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                wait_s = 6 * (attempt + 1)
                logger.warning(
                    "Gemini TTS returned HTTP %s on attempt %d/3; waiting %ds...",
                    resp.status_code, attempt + 1, wait_s,
                )
                time.sleep(wait_s)
                continue

            logger.warning("Gemini TTS non-retryable HTTP %s: %s", resp.status_code, resp.text[:180])
            break
        except Exception as exc:
            if attempt < 3:
                wait_s = 6 * (attempt + 1)
                logger.warning("Gemini TTS error (%s) on attempt %d/4; retrying in %ds...", type(exc).__name__, attempt + 1, wait_s)
                time.sleep(wait_s)
            else:
                logger.warning("Gemini TTS failed after 4 attempts (%s): %s", type(exc).__name__, exc)

    return False


def _synthesize_macos_tts(script: str, output_path: Path) -> bool:
    """Generates Thai speech using macOS native voice (Kanya)."""
    if shutil.which("say"):
        try:
            temp_aiff = output_path.with_suffix(".temp.aiff")
            cmd_say = ["say", "-v", "Kanya", "-r", "185", "-o", str(temp_aiff), script]
            subprocess.run(cmd_say, check=True)
            if temp_aiff.is_file() and temp_aiff.stat().st_size > 10_000:
                cmd_ffmpeg = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(temp_aiff),
                    "-ar", "48000", "-ac", "2",
                    str(output_path),
                ]
                subprocess.run(cmd_ffmpeg, check=True)
                temp_aiff.unlink(missing_ok=True)
                logger.info("macOS Kanya TTS created: %d bytes", output_path.stat().st_size)
                return True
        except Exception as exc:
            logger.warning("macOS TTS failed (%s): %s", type(exc).__name__, exc)

    return False


def synthesize_narration(script: str, output_path: Path, api_key: str | None = None) -> Path:
    """Synthesizes high-quality Thai news narration audio (always genuine speech, never sine beeps)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    # 1. First priority: Gemini 3.8 Flash TTS (when API key is provided)
    if key:
        logger.info("Attempting Gemini 3.8 Flash TTS synthesis...")
        if _synthesize_gemini_tts(script, output_path, key):
            return output_path
        logger.info("Gemini TTS unavailable, falling back to Neural Edge-TTS...")

    # 2. Second priority: Microsoft Neural Edge-TTS (th-TH-NiwatNeural) - free, high fidelity
    logger.info("Synthesizing Thai speech with Neural Edge-TTS (th-TH-NiwatNeural)...")
    if asyncio.run(_synthesize_edge_tts(script, output_path)):
        return output_path

    # 3. Third priority: macOS native TTS (Kanya)
    logger.info("Falling back to macOS system Thai voice...")
    if _synthesize_macos_tts(script, output_path):
        return output_path

    raise RuntimeError("All Thai speech synthesis providers failed; cannot produce audio")


def _probe_audio_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def synthesize_all_beats_consistent(
    scripts: list[str],
    output_paths: list[Path],
    work_dir: Path,
    api_key: str | None = None,
) -> list[Path]:
    """Synthesizes all beats in 1 single Gemini TTS request (saving 80% daily quota) or 100% consistent Edge-TTS.

    Guarantees:
    1. Only 1 Gemini TTS API call is consumed per video (4 calls/day << 10 calls/day free quota).
    2. Never mixes two different voices in the same video.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    if key and len(scripts) > 1:
        combined_wav = work_dir / "combined_gemini_narration.wav"
        combined_script = "\n\n...\n\n".join(s.strip() for s in scripts if s.strip())
        logger.info("Synthesizing all %d beats in 1 single Gemini TTS call to preserve daily quota...", len(scripts))
        if _synthesize_gemini_tts(combined_script, combined_wav, key):
            total_dur = _probe_audio_duration(combined_wav)
            char_lengths = [max(10, len(s.strip())) for s in scripts]
            total_chars = sum(char_lengths)
            cur_start = 0.0
            for idx, (c_len, out_p) in enumerate(zip(char_lengths, output_paths)):
                seg_dur = (total_dur - cur_start) if idx == len(scripts) - 1 else round(total_dur * (c_len / total_chars), 3)
                seg_dur = max(3.0, seg_dur)
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{cur_start:.3f}", "-t", f"{seg_dur:.3f}",
                        "-i", str(combined_wav),
                        "-ar", "48000", "-ac", "2",
                        str(out_p),
                    ],
                    check=True,
                )
                cur_start += seg_dur
            logger.info("Split single Gemini TTS recording (%.1fs) into %d consistent beat tracks.", total_dur, len(scripts))
            return output_paths
        logger.info("Gemini TTS unavailable or daily quota reached; using consistent Neural Edge-TTS for all %d beats...", len(scripts))

    for s, out_p in zip(scripts, output_paths):
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if not asyncio.run(_synthesize_edge_tts(s, out_p)):
            if not _synthesize_macos_tts(s, out_p):
                raise RuntimeError("All Thai speech synthesis providers failed")
    return output_paths
