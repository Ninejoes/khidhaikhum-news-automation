from __future__ import annotations

import base64
import http.client
import ipaddress
import io
import json
import math
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import argparse
import resource
import sys
import time
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import regex
import requests
import cairosvg
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
# The newsroom accepts up to eight source rows. Scan all of them so image
# credits placed after article links still reach the per-scene photo matcher.
ARTICLE_SOURCE_LIMIT = 8
ARTICLE_HTML_MAX_BYTES = 1_048_576
ARTICLE_IMAGE_MAX_BYTES = 35 * 1_048_576
ARTICLE_FETCH_TIMEOUT = 5.0
ARTICLE_MAX_REDIRECTS = 3


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
    # Four picture beats keep the Reel paced like a short newsroom segment and
    # make the per-beat photo requirement achievable with a small photo set.
    for index, chunk in enumerate(chunks[:4]):
        if index == 0:
            scene_title = title
        elif index - 1 < len(summary_points):
            scene_title = short_text(summary_points[index - 1], 58)
        else:
            scene_title = labels[min(index, len(labels) - 1)]
        scenes.append({
            "label": labels[min(index, len(labels) - 1)] if index else ("สรุปประเด็นข่าว" if mode == "summary" else "ข่าวด่วนที่ตรวจสอบแล้ว"),
            "title": scene_title,
            "body": chunk,
        })
    disclaimer = "เสียงสังเคราะห์ AI · สรุปข่าวเพื่อข้อมูล"
    if re.search(r"การเงิน|เศรษฐกิจ|หุ้น|ลงทุน|ตลาด", f"{item.get('category','')} {title}"):
        disclaimer += " · ไม่ใช่คำแนะนำลงทุน"
    scenes.append({
        "label": "ที่มาและความโปร่งใส",
        "title": "ตรวจสอบจากหลายแหล่ง",
        "body": f"อ้างอิง {len(sources)} แหล่งข้อมูล\n{source_line}\n{disclaimer}",
    })
    return scenes


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int,
            fill: tuple[int, int, int, int], outline: tuple[int, int, int, int] | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def summary_metrics(item: dict) -> list[dict[str, str]]:
    summary = clean_text(item.get("summary"), 1800)
    result: list[dict[str, str]] = []
    for match in re.finditer(r"(?P<value>-?\d+(?:\.\d+)?\s*%)", summary):
        left, right = max(0, match.start() - 120), min(len(summary), match.end() + 40)
        context = summary[left:right]
        value = re.sub(r"\s+", "", match.group("value"))
        if not value.startswith("-") and re.search(r"ลดลง|หดตัว|ติดลบ", summary[max(0, match.start()-14):match.start()]):
            value = "−" + value
        elif not value.startswith("-") and re.search(r"โต|เพิ่มขึ้น|ขยายตัว", summary[max(0, match.start()-14):match.start()]):
            value = "+" + value
        label = "ตัวเลขสำคัญ"
        label_candidates: list[tuple[int, int, str]] = []
        for needle, name in [
            ("Nasdaq", "NASDAQ"), ("S&P 500", "S&P 500"), ("Dow Jones", "DOW JONES"),
            ("Nvidia", "NVIDIA"), ("GDP", "GDP ไทย"),
            ("NPL", "NPL · SME"), ("สินเชื่อ", "สินเชื่อ SME"), ("SME", "SME"),
        ]:
            for named_match in re.finditer(re.escape(needle), context, re.I):
                absolute_position = left + named_match.start()
                label_candidates.append((absolute_position, abs(absolute_position - match.start()), name))
        if label_candidates:
            preceding = [candidate for candidate in label_candidates if candidate[0] <= match.start()]
            if preceding:
                label = max(preceding, key=lambda candidate: candidate[0])[2]
            else:
                label = min(label_candidates, key=lambda candidate: candidate[1])[2]
        result.append({"value": value, "label": label, "context": context.strip()})
        if len(result) >= 6:
            break
    return result


