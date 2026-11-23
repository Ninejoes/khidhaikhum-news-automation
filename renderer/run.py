from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import argparse
import resource
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import regex
import requests
from cairosvg import svg2png
from PIL import Image, ImageDraw, ImageFont, ImageFilter


WIDTH, HEIGHT, FPS = 1080, 1920, 30
VOICE = "th-TH-NiwatNeural"
ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Bangkok")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment setting: {name}")
    return value


def pick_mode() -> str:
    requested = os.environ.get("REQUESTED_MODE", "auto").strip().lower()
    if requested in {"summary", "breaking"}:
        return requested
    return "summary" if datetime.now(TZ).hour in {12, 18} else "breaking"


def font_path(bold: bool = False) -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
        "/usr/share/fonts/opentype/tlwg/TlwgTypo-Bold.ttf" if bold else "/usr/share/fonts/opentype/tlwg/TlwgTypo.ttf",
        "/usr/share/fonts/truetype/tlwg/TlwgTypo-Bold.ttf" if bold else "/usr/share/fonts/truetype/tlwg/TlwgTypo.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    style = "Bold" if bold else "Regular"
    result = subprocess.run(["fc-match", f"Noto Sans Thai:style={style}", "-f", "%{file}"], check=True, capture_output=True, text=True)
    path = result.stdout.strip()
    if not path:
        raise RuntimeError("Thai font not found on the online rendering runner")
    return path


def fallback_font_path(bold: bool = False) -> str:
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if Path(path).exists():
        return path
    style = "Bold" if bold else "Regular"
    result = subprocess.run(["fc-match", f"DejaVu Sans:style={style}", "-f", "%{file}"], check=True, capture_output=True, text=True)
    path = result.stdout.strip()
    if not path:
        raise RuntimeError("Fallback font not found on the online rendering runner")
    return path


FONT_REGULAR = font_path(False)
FONT_BOLD = font_path(True)
FONT_FALLBACK_REGULAR = fallback_font_path(False)
FONT_FALLBACK_BOLD = fallback_font_path(True)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    face = ImageFont.truetype(path, size)
    if hasattr(face, "set_variation_by_name"):
        try:
            face.set_variation_by_name("Bold" if bold else "Regular")
        except OSError:
            pass
    return face


def fallback_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_FALLBACK_BOLD if bold else FONT_FALLBACK_REGULAR, size)


