"""Dynamic Visual Scene & Dramatic Cover Generator for KhidHaiKhum Reels.

Provides:
1. High-Impact 3D-Style Financial News Cover (build_cover_html)
   - Dramatic dark studio background with glowing candlestick chart
   - Topic-aware 3D-styled SVG hero artwork (AI chip/GPU, Gold bullion, Fuel/Diesel, Banking/Salary, Home/Refinance, Tax/Economy)
   - Giant 3D glossy trend arrow (crashing red or soaring green) with glowing impact flare
   - Top-right 'คิดให้คุ้ม NEWS' badge
   - Giant 2-line Orange + White Thai headline with bottom accent bar

2. Fast-Paced 3-4 Second Multi-Template Scene Generator (build_subshot_html)
   - Cycles through 8 distinct visual layouts every 3-4 seconds:
     * Template 0: Dramatic Cover Hook Poster
     * Template 1: 2D Character 'ต้น' + Mobile Banking App UI + Top-Left HUD (Warm Cream)
     * Template 2: High-Impact Dark Navy Number & Delta Spotlight Card + Character 'ต้น'
     * Template 3: 2D Character 'ต้น' + Calendar Flip & Expense Deduction Slips (Dark/Cream)
     * Template 4: Interactive Whiteboard Doodly + 3D Marker Pen Highlight
     * Template 5: Red Alert Financial Trap Card + Shocked Character 'ต้น'
     * Template 6: Horizontal Proportion Breakdown Bar Chart ('เงินหายไปไหน')
     * Template 7: Forest Green 1-2-3 Actionable Checklist Card
"""
from __future__ import annotations

import html
import re
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
DOODLES_DIR = ASSETS_DIR / "doodles"
FONTS_DIR = ASSETS_DIR / "fonts"


def _font_urls() -> tuple[str, str]:
    font_bold = f"file://{(FONTS_DIR / 'Kanit-Bold.ttf').resolve()}"
    font_med = f"file://{(FONTS_DIR / 'Kanit-Medium.ttf').resolve()}"
    return font_bold, font_med


def detect_visual_theme(text: str) -> str:
    """Detects the best visual theme for cover & prop illustrations."""
    t = text.lower()
    if any(k in t for k in ["ai", "ชิป", "หุ้น", "เทค", "nvidia", "เซิร์ฟเวอร์", "ดัชนี", "ตลาดหุ้น", "บิตคอยน์", "คริปโต"]):
        return "ai_tech"
    if any(k in t for k in ["ทอง", "gold", "รูปพรรณ", "ทองแท่ง"]):
        return "gold"
    if any(k in t for k in ["ดีเซล", "น้ำมัน", "เบนซิน", "ค่าไฟ", "พลังงาน", "ก๊าซ", "ค่ารถ"]):
        return "fuel"
    if any(k in t for k in ["บ้าน", "คอนโด", "รีไฟแนนซ์", "ดอกเบี้ยบ้าน", "ผ่อนบ้าน", "อสังหา"]):
        return "home"
    if any(k in t for k in ["ภาษี", "สรรพากร", "ลดหย่อน", "ประกันสังคม", "บำนาญ", "รัฐ"]):
        return "tax"
    return "salary"


def split_cover_headlines(title: str, subtitle: str = "") -> tuple[str, str]:
    """Splits a topic title into two punchy cover headline lines (Line 1 Orange, Line 2 White) without mid-word cutoffs."""
    clean_title = re.sub(r"—\s*—", "—", title).strip()
    clean_title = re.sub(r"\s*—\s*สรุปประเด็นตัวเลขจริง.*$", "", clean_title).strip()
    clean_title = re.sub(
        r"^(?:ข่าวด่วน|ด่วนพิเศษ|ด่วน)\s*(?:\d{1,2}[:.]\d{2}(?:\s*น\.?)?)?\s*(?:[—–\-:|•]\s*)?",
        "",
        clean_title,
    ).strip()
    clean_title = re.sub(r"^\d{1,2}[:.]\d{2}(?:\s*น\.?)?\s*(?:[—–\-:|•]\s*)+", "", clean_title).strip()

    for sep in ("—", ":", "|", "/"):
        if sep in clean_title:
            parts = [p.strip() for p in clean_title.split(sep) if p.strip()]
            if len(parts) >= 2 and len(parts[0]) >= 6:
                return parts[0][:28], parts[1][:32]

    words = clean_title.split()
    if len(words) >= 2:
        # Find split point closest to 45% of total character length
        target_len = len(clean_title) * 0.46
        best_idx = 1
        best_diff = 999.0
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            diff = abs(len(l1) - target_len)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        line1 = " ".join(words[:best_idx]).strip()
        line2 = " ".join(words[best_idx:]).strip()
        if len(line2) > 32:
            w2 = line2.split()
            out2 = ""
            for w in w2:
                if len(out2) + 1 + len(w) <= 32:
                    out2 = f"{out2} {w}".strip()
                else:
                    break
            line2 = out2 or line2[:32]
        return line1, line2

    line1 = clean_title[:26]
    line2 = subtitle.strip()[:30] if subtitle.strip() else "กระทบเงินในกระเป๋าแค่ไหน?"
    return line1, line2