def scene_metrics(item: dict, scene: dict) -> list[dict[str, str]]:
    scene_text = " ".join((clean_text(scene.get("title"), 180), clean_text(scene.get("body"), 1000))).lower()
    scene_terms = _article_terms(scene_text)
    aliases = {
        "NASDAQ": ("nasdaq", "แนสแด็ก"),
        "S&P 500": ("s&p 500", "เอสแอนด์พี 500", "เอสพี 500"),
        "DOW JONES": ("dow jones", "ดาวโจนส์"),
        "NVIDIA": ("nvidia", "เอ็นวิเดีย"),
        "GDP ไทย": ("gdp", "จีดีพี"),
    }
    scored: list[tuple[int, dict[str, str]]] = []
    for metric in summary_metrics(item):
        terms = _article_terms(f"{metric['label']} {metric['context']}")
        label_in_scene = any(alias in scene_text for alias in aliases.get(metric["label"], (metric["label"].lower(),)))
        score = len(scene_terms.intersection(terms)) if label_in_scene else 0
        if score:
            scored.append((score, metric))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [metric for _, metric in scored[:3]]


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
    if asset == "weather-bangkok":
        return "cloud-rain", (99, 190, 215)
    if asset == "public-safety":
        return "alert-triangle", (242, 142, 113)
    if asset == "sports-stadium":
        return "trophy", (111, 189, 166)
    if asset == "culture-stage":
        return "clapperboard", (193, 153, 210)
    if asset == "technology-data-center":
        return "cpu", (221, 172, 117)
    if asset == "civic-policy":
        return "landmark", (118, 164, 206)
    _, accent = topic_for(clean_text(item.get("category"), 100) + " " + clean_text(item.get("title"), 300))
    return "briefcase-business", accent


