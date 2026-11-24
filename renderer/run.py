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
from PIL import Image, ImageDraw, ImageFont, ImageOps, features


WIDTH, HEIGHT, FPS = 1080, 1920, 30
SAFE_MARGIN = 84
RIGHT_EDGE = WIDTH - SAFE_MARGIN
CARD_PADDING = 32
CONTENT_X = SAFE_MARGIN + CARD_PADDING
CONTENT_WIDTH = WIDTH - 2 * CONTENT_X
VOICE = "th-TH-NiwatNeural"
ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Bangkok")
FONT_LAYOUT = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC


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
    bundled = Path(__file__).resolve().parent / "assets" / "fonts" / ("GoogleSans-Bold.ttf" if bold else "GoogleSansText-Regular.ttf")
    if bundled.is_file():
        return str(bundled)
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
    face = ImageFont.truetype(path, size, layout_engine=FONT_LAYOUT)
    if hasattr(face, "set_variation_by_name"):
        try:
            face.set_variation_by_name("Bold" if bold else "Regular")
        except OSError:
            pass
    return face


def fallback_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_FALLBACK_BOLD if bold else FONT_FALLBACK_REGULAR, size, layout_engine=FONT_LAYOUT)


def _font_for_cluster(cluster: str, thai: ImageFont.FreeTypeFont,
                      fallback: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont:
    # Google Sans includes Thai and Latin; keep both in one family and reserve
    # the fallback for supplementary-plane symbols such as emoji.
    return fallback if any(ord(char) > 0xFFFF for char in cluster) else thai


def _font_runs(text: str, thai: ImageFont.FreeTypeFont,
               fallback: ImageFont.FreeTypeFont | None) -> list[tuple[ImageFont.FreeTypeFont, str]]:
    if fallback is None:
        return [(thai, text)]
    runs: list[tuple[ImageFont.FreeTypeFont, str]] = []
    for cluster in regex.findall(r"\X", text):
        selected = _font_for_cluster(cluster, thai, fallback)
        if runs and runs[-1][0] is selected:
            runs[-1] = (selected, runs[-1][1] + cluster)
        else:
            runs.append((selected, cluster))
    return runs


def text_width(text: str, thai: ImageFont.FreeTypeFont,
               fallback: ImageFont.FreeTypeFont | None = None) -> float:
    return sum(selected.getlength(run) for selected, run in _font_runs(text, thai, fallback))


def draw_text_with_fallback(draw: ImageDraw.ImageDraw, text: str, xy: tuple[float, float],
                            thai: ImageFont.FreeTypeFont, fallback: ImageFont.FreeTypeFont | None,
                            fill: tuple[int, int, int, int]) -> float:
    x, y = xy
    for selected, run in _font_runs(text, thai, fallback):
        draw.text((x, y), run, font=selected, fill=fill, stroke_width=0)
        x += selected.getlength(run)
    return x


def draw_text_right(draw: ImageDraw.ImageDraw, text: str, right: int, y: int,
                    selected_font: ImageFont.FreeTypeFont, fallback: ImageFont.FreeTypeFont | None,
                    fill: tuple[int, int, int, int]) -> float:
    left = right - text_width(text, selected_font, fallback)
    return draw_text_with_fallback(draw, text, (left, y), selected_font, fallback, fill)


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
            # Avoid orphaning a one- or two-character Thai fragment at the
            # start of the next line (for example, splitting "โลก" into "โล"/"ก").
            remainder = len(clusters) - cut
            if 0 < remainder < 3 and len(clusters) >= 4:
                cut = max(1, cut - (3 - remainder))
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
        (("ศาล", "อุทธรณ์", "ยุติธรรม", "มาตรา 112", "กฎหมาย"), ("กฎหมาย", (151, 188, 211))),
        (("น้ำท่วม", "น้ำป่า", "น้ำหลาก", "ฝนตก", "อากาศ", "พายุ", "มรสุม", "คลื่น"), ("สภาพอากาศ", (99, 190, 215))),
        (("อาชญาก", "ตำรวจ", "คดี", "จับกุม", "ผู้ต้องหา", "เหตุการณ์", "อุบัติเหตุ", "ภัยพิบัติ"), ("เหตุการณ์", (242, 142, 113))),
        (("กีฬา", "ฟุตบอล", "บาส", "นักกีฬา", "ทีมชาติ", "พรีเมียร์ลีก", "แชมป์"), ("กีฬา", (111, 189, 166))),
        (("บันเทิง", "นักแสดง", "ดารา", "ภาพยนตร์", "เพลง", "คอนเสิร์ต", "ศิลปิน"), ("บันเทิง", (193, 153, 210))),
        (("หุ้น", "ลงทุน", "ตลาด", "เศรษฐกิจ", "การเงิน", "ธนาคาร", "เงิน", "ทอง", "พันธบัตร", "ตราสารหนี้", "ภาษี", "หนี้", "ดอกเบี้ย"), ("การเงิน", (149, 190, 135))),
        (("ai", "เอไอ", "ชิป", "เทคโนโลยี", "เทค", "ดาต้าเซ็นเตอร์", "ปัญญาประดิษฐ์"), ("เทคโนโลยี", (221, 172, 117))),
        (("การเมือง", "รัฐบาล", "นายก", "รัฐมนตรี", "นโยบาย", "สภา", "เลือกตั้ง"), ("นโยบาย", (118, 164, 206))),
    ]
    for words, result in checks:
        if any(word in value for word in words):
            return result
    return "กระแสวันนี้", (154, 183, 170)


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