def _build_cover_centerpiece_svg(theme: str) -> str:
    """Returns a rich 3D-styled isometric SVG centerpiece with candlestick backdrop & giant 3D glossy arrow."""
    # Common candlestick background + glowing grid + giant 3D red crashing arrow with impact flare
    candlesticks = """
      <!-- Glowing Candlestick Chart in Upper Background -->
      <g opacity="0.65" filter="url(#glow-soft)">
        <line x1="120" y1="80" x2="120" y2="260" stroke="#EF4444" stroke-width="4"/>
        <rect x="106" y="110" width="28" height="110" rx="4" fill="#EF4444"/>
        <line x1="180" y1="140" x2="180" y2="310" stroke="#EF4444" stroke-width="4"/>
        <rect x="166" y="170" width="28" height="105" rx="4" fill="#DC2626"/>
        <line x1="240" y1="120" x2="240" y2="270" stroke="#10B981" stroke-width="4"/>
        <rect x="226" y="150" width="28" height="80" rx="4" fill="#10B981"/>
        <line x1="300" y1="180" x2="300" y2="380" stroke="#EF4444" stroke-width="4"/>
        <rect x="286" y="210" width="28" height="130" rx="4" fill="#EF4444"/>
        <line x1="360" y1="240" x2="360" y2="430" stroke="#EF4444" stroke-width="4"/>
        <rect x="346" y="270" width="28" height="120" rx="4" fill="#B91C1C"/>
        <line x1="420" y1="210" x2="420" y2="390" stroke="#10B981" stroke-width="4"/>
        <rect x="406" y="245" width="28" height="90" rx="4" fill="#10B981"/>
        <line x1="480" y1="280" x2="480" y2="490" stroke="#EF4444" stroke-width="4"/>
        <rect x="466" y="310" width="28" height="140" rx="4" fill="#EF4444"/>
        <line x1="540" y1="340" x2="540" y2="550" stroke="#EF4444" stroke-width="4"/>
        <rect x="526" y="370" width="28" height="145" rx="4" fill="#DC2626"/>
        <line x1="600" y1="390" x2="600" y2="610" stroke="#EF4444" stroke-width="4"/>
        <rect x="586" y="425" width="28" height="140" rx="4" fill="#991B1B"/>
        <line x1="660" y1="450" x2="660" y2="670" stroke="#EF4444" stroke-width="4"/>
        <rect x="646" y="480" width="28" height="150" rx="4" fill="#EF4444"/>
      </g>
    """

    if theme == "ai_tech":
        subject_svg = """
        <!-- Server Racks Left Background -->
        <g transform="translate(40, 360)">
          <rect x="0" y="0" width="130" height="420" rx="10" fill="url(#metal-dark)" stroke="#334155" stroke-width="3"/>
          <rect x="15" y="25" width="100" height="22" rx="4" fill="#0F172A"/>
          <circle cx="30" cy="36" r="5" fill="#38BDF8"/><circle cx="50" cy="36" r="5" fill="#38BDF8"/><circle cx="95" cy="36" r="5" fill="#EF4444"/>
          <rect x="15" y="65" width="100" height="22" rx="4" fill="#0F172A"/>
          <circle cx="30" cy="76" r="5" fill="#38BDF8"/><circle cx="50" cy="76" r="5" fill="#22C55E"/><circle cx="95" cy="76" r="5" fill="#EF4444"/>
          <rect x="15" y="105" width="100" height="22" rx="4" fill="#0F172A"/>
          <circle cx="30" cy="116" r="5" fill="#38BDF8"/><circle cx="50" cy="116" r="5" fill="#38BDF8"/><circle cx="95" cy="116" r="5" fill="#F59E0B"/>
          <rect x="15" y="145" width="100" height="22" rx="4" fill="#0F172A"/>
          <circle cx="30" cy="156" r="5" fill="#EF4444"/><circle cx="50" cy="156" r="5" fill="#38BDF8"/>

          <rect x="145" y="35" width="120" height="385" rx="10" fill="url(#metal-dark)" stroke="#334155" stroke-width="3"/>
          <rect x="160" y="60" width="90" height="20" rx="4" fill="#0F172A"/>
          <circle cx="175" cy="70" r="4" fill="#38BDF8"/><circle cx="195" cy="70" r="4" fill="#EF4444"/>
          <rect x="160" y="95" width="90" height="20" rx="4" fill="#0F172A"/>
          <circle cx="175" cy="105" r="4" fill="#38BDF8"/><circle cx="195" cy="105" r="4" fill="#38BDF8"/>
          <rect x="160" y="130" width="90" height="20" rx="4" fill="#0F172A"/>
          <circle cx="175" cy="140" r="4" fill="#EF4444"/><circle cx="195" cy="140" r="4" fill="#F59E0B"/>
        </g>

        <!-- Cyber AI Humanoid Silhouette Top Right -->
        <g transform="translate(650, 40)">
          <circle cx="150" cy="120" r="105" fill="#1E293B" stroke="#38BDF8" stroke-width="3" opacity="0.7"/>
          <circle cx="115" cy="115" r="58" fill="#0F172A" stroke="#00F0FF" stroke-width="6" filter="url(#glow-cyan)"/>
          <circle cx="115" cy="115" r="32" fill="none" stroke="#38BDF8" stroke-width="4" stroke-dasharray="12 6"/>
          <circle cx="115" cy="115" r="14" fill="#00F0FF"/>
          <path d="M210,70 C245,95 255,145 235,190 C220,220 175,245 135,245" fill="none" stroke="#94A3B8" stroke-width="8"/>
        </g>

        <!-- Triple-Fan GPU Card Right -->
        <g transform="translate(500, 470) rotate(-14)">
          <rect x="0" y="0" width="490" height="210" rx="22" fill="url(#metal-silver)" stroke="#94A3B8" stroke-width="5"/>
          <rect x="18" y="18" width="454" height="174" rx="14" fill="#0F172A"/>
          <circle cx="105" cy="105" r="68" fill="#1E293B" stroke="#64748B" stroke-width="5"/>
          <circle cx="105" cy="105" r="22" fill="#475569"/>
          <circle cx="255" cy="105" r="68" fill="#1E293B" stroke="#64748B" stroke-width="5"/>
          <circle cx="255" cy="105" r="22" fill="#475569"/>
          <circle cx="400" cy="105" r="60" fill="#1E293B" stroke="#64748B" stroke-width="5"/>
          <circle cx="400" cy="105" r="20" fill="#475569"/>
        </g>

        <!-- 3D Isometric Glowing AI Processor Chip Foreground Left -->
        <g transform="translate(80, 680)">
          <!-- Gold/Silver Pins -->
          <path d="M50,210 L290,330 L520,195 L280,75 Z" fill="#F59E0B" opacity="0.85" filter="url(#glow-soft)"/>
          <!-- 3D Chip Base Extrusion -->
          <polygon points="70,195 290,310 500,185 280,70" fill="#1E293B" stroke="#38BDF8" stroke-width="5"/>
          <polygon points="70,195 70,230 290,345 290,310" fill="#0F172A" stroke="#0284C7" stroke-width="3"/>
          <polygon points="290,310 290,345 500,220 500,185" fill="#334155" stroke="#38BDF8" stroke-width="3"/>
          <!-- Glowing Inner Die -->
          <polygon points="115,188 288,278 455,178 282,88" fill="url(#chip-top)" stroke="#00F0FF" stroke-width="5" filter="url(#glow-cyan)"/>
          <!-- Isometric 'AI' Glowing Text -->
          <text x="285" y="210" text-anchor="middle" fill="#E0F2FE" font-family="Kanit, sans-serif" font-weight="900" font-size="118" transform="skewX(-24) rotate(-12 285 210)" filter="url(#glow-cyan)">AI</text>
        </g>
        """
    elif theme == "gold":
        subject_svg = """
        <!-- 3D Gleaming Gold Bullion Bars Stack & Price Ticker -->
        <g transform="translate(545, 320)">
          <rect x="0" y="0" width="475" height="195" rx="22" fill="#0F172A" stroke="#F59E0B" stroke-width="5" filter="url(#glow-soft)"/>
          <text x="237" y="72" text-anchor="middle" fill="#FBBF24" font-family="Kanit, sans-serif" font-size="36" font-weight="800">GOLD SPOT • ทองคำแท่ง 96.5%</text>
          <text x="237" y="150" text-anchor="middle" fill="#EF4444" font-family="Kanit, sans-serif" font-size="70" font-weight="900">▼ ผันผวนหนัก</text>
        </g>
        <g transform="translate(70, 650)">
          <!-- Gold Bar 1 (Bottom Left) -->
          <polygon points="40,220 260,330 470,210 250,100" fill="url(#gold-top)" stroke="#FEF08A" stroke-width="4"/>
          <polygon points="40,220 20,275 245,385 260,330" fill="url(#gold-side)" stroke="#CA8A04" stroke-width="3"/>
          <polygon points="260,330 245,385 485,260 470,210" fill="url(#gold-front)" stroke="#EAB308" stroke-width="3"/>
          <text x="255" y="235" text-anchor="middle" fill="#78350F" font-family="Kanit, sans-serif" font-weight="900" font-size="52" transform="skewX(-22) rotate(-14 255 235)">999.9 GOLD</text>

          <!-- Gold Bar 2 (Top Stacked) -->
          <g transform="translate(80, -95)">
            <polygon points="40,220 260,330 470,210 250,100" fill="url(#gold-top)" stroke="#FEF9C3" stroke-width="5" filter="url(#glow-gold)"/>
            <polygon points="40,220 20,275 245,385 260,330" fill="url(#gold-side)" stroke="#CA8A04" stroke-width="3"/>
            <polygon points="260,330 245,385 485,260 470,210" fill="url(#gold-front)" stroke="#EAB308" stroke-width="3"/>
            <text x="255" y="235" text-anchor="middle" fill="#78350F" font-family="Kanit, sans-serif" font-weight="900" font-size="54" transform="skewX(-22) rotate(-14 255 235)">GOLD 96.5%</text>
          </g>
        </g>
        """
    elif theme == "fuel":
        subject_svg = """
        <!-- 3D Fuel Price Board & Oil Barrels -->
        <g transform="translate(520, 390)">
          <rect x="0" y="0" width="460" height="240" rx="24" fill="#0F172A" stroke="#38BDF8" stroke-width="5" filter="url(#glow-cyan)"/>
          <text x="230" y="70" text-anchor="middle" fill="#38BDF8" font-family="Kanit, sans-serif" font-size="40" font-weight="800">ราคาน้ำมันขายปลีก</text>
          <text x="230" y="150" text-anchor="middle" fill="#22C55E" font-family="Kanit, sans-serif" font-size="74" font-weight="900">DIESEL -0.60</text>
          <text x="230" y="210" text-anchor="middle" fill="#F8FAFC" font-family="Kanit, sans-serif" font-size="34" font-weight="600">บาท/ลิตร • กองทุนน้ำมันฯ</text>
        </g>
        <!-- 3D Metallic Oil Drums Foreground -->
        <g transform="translate(90, 580)">
          <ellipse cx="180" cy="80" rx="135" ry="50" fill="#1E293B" stroke="#64748B" stroke-width="5"/>
          <path d="M45,80 L45,360 A135,50 0 0,0 315,360 L315,80 Z" fill="url(#metal-dark)" stroke="#475569" stroke-width="5"/>
          <ellipse cx="180" cy="80" rx="135" ry="50" fill="#334155" stroke="#94A3B8" stroke-width="4"/>
          <rect x="85" y="175" width="190" height="90" rx="14" fill="#F59E0B"/>
          <text x="180" y="238" text-anchor="middle" fill="#0F172A" font-family="Kanit, sans-serif" font-size="56" font-weight="900">OIL / ฿</text>
        </g>
        """
    else:
        subject_svg = """
        <!-- 3D Financial Smartphone, Wallet & Baht Banknotes -->
        <g transform="translate(540, 410) rotate(-8)">
          <rect x="0" y="0" width="420" height="250" rx="26" fill="#0F172A" stroke="#38BDF8" stroke-width="5" filter="url(#glow-cyan)"/>
          <rect x="24" y="24" width="372" height="70" rx="14" fill="#10B981"/>
          <text x="210" y="72" text-anchor="middle" fill="#FFFFFF" font-family="Kanit, sans-serif" font-size="38" font-weight="800">เงินในกระเป๋า / บัญชี</text>
          <text x="210" y="175" text-anchor="middle" fill="#EF4444" font-family="Kanit, sans-serif" font-size="78" font-weight="900">▼ เช็กด่วน!</text>
        </g>
        <g transform="translate(80, 650)">
          <polygon points="50,195 285,315 510,185 275,65" fill="#1E293B" stroke="#F59E0B" stroke-width="5"/>
          <polygon points="95,188 282,282 465,178 278,84" fill="url(#gold-top)" stroke="#FEF08A" stroke-width="4" filter="url(#glow-gold)"/>
          <text x="280" y="205" text-anchor="middle" fill="#78350F" font-family="Kanit, sans-serif" font-weight="900" font-size="96" transform="skewX(-22) rotate(-12 280 205)">฿ THB</text>
        </g>
        """

    return f"""
    <svg width="1080" height="1350" viewBox="0 0 1080 1350" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <filter id="glow-red" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="14" stdDeviation="22" flood-color="#FF1744" flood-opacity="0.85"/>
        </filter>
        <filter id="glow-cyan" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="0" stdDeviation="18" flood-color="#00F0FF" flood-opacity="0.75"/>
        </filter>
        <filter id="glow-gold" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="10" stdDeviation="20" flood-color="#F59E0B" flood-opacity="0.8"/>
        </filter>
        <filter id="glow-soft" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <linearGradient id="arrow-red-main" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#FF5252"/>
          <stop offset="45%" stop-color="#E50914"/>
          <stop offset="100%" stop-color="#8E0000"/>
        </linearGradient>
        <linearGradient id="arrow-red-side" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#7F0000"/>
          <stop offset="100%" stop-color="#3E0000"/>
        </linearGradient>
        <linearGradient id="metal-dark" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#334155"/>
          <stop offset="100%" stop-color="#0F172A"/>
        </linearGradient>
        <linearGradient id="metal-silver" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#E2E8F0"/>
          <stop offset="50%" stop-color="#94A3B8"/>
          <stop offset="100%" stop-color="#475569"/>
        </linearGradient>
        <linearGradient id="chip-top" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#0F172A"/>
          <stop offset="50%" stop-color="#1E3A8A"/>
          <stop offset="100%" stop-color="#090D16"/>
        </linearGradient>
        <linearGradient id="gold-top" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#FEF08A"/>
          <stop offset="45%" stop-color="#F59E0B"/>
          <stop offset="100%" stop-color="#B45309"/>
        </linearGradient>
        <linearGradient id="gold-side" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#D97706"/>
          <stop offset="100%" stop-color="#78350F"/>
        </linearGradient>
        <linearGradient id="gold-front" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#FBBF24"/>
          <stop offset="100%" stop-color="#92400E"/>
        </linearGradient>
        <radialGradient id="impact-flare" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#FFFFFF" stop-opacity="1"/>
          <stop offset="25%" stop-color="#FFAB00" stop-opacity="0.95"/>
          <stop offset="60%" stop-color="#FF1744" stop-opacity="0.6"/>
          <stop offset="100%" stop-color="#FF1744" stop-opacity="0"/>
        </radialGradient>
      </defs>

      <!-- Cyber Motherboard Circuit Traces on Floor -->
      <g opacity="0.38" stroke="#F59E0B" stroke-width="3" fill="none">
        <path d="M0,1050 L320,1050 L420,960 L1080,960"/>
        <path d="M120,1200 L480,1200 L610,1060 L1080,1060"/>
        <path d="M240,880 L550,880 L720,1150 L1080,1150" stroke="#38BDF8"/>
        <path d="M680,820 L680,1300"/>
        <path d="M400,820 L400,1300"/>
      </g>

      {candlesticks}
      {subject_svg}

      <!-- Impact Spark & Glowing Flare at Arrow Tip (x=785, y=975) -->
      <circle cx="785" cy="975" r="190" fill="url(#impact-flare)"/>
      <g stroke="#FFF8E1" stroke-width="4" opacity="0.9">
        <line x1="650" y1="975" x2="920" y2="975"/>
        <line x1="785" y1="860" x2="785" y2="1090"/>
        <line x1="695" y1="895" x2="875" y2="1055"/>
        <line x1="875" y1="895" x2="695" y2="1055"/>
      </g>

      <!-- GIANT 3D GLOSSY RED TREND ARROW (Shadow/Extrusion Layer + Main Glossy Layer) -->
      <g filter="url(#glow-red)">
        <!-- 3D Depth Extrusion -->
        <path d="M 35,95 L 225,295 L 300,205 L 445,485 L 525,380 L 725,795 L 820,735 L 795,1005 L 555,895 L 645,840 L 495,535 L 415,635 L 265,355 L 190,445 L 10,175 Z"
              fill="url(#arrow-red-side)" transform="translate(-18, 26)"/>
        <!-- Glossy Top Face -->
        <path d="M 35,95 L 225,295 L 300,205 L 445,485 L 525,380 L 725,795 L 820,735 L 795,1005 L 555,895 L 645,840 L 495,535 L 415,635 L 265,355 L 190,445 L 10,175 Z"
              fill="url(#arrow-red-main)" stroke="#FF8A80" stroke-width="5" stroke-linejoin="round"/>
      </g>
    </svg>
    """