def _font_for_cluster(cluster: str, thai: ImageFont.FreeTypeFont,
                      fallback: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont:
    return thai if any("\u0e00" <= char <= "\u0e7f" for char in cluster) else fallback


def text_width(text: str, thai: ImageFont.FreeTypeFont,
               fallback: ImageFont.FreeTypeFont | None = None) -> float:
    if fallback is None:
        return thai.getlength(text)
    return sum(_font_for_cluster(cluster, thai, fallback).getlength(cluster)
               for cluster in regex.findall(r"\X", text))


def draw_text_with_fallback(draw: ImageDraw.ImageDraw, text: str, xy: tuple[float, float],
                            thai: ImageFont.FreeTypeFont, fallback: ImageFont.FreeTypeFont | None,
                            fill: tuple[int, int, int, int]) -> float:
    x, y = xy
    if fallback is None:
        draw.text((x, y), text, font=thai, fill=fill, stroke_width=0)
        return x + thai.getlength(text)
    for cluster in regex.findall(r"\X", text):
        selected = _font_for_cluster(cluster, thai, fallback)
        draw.text((x, y), cluster, font=selected, fill=fill, stroke_width=0)
        x += selected.getlength(cluster)
    return x


def clean_text(value: object, limit: int = 2000) -> str:
    text = str(value or "").replace("\r", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def short_text(value: object, limit: int) -> str:
    text = clean_text(value, 1800)
    clusters = regex.findall(r"\X", text)
    if len(clusters) <= limit:
        return text
    visible = "".join(clusters[:limit])
    boundary = visible.rfind(" ")
    if boundary >= limit // 2:
        visible = visible[:boundary]
    return visible.rstrip(" ,ฯ") + "…"


def wrap_text(text: str, selected_font: ImageFont.FreeTypeFont, max_width: int, max_lines: int,
              fallback: ImageFont.FreeTypeFont | None = None) -> list[str]:
    measure = lambda value: text_width(value, selected_font, fallback)
    words = re.findall(r"\S+", text)
    lines: list[str] = []
    current = ""
    truncated = False
    for word_index, word in enumerate(words):
        candidate = word if not current else f"{current} {word}"
        if measure(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                truncated = True
                break
        clusters = regex.findall(r"\X", word)
        while clusters and measure("".join(clusters)) > max_width:
            cut = len(clusters)
            while cut > 1 and measure("".join(clusters[:cut])) > max_width:
                cut -= 1
            lines.append("".join(clusters[:cut]))
            clusters = clusters[cut:]
            if len(lines) >= max_lines:
                truncated = bool(clusters) or word_index < len(words) - 1
                break
        if truncated:
            break
        current = "".join(clusters)
    if current and len(lines) < max_lines:
        lines.append(current)
    elif current:
        truncated = True
    if truncated and lines:
        lines[-1] = lines[-1].rstrip(" .…") + "…"
    return [line for line in lines if line]


def draw_wrapped(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], selected_font: ImageFont.FreeTypeFont,
                 fill: tuple[int, int, int, int], max_width: int, max_lines: int, spacing: int = 16,
                 fallback: ImageFont.FreeTypeFont | None = None) -> int:
    x, y = xy
    lines = wrap_text(text, selected_font, max_width, max_lines, fallback)
    for line in lines:
        draw_text_with_fallback(draw, line, (x, y), selected_font, fallback, fill)
        box = draw.textbbox((x, y), line, font=selected_font)
        y = box[3] + spacing
    return y


def topic_for(text: str) -> tuple[str, tuple[int, int, int]]:
    value = text.lower()
    checks = [
        (("น้ำท่วม", "น้ำป่า", "น้ำหลาก", "ฝนตก", "อากาศ", "พายุ", "มรสุม", "คลื่น"), ("สภาพอากาศ", (99, 190, 215))),
        (("อาชญาก", "ตำรวจ", "คดี", "จับกุม", "ผู้ต้องหา", "เหตุ", "อุบัติเหตุ", "ภัย"), ("เหตุการณ์", (242, 142, 113))),
        (("กีฬา", "ฟุตบอล", "บาส", "นักกีฬา", "ทีมชาติ", "พรีเมียร์ลีก", "แชมป์"), ("กีฬา", (111, 189, 166))),
        (("บันเทิง", "นักแสดง", "ดารา", "ภาพยนตร์", "เพลง", "คอนเสิร์ต", "ศิลปิน"), ("บันเทิง", (193, 153, 210))),
        (("หุ้น", "ลงทุน", "ตลาด", "เศรษฐกิจ", "การเงิน", "ธนาคาร", "เงิน", "ภาษี", "หนี้", "ดอกเบี้ย"), ("การเงิน", (149, 190, 135))),
        (("ai", "เอไอ", "ชิป", "เทคโนโลยี", "เทค", "ดาต้าเซ็นเตอร์", "ปัญญาประดิษฐ์"), ("เทคโนโลยี", (221, 172, 117))),
        (("การเมือง", "รัฐบาล", "นายก", "รัฐมนตรี", "นโยบาย", "สภา", "เลือกตั้ง"), ("นโยบาย", (118, 164, 206))),
    ]
    for words, result in checks:
        if any(word in value for word in words):
            return result
    return "กระแสวันนี้", (154, 183, 170)


def icon_for(text: str) -> str:
    category = topic_for(text)[0]
    value = text.lower()
    if "ที่มาและความโปร่งใส" in text or "ตรวจสอบจากหลายแหล่ง" in text:
        return "newspaper"
    if category == "การเงิน":
        if any(word in value for word in ("หุ้น", "nasdaq", "set", "s&p", "ตลาด")):
            return "briefcase-business"
        if any(word in value for word in ("sme", "สินเชื่อ", "npl", "หนี้", "กู้")):
            return "hand-coins"
        if any(word in value for word in ("กฎ", "มาตรการ", "ภาษี", "รัฐบาล", "ควบคุม")):
            return "file-text"
    if category == "นโยบาย" and any(word in value for word in ("มาตรการ", "กฎ", "ควบคุม", "รัฐบาล")):
        return "file-text"
    return {
        "สภาพอากาศ": "cloud-rain",
        "เหตุการณ์": "alert-triangle",
        "กีฬา": "trophy",
        "บันเทิง": "clapperboard",
        "เทคโนโลยี": "cpu",
        "นโยบาย": "landmark",
        "การเงิน": "landmark",
    }.get(category, "newspaper")


def split_summary(item: dict) -> list[str]:
    summary = clean_text(item.get("summary"), 1600)
    parts = re.split(r"(?=(?<!\S)(?:\d{1,2}\s*[\).]\s+|•\s+|เรื่องที่\s*(?:หนึ่ง|สอง|สาม|สี่|สุดท้าย)))", summary)
    parts = [re.sub(r"^\s*(?:\d+\s*[\).]|•)\s*", "", p).strip() for p in parts]
    parts = [p for p in parts if len(p) > 24]
    if len(parts) >= 2:
        return parts[:4]
    sentences = re.split(r"(?<=[.!?])\s+|(?<=\u0e2f)\s+", summary)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 18]
    return sentences[:4] or [summary]


def split_spoken(text: str, max_chars: int = 92) -> list[str]:
    text = clean_text(text, 1800)
    sentences = re.split(r"(?<=[.!?。！？])\s*|(?=เรื่อง(?:ที่)?(?:สอง|สาม|สี่|สุดท้าย))", text)
    chunks: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        clusters = regex.findall(r"\X", sentence)
        while len(clusters) > max_chars:
            cut = max_chars
            for position in range(max_chars, max_chars // 2, -1):
                if clusters[position - 1].isspace():
                    cut = position
                    break
            chunks.append("".join(clusters[:cut]).strip())
            clusters = clusters[cut:]
        if clusters:
            chunks.append("".join(clusters).strip())
    return [chunk for chunk in chunks if chunk]


def split_for_scenes(text: str) -> list[str]:
    text = clean_text(text, 1800)
    markers = list(re.finditer(r"เรื่อง(?:ที่)?(?:แรก|สอง|สาม|สี่|สุดท้าย)", text))
    if len(markers) >= 2:
        intro = text[:markers[0].start()].strip()
        groups = []
        for index, match in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            group = text[match.start():end].strip()
            if group:
                groups.append(group)
        if groups and intro:
            groups[0] = f"{intro} {groups[0]}"
        return groups
    return split_spoken(text, max_chars=140)


def create_scenes(item: dict, mode: str) -> list[dict]:
    title = clean_text(item.get("title"), 180)
    script = clean_text(item.get("script"), 1800)
    chunks = split_for_scenes(script)
    summary_points = split_summary(item)
    sources = item.get("sources") or []
    source_line = " · ".join(clean_text(s.get("name"), 60) for s in sources[:3] if isinstance(s, dict))
    category, _ = topic_for(f"{item.get('category','')} {title}")
    scenes: list[dict] = []
    labels = ["ข่าวที่กำลังจับตา", "รายละเอียดที่ยืนยันได้", "ข้อมูลที่ต้องรู้", "ผลกระทบและสิ่งที่ตามมา", "ประเด็นสำคัญ"]
    for index, chunk in enumerate(chunks[:7]):
        scene_title = title if index == 0 else short_text(summary_points[min(index, len(summary_points) - 1)], 58)
        scenes.append({
            "label": labels[min(index, len(labels) - 1)] if index else ("สรุปประเด็นข่าว" if mode == "summary" else "ข่าวด่วนที่ตรวจสอบแล้ว"),
            "title": scene_title if index < len(summary_points) else (title if index == 0 else labels[min(index, len(labels) - 1)]),
            "body": chunk,
        })
    disclaimer = "เสียงสังเคราะห์ AI · สรุปข่าวเพื่อข้อมูล"
    if re.search(r"การเงิน|เศรษฐกิจ|หุ้น|ลงทุน|ตลาด", f"{item.get('category','')} {title}"):
        disclaimer += " · ไม่ใช่คำแนะนำลงทุน"
    scenes.append({
        "label": "ที่มาและความโปร่งใส",
        "title": "ตรวจสอบจากหลายแหล่ง",
        "body": f"ตรวจจาก {len(sources)} แหล่งข่าวอิสระ\n{source_line}\n{disclaimer}",
    })
    return scenes


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int,
            fill: tuple[int, int, int, int], outline: tuple[int, int, int, int] | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def summary_metrics(item: dict) -> list[dict[str, str]]:
    summary = clean_text(item.get("summary"), 1800)
    result: list[dict[str, str]] = []
    for match in re.finditer(r"(?P<value>-?\d+(?:\.\d+)?\s*%)", summary):
        left, right = max(0, match.start() - 44), min(len(summary), match.end() + 36)
        context = summary[left:right]
        value = re.sub(r"\s+", "", match.group("value"))
        if not value.startswith("-") and re.search(r"ลดลง|หดตัว|ติดลบ", summary[max(0, match.start()-14):match.start()]):
            value = "−" + value
        elif not value.startswith("-") and re.search(r"โต|เพิ่มขึ้น|ขยายตัว", summary[max(0, match.start()-14):match.start()]):
            value = "+" + value
        label = "ตัวเลขสำคัญ"
        for needle, name in [
            ("Nasdaq", "NASDAQ"), ("S&P 500", "S&P 500"), ("GDP", "GDP ไทย"),
            ("NPL", "NPL · SME"), ("สินเชื่อ", "สินเชื่อ SME"), ("SME", "SME"),
        ]:
            if needle.lower() in context.lower():
                label = name
                break
        result.append({"value": value, "label": label, "context": context.strip()})
        if len(result) >= 6:
            break
    return result


def make_background(path: Path, item: dict, scene: dict, scene_index: int, scene_count: int) -> Path:
    theme_text = f"{item.get('category','')} {item.get('title','')} {scene.get('title','')} {scene.get('body','')}"
    topic, accent = topic_for(theme_text)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (9, 17, 24, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(HEIGHT):
        depth = y / HEIGHT
        color = (9 + int(depth * 5), 18 + int(depth * 8), 24 + int(depth * 10), 255)
        draw.line((0, y, WIDTH, y), fill=color)

    # One soft studio light and one topic icon replace the old grid and chart-like ornament.
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((505, 650, 1230, 1375), fill=(*accent, 38))
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(155)))
    draw = ImageDraw.Draw(image, "RGBA")

    draw_text_with_fallback(draw, "คิดให้คุ้ม", (76, 62), font(34, True), fallback_font(34, True), (244, 247, 245, 255))
    draw_text_with_fallback(draw, "ข่าวที่ตรวจสอบแล้ว", (76, 112), font(21, True), fallback_font(21, True), (154, 174, 178, 255))
    checked_at = item.get("checkedAt") or item.get("checked_at")
    checked_label = "ตรวจข้อมูลล่าสุด"
    if checked_at:
        try:
            checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00")).astimezone(TZ)
            checked_label = "ตรวจข้อมูล " + checked.strftime("%d %b · %H:%M")
        except ValueError:
            pass
    draw_text_with_fallback(draw, checked_label, (700, 81), font(21, True), fallback_font(21, True), (178, 194, 197, 255))

    rounded(draw, (76, 196, 366, 250), 22, (*accent, 28))
    draw.ellipse((97, 216, 113, 232), fill=(*accent, 255))
    draw_text_with_fallback(draw, topic, (129, 205), font(24, True), fallback_font(24, True), (235, 242, 239, 255))
    draw_text_with_fallback(draw, f"{scene_index + 1:02d}/{scene_count:02d}", (920, 210), font(21, True), fallback_font(21, True), (158, 179, 183, 255))

    heading = clean_text(scene.get("title"), 150)
    if scene_index == 0:
        heading = re.sub(r"^(?:สรุปข่าว(?:เช้า|เที่ยง|เย็น)?\s*\d{1,2}:\d{2}\s*[—–-]\s*)", "", heading, flags=re.I)
    heading_font = font(68 if scene_index == 0 else 54, True)
    draw_wrapped(draw, heading, (76, 304), heading_font, (247, 249, 247, 255), 928, 3,
                 spacing=17, fallback=fallback_font(heading_font.size, True))

    # Keep the visual vocabulary relevant to the story; no stock people and no generic charts.
    takeaway = short_text(item.get("impact") or item.get("summary"), 72)
    if takeaway and scene_index == 0:
        rounded(draw, (76, 1070, 1004, 1246), 25, (17, 31, 37, 208))
        draw_text_with_fallback(draw, "ประเด็นที่ควรรู้", (108, 1094), font(23, True), fallback_font(23, True), (*accent, 255))
        draw_wrapped(draw, takeaway, (108, 1138), font(31, True), (228, 236, 233, 255), 852, 2,
                     spacing=10, fallback=fallback_font(31, True))

    body = clean_text(scene.get("body"), 220)
    body_top = 1294 if scene_index == 0 else 1090
    body_start = 1344 if scene_index == 0 else 1140
    body_font = font(40 if scene_index == 0 else 36, False)
    body_lines = 3 if scene_index == 0 else 4
    draw_text_with_fallback(draw, clean_text(scene.get("label") or "สรุปข่าว", 50), (76, body_top),
                            font(24, True), fallback_font(24, True), (*accent, 255))
    draw_wrapped(draw, body, (76, body_start), body_font, (243, 246, 244, 255), 928, body_lines,
                 spacing=14, fallback=fallback_font(body_font.size, False))

    draw_text_with_fallback(draw, "แหล่งข่าวและรายละเอียดอยู่ในคำบรรยายโพสต์", (76, 1740),
                            font(22), fallback_font(22), (171, 189, 192, 255))
    draw_text_with_fallback(draw, "เสียงผู้บรรยายสังเคราะห์ด้วย AI", (76, 1792),
                            font(20, True), fallback_font(20, True), (132, 154, 159, 255))

    out = path / f"scene-{scene_index:02d}.png"
    image.convert("RGB").save(out, optimize=True)
    return out


def make_object(path: Path, item: dict, scene: dict, scene_index: int) -> Path:
    theme_text = f"{item.get('category','')} {scene.get('title','')} {scene.get('body','')}"
    _, accent = topic_for(theme_text)
    icon_name = icon_for(theme_text)
    svg_path = Path(__file__).resolve().parent / "assets" / "lucide" / f"{icon_name}.svg"
    svg = svg_path.read_text(encoding="utf-8").replace("currentColor", "#%02x%02x%02x" % accent)
    image = svg2png(bytestring=svg.encode("utf-8"), output_width=360, output_height=360)
    out = path / f"object-{scene_index:02d}.png"
    out.write_bytes(image)
    return out
def make_clip_scene(base: Path, object_path: Path, output: Path, duration: float, scene_index: int) -> None:
    movement = "if(lt(t\\,0.42)\\,W-(W-620)*t/0.42\\,620+8*sin(2*PI*t/4))"
    vertical = f"680+8*sin(2*PI*t/{3.6 + scene_index * 0.17:.2f})"
    vf = (
        "[0:v]scale=1080:1920,format=rgba[bg];"
        f"[1:v]scale=w='360+6*sin(2*PI*t/4)':h='360+6*sin(2*PI*t/4)':eval=frame,format=rgba[obj];"
        f"[bg][obj]overlay=x='{movement}':y='{vertical}':shortest=1,"
        "fade=t=in:st=0:d=0.22,"
        f"fade=t=out:st={max(0.1, duration - 0.25):.3f}:d=0.25,format=yuv420p[v]"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", str(FPS), "-i", str(base),
        "-loop", "1", "-framerate", str(FPS), "-i", str(object_path),
        "-t", f"{duration:.3f}", "-filter_complex", vf,
        "-map", "[v]", "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def synthesize_gemini(script: str, path: Path) -> None:
    api_key = required_env("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts").strip()
    voice = os.environ.get("GEMINI_TTS_VOICE", "Charon").strip()
    style = (
        "A calm, warm, low-pitched adult Thai male news anchor; "
        "clear Thai pronunciation, steady pace, confident and natural."
    )
    request_body = {
        "model": model,
        "input": [{
            "type": "user_input",
            "content": [{
                "type": "text",
                "text": script,
                "annotations": [{"type": "speech_metadata", "style": style}],
            }],
        }],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_body,
            timeout=(15, 180),
        )
    except requests.RequestException as exc:
        raise RuntimeError("Gemini TTS request failed before an audio response was received") from exc
    if not response.ok:
        raise RuntimeError(f"Gemini TTS returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Gemini TTS returned an invalid response") from exc

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
    if not encoded_audio:
        raise RuntimeError("Gemini TTS response did not contain audio")
    try:
        audio = base64.b64decode(encoded_audio, validate=True)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Gemini TTS returned audio in an invalid format") from exc
    if not audio.startswith(b"RIFF") or len(audio) < 100_000:
        raise RuntimeError("Gemini TTS did not return a usable WAV file")
    path.write_bytes(audio)
    print(f"Gemini TTS narration created ({len(audio)} bytes).", flush=True)


def synthesize_voxcpm2(script: str, path: Path) -> None:
    cli = Path(os.environ.get("VOXCPM2_CLI", ROOT / "third_party/llama.cpp-omni/build/bin/voxcpm2-cli"))
    base_model = Path(os.environ.get("VOXCPM2_BASE_MODEL", ROOT / "models/VoxCPM2-BaseLM-Q8_0.gguf"))
    acoustic_model = Path(os.environ.get("VOXCPM2_ACOUSTIC_MODEL", ROOT / "models/VoxCPM2-Acoustic-F16.gguf"))
    timesteps = int(os.environ.get("VOXCPM2_TIMESTEPS", "6"))
    if not 1 <= timesteps <= 10:
        raise RuntimeError("VoxCPM2 timesteps must be between 1 and 10")
    missing = [str(path) for path in (cli, base_model, acoustic_model) if not path.is_file()]
    if missing:
        raise RuntimeError("VoxCPM2 renderer files are missing: " + ", ".join(missing))
    direction = "(A calm, warm, low-pitched adult Thai male news anchor; clear native Thai pronunciation, pleasant steady pace, confident and natural.)"
    command = [
        str(cli), "--text", f"{direction}{script}", "--output", str(path),
        "--cfg", "2.0", "--timesteps", str(timesteps), "--seed", "42",
        str(base_model), str(acoustic_model),
    ]
    if os.environ.get("VOXCPM2_USE_CPU", "").strip().lower() in {"1", "true", "yes"}:
        command.insert(1, "--cpu")
    log_path = path.parent / "voxcpm2-render.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, text=True)
        started = time.monotonic()
        while process.poll() is None:
            time.sleep(30)
            if process.poll() is None:
                elapsed = int(time.monotonic() - started)
                print(f"VoxCPM2 narration is running ({elapsed}s).", flush=True)
        if process.returncode:
            diagnostics = log_path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"out of memory|memory allocation|failed to allocate|std::bad_alloc|not enough memory", diagnostics, re.I):
                category = "memory allocation"
            elif re.search(r"metal.*(?:error|failed|failure)|(?:error|failed|failure).*metal", diagnostics, re.I):
                category = "Metal backend"
            elif re.search(r"assertion|GGML_ASSERT|abort trap", diagnostics, re.I):
                category = "native assertion"
            else:
                category = "no safe diagnostic string"
            peak_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            peak_mib = peak_rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
            print(f"VoxCPM2 failed (exit {process.returncode}, peak resident ~{peak_mib:.0f} MiB, diagnostic: {category}).", flush=True)
            raise RuntimeError(f"VoxCPM2 narration failed with exit {process.returncode}")
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError("VoxCPM2 did not produce a usable WAV file")


def synthesize(script: str, path: Path) -> None:
    provider = os.environ.get("TTS_PROVIDER", "voxcpm2").strip().lower()
    if provider == "gemini":
        synthesize_gemini(script, path)
    elif provider == "voxcpm2":
        synthesize_voxcpm2(script, path)
    else:
        raise RuntimeError("TTS_PROVIDER must be 'gemini' or 'voxcpm2'")


def build_video(item: dict, mode: str, work: Path, audio_source: Path | None = None) -> Path:
    script = clean_text(item.get("script"), 1800)
    if len(script) < 80:
        raise RuntimeError("The saved Thai narration script is too short to publish")
    audio = work / (f"voice{audio_source.suffix}" if audio_source else "voice.wav")
    if audio_source:
        shutil.copy2(audio_source, audio)
    else:
        synthesize(script, audio)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio)],
        check=True, capture_output=True, text=True,
    )
    audio_duration = float(json.loads(probe.stdout)["format"]["duration"])
    scenes = create_scenes(item, mode)
    # Give every visual beat a share of the narration duration, with a short cover and source close.
    weights = [max(1, len(clean_text(scene.get("body")))) for scene in scenes]
    weights[0] += max(1, len(clean_text(item.get("title"))))
    spoken_scenes = len(scenes) - 1
    closing_duration = 3.2
    spoken_total = audio_duration
    durations = [audio_duration * weight / sum(weights[:spoken_scenes]) for weight in weights[:spoken_scenes]]
    durations.append(closing_duration)
    segments: list[Path] = []
    for index, scene in enumerate(scenes):
        base = make_background(work, item, scene, index, len(scenes))
        obj = make_object(work, item, scene, index)
        output = work / f"clip-{index:02d}.mp4"
        make_clip_scene(base, obj, output, durations[index], index)
        segments.append(output)

    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8")
    visual = work / "visual.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", "-movflags", "+faststart", str(visual),
    ], check=True, capture_output=True, text=True)

    final = work / "news-reel.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(visual), "-i", str(audio),
        "-filter_complex", f"[1:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur={closing_duration:.1f},afade=t=out:st={max(0.0, spoken_total - 0.2):.3f}:d=0.2[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(final),
    ], check=True, capture_output=True, text=True)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Render verified Thai news Reels")
    parser.add_argument("--item-file", type=Path, help="Render a saved newsroom item JSON instead of polling the online queue")
    parser.add_argument("--output", type=Path, help="Output MP4 path for local rendering")
    parser.add_argument("--audio-file", type=Path, help="Reuse a narration file when reviewing visuals locally")
    parser.add_argument("--mode", choices=["summary", "breaking"], default="summary")
    parser.add_argument("--render-only", action="store_true", help="Render and validate one queued item without publishing it")
    args = parser.parse_args()

    if args.item_file:
        if args.render_only:
            parser.error("--render-only can only be used with the online newsroom queue")
        item = json.loads(args.item_file.read_text(encoding="utf-8"))
        output = (args.output or (ROOT / "outputs" / "news-reel.mp4")).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="khidhaikhum-news-") as temporary:
            video = build_video(item, args.mode, Path(temporary), args.audio_file)
            shutil.copy2(video, output)
        print(f"Rendered: {output}")
        return

    if args.audio_file:
        parser.error("--audio-file can only be used with --item-file")

    base_url = required_env("NEWSROOM_URL").rstrip("/")
    secret = required_env("AUTO_PUBLISH_SECRET")
    siwc_token = required_env("SIWC_BYPASS_TOKEN")
    mode = pick_mode()
    retry_item_id = os.environ.get("RETRY_ITEM_ID", "").strip()
    headers = {
        "Authorization": f"Bearer {secret}",
        "OAI-Sites-Authorization": f"Bearer {siwc_token}",
    }
    if retry_item_id:
        if mode != "summary":
            raise RuntimeError("A saved item retry must use summary mode")
        retry = requests.post(
            f"{base_url}/api/automation/retry",
            headers=headers,
            json={"itemId": retry_item_id},
            timeout=25,
        )
        retry.raise_for_status()
        print("The saved item was explicitly re-queued for this publish attempt.", flush=True)

    queue_params = {"mode": mode}
    if retry_item_id:
        queue_params["itemId"] = retry_item_id
    queue = requests.get(f"{base_url}/api/automation/queue", params=queue_params, headers=headers, timeout=25)
    queue.raise_for_status()
    data = queue.json()
    items = data.get("items") or []
    if not items:
        print(f"No eligible {mode} news item; nothing was posted.")
        return

    item = items[0]
    print(f"Rendering verified {mode} item.")
    with tempfile.TemporaryDirectory(prefix="khidhaikhum-news-") as temporary:
        video = build_video(item, mode, Path(temporary))
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,format_name:stream=codec_type,codec_name,width,height", "-of", "json", str(video)],
            check=True, capture_output=True, text=True,
        )
        metadata = json.loads(probe.stdout)
        video_stream = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"), None)
        audio_stream = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), None)
        duration = float(metadata.get("format", {}).get("duration", 0))
        size = int(metadata.get("format", {}).get("size", 0))
        if not video_stream or video_stream.get("width") != WIDTH or video_stream.get("height") != HEIGHT:
            raise RuntimeError("Rendered video failed the 1080×1920 metadata check")
        if not audio_stream or video_stream.get("codec_name") != "h264" or audio_stream.get("codec_name") != "aac":
            raise RuntimeError("Rendered video failed the H.264/AAC stream check")
        if not 1 <= duration <= 120 or not 100_000 <= size <= 50 * 1024 * 1024:
            raise RuntimeError("Rendered video failed the duration or upload-size check")
        print(f"Render validated: {duration:.1f}s, {size:,} bytes.")
        if args.render_only:
            print("Render-only mode; Facebook upload skipped.")
            return
        with video.open("rb") as handle:
            response = requests.post(
                f"{base_url}/api/automation/publish",
                headers=headers,
                data={"itemId": str(item["id"]), "width": str(WIDTH), "height": str(HEIGHT)},
                files={"video": ("news-reel.mp4", handle, "video/mp4")},
                timeout=240,
            )
        response.raise_for_status()
        response.json()
        print("Facebook accepted the Reel.")


if __name__ == "__main__":
    main()