def illustration_asset(item: dict, scene: dict | None = None) -> Path:
    item_text = " ".join(clean_text(item.get(key), 1000) for key in ("category", "title", "summary")).lower()
    scene_text = ""
    if scene:
        scene_body = clean_text(scene.get("body"), 1000)
        if clean_text(scene.get("label")) in {"สรุปประเด็นข่าว", "ข่าวด่วนที่ตรวจสอบแล้ว"}:
            first_story = re.search(r"เรื่อง(?:ที่)?(?:แรก|สอง|สาม|สี่|สุดท้าย)", scene_body)
            if first_story:
                scene_body = scene_body[first_story.start():]
            scene_text = scene_body.lower()
        else:
            scene_text = (scene_body + " " + clean_text(scene.get("title"), 1000)).lower()
    patterns = [
        (r"ศาล|อุทธรณ์|ยุติธรรม|มาตรา\s*112|กฎหมาย|คำพิพากษา|\bcourt\b|\blaw\b", "thai-court.jpg"),
        (r"พันธบัตร|ตราสารหนี้|ออมพลัส|ออมทรัพย์|bond|treasury", "bonds-civic.jpg"),
        (r"ทองคำ?|ทองคำแท่ง|gold|โลหะมีค่า", "gold-vault.jpg"),
        (r"น้ำท่วม|น้ำป่า|น้ำหลาก|ฝนตก|สภาพอากาศ|พายุ|มรสุม|คลื่น|ฝุ่น|อากาศ", "weather-bangkok.jpg"),
        (r"ตำรวจ|อาชญาก|คดี|จับกุม|ผู้ต้องหา|อุบัติเหตุ|ภัย|เหตุการณ์", "public-safety.jpg"),
        (r"กีฬา|ฟุตบอล|บาส|นักกีฬา|ทีมชาติ|พรีเมียร์ลีก|แชมป์|แข่งขัน", "sports-stadium.jpg"),
        (r"บันเทิง|นักแสดง|ดารา|ภาพยนตร์|เพลง|คอนเสิร์ต|ศิลปิน|วัฒนธรรม", "culture-stage.jpg"),
        (r"ai|เอไอ|ชิป|เทคโนโลยี|ดาต้าเซ็นเตอร์|ปัญญาประดิษฐ์|ไซเบอร์", "technology-data-center.jpg"),
        (r"รัฐบาล|นายก|รัฐมนตรี|นโยบาย|สภา|เลือกตั้ง|กระทรวง|มาตรการ", "civic-policy.jpg"),
        (r"หุ้น|ลงทุน|ตลาด|เศรษฐกิจ|การเงิน|ธนาคาร|ภาษี|หนี้|ดอกเบี้ย|set|nasdaq|s&p", "market-bangkok.jpg"),
    ]
    # Use the current beat first; searching the whole summary first made one
    # keyword determine the image for every beat in a multi-topic reel.
    for text in (scene_text, item_text):
        for pattern, filename in patterns:
            if re.search(pattern, text, re.I):
                return Path(__file__).resolve().parent / "assets" / "illustrations" / filename
    return Path(__file__).resolve().parent / "assets" / "illustrations" / "market-bangkok.jpg"


def illustration_icon(item: dict, scene: dict | None = None) -> tuple[str, tuple[int, int, int]]:
    asset = illustration_asset(item, scene).stem
    if asset == "thai-court":
        return "landmark", (173, 203, 218)
    if asset == "gold-vault":
        return "hand-coins", (235, 197, 118)
    if asset == "bonds-civic":
        return "landmark", (144, 204, 213)
    _, accent = topic_for(clean_text(item.get("category"), 100) + " " + clean_text(item.get("title"), 300))
    return "briefcase-business", accent