def build_cover_html(
    title: str,
    subtitle: str = "",
    category: str = "NEWS",
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Builds the high-impact 3D-style financial news cover matching reference media_1795603906607."""
    font_bold, font_med = _font_urls()
    theme = detect_visual_theme(f"{title} {subtitle} {category}")
    line1, line2 = split_cover_headlines(title, subtitle)
    svg_art = _build_cover_centerpiece_svg(theme)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'Kanit';
    src: url('{font_bold}') format('truetype');
    font-weight: 800;
  }}
  @font-face {{
    font-family: 'Kanit';
    src: url('{font_med}') format('truetype');
    font-weight: 600;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {width}px;
    height: {height}px;
    background: radial-gradient(circle at 55% 35%, #172542 0%, #090D1A 58%, #04060C 100%);
    font-family: 'Kanit', sans-serif;
    position: relative;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }}
  .art-layer {{
    position: absolute;
    top: 0;
    left: 0;
    width: 1080px;
    height: 1400px;
    z-index: 1;
  }}
  .news-badge {{
    position: absolute;
    top: 64px;
    right: 64px;
    z-index: 10;
    text-align: right;
  }}
  .news-brand-pill {{
    display: inline-block;
    background: linear-gradient(90deg, #FF6D00, #FFAB00);
    color: #090D16;
    font-size: 26px;
    font-weight: 800;
    padding: 4px 18px;
    border-radius: 8px;
    letter-spacing: 1px;
    box-shadow: 0 6px 20px rgba(255, 109, 0, 0.5);
  }}
  .news-word {{
    font-size: 64px;
    font-weight: 900;
    color: #F8FAFC;
    letter-spacing: 3px;
    line-height: 1.05;
    text-shadow: 0 8px 28px rgba(0, 0, 0, 0.9), 0 0 18px rgba(56, 189, 248, 0.45);
  }}
  .bottom-vignette {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 820px;
    background: linear-gradient(180deg, rgba(4,6,12,0) 0%, rgba(4,6,12,0.82) 35%, rgba(4,6,12,0.97) 70%, #03050A 100%);
    z-index: 5;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    align-items: center;
    padding: 0 56px 280px 56px;
    text-align: center;
  }}
  .headline-l1 {{
    font-size: 92px;
    font-weight: 900;
    color: #FF9800;
    background: linear-gradient(180deg, #FFD54F 0%, #FF8F00 55%, #E65100 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    filter: drop-shadow(0 10px 22px rgba(0,0,0,0.95)) drop-shadow(0 0 28px rgba(255,145,0,0.35));
    line-height: 1.18;
    margin-bottom: 12px;
  }}
  .headline-l2 {{
    font-size: 76px;
    font-weight: 900;
    color: #FFFFFF;
    text-shadow: 0 10px 26px rgba(0,0,0,0.98), 0 4px 8px rgba(0,0,0,0.95);
    line-height: 1.22;
    margin-bottom: 38px;
  }}
  .accent-bar {{
    width: 920px;
    height: 12px;
    border-radius: 6px;
    background: linear-gradient(90deg, #FF6D00 0%, #FFD54F 50%, #FF6D00 100%);
    box-shadow: 0 0 26px rgba(255, 145, 0, 0.8);
  }}
</style>
</head>
<body>
  <div class="art-layer">{svg_art}</div>
  <div class="news-badge">
    <div class="news-brand-pill">คิดให้คุ้ม</div>
    <div class="news-word">NEWS</div>
  </div>
  <div class="bottom-vignette">
    <div class="headline-l1">{html.escape(line1)}</div>
    <div class="headline-l2">{html.escape(line2)}</div>
    <div class="accent-bar"></div>
  </div>
</body>
</html>"""


def _build_ton_character_svg(emotion: str = "happy", show_waves: bool = True) -> str:
    """Renders 2D Vector Character 'ต้น' (office worker with white shirt, red necktie & 5 distinct emotions)."""
    if emotion == "smug":
        eyes_mouth = """
        <!-- Smug Half-Closed Eyes & Side Smirk -->
        <path d="M175,210 Q195,202 215,210" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        <path d="M250,210 Q270,202 290,210" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        <line x1="178" y1="226" x2="212" y2="226" stroke="#1E1E1E" stroke-width="7" stroke-linecap="round"/>
        <line x1="252" y1="226" x2="288" y2="226" stroke="#1E1E1E" stroke-width="7" stroke-linecap="round"/>
        <circle cx="198" cy="230" r="6" fill="#1E1E1E"/>
        <circle cx="272" cy="230" r="6" fill="#1E1E1E"/>
        <path d="M210,275 Q245,288 272,262" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        """
    elif emotion == "tired":
        eyes_mouth = """
        <!-- Tired Eyes with Dark Eye Bags & Flat Mouth -->
        <path d="M175,205 Q195,198 215,206" stroke="#1E1E1E" stroke-width="6" fill="none" stroke-linecap="round"/>
        <path d="M250,206 Q270,198 290,205" stroke="#1E1E1E" stroke-width="6" fill="none" stroke-linecap="round"/>
        <circle cx="195" cy="226" r="10" fill="#1E1E1E"/>
        <circle cx="270" cy="226" r="10" fill="#1E1E1E"/>
        <path d="M178,244 Q195,254 212,244" stroke="#9C7A63" stroke-width="5" fill="none" stroke-linecap="round"/>
        <path d="M253,244 Q270,254 287,244" stroke="#9C7A63" stroke-width="5" fill="none" stroke-linecap="round"/>
        <path d="M208,282 Q235,270 262,282" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        """
    elif emotion == "shocked":
        eyes_mouth = """
        <!-- Wide Shocked Eyes & Open Oval Mouth -->
        <path d="M172,190 Q195,176 218,190" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        <path d="M248,190 Q270,176 292,190" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        <circle cx="195" cy="224" r="22" fill="#FFFFFF" stroke="#1E1E1E" stroke-width="6"/>
        <circle cx="195" cy="224" r="7" fill="#1E1E1E"/>
        <circle cx="270" cy="224" r="22" fill="#FFFFFF" stroke="#1E1E1E" stroke-width="6"/>
        <circle cx="270" cy="224" r="7" fill="#1E1E1E"/>
        <ellipse cx="236" cy="285" rx="22" ry="28" fill="#4A151B" stroke="#1E1E1E" stroke-width="7"/>
        """
    elif emotion == "sigh":
        eyes_mouth = """
        <!-- Closed Wavy Exhausted Eyes & Sighing Mouth -->
        <path d="M175,215 Q195,225 215,215" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        <path d="M250,215 Q270,225 290,215" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        <path d="M176,232 Q195,242 214,232" stroke="#9C7A63" stroke-width="5" fill="none" stroke-linecap="round"/>
        <path d="M251,232 Q270,242 289,232" stroke="#9C7A63" stroke-width="5" fill="none" stroke-linecap="round"/>
        <ellipse cx="235" cy="278" rx="18" ry="20" fill="#5C1D24" stroke="#1E1E1E" stroke-width="6"/>
        """
    else:
        eyes_mouth = """
        <!-- Happy Optimistic Eyes & Friendly Smile -->
        <path d="M176,200 Q195,190 214,200" stroke="#1E1E1E" stroke-width="6" fill="none" stroke-linecap="round"/>
        <path d="M252,200 Q270,190 288,200" stroke="#1E1E1E" stroke-width="6" fill="none" stroke-linecap="round"/>
        <circle cx="195" cy="224" r="10" fill="#1E1E1E"/>
        <circle cx="270" cy="224" r="10" fill="#1E1E1E"/>
        <path d="M208,268 Q235,292 264,268" stroke="#1E1E1E" stroke-width="7" fill="none" stroke-linecap="round"/>
        """

    waves_svg = ""
    if show_waves:
        waves_svg = """
        <!-- Sound Waves ))) -->
        <g stroke="#FFD54F" stroke-width="7" fill="none" stroke-linecap="round">
          <path d="M370,155 Q390,180 370,205" stroke="#1E1E1E" stroke-width="12"/>
          <path d="M370,155 Q390,180 370,205"/>
          <path d="M392,140 Q418,180 392,220" stroke="#1E1E1E" stroke-width="12"/>
          <path d="M392,140 Q418,180 392,220"/>
          <path d="M415,125 Q446,180 415,235" stroke="#1E1E1E" stroke-width="12"/>
          <path d="M415,125 Q446,180 415,235"/>
        </g>
        """

    return f"""
    <svg width="460" height="540" viewBox="0 0 460 540" xmlns="http://www.w3.org/2000/svg">
      {waves_svg}
      <!-- White Shirt & Shoulders -->
      <path d="M45,530 C52,390 115,345 215,345 C315,345 372,390 380,530 Z" fill="#E8EEF5" stroke="#18181B" stroke-width="9" stroke-linejoin="round"/>
      <!-- Red Necktie -->
      <polygon points="204,348 228,348 238,445 216,472 194,445" fill="#E53935" stroke="#18181B" stroke-width="7" stroke-linejoin="round"/>
      <!-- Left Ear -->
      <path d="M100,225 C72,225 72,282 105,282" fill="#FCE5C8" stroke="#18181B" stroke-width="8" stroke-linecap="round"/>
      <path d="M96,242 L106,242 L106,268" fill="none" stroke="#18181B" stroke-width="6" stroke-linecap="round"/>
      <!-- Head Circle -->
      <ellipse cx="222" cy="225" rx="128" ry="122" fill="#FCE5C8" stroke="#18181B" stroke-width="9"/>
      <!-- Black Hair Cap -->
      <path d="M94,220 C90,115 160,82 238,85 C318,88 358,138 348,225 C325,180 295,158 215,156 C155,155 138,162 128,195 C118,215 104,222 94,220 Z" fill="#1F242D" stroke="#18181B" stroke-width="9" stroke-linejoin="round"/>
      {eyes_mouth}
    </svg>
    """


def _extract_number_badge(text: str, fallback: str = "เช็กตัวเลข") -> str:
    """Extracts a prominent number/unit from callout or subtitle text."""
    m = re.search(r"([+-]?\d[\d,]*(?:\.\d+)?\s*(?:บาท|%|สต\.|ล้าน|พัน|ปี|เดือน|วัน)?)", text)
    if m and len(m.group(1).strip()) >= 2:
        return m.group(1).strip()
    return fallback


def build_subshot_html(
    topic_title: str,
    topic_category: str,
    beat_id: str,
    beat_title: str,
    beat_subtitle: str,
    callouts: list[str],
    doodle_name: str,
    subtitle_text: str,
    global_shot_idx: int,
    subshot_idx: int,
    total_subshots: int,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Builds a distinct, visually rich 1080x1920 frame that changes template every 3-4 seconds."""
    font_bold, font_med = _font_urls()

    # Shot 0 of the entire video is ALWAYS the high-impact 3D Cinematic News Cover!
    if global_shot_idx == 0:
        return build_cover_html(topic_title, beat_subtitle or beat_title, topic_category, width, height)

    # Select rotating visual template so every 3-4 second cut changes look & layout!
    # Beat-aware template selection:
    if beat_id == "checklist":
        template_type = "forest_checklist" if subshot_idx % 2 == 0 else "ton_prop_card"
    elif beat_id == "warning":
        template_type = ["red_warning_trap", "ton_prop_card", "dark_data_spotlight", "whiteboard_doodle"][subshot_idx % 4]
    elif beat_id == "math":
        template_type = ["proportion_bar", "ton_banking_app", "dark_data_spotlight", "whiteboard_doodle"][subshot_idx % 4]
    else:
        template_type = [
            "ton_banking_app",
            "dark_data_spotlight",
            "ton_prop_card",
            "whiteboard_doodle",
            "proportion_bar",
        ][(global_shot_idx + subshot_idx) % 5]

    emotions = ["happy", "smug", "tired", "shocked", "sigh"]
    if beat_id == "warning":
        emotion = "shocked" if subshot_idx % 2 == 0 else "tired"
    elif beat_id == "hook":
        emotion = "happy" if subshot_idx == 0 else "smug"
    elif beat_id == "checklist":
        emotion = "happy"
    else:
        emotion = emotions[(global_shot_idx + subshot_idx) % len(emotions)]

    active_callout = callouts[subshot_idx % len(callouts)] if callouts else beat_subtitle
    secondary_callout = callouts[(subshot_idx + 1) % len(callouts)] if len(callouts) > 1 else beat_title
    num_highlight = _extract_number_badge(f"{active_callout} {subtitle_text} {beat_title}", "ตัวเลขจริง")

    ton_svg = _build_ton_character_svg(emotion=emotion, show_waves=True)

    # Rotate doodle SVG so whiteboard shots never show the same doodle twice in a row
    all_doodles = ["house", "bank", "calculator", "chart", "checklist", "globe", "money_bag", "refinance", "warning"]
    chosen_doodle = doodle_name if subshot_idx == 0 else all_doodles[(global_shot_idx + subshot_idx) % len(all_doodles)]
    doodle_path = DOODLES_DIR / f"{chosen_doodle}.svg"
    if not doodle_path.is_file():
        doodle_path = DOODLES_DIR / "chart.svg"
    doodle_url = f"file://{doodle_path.resolve()}"
    marker_url = f"file://{(DOODLES_DIR / 'marker_pen.svg').resolve()}"

    speaker_label = "ต้น" if (global_shot_idx % 2 == 1) else "ผู้บรรยาย"
    speaker_bg = "#FFD54F" if speaker_label == "ต้น" else "#F1F5F9"

    # Base CSS shared across templates
    base_css = f"""
      @font-face {{
        font-family: 'Kanit';
        src: url('{font_bold}') format('truetype');
        font-weight: 800;
      }}
      @font-face {{
        font-family: 'Kanit';
        src: url('{font_med}') format('truetype');
        font-weight: 600;
      }}
      * {{ box-sizing: border-box; margin: 0; padding: 0; }}
      body {{
        width: {width}px;
        height: {height}px;
        font-family: 'Kanit', sans-serif;
        position: relative;
        overflow: hidden;
        -webkit-font-smoothing: antialiased;
      }}
      .hud-top-left {{
        position: absolute;
        top: 118px;
        left: 54px;
        background: #1E2433;
        border: 3px solid #E2E8F0;
        border-radius: 22px;
        padding: 16px 28px;
        color: #FFFFFF;
        z-index: 10;
        box-shadow: 0 12px 28px rgba(0,0,0,0.22);
      }}
      .hud-line1 {{
        font-size: 26px;
        font-weight: 700;
        color: #F8FAFC;
      }}
      .hud-line1 span {{
        color: #FFD54F;
      }}
      .hud-line2 {{
        font-size: 34px;
        font-weight: 800;
        color: #4ADE80;
        margin-top: 4px;
      }}
      .day-pill {{
        position: absolute;
        top: 122px;
        right: 54px;
        max-width: 440px;
        background: #FFD54F;
        border: 4px solid #18181B;
        border-radius: 22px;
        padding: 14px 28px;
        font-size: 32px;
        font-weight: 900;
        color: #18181B;
        transform: rotate(-2deg);
        box-shadow: 0 8px 0 #18181B;
        z-index: 10;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .dialogue-footer {{
        position: absolute;
        bottom: 290px;
        left: 54px;
        right: 54px;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        z-index: 20;
      }}
      .speaker-pill {{
        background: {speaker_bg};
        border: 3.5px solid #18181B;
        border-radius: 999px;
        padding: 6px 32px;
        font-size: 28px;
        font-weight: 800;
        color: #18181B;
        margin-bottom: 14px;
        box-shadow: 0 6px 16px rgba(0,0,0,0.2);
      }}
      .sub-box {{
        background: rgba(15, 23, 42, 0.94);
        border: 3px solid rgba(255,255,255,0.26);
        border-radius: 26px;
        padding: 22px 36px;
        font-size: 40px;
        font-weight: 800;
        color: #FFFBEB;
        line-height: 1.3;
        text-shadow: 0 4px 12px rgba(0,0,0,0.8);
        box-shadow: 0 16px 36px rgba(0,0,0,0.38);
      }}
    """

    # TEMPLATE 1: 2D Character 'ต้น' + Mobile Banking App UI (Warm Cream / IG Reel Style)
    if template_type == "ton_banking_app":
        body_html = f"""
        <div style="width:100%;height:100%;background:#F3E9D2;position:relative;">
          <!-- Brown Table Desk Floor -->
          <div style="position:absolute;bottom:0;left:0;right:0;height:360px;background:#A67B5B;border-top:7px solid #18181B;"></div>

          <div class="hud-top-left">
            <div class="hud-line1">คิดให้คุ้ม • <span>ฉากที่ {global_shot_idx}</span></div>
            <div class="hud-line2">{html.escape(num_highlight)}</div>
          </div>
          <div class="day-pill">{html.escape(topic_category[:18])}</div>

          <!-- Headline Card Center-Top -->
          <div style="position:absolute;top:240px;left:60px;right:60px;background:#18181B;color:#FFFFFF;border-radius:28px;padding:28px 38px;box-shadow:0 14px 30px rgba(0,0,0,0.18);">
            <div style="font-size:30px;color:#FFD54F;font-weight:700;">{html.escape(beat_title)}</div>
            <div style="font-size:44px;font-weight:800;margin-top:6px;line-height:1.25;">{html.escape(active_callout)}</div>
          </div>

          <!-- Calendar Card Behind Phone -->
          <div style="position:absolute;top:490px;left:335px;width:225px;height:245px;background:#FFFFFF;border:6px solid #18181B;border-radius:22px;overflow:hidden;transform:rotate(-4deg);box-shadow:0 12px 24px rgba(0,0,0,0.15);">
            <div style="height:64px;background:#E53935;border-bottom:5px solid #18181B;display:flex;align-items:center;justify-content:center;color:#FFF;font-size:26px;font-weight:800;">เช็กด่วน</div>
            <div style="display:flex;align-items:center;justify-content:center;height:175px;font-size:88px;font-weight:900;color:#18181B;">#{global_shot_idx}</div>
          </div>

          <!-- Mobile Banking App Mockup Right -->
          <div style="position:absolute;top:520px;right:55px;width:430px;height:780px;background:#FFFFFF;border:12px solid #18181B;border-radius:48px;overflow:hidden;box-shadow:0 20px 45px rgba(0,0,0,0.25);z-index:6;">
            <div style="height:175px;background:#2EBD6B;padding:34px 28px;color:#FFFFFF;">
              <div style="font-size:30px;font-weight:800;">บัญชีคิดให้คุ้ม</div>
              <div style="font-size:22px;opacity:0.9;margin-top:4px;">ตัวเลขผลกระทบจริง</div>
            </div>
            <div style="padding:42px 26px;text-align:center;">
              <div style="font-size:26px;color:#64748B;font-weight:700;">ตัวเลขสำคัญในช็อตนี้</div>
              <div style="font-size:58px;font-weight:900;color:#18181B;margin:18px 0;line-height:1.15;">{html.escape(num_highlight)}</div>
              <div style="font-size:26px;color:#E53935;font-weight:700;margin-bottom:34px;line-height:1.3;">{html.escape(beat_subtitle)}</div>
              <div style="background:#2EBD6B;color:#FFFFFF;font-size:32px;font-weight:800;padding:18px 0;border-radius:18px;">ดูตัวเลขจริง</div>
            </div>
          </div>

          <!-- Character Ton Bottom-Left -->
          <div style="position:absolute;bottom:285px;left:20px;z-index:8;">
            {ton_svg}
          </div>

          <div class="dialogue-footer">
            <div class="speaker-pill">{speaker_label}</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    # TEMPLATE 2: High-Impact Dark Navy Number & Expense Slip Card + Character 'ต้น'
    elif template_type == "dark_data_spotlight":
        body_html = f"""
        <div style="width:100%;height:100%;background:#15192B;position:relative;">
          <div class="hud-top-left" style="background:#0F1322;">
            <div class="hud-line1">เจาะตัวเลข • <span>ช็อตที่ {global_shot_idx}</span></div>
            <div class="hud-line2" style="color:#FFD54F;">{html.escape(num_highlight)}</div>
          </div>
          <div class="day-pill">{html.escape(topic_category[:18])}</div>

          <!-- White Expense/Highlight Pill Bar -->
          <div style="position:absolute;top:260px;left:60px;right:60px;background:#FFFFFF;border-radius:26px;padding:26px 34px;display:flex;align-items:center;gap:26px;box-shadow:0 16px 36px rgba(0,0,0,0.4);">
            <div style="width:82px;height:82px;border-radius:20px;background:#E53935;color:#FFF;display:flex;align-items:center;justify-content:center;font-size:56px;font-weight:900;flex-shrink:0;">!</div>
            <div style="font-size:38px;font-weight:800;color:#18181B;line-height:1.28;">{html.escape(active_callout)}</div>
          </div>

          <!-- Dark Center Data Card -->
          <div style="position:absolute;top:460px;right:60px;width:540px;background:#0D101D;border:3px solid #334155;border-radius:34px;padding:42px 36px;transform:rotate(1.5deg);box-shadow:0 22px 50px rgba(0,0,0,0.55);z-index:6;">
            <div style="font-size:32px;color:#94A3B8;font-weight:700;">ประเด็นสำคัญที่ต้องรู้</div>
            <div style="font-size:66px;color:#4ADE80;font-weight:900;margin:18px 0;line-height:1.15;">{html.escape(num_highlight)}</div>
            <div style="font-size:34px;color:#F8FAFC;font-weight:700;line-height:1.35;">{html.escape(secondary_callout)}</div>
          </div>

          <!-- Character Ton Left -->
          <div style="position:absolute;bottom:290px;left:15px;z-index:8;">
            {ton_svg}
          </div>

          <div class="dialogue-footer">
            <div class="speaker-pill">{speaker_label}</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    # TEMPLATE 3: Character 'ต้น' + Dual Expense / Factor Cards (เหมือนฉาก กาแฟ -120 / วิน -89)
    elif template_type == "ton_prop_card":
        body_html = f"""
        <div style="width:100%;height:100%;background:#F3E9D2;position:relative;">
          <div style="position:absolute;bottom:0;left:0;right:0;height:360px;background:#9A6B4C;border-top:7px solid #18181B;"></div>

          <div class="hud-top-left">
            <div class="hud-line1">เทียบชัดๆ • <span>ช็อตที่ {global_shot_idx}</span></div>
            <div class="hud-line2">{html.escape(num_highlight)}</div>
          </div>
          <div class="day-pill">จุดเปลี่ยน #{subshot_idx + 1}</div>

          <!-- Dual Dark Floating Cards -->
          <div style="position:absolute;top:255px;left:60px;right:60px;background:#161925;border-radius:32px;padding:36px 40px;color:#FFF;transform:rotate(-1deg);box-shadow:0 18px 40px rgba(0,0,0,0.25);">
            <div style="font-size:32px;color:#FFD54F;font-weight:800;">{html.escape(beat_title)}</div>
            <div style="font-size:48px;color:#FF6B6B;font-weight:900;margin-top:10px;line-height:1.25;">{html.escape(active_callout)}</div>
          </div>

          <!-- Right Visual Prop Box -->
          <div style="position:absolute;top:545px;right:65px;width:470px;background:#FFFFFF;border:7px solid #18181B;border-radius:34px;padding:34px;text-align:center;box-shadow:0 16px 0 #18181B;z-index:6;">
            <img src="{doodle_url}" style="width:240px;height:200px;object-fit:contain;margin-bottom:16px;">
            <div style="font-size:34px;font-weight:800;color:#18181B;line-height:1.3;">{html.escape(secondary_callout)}</div>
          </div>

          <div style="position:absolute;bottom:285px;left:15px;z-index:8;">
            {ton_svg}
          </div>

          <div class="dialogue-footer">
            <div class="speaker-pill">{speaker_label}</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    # TEMPLATE 4: Red Alert Trap Card + Shocked Character 'ต้น' (เหมือนฉาก วันที่ 9 ยอดเงินไม่เพียงพอ)
    elif template_type == "red_warning_trap":
        body_html = f"""
        <div style="width:100%;height:100%;background:#1A1423;position:relative;">
          <div class="hud-top-left" style="border-color:#EF4444;">
            <div class="hud-line1">จุดที่ต้องระวัง • <span>ช็อตที่ {global_shot_idx}</span></div>
            <div class="hud-line2" style="color:#EF4444;">⚠️ เช็กก่อนพลาด</div>
          </div>
          <div class="day-pill" style="background:#EF4444;color:#FFFFFF;">คำเตือนสำคัญ</div>

          <!-- Red Alert Banner -->
          <div style="position:absolute;top:250px;left:60px;right:60px;background:#DC2626;border:6px solid #18181B;border-radius:28px;padding:30px 38px;color:#FFFFFF;box-shadow:0 12px 0 #18181B;">
            <div style="font-size:30px;font-weight:700;color:#FEF08A;">⚠️ หลายคนพลาดตรงนี้!</div>
            <div style="font-size:46px;font-weight:900;margin-top:8px;line-height:1.25;">{html.escape(active_callout)}</div>
          </div>

          <!-- Secondary Warning Card Right -->
          <div style="position:absolute;top:540px;right:60px;width:490px;background:#FFFFFF;border:7px solid #18181B;border-radius:32px;padding:36px;z-index:6;box-shadow:0 16px 36px rgba(0,0,0,0.4);">
            <div style="font-size:28px;font-weight:800;color:#DC2626;">ผลกระทบโดยตรง</div>
            <div style="font-size:56px;font-weight:900;color:#18181B;margin:14px 0;">{html.escape(num_highlight)}</div>
            <div style="font-size:32px;font-weight:700;color:#334155;line-height:1.35;">{html.escape(secondary_callout)}</div>
          </div>

          <div style="position:absolute;bottom:285px;left:15px;z-index:8;">
            {_build_ton_character_svg(emotion="shocked", show_waves=True)}
          </div>

          <div class="dialogue-footer">
            <div class="speaker-pill" style="background:#FCA5A5;">แจ้งเตือน</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    # TEMPLATE 5: Horizontal Proportion Breakdown Bar Chart ('เงินหายไปไหน')
    elif template_type == "proportion_bar":
        body_html = f"""
        <div style="width:100%;height:100%;background:#16192E;position:relative;padding:70px 60px;">
          <div class="hud-top-left">
            <div class="hud-line1">ผ่าโครงสร้างตัวเลข • <span>ช็อตที่ {global_shot_idx}</span></div>
            <div class="hud-line2">{html.escape(num_highlight)}</div>
          </div>

          <div style="margin-top:185px;text-align:center;">
            <div style="font-size:58px;font-weight:900;color:#FFD54F;line-height:1.2;">{html.escape(beat_title)}</div>
            <div style="font-size:34px;font-weight:600;color:#CBD5E1;margin-top:12px;">{html.escape(beat_subtitle)}</div>
          </div>

          <!-- Horizontal Stacked Proportion Bar (like IG Reel arc_11) -->
          <div style="margin-top:55px;width:100%;height:190px;border:7px solid #090D16;border-radius:24px;overflow:hidden;display:flex;box-shadow:0 18px 42px rgba(0,0,0,0.45);">
            <div style="width:65%;background:#DC4C3E;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;border-right:6px solid #090D16;">
              <div style="font-size:32px;font-weight:800;color:#FFFFFF;text-shadow:0 3px 8px rgba(0,0,0,0.6);">ตัวเลขหลัก</div>
              <div style="font-size:44px;font-weight:900;color:#FEF08A;margin-top:4px;">{html.escape(num_highlight)}</div>
            </div>
            <div style="width:35%;background:#F59E0B;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:14px;">
              <div style="font-size:28px;font-weight:800;color:#18181B;">จุดเปรียบเทียบ</div>
              <div style="font-size:34px;font-weight:900;color:#18181B;margin-top:4px;">{html.escape(_extract_number_badge(secondary_callout, "เช็กผลกระทบ"))}</div>
            </div>
          </div>

          <!-- Bullet Breakdown Details -->
          <div style="margin-top:48px;background:rgba(255,255,255,0.07);border:2px solid rgba(255,255,255,0.16);border-radius:28px;padding:36px 42px;">
            <div style="font-size:38px;font-weight:800;color:#FFFFFF;line-height:1.4;">• {html.escape(active_callout)}</div>
            <div style="font-size:34px;font-weight:700;color:#FFD54F;line-height:1.4;margin-top:18px;">• {html.escape(secondary_callout)}</div>
          </div>

          <div style="position:absolute;bottom:280px;right:15px;transform:scale(0.72);transform-origin:bottom right;z-index:8;">
            {ton_svg}
          </div>

          <div class="dialogue-footer">
            <div class="speaker-pill">{speaker_label}</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    # TEMPLATE 6: Forest Green 1-2-3 Actionable Checklist (เหมือนฉาก end_05 ใน IG Reel)
    elif template_type == "forest_checklist":
        items = callouts if len(callouts) >= 2 else [active_callout, beat_subtitle, "เปรียบเทียบตัวเลขจริงก่อนตัดสินใจ"]
        rows_html = ""
        for i, item_txt in enumerate(items[:3]):
            active_border = "border: 4px solid #FFD54F; background: rgba(255,255,255,0.13);" if (i == subshot_idx % len(items[:3])) else "background: rgba(255,255,255,0.05);"
            rows_html += f"""
            <div style="display:flex;align-items:center;gap:28px;padding:28px 32px;border-radius:26px;margin-bottom:26px;{active_border}">
              <div style="width:82px;height:82px;border-radius:999px;background:#34D399;border:5px solid #064E3B;display:flex;align-items:center;justify-content:center;font-size:44px;font-weight:900;color:#064E3B;flex-shrink:0;">{i+1}</div>
              <div style="font-size:38px;font-weight:800;color:#FFFFFF;line-height:1.32;">{html.escape(item_txt)}</div>
            </div>
            """
        body_html = f"""
        <div style="width:100%;height:100%;background:#143825;position:relative;padding:75px 60px;">
          <div style="font-size:32px;font-weight:800;color:#6EE7B7;letter-spacing:1px;">คิดให้คุ้ม • แนวทางรับมือ</div>
          <div style="font-size:58px;font-weight:900;color:#FFFFFF;margin-top:10px;margin-bottom:48px;line-height:1.2;">{html.escape(beat_title)}</div>
          {rows_html}
          <div style="position:absolute;bottom:285px;left:35px;transform:scale(0.82);transform-origin:bottom left;z-index:8;">
            {_build_ton_character_svg(emotion="happy", show_waves=True)}
          </div>
          <div class="dialogue-footer">
            <div class="speaker-pill">ผู้บรรยาย</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    # TEMPLATE 7: Interactive Whiteboard Doodly + 3D Marker Pen Highlight
    else:
        body_html = f"""
        <div style="width:100%;height:100%;background:#FAF9F6;padding:65px 75px;position:relative;">
          <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #E2E8F0;padding-bottom:22px;">
            <div>
              <div style="font-size:38px;font-weight:800;color:#2B3A42;">คิดให้คุ้ม 💡</div>
              <div style="font-size:24px;font-weight:600;color:#64748B;">เห็นตัวเลขจริงก่อนตัดสินใจ • ช็อต #{global_shot_idx}</div>
            </div>
            <div style="background:#E06D53;color:#FFF;padding:12px 28px;border-radius:999px;font-size:28px;font-weight:800;">{html.escape(num_highlight)}</div>
          </div>

          <div style="margin-top:38px;">
            <div style="font-size:60px;font-weight:900;color:#E06D53;line-height:1.22;">{html.escape(beat_title)}</div>
            <div style="font-size:36px;font-weight:700;color:#2B3A42;margin-top:12px;line-height:1.3;">{html.escape(beat_subtitle)}</div>
          </div>

          <div style="width:100%;height:440px;display:flex;align-items:center;justify-content:center;margin-top:30px;background:#FFFFFF;border:3px dashed #CBD5E1;border-radius:32px;padding:24px;">
            <img src="{doodle_url}" style="max-width:740px;max-height:390px;object-fit:contain;">
          </div>

          <div style="margin-top:34px;position:relative;">
            <div style="background:#FFFFFF;border:4px solid #3F8A8C;border-radius:24px;padding:26px 36px;font-size:36px;font-weight:800;color:#1E293B;box-shadow:0 10px 26px rgba(0,0,0,0.07);margin-bottom:20px;">
              {html.escape(active_callout)}
            </div>
            <div style="background:#FDF2EE;border:4px solid #E06D53;border-radius:24px;padding:24px 36px;font-size:34px;font-weight:800;color:#E06D53;">
              {html.escape(secondary_callout)}
            </div>
            <img src="{marker_url}" style="position:absolute;right:-20px;top:35px;width:165px;height:165px;transform:rotate(14deg);filter:drop-shadow(0 12px 20px rgba(0,0,0,0.18));">
          </div>

          <div class="dialogue-footer">
            <div class="speaker-pill">{speaker_label}</div>
            <div class="sub-box">{html.escape(subtitle_text)}</div>
          </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{base_css}</style>
</head>
<body>
{body_html}
</body>
</html>"""