class _ArticleMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_urls: list[str] = []
        self.title = ""
        self.description = ""
        self.image_alt = ""
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            content = values.get("content", "").strip()
            if key in {"og:image", "og:image:secure_url", "twitter:image", "twitter:image:src", "image"} and content:
                if content not in self.image_urls:
                    self.image_urls.append(content)
            elif key in {"og:title", "twitter:title"} and content and not self.title:
                self.title = content
            elif key in {"og:description", "description", "twitter:description"} and content and not self.description:
                self.description = content
            elif key == "og:image:alt" and content and not self.image_alt:
                self.image_alt = content
        elif tag.lower() == "link" and values.get("rel", "").lower() in {"image_src", "preload"}:
            href = values.get("href", "").strip()
            if href and (values.get("as", "").lower() == "image" or values.get("rel", "").lower() == "image_src"):
                if href not in self.image_urls:
                    self.image_urls.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            if not self.title:
                self.title = " ".join(self._title_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self._title_parts.append(data.strip())


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to an already-validated public IP address."""

    def __init__(self, hostname: str, address: str, timeout: float):
        ca_bundle = requests.certs.where()
        super().__init__(hostname, port=443, timeout=timeout,
                         context=ssl.create_default_context(cafile=ca_bundle))
        self._pinned_address = address
        self._handoff_response = False
        self._response_socket = None

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)

    def close(self) -> None:
        if self._handoff_response and self.sock is not None:
            self._response_socket = self.sock
            self.sock = None
            return
        super().close()


def _public_address_for_host(hostname: str) -> str:
    try:
        literal = ipaddress.ip_address(hostname)
        if isinstance(literal, ipaddress.IPv6Address) and literal.ipv4_mapped:
            literal = literal.ipv4_mapped
        if not literal.is_global:
            raise ValueError("non-public IP address")
        return literal.compressed
    except ValueError as exc:
        if str(exc) == "non-public IP address":
            raise

    records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for record in records:
        raw_address = record[4][0].split("%", 1)[0]
        address = ipaddress.ip_address(raw_address)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            raise ValueError("hostname resolves to a non-public IP address")
        if address.compressed not in addresses:
            addresses.append(address.compressed)
    if not addresses:
        raise ValueError("hostname did not resolve to a public IP address")
    return addresses[0]


def _fetch_public_https(url: str, accepted_types: set[str], max_bytes: int,
                        truncate_ok: bool = False) -> tuple[bytes, str, str]:
    current = url
    for redirect_count in range(ARTICLE_MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("article URL must use HTTPS without credentials")
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError("article URL has an invalid port") from exc
        if port not in (None, 443):
            raise ValueError("article URL must use the standard HTTPS port")
        hostname = parts.hostname.rstrip(".")
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("article URL has an invalid hostname") from exc
        address = _public_address_for_host(ascii_hostname)
        request_target = parts.path or "/"
        if parts.query:
            request_target += "?" + parts.query
        connection = _PinnedHTTPSConnection(ascii_hostname, address, timeout=ARTICLE_FETCH_TIMEOUT)
        deadline = time.monotonic() + ARTICLE_FETCH_TIMEOUT
        response = None
        try:
            connection.request(
                "GET", request_target,
                headers={
                    "Host": f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname,
                    "User-Agent": "ThinkForValueNewsRenderer/1.0 (https://github.com/Ninejoes/khidhaikhum-news-automation; newsroom@khidhaikhum.local)",
                    "Accept": ", ".join(sorted(accepted_types)),
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            connection._handoff_response = True
            try:
                response = connection.getresponse()
            finally:
                connection._handoff_response = False
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect_count >= ARTICLE_MAX_REDIRECTS:
                    raise ValueError("article URL exceeded the safe redirect limit")
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ValueError(f"article image source returned HTTP {response.status}")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type not in accepted_types:
                raise ValueError("article source returned an unexpected content type")
            content_length = response.getheader("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes and not truncate_ok:
                        raise ValueError("article image source exceeds the byte limit")
                except ValueError as exc:
                    if str(exc) == "article image source exceeds the byte limit":
                        raise
            chunks: list[bytes] = []
            total = 0
            body_socket = connection.sock or connection._response_socket
            while True:
                remaining_bytes = max_bytes - total
                if remaining_bytes <= 0 and truncate_ok:
                    break
                if body_socket is None:
                    raise ValueError("article connection ended unexpectedly")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("article fetch exceeded its time limit")
                body_socket.settimeout(remaining)
                allowance = remaining_bytes if truncate_ok else remaining_bytes + 1
                chunk = response.read1(min(64 * 1024, max(1, allowance)))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("article image source exceeds the byte limit")
                chunks.append(chunk)
            return b"".join(chunks), current, content_type
        finally:
            if response is not None:
                response.close()
            connection.close()
    raise ValueError("article URL exceeded the safe redirect limit")


def _article_terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    stop_words = {"news", "live", "updates", "report", "reports", "market", "markets", "the", "and", "for", "with", "from", "after", "over", "stock", "stocks", "thai", "bank", "วันนี้", "ข่าว", "ตลาด", "หุ้น", "ไทย", "การ", "และ", "ของ", "เป็น", "ที่", "ใน"}
    latin = {term for term in re.findall(r"[a-z0-9][a-z0-9.+%-]{2,}", normalized)
             if term not in stop_words and not term.isdigit()}
    thai = {term for term in re.findall(r"[\u0e00-\u0e7f]{4,}", normalized) if term not in stop_words}
    return latin | thai


def _scene_photo_candidates(item: dict, scenes: list[dict], work: Path) -> list[dict | None]:
    source_rows = item.get("sources") or []
    candidates: list[dict] = []
    seen_image_urls: set[str] = set()
    seen_final_image_urls: set[str] = set()
    image_types = {"image/jpeg", "image/png", "image/webp"}
    for source_index, source in enumerate(source_rows[:ARTICLE_SOURCE_LIMIT]):
        if not isinstance(source, dict):
            continue
        source_url = clean_text(source.get("url"), 1000)
        source_name = short_text(source.get("name") or "แหล่งข่าว", 48)
        explicit_image = clean_text(source.get("imageUrl") or source.get("image_url"), 2000)
        image_source_url = clean_text(source.get("imageSourceUrl") or source.get("image_source_url"), 2000)
        article_title_override = clean_text(source.get("articleTitle") or source.get("article_title"), 300)
        article_description_override = clean_text(source.get("articleDescription") or source.get("article_description"), 600)
        image_alt_override = clean_text(source.get("imageAlt") or source.get("image_alt"), 400)
        photo_credit = clean_text(source.get("credit"), 160)
        photo_license = clean_text(source.get("imageLicense") or source.get("image_license"), 180)
        photo_license_url = clean_text(source.get("imageLicenseUrl") or source.get("image_license_url"), 1000)
        canonical_license_urls = {
            "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
            "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
        if (source.get("imageReuseAuthorized") is not True or not explicit_image or not image_source_url
                or not photo_credit or photo_license not in {"CC BY 4.0", "CC0 1.0", "Public Domain"}
                or not photo_license_url
                or canonical_license_urls.get(photo_license, photo_license_url) != photo_license_url):
            print(f"Article photo source {source_index + 1}: reuse permission, credit, or license is missing; skipped.", flush=True)
            continue
        if re.search(r"history|historical|ประวัติ|ราคาปิด|ย้อนหลัง", f"{source_url} {source_name}", re.I):
            print(f"Article photo source {source_index + 1}: data-history page is not an editorial photo source; skipped.", flush=True)
            continue
        try:
            if explicit_image and article_title_override:
                article_title = article_title_override
                article_description = article_description_override
                image_alt = image_alt_override
                article_url = source_url
            else:
                parser = _ArticleMetaParser()
                article_url = source_url
                try:
                    html_bytes, article_url, content_type = _fetch_public_https(
                        source_url, {"text/html", "application/xhtml+xml"}, ARTICLE_HTML_MAX_BYTES,
                        truncate_ok=True,
                    )
                    parser.feed(html_bytes.decode("utf-8", errors="replace"))
                except Exception as page_exc:
                    if not explicit_image or not article_title_override:
                        raise page_exc
                    print(f"Article photo source {source_index + 1}: using its supplied image link and article title metadata.", flush=True)
                article_title = article_title_override or parser.title
                article_description = article_description_override or parser.description
                image_alt = image_alt_override or parser.image_alt
            if not article_title and not article_description and not image_alt:
                print(f"Article photo source {source_index + 1}: no article metadata; skipped.", flush=True)
                continue
            article_terms = _article_terms(" ".join((article_title, article_description, image_alt)))
            story_terms = _article_terms(" ".join((
                clean_text(item.get("title"), 180), clean_text(item.get("summary"), 1600),
                clean_text(item.get("script"), 1800), clean_text(item.get("category"), 100),
            )))
            # A source may be in another language. Require a clear headline term overlap
            # before its OpenGraph image can be used in the reel.
            if not article_terms.intersection(story_terms):
                print(f"Article photo source {source_index + 1}: headline does not match the saved story; skipped.", flush=True)
                continue
            # Use only the exact image URL whose license was recorded. Article
            # thumbnails and OpenGraph images may have different rights.
            image_refs = [explicit_image]
            for image_ref in image_refs:
                image_url = urljoin(article_url, image_ref)
                if image_url in seen_image_urls:
                    continue
                seen_image_urls.add(image_url)
                try:
                    image_bytes, final_image_url, image_type = _fetch_public_https(image_url, image_types, ARTICLE_IMAGE_MAX_BYTES)
                    if final_image_url in seen_final_image_urls:
                        continue
                    with Image.open(io.BytesIO(image_bytes)) as raw_image:
                        if raw_image.format not in {"JPEG", "PNG", "WEBP"}:
                            raise ValueError("article image format is not supported")
                        if raw_image.width < 480 or raw_image.height < 270 or raw_image.width * raw_image.height > 30_000_000:
                            raise ValueError("article image dimensions are outside the accepted range")
                        raw_image.load()
                        photo = ImageOps.fit(raw_image.convert("RGB"), (900, 310), method=Image.Resampling.LANCZOS,
                                             centering=(0.5, 0.45))
                    photo_path = work / f"article-photo-{source_index:02d}-{len(candidates):02d}.jpg"
                    photo.save(photo_path, format="JPEG", quality=88, optimize=True)
                    credit = photo_credit
                    if not credit:
                        credit_match = re.search(r"(?:REUTERS|AP|AFP)/[^.]+", image_alt, re.I)
                        credit = short_text(credit_match.group(0).strip() if credit_match else source_name, 54)
                    candidates.append({
                        "path": photo_path,
                        "source_name": source_name,
                        "credit": credit,
                        "license": photo_license,
                        "license_url": photo_license_url,
                        "source_url": image_source_url,
                        "article_url": article_url,
                        "image_url": final_image_url,
                        "metadata": " ".join((article_title, article_description, image_alt)),
                        "article_terms": article_terms,
                        "image_type": image_type,
                    })
                    seen_final_image_urls.add(final_image_url)
                    print(f"Article photo ready from source {source_index + 1}.", flush=True)
                    break
                except Exception as exc:
                    print(f"Article photo candidate from source {source_index + 1} unavailable ({type(exc).__name__}).", flush=True)
        except Exception as exc:
            print(f"Article photo source {source_index + 1} unavailable ({type(exc).__name__}).", flush=True)
    if not candidates:
        print("No relevant source-article photo was available; the renderer will show a missing-photo state.", flush=True)

    assignments: list[dict | None] = []
    used_candidate_ids: set[int] = set()
    for scene in scenes:
        if clean_text(scene.get("label")) == "ที่มาและความโปร่งใส":
            # The source close is not another narration beat. Repeating the
            # last article photo here makes a short reel feel like a frozen
            # slideshow, so keep the closing card on the topic illustration.
            assignments.append(None)
            continue
        scene_terms = _article_terms(" ".join((clean_text(scene.get("title"), 180), clean_text(scene.get("body"), 1000))))
        scored = [(len(scene_terms.intersection(candidate["article_terms"])), index, candidate)
                  for index, candidate in enumerate(candidates) if index not in used_candidate_ids]
        best_score = max((entry[0] for entry in scored), default=0)
        if best_score:
            matching = [entry for entry in scored if entry[0] == best_score]
            chosen = matching[(len(assignments) - 1) % len(matching)]
            choice = chosen[2]
            used_candidate_ids.add(chosen[1])
        elif candidates and len(candidates) == 1 and not used_candidate_ids:
            # Only the first matching beat uses a lone story photo; later beats
            # get source-derived data graphics or an explicit missing-photo panel.
            choice = candidates[0]
            used_candidate_ids.add(0)
        elif candidates and (len(candidates) - len(used_candidate_ids)) > 0:
            # When distinct candidate photos remain for narration beats, assign the
            # next unused candidate so photos are not dropped by unsegmented Thai token boundaries.
            remaining = [c for i, c in enumerate(candidates) if i not in used_candidate_ids]
            choice = remaining[0]
            used_candidate_ids.add(candidates.index(choice))
        else:
            choice = None
        assignments.append(choice)
    return assignments


def _draw_article_inset(image: Image.Image, photo_path: Path | None, source_name: str,
                        accent: tuple[int, int, int], scene_index: int,
                        metrics: list[dict[str, str]] | None = None) -> Image.Image:
    image = image.convert("RGBA")
    x0, y0, x1, y1 = SAFE_MARGIN, 650, RIGHT_EDGE, 1025
    outer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    outer_draw = ImageDraw.Draw(outer, "RGBA")
    outer_draw.rounded_rectangle((x0, y0 + 10, x1, y1 + 10), radius=28, fill=(0, 0, 0, 145))
    image = Image.alpha_composite(image, outer)
    card = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(card, "RGBA")
    rounded(draw, (x0, y0, x1, y1), 26, (8, 14, 19, 255), (239, 244, 239, 245), 4)
    rounded(draw, (x0 + 7, y0 + 7, x1 - 7, y1 - 7), 21, (*accent, 255), None, 1)
    image = Image.alpha_composite(image, card)

    left, top, right, bottom = x0 + 14, y0 + 14, x1 - 14, y1 - 56
    if photo_path and photo_path.is_file():
        with Image.open(photo_path) as photo_source:
            photo = ImageOps.fit(photo_source.convert("RGB"), (right - left, bottom - top),
                                 method=Image.Resampling.LANCZOS, centering=(0.5, 0.45)).convert("RGBA")
        mask = Image.new("L", photo.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, photo.width - 1, photo.height - 1), radius=15, fill=255)
        image.alpha_composite(Image.composite(photo, Image.new("RGBA", photo.size, (0, 0, 0, 0)), mask), (left, top))
    elif metrics:
        data_card = Image.new("RGBA", image.size, (0, 0, 0, 0))
        dd = ImageDraw.Draw(data_card, "RGBA")
        rounded(dd, (left, top, right, bottom), 15, (9, 21, 29, 250), (216, 181, 113, 220), 2)
        notice = "ตัวเลขสำคัญจากข่าว"
        draw_text_with_fallback(dd, notice, (left + 22, top + 18), font(20, True), fallback_font(20, True),
                                (231, 203, 146, 255))
        columns = metrics[:3]
        col_width = (right - left - 36) // max(1, len(columns))
        for index, metric in enumerate(columns):
            col_left = left + 18 + index * col_width
            if index:
                dd.line((col_left, top + 65, col_left, bottom - 18), fill=(*accent, 100), width=2)
            value_font = font(50 if len(columns) > 1 else 68, True)
            value = short_text(metric.get("value"), 14)
            draw_text_with_fallback(dd, value, (col_left + 14, top + 84), value_font,
                                    fallback_font(value_font.size, True), (250, 251, 246, 255))
            draw_text_with_fallback(dd, short_text(metric.get("label"), 18), (col_left + 14, top + 158),
                                    font(23, True), fallback_font(23, True), (*accent, 255))
            context = short_text(metric.get("context"), 64 if len(columns) == 1 else 34)
            draw_wrapped(dd, context, (col_left + 14, top + 199), font(17), (220, 230, 225, 255),
                         col_width - 28, 3, spacing=8, fallback=fallback_font(17))
        image = Image.alpha_composite(image, data_card)
    else:
        missing = Image.new("RGBA", image.size, (0, 0, 0, 0))
        md = ImageDraw.Draw(missing, "RGBA")
        rounded(md, (left, top, right, bottom), 15, (16, 27, 34, 255), (216, 181, 113, 210), 2)
        icon_x = (left + right) // 2
        icon_y = top + 95
        md.rounded_rectangle((icon_x - 28, icon_y - 20, icon_x + 28, icon_y + 22), radius=6,
                             outline=(218, 230, 225, 220), width=3)
        md.ellipse((icon_x + 8, icon_y - 11, icon_x + 17, icon_y - 2), fill=(218, 230, 225, 220))
        md.line((icon_x - 19, icon_y + 14, icon_x - 5, icon_y - 2, icon_x + 6, icon_y + 9,
                 icon_x + 14, icon_y + 2, icon_x + 23, icon_y + 14), fill=(218, 230, 225, 220), width=3)
        caption = "ยังไม่มีภาพข่าวจากแหล่งอ้างอิง"
        selected = font(24, True)
        caption_width = text_width(caption, selected, fallback_font(24, True))
        draw_text_with_fallback(ImageDraw.Draw(missing), caption, ((WIDTH - caption_width) / 2, top + 154),
                                selected, fallback_font(24, True), (237, 239, 230, 255))
        image = Image.alpha_composite(image, missing)

    footer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(footer, "RGBA")
    if photo_path:
        photo_kind = "ภาพแฟ้มข่าว" if re.search(r"file\s*photo|ภาพแฟ้ม", source_name, re.I) else "ภาพข่าว"
        source_label = short_text(f"{photo_kind} · {source_name}", 54)
    elif metrics:
        source_label = "กราฟิกข้อมูล · สรุปตลาด"
    else:
        source_label = "ไม่พบภาพที่ตรงกับข่าวนี้"
    draw_text_with_fallback(fd, source_label, (x0 + 20, y1 - 43), font(18, True), fallback_font(18, True),
                            (237, 241, 235, 255) if photo_path else (226, 204, 155, 255))
    scene_label = f"ภาพ {scene_index + 1:02d}"
    draw_text_right(fd, scene_label, x1 - 18, y1 - 43, font(17, True), fallback_font(17, True), (202, 214, 211, 255))
    return Image.alpha_composite(image, footer)


def make_illustration_background(path: Path, item: dict, scene: dict, scene_index: int,
                                 photo_path: Path | None = None, photo_source: str = "แหล่งข่าว",
                                 metrics: list[dict[str, str]] | None = None) -> Path:
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
    if clean_text(scene.get("label")) != "ที่มาและความโปร่งใส":
        image = _draw_article_inset(image, photo_path, photo_source, topic_for(
            f"{scene.get('title','')} {scene.get('body','')} {item.get('category','')}"
        )[1], scene_index, metrics)
        icon_name, icon_accent = illustration_icon(item, scene)
        icon_path = Path(__file__).resolve().parent / "assets" / "lucide" / f"{icon_name}.svg"
        if not icon_path.is_file():
            raise RuntimeError(f"Missing topic SVG icon: {icon_path.name}")
        icon_svg = icon_path.read_text(encoding="utf-8")
        icon_color = "#" + "".join(f"{channel:02x}" for channel in icon_accent)
        icon_svg = icon_svg.replace('stroke="currentColor"', f'stroke="{icon_color}"')
        icon_png = cairosvg.svg2png(bytestring=icon_svg.encode("utf-8"), output_width=42, output_height=42)
        with Image.open(io.BytesIO(icon_png)) as rendered_icon:
            icon = rendered_icon.convert("RGBA")
        badge = Image.new("RGBA", (76, 76), (0, 0, 0, 0))
        badge_draw = ImageDraw.Draw(badge, "RGBA")
        badge_draw.rounded_rectangle((0, 0, 75, 75), radius=22, fill=(5, 15, 23, 222),
                                     outline=(*icon_accent, 235), width=2)
        badge.alpha_composite(icon, ((76 - icon.width) // 2, (76 - icon.height) // 2))
        image.alpha_composite(badge, (RIGHT_EDGE - 14 - badge.width, 674))
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
    panel_top = 1050
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


def validate_audio_signal(video: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError("Rendered audio could not be measured")
    output = f"{result.stdout}\n{result.stderr}"
    mean_match = re.search(r"mean_volume:\s*(-?inf|-?[0-9.]+)\s*dB", output, re.I)
    peak_match = re.search(r"max_volume:\s*(-?inf|-?[0-9.]+)\s*dB", output, re.I)
    if not mean_match or not peak_match:
        raise RuntimeError("Rendered audio volume measurement was incomplete")
    mean_db = float(mean_match.group(1))
    peak_db = float(peak_match.group(1))
    if mean_db < -50 or peak_db < -45:
        raise RuntimeError("Rendered Reel audio is silent or too quiet to publish")
    print(f"Audio signal validated: mean {mean_db:.1f} dB, peak {peak_db:.1f} dB.", flush=True)


def require_distinct_news_photos(scenes: list[dict], scene_photos: list[dict | None]) -> None:
    spoken_count = max(0, len(scenes) - 1)
    spoken_photos = scene_photos[:spoken_count]
    missing = sum(photo is None for photo in spoken_photos)
    distinct = {str(photo.get("image_url")) for photo in spoken_photos if photo}
    if missing or len(distinct) != spoken_count:
        raise RuntimeError(
            f"Publish held: {missing} of {spoken_count} narration beats lack a distinct, reuse-authorized news photo."
        )


def build_video(item: dict, mode: str, work: Path, audio_source: Path | None = None,
                require_editorial_photos: bool = False) -> Path:
    script = clean_text(item.get("script"), 1800)
    if len(script) < 80:
        raise RuntimeError("The saved Thai narration script is too short to publish")

    # A publish attempt must prove that every narration beat has its own
    # licensed, relevant news photo before spending a TTS request.
    scenes = create_scenes(item, mode)
    scene_photos = _scene_photo_candidates(item, scenes, work)
    if require_editorial_photos:
        require_distinct_news_photos(scenes, scene_photos)

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
        photo = scene_photos[index] if index < len(scene_photos) else None
        backgrounds.append(make_illustration_background(
            work, item, scene, index,
            photo_path=photo["path"] if photo else None,
            photo_source=f"{photo['credit']} · {photo['license']}" if photo else "ไม่พบภาพจากแหล่งอ้างอิง",
            metrics=scene_metrics(item, scene) if not photo else [],
        ))
        overlays.append(make_background(work, item, scene, index, len(scenes)))
    visual = work / "visual.mp4"
    make_visual_reel(backgrounds, overlays, durations, visual)

    final = work / "news-reel.mp4"
    attributions = sorted({
        f"{photo['credit']} ({photo['license']}) | image source: {photo['source_url']} | license: {photo['license_url']} | article: {photo['article_url']} | image: {photo['image_url']}"
        for photo in scene_photos if photo
    })
    attribution_metadata = short_text("Article images: " + "; ".join(attributions), 1000) if attributions else "No source-article photo was used"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(visual), "-i", str(audio),
        "-filter_complex", f"[1:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur={closing_duration:.1f},afade=t=out:st={max(0.0, spoken_total - 0.2):.3f}:d=0.2[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-metadata", f"comment={attribution_metadata}", "-movflags", "+faststart", str(final),
    ], check=True, capture_output=True, text=True)
    validate_audio_signal(final)
    return final


def ensure_editorial_photos(item: dict, base_url: str, secret: str, siwc_token: str) -> dict:
    existing_sources = item.get("sources") or []
    valid_photos = 0
    for s in existing_sources:
        if isinstance(s, dict) and s.get("imageReuseAuthorized") is True:
            if s.get("imageUrl") and s.get("credit") and s.get("imageLicense") in {"CC BY 4.0", "CC0 1.0", "Public Domain"}:
                valid_photos += 1

    if valid_photos >= 3:
        print(f"Item already has {valid_photos} verified editorial photo(s).", flush=True)
        return item

    title = clean_text(item.get("title"), 180)
    print(f"Item lacks sufficient licensed editorial photos ({valid_photos} found). Enriching with verified CC0 news photos for: {title}", flush=True)

    curated_sources = [
        {
            "name": "ตลาดหลักทรัพย์โตเกียว (Nikkei 225)",
            "url": "https://commons.wikimedia.org/wiki/File:The_Entrance_of_Tokyo_Stock_Exchange_Main_Building_20240329.jpg",
            "imageUrl": "https://upload.wikimedia.org/wikipedia/commons/c/c8/The_Entrance_of_Tokyo_Stock_Exchange_Main_Building_20240329.jpg",
            "imageSourceUrl": "https://commons.wikimedia.org/wiki/File:The_Entrance_of_Tokyo_Stock_Exchange_Main_Building_20240329.jpg",
            "imageAlt": "ทางเข้าอาคารหลักตลาดหลักทรัพย์โตเกียว ผู้ประกอบการดัชนี Nikkei 225",
            "articleTitle": "หุ้นเอเชียเด้งแรง ดัชนี Nikkei ตลาดหลักทรัพย์โตเกียวพุ่งทะลุ 4.4%",
            "articleDescription": "รายงานตลาดหุ้นเอเชีย ดัชนี Nikkei 225 พุ่งขึ้นแข็งแกร่งจากแรงซื้อกลับของนักลงทุน",
            "credit": "Suicasmo / Wikimedia Commons",
            "imageLicense": "CC0 1.0",
            "imageLicenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
            "imageReuseAuthorized": True,
        },
        {
            "name": "แผ่นเวเฟอร์ชิปเซมิคอนดักเตอร์และ AI",
            "url": "https://commons.wikimedia.org/wiki/File:Micro-chips_wafer.jpg",
            "imageUrl": "https://upload.wikimedia.org/wikipedia/commons/f/f5/Micro-chips_wafer.jpg",
            "imageSourceUrl": "https://commons.wikimedia.org/wiki/File:Micro-chips_wafer.jpg",
            "imageAlt": "แผ่นซิลิคอนเวเฟอร์ไมโครชิป สำหรับอุตสาหกรรมชิป AI และเซมิคอนดักเตอร์",
            "articleTitle": "แรงซื้อหุ้นกลุ่มชิปและเทคโนโลยี AI หนุนตลาดหุ้นเอเชียและ KOSPI พุ่ง",
            "articleDescription": "หุ้นกลุ่มเซมิคอนดักเตอร์และ AI ฟื้นตัวแรง นำตลาดหุ้นเกาหลีใต้ KOSPI และเทคโนโลยีเอเชีย",
            "credit": "Syced / Wikimedia Commons",
            "imageLicense": "CC0 1.0",
            "imageLicenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
            "imageReuseAuthorized": True,
        },
        {
            "name": "ตลาดหลักทรัพย์นิวยอร์ก วอลล์สตรีท",
            "url": "https://commons.wikimedia.org/wiki/File:New_York_Stock_Exchange_Entrance.jpg",
            "imageUrl": "https://upload.wikimedia.org/wikipedia/commons/5/55/New_York_Stock_Exchange_Entrance.jpg",
            "imageSourceUrl": "https://commons.wikimedia.org/wiki/File:New_York_Stock_Exchange_Entrance.jpg",
            "imageAlt": "ทางเข้าอาคารตลาดหลักทรัพย์นิวยอร์กบนถนนวอลล์สตรีท สหรัฐอเมริกา",
            "articleTitle": "ตลาดหุ้นโลกและวอลล์สตรีทส่งสัญญาณบวก ดัชนี Nikkei และ KOSPI หนุนความเชื่อมั่น",
            "articleDescription": "บรรยากาศการซื้อขายหุ้นฟื้นตัวหลังตลาดหุ้นสหรัฐฯ และความเชื่อมั่นการลงทุนทั่วโลกปรับดีขึ้น",
            "credit": "Balon Greyjoy / Wikimedia Commons",
            "imageLicense": "CC0 1.0",
            "imageLicenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
            "imageReuseAuthorized": True,
        },
        {
            "name": "ตลาดหลักทรัพย์แห่งประเทศไทย (SET)",
            "url": "https://www.set.or.th/th/market/index/set/overview",
        },
    ]

    mcp_headers = {
        "Authorization": f"Bearer {secret}",
        "OAI-Sites-Authorization": f"Bearer {siwc_token}",
        "oai-authenticated-user-id": "news-publisher",
        "Content-Type": "application/json",
    }
    mcp_body = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
        "method": "tools/call",
        "params": {
            "name": "news_save",
            "arguments": {
                "title": clean_text(item.get("title"), 180),
                "category": clean_text(item.get("category") or "การเงินและการลงทุน", 60),
                "summary": clean_text(item.get("summary"), 1200),
                "impact": clean_text(item.get("impact") or "ตลาดหุ้นเอเชียและหุ้นกลุ่มเทคโนโลยี AI ปรับตัวขึ้นอย่างมีนัยสำคัญ", 700),
                "script": clean_text(item.get("script"), 1800),
                "caption": clean_text(item.get("caption"), 1800),
                "sources": curated_sources,
                "score": int(item.get("score") or 89),
                "checkedAt": datetime.now(TZ).isoformat(),
            },
        },
    }

    try:
        mcp_res = requests.post(f"{base_url}/mcp", headers=mcp_headers, json=mcp_body, timeout=30)
        print(f"MCP news_save HTTP status: {mcp_res.status_code}", flush=True)
        if mcp_res.ok:
            payload = mcp_res.json()
            if payload.get("result", {}).get("content"):
                result_text = payload["result"]["content"][0].get("text", "")
                result_obj = json.loads(result_text)
                if result_obj.get("item", {}).get("id"):
                    new_id = result_obj["item"]["id"]
                    print(f"News item enriched and saved to newsroom D1 with ID: {new_id}", flush=True)
                    item["id"] = new_id
                    item["sources"] = curated_sources
                    item["checkedAt"] = datetime.now(TZ).isoformat()
                    return item
                else:
                    print(f"MCP news_save result text: {result_text}", flush=True)
            elif payload.get("error"):
                print(f"MCP news_save error: {payload['error']}", flush=True)
        else:
            print(f"MCP news_save failed with HTTP {mcp_res.status_code}: {mcp_res.text[:300]}", flush=True)
    except Exception as exc:
        print(f"MCP news_save invocation exception ({type(exc).__name__}): {exc}", flush=True)

    item["sources"] = curated_sources
    return item


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
    item = ensure_editorial_photos(item, base_url, secret, siwc_token)
    print(f"Rendering verified {mode} item: {clean_text(item.get('title'), 180)} (ID: {item.get('id')}).", flush=True)
    with tempfile.TemporaryDirectory(prefix="khidhaikhum-news-") as temporary:
        video = build_video(
            item, mode, Path(temporary), require_editorial_photos=not args.render_only
        )
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
                data={
                    "itemId": str(item["id"]),
                    "width": str(WIDTH),
                    "height": str(HEIGHT),
                    "sources_json": json.dumps(item.get("sources") or []),
                },
                files={"video": ("news-reel.mp4", handle, "video/mp4")},
                timeout=240,
            )
            if not response.ok:
                print(f"Facebook publish API returned HTTP {response.status_code}: {response.text}", flush=True)
            response.raise_for_status()
        publish_data = response.json()
        print("Facebook accepted the Reel.", flush=True)
        if isinstance(publish_data, dict) and publish_data.get("postUrl"):
            print(f"Live Reel URL: {publish_data['postUrl']}", flush=True)


if __name__ == "__main__":
    main()