def make_illustration_background(path: Path, item: dict, scene: dict, scene_index: int) -> Path:
    source_path = illustration_asset(item, scene)
    if not source_path.is_file():
        raise RuntimeError(f"Missing bundled news illustration: {source_path.name}")
    with Image.open(source_path) as source:
        image = ImageOps.fit(source.convert("RGB"), (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS,
                             centering=(0.5, 0.5)).convert("RGBA")

    # Still, full-frame editorial art with a restrained grade for white text.
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    for y in range(HEIGHT):
        progress = max(0.0, min(1.0, (y - 420) / 1380))
        alpha = 42 + int(58 * progress)
        shade_draw.line((0, y, WIDTH, y), fill=(3, 10, 19, alpha))
    image = Image.alpha_composite(image, shade)
    output = path / f"illustration-background-{scene_index:02d}.png"
    image.convert("RGB").save(output, optimize=True)
    return output


def make_background(path: Path, item: dict, scene: dict, scene_index: int,
                    scene_count: int) -> Path:
    theme_text = f"{scene.get('title','')} {scene.get('body','')} {item.get('category','')}"
    topic, accent = topic_for(theme_text)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    # Editorial masthead and a clear three-level type hierarchy.
    draw_text_with_fallback(draw, "คิดให้คุ้ม", (SAFE_MARGIN, 58), font(38, True), fallback_font(38, True), (248, 250, 248, 255))
    draw_text_with_fallback(draw, "ข่าวที่ตรวจสอบแล้ว", (SAFE_MARGIN, 111), font(21, True), fallback_font(21, True), (190, 205, 207, 255))
    checked_at = item.get("checkedAt") or item.get("checked_at")
    checked_label = "ตรวจข้อมูลล่าสุด"
    if checked_at:
        try:
            checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00")).astimezone(TZ)
            checked_label = "ตรวจข้อมูล " + checked.strftime("%d %b · %H:%M")
        except ValueError:
            pass
    draw_text_right(draw, checked_label, RIGHT_EDGE, 81, font(21, True), fallback_font(21, True), (220, 229, 228, 255))
    draw.line((SAFE_MARGIN, 165, RIGHT_EDGE, 165), fill=(235, 244, 241, 70), width=2)

    rounded(draw, (SAFE_MARGIN, 204, SAFE_MARGIN + 300, 264), 24, (*accent, 48), (*accent, 112), 1)
    draw.ellipse((SAFE_MARGIN + 21, 226, SAFE_MARGIN + 37, 242), fill=(*accent, 255))
    draw_text_with_fallback(draw, topic, (SAFE_MARGIN + 54, 214), font(25, True), fallback_font(25, True), (245, 248, 246, 255))
    draw_text_right(draw, f"ช่วง {scene_index + 1:02d} / {scene_count:02d}", RIGHT_EDGE, 222,
                    font(22, True), fallback_font(22, True), (221, 232, 230, 255))

    heading = clean_text(scene.get("title"), 150)
    if scene_index == 0:
        heading = re.sub(r"^(?:สรุปข่าว(?:เช้า|เที่ยง|เย็น)?\s*\d{1,2}:\d{2}\s*[—–-]\s*)", "", heading, flags=re.I)
    heading_font = font(64 if scene_index == 0 else 58, True)
    draw_wrapped(draw, heading, (SAFE_MARGIN, 310), heading_font, (250, 251, 249, 255), WIDTH - 2 * SAFE_MARGIN, 3,
                 spacing=20, fallback=fallback_font(heading_font.size, True))

    body = clean_text(scene.get("body"), 260)
    body_font = font(38, False)
    body_fallback = fallback_font(38, False)
    body_lines = wrap_text(body, body_font, CONTENT_WIDTH - 16, 5, body_fallback)
    panel_top = 1000
    panel_bottom = min(1575, panel_top + 166 + max(1, len(body_lines)) * 62)
    rounded(draw, (SAFE_MARGIN, panel_top, RIGHT_EDGE, panel_bottom), 30,
            (5, 17, 25, 232), (*accent, 118), 2)
    rounded(draw, (SAFE_MARGIN + 1, panel_top + 34, SAFE_MARGIN + 9, panel_top + 106), 4, (*accent, 255))
    draw_text_with_fallback(draw, clean_text(scene.get("label") or "สรุปข่าว", 50),
                            (CONTENT_X + 8, panel_top + 43), font(26, True), fallback_font(26, True), (*accent, 255))
    draw_wrapped(draw, body, (CONTENT_X + 8, panel_top + 112), body_font,
                 (247, 249, 247, 255), CONTENT_WIDTH - 16, 5, spacing=17,
                 fallback=body_fallback)

    progress_y = 1644
    rounded(draw, (SAFE_MARGIN, progress_y, RIGHT_EDGE, progress_y + 9), 5, (230, 240, 237, 58))
    progress_right = SAFE_MARGIN + int((RIGHT_EDGE - SAFE_MARGIN) * (scene_index + 1) / scene_count)
    rounded(draw, (SAFE_MARGIN, progress_y, progress_right, progress_y + 9), 5, (*accent, 255))
    draw_text_with_fallback(draw, "แหล่งข่าวและรายละเอียดอยู่ในคำบรรยายโพสต์", (SAFE_MARGIN, 1695),
                            font(22), fallback_font(22), (224, 233, 231, 255))
    draw_text_with_fallback(draw, "เสียงผู้บรรยายสังเคราะห์ด้วย AI", (SAFE_MARGIN, 1750),
                            font(20, True), fallback_font(20, True), (176, 194, 195, 255))

    out = path / f"scene-{scene_index:02d}.png"
    image.save(out, optimize=True)
    return out


def make_visual_reel(backgrounds: list[Path], overlays: list[Path],
                     scene_durations: list[float], output: Path) -> None:
    if not backgrounds or len(backgrounds) != len(overlays) or len(backgrounds) != len(scene_durations):
        raise RuntimeError("Every reel scene needs one background, one text overlay, and one duration")
    transition = min(0.45, min(scene_durations) * 0.25)
    filters: list[str] = []
    for index in range(len(backgrounds)):
        filters.append(
            f"[{index}:v]fps={FPS},setsar=1,settb=1/{FPS},setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        )

    active = "v0"
    elapsed = scene_durations[0]
    for index in range(1, len(backgrounds)):
        next_label = f"xf{index}"
        offset = max(0.0, elapsed - transition)
        filters.append(
            f"[{active}][v{index}]xfade=transition=fade:duration={transition:.3f}:offset={offset:.3f}[{next_label}]"
        )
        active = next_label
        elapsed += scene_durations[index]

    text_start = 0.0
    for index, duration in enumerate(scene_durations):
        text_end = text_start + duration
        overlay_index = len(backgrounds) + index
        text_label = f"text{index}"
        enable = f"gte(t\\,{text_start:.3f})*lt(t\\,{text_end:.3f})"
        filters.append(
            f"[{active}][{overlay_index}:v]overlay=x=0:y=0:format=auto:enable='{enable}'[{text_label}]"
        )
        active = text_label
        text_start = text_end

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for still in [*backgrounds, *overlays]:
        command.extend(["-loop", "1", "-framerate", str(FPS), "-i", str(still)])
    command.extend([
        "-filter_complex", ";".join(filters), "-map", f"[{active}]", "-an",
        "-t", f"{sum(scene_durations):.3f}", "-r", str(FPS), "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ])
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
    backgrounds: list[Path] = []
    overlays: list[Path] = []
    for index, scene in enumerate(scenes):
        backgrounds.append(make_illustration_background(work, item, scene, index))
        overlays.append(make_background(work, item, scene, index, len(scenes)))
    visual = work / "visual.mp4"
    make_visual_reel(backgrounds, overlays, durations, visual)

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
    parser.add_argument("--output", type=Path, help="Output MP4 path for local or render-only output")
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
    requested_item_id = os.environ.get("REQUESTED_ITEM_ID", "").strip()
    if retry_item_id and requested_item_id:
        raise RuntimeError("Choose either a retry item or a direct item ID, not both")
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
    if retry_item_id or requested_item_id:
        queue_params["itemId"] = retry_item_id or requested_item_id
    queue = requests.get(f"{base_url}/api/automation/queue", params=queue_params, headers=headers, timeout=25)
    queue.raise_for_status()
    data = queue.json()
    items = data.get("items") or []
    if not items:
        target = retry_item_id or requested_item_id
        if target:
            print(f"No eligible {mode} news item for the requested ID; nothing was posted.")
        else:
            print(f"No eligible {mode} news item; nothing was posted.")
        return

    item = items[0]
    target = retry_item_id or requested_item_id
    if target and str(item.get("id")) != target:
        raise RuntimeError("Newsroom returned a different item than the requested ID; nothing was posted")
    print(f"Rendering verified {mode} item: {clean_text(item.get('title'), 180)}.", flush=True)
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
            if args.output:
                output = args.output.expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(video, output)
                print(f"Rendered preview saved: {output}", flush=True)
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
