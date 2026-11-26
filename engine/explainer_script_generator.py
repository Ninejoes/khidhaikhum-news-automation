"""Explainer Script Generator module.

Generates 5-beat educational financial and news explainer scripts matching the
"คิดให้คุ้ม - เห็นตัวเลขจริงก่อนตัดสินใจ" brand identity:
1. The Hook (Pain Point / Breaking Impact)
2. The Mechanism (Root Cause / Underlying Concept)
3. Hidden Costs & Caveats (Warning / Risks)
4. Real Math & Calculation (Seeing the actual numbers)
5. Actionable Checklist & Call to Action (How to prepare + Comment invite)
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import requests

from engine.whiteboard_renderer import ExplainerBeat, ExplainerTopic

logger = logging.getLogger(__name__)

GEMINI_PRIMARY_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_FALLBACK_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"

NEWS_EXPLAINER_SYSTEM_PROMPT = """คุณคือบรรณาธิการและผู้เชี่ยวชาญด้านการเงินของเพจ "คิดให้คุ้ม - เห็นตัวเลขจริงก่อนตัดสินใจ"
หน้าที่ของคุณคือนำ "ข่าวเศรษฐกิจ/การเงิน/กระแสสังคม/นโยบาย" มาแปลงเป็นบทวิดีโอสั้น Whiteboard Explainer 5 Beats
ความยาวประมาณ 1.5 - 2 นาที (180-250 คำ) ในสไตล์คุยง่าย สบายๆ เหมือนเพื่อนเล่าให้ฟัง เห็นตัวเลขชัดเจน

กฎสำคัญในการเล่าเรื่อง:
1. หากเป็นข่าวทั่วไป ข่าวกระแสสังคม หรือนโยบายรัฐ ให้เชื่อมโยงเข้าสู่มุมมอง "กระทบเงินในกระเป๋าเรากี่บาท" หรือ "เห็นตัวเลขจริงก่อนตัดสินใจ" เสมอ
2. ตัวเลขและสถิติต้องแม่นยำ อิงตามเนื้อหาข่าวจริง
3. แฮชแท็กและแคปชั่นต้องทำ Facebook SEO เพื่อการเข้าถึงสูงสุด

โครงสร้างต้องแบ่งออกเป็น 5 Beats เสมอ:
1. beat_id: "hook" -> เปิดด้วยประเด็นข่าวร้อน/ข้อเท็จจริงชวนคิด ทำไมคนดูต้องแคร์ (doodle_name: "money_bag", "chart", "globe", "bank", "house", หรือ "warning")
2. beat_id: "mechanism" -> อธิบายสาเหตุ ที่มาที่ไป ทำไมถึงเกิดเหตุการณ์นี้ขึ้น (doodle_name: "chart", "bank", "globe", "refinance")
3. beat_id: "warning" -> ข้อควรระวัง ความเสี่ยง ผลกระทบ หรือสิ่งที่ต้องจับตา (doodle_name: "warning")
4. beat_id: "math" -> ตัวเลขจริง คำนวณให้ดูจะๆ: ราคากระทบกี่บาท, ขาดทุน/กำไรเท่าไหร่, กระทบค่าครองชีพยังไง (doodle_name: "calculator", "money_bag", หรือ "chart")
5. beat_id: "checklist" -> 3-4 ข้อต้องรู้เพื่อรับมือ/วางแผน พร้อมคำถามชวนคอมเมนต์ (doodle_name: "checklist")

doodle_name ที่ระบบรองรับ: "bank", "calculator", "checklist", "house", "money_bag", "refinance", "warning", "chart", "globe"

ตอบกลับเป็น JSON เท่านั้นตามโครงสร้างนี้:
{
  "title": "หัวข้อคลิปที่น่าสนใจ ชัดเจน ตรงประเด็น",
  "category": "หมวดหมู่ เช่น ราคาทองคำ, ตลาดหุ้น, ดอกเบี้ย, การบริหารเงิน",
  "summary": "สรุปเนื้อหาข่าวแบบกระชับ 2-3 ประโยค",
  "caption": "แคปชั่น Facebook Reels แบบเต็ม พร้อม Hook, ตัวเลขสำคัญ, และแฮชแท็ก SEO 4-5 อัน",
  "beats": [
    {
      "beat_id": "hook",
      "doodle_name": "money_bag",
      "title": "หัวข้อสั้นบนกระดาน (ไม่เกิน 30 ตัวอักษร)",
      "subtitle": "คำอธิบายกระชับ (ไม่เกิน 40 ตัวอักษร)",
      "callouts": [
        "ข้อความไฮไลต์ที่ 1",
        "ข้อความไฮไลต์ที่ 2"
      ],
      "spoken_script": "บทพูดภาษาไทยสำหรับเสียงบรรยาย ชัดเจน ลื่นไหล เป็นธรรมชาติ",
      "marker_coords": [820, 1150]
    }
  ]
}"""

TOPIC_EXPLAINER_SYSTEM_PROMPT = """คุณคือบรรณาธิการและผู้เชี่ยวชาญด้านการเงินส่วนบุคคลของเพจ "คิดให้คุ้ม - เห็นตัวเลขจริงก่อนตัดสินใจ"
หน้าที่ของคุณคือสร้างบทวิดีโอสั้น Whiteboard Explainer ความยาว 1.5 - 2 นาที (ประมาณ 180-250 คำ) ในสไตล์คุยง่าย เข้าใจทันที มีตัวเลขชัดเจน
ห้ามใช้คำศัพท์วิชาการยากๆ ให้เล่าเหมือนเพื่อนที่มีความรู้การเงินอธิบายให้ฟัง

โครงสร้างต้องแบ่งออกเป็น 5 Beats เสมอ:
1. beat_id: "hook" -> เปิดด้วยปัญหาคาใจ (doodle_name: "house", "bank", "money_bag")
2. beat_id: "mechanism" -> อธิบายหลักการทำงาน (doodle_name: "refinance", "bank", "chart")
3. beat_id: "warning" -> ข้อควรระวังและค่าใช้จ่ายแฝง (doodle_name: "warning")
4. beat_id: "math" -> ตัวเลขจริง คำนวณให้ดูจะๆ ว่าประหยัดหรือได้ผลตอบแทนเท่าไหร่ (doodle_name: "calculator", "money_bag")
5. beat_id: "checklist" -> เช็กลิสต์ก่อนตัดสินใจ 3-5 ข้อ พร้อมชวนคอมเมนต์ (doodle_name: "checklist")

ตอบกลับเป็น JSON เท่านั้นตามโครงสร้างมาตรฐาน"""


def get_curated_refinance_topic() -> ExplainerTopic:
    """Returns the flagship Refinance Explainer matching reference reel #4742958775935653."""
    beats = [
        ExplainerBeat(
            beat_id="hook",
            doodle_name="house",
            title="รีไฟแนนซ์บ้าน คืออะไร?",
            subtitle="ครบ 3 ปี ดอกเบี้ยพุ่งขึ้นเท่าตัว!",
            callouts=[
                "🏠 3 ปีแรก ดอกเบี้ยโปรโมชันเฉลี่ย 2.8 - 3.5%",
                "📈 ปีที่ 4 เป็นต้นไป ลอยตัวพุ่งสูงถึง 5.5 - 6.5%!",
            ],
            spoken_script="ผ่อนบ้านมาครบ 3 ปี สังเกตไหมครับว่าดอกเบี้ยปรับพุ่งสูงขึ้นเกือบเท่าตัว จากที่เคยจ่ายดอกเบี้ยต่ำๆ เงินต้นแทบไม่ลดเลย วันนี้ คิดให้คุ้ม พามาดูวิธีลดดอกเบี้ยกันครับ",
            marker_coords=(840, 1200),
        ),
        ExplainerBeat(
            beat_id="mechanism",
            doodle_name="refinance",
            title="ย้ายหนี้ไป แบงก์ใหม่",
            subtitle="กู้ที่ใหม่ ดอกเบี้ยถูกกว่าเดิม มาปิดที่เก่า",
            callouts=[
                "🏦 แบงก์เดิม: ดอกเบี้ยลอยตัว 6.0% ต่อปี",
                "✨ แบงก์ใหม่: โปรโมชันลดเหลือเพียง 3.2% ต่อปี",
            ],
            spoken_script="รีไฟแนนซ์ ก็คือการขอกู้เงินจากธนาคารใหม่ ที่ให้ดอกเบี้ยโปรโมชันถูกกว่าเดิม มาปิดยอดหนี้คงเหลือกับธนาคารเดิม เพื่อให้เราจ่ายค่างวดลดลง หรือตัดเงินต้นได้มากขึ้นครับ",
            marker_coords=(820, 1220),
        ),
        ExplainerBeat(
            beat_id="warning",
            doodle_name="warning",
            title="ระวัง 3 ค่าใช้จ่ายแฝง!",
            subtitle="คิดให้คุ้ม ก่อนตัดสินใจย้ายแบงก์",
            callouts=[
                "⚠️ ค่าปรับไถ่ถอนก่อน 3 ปี (1-3% ของยอดหนี้)",
                "📑 ค่าจดจำนอง 1% + ค่าประเมินหลักทรัพย์",
            ],
            spoken_script="แต่ช้าก่อนครับ ก่อนจะย้ายแบงก์ ต้องระวังค่าใช้จ่ายแฝง เช่น ค่าจดจำนอง 1 เปอร์เซ็นต์ และค่าประเมินราคาหลักทรัพย์ ถ้าประหยัดดอกเบี้ยได้น้อยกว่าค่าธรรมเนียมพวกนี้ ก็อาจจะไม่คุ้มครับ",
            marker_coords=(840, 1210),
        ),
        ExplainerBeat(
            beat_id="math",
            doodle_name="calculator",
            title="ตัวเลขจริง: หนี้ 2 ล้านบาท",
            subtitle="ผ่อนต่อ 20 ปี ประหยัดได้ขนาดไหน?",
            callouts=[
                "💰 แบบเดิม: จ่ายดอกเบี้ย 3 ปี รวม 360,000 บาท",
                "🎉 รีไฟแนนซ์: ดอกเบี้ยเหลือ 192,000 บาท (ประหยัด 1.6 แสน!)",
            ],
            spoken_script="มาดูตัวเลขจริงกันครับ สมมติยอดหนี้คงเหลือ 2 ล้านบาท ถ้าปล่อยดอกเบี้ย 6 เปอร์เซ็นต์ 3 ปีจะเสียดอก 3.6 แสน แต่ถ้ารีไฟแนนซ์เหลือ 3.2 เปอร์เซ็นต์ 3 ปีจ่ายดอกแค่ 1.9 แสน ประหยัดเงินในกระเป๋าไปได้ถึง 1.6 แสนบาทเลยครับ",
            marker_coords=(820, 1220),
        ),
        ExplainerBeat(
            beat_id="checklist",
            doodle_name="checklist",
            title="เช็กลิสต์ 4 ข้อก่อนเริ่ม",
            subtitle="ทำตามนี้ คุ้มชัวร์ ไม่เสียเที่ยว",
            callouts=[
                "1. ผ่อนครบ 3 ปีหรือยังเพื่อเลี่ยงค่าปรับ",
                "2. ลองขอ Retention ขอลดดอกกับแบงก์เดิมก่อน",
            ],
            spoken_script="สรุป 4 ข้อต้องเช็ก 1. ผ่อนครบ 3 ปีแล้ว 2. ลองขอลดดอกเบี้ยกับแบงก์เดิมก่อน ถ้าไม่ได้ค่อยย้าย 3. เปรียบเทียบโปรโมชันอย่างน้อย 3 แบงก์ ใครกำลังผ่อนบ้านอยู่ คอมเมนต์ปรึกษาได้เลยครับ",
            marker_coords=(840, 1200),
        ),
    ]

    return ExplainerTopic(
        title="รีไฟแนนซ์บ้าน คืออะไร? ดูจบรู้เลยว่าควรทำไหม 🏠",
        category="กู้บ้าน & ดอกเบี้ย",
        summary="เจาะลึกการรีไฟแนนซ์บ้าน ผ่อนครบ 3 ปี ย้ายหนี้ไปแบงก์ใหม่คุ้มจริงไหม พร้อมสูตรคำนวณเงินหนี้ 2 ล้าน ประหยัดดอกเบี้ยได้เป็นแสน",
        caption=(
            "ผ่อนบ้านครบ 3 ปี ดอกเบี้ยพุ่งขึ้นเท่าตัว! 🏠💸\n\n"
            "รีไฟแนนซ์บ้านคุ้มจริงไหม หรือแค่ย้ายหนี้ไปมา? วันนี้ 'คิดให้คุ้ม' พามาดูตัวเลขจริง หนี้ 2 ล้านบาท ช่วยประหยัดเงินในกระเป๋าได้ถึง 1.6 แสนบาท พร้อมเช็กลิสต์ 4 ข้อที่ต้องรู้ก่อนตัดสินใจ!\n\n"
            "💡 ตัวเลขจริงที่ต้องรู้:\n"
            "• ดอกเบี้ยเดิม 6.0% = 3 ปี เสียดอกเบี้ย 360,000 บาท\n"
            "• ดอกเบี้ยใหม่ 3.2% = 3 ปี เสียดอกเบี้ย 192,000 บาท\n"
            "• ประหยัดเงินต้น-ดอกเบี้ยทันที 168,000 บาท!\n\n"
            "คิดให้คุ้ม อยากชวนทุกคนมาแชร์กันครับว่า ดอกเบี้ยบ้านตอนนี้ผ่อนอยู่กี่เปอร์เซ็นต์? คอมเมนต์แลกเปลี่ยนกันได้เลย!\n\n"
            "#คิดให้คุ้ม #รีไฟแนนซ์บ้าน #ผ่อนบ้าน #ดอกเบี้ยบ้าน #วางแผนการเงิน"
        ),
        beats=beats,
    )


def select_doodle_for_text(text: str) -> str:
    """Intelligently picks a suitable doodle icon matching the topic keywords."""
    lower = text.lower()
    if any(k in lower for k in ["ทอง", "gold", "เหรียญ", "เงิน", "บาท", "ดอลลาร์", "currency", "crypto"]):
        return "money_bag"
    if any(k in lower for k in ["หุ้น", "set", "ตลาด", "เศรษฐกิจ", "gdp", "ดัชนี", "trade", "ชิป", "ai"]):
        return "chart"
    if any(k in lower for k in ["โลก", "ต่างประเทศ", "fed", "สงคราม", "สหรัฐ", "จีน", "ยุโรป", "global"]):
        return "globe"
    if any(k in lower for k in ["บ้าน", "คอนโด", "ที่ดิน", "อสังหา", "เช่า"]):
        return "house"
    if any(k in lower for k in ["หนี้", "ดอกเบี้ย", "รีไฟแนนซ์", "บัตร", "กู้", "เงินกู้"]):
        return "refinance"
    if any(k in lower for k in ["ธนาคาร", "แบงก์", "bot", "แบงก์ชาติ", "ฝากเงิน"]):
        return "bank"
    if any(k in lower for k in ["ระวัง", "ร่วง", "เตือน", "หลุมพราง", "วิกฤต", "ระเบิด"]):
        return "warning"
    if any(k in lower for k in ["คำนวณ", "ตัวเลข", "ภาษี", "สูตร"]):
        return "calculator"
    return "money_bag"


def build_seo_caption(title: str, summary: str, math_points: list[str], hashtags: list[str] | None = None) -> str:
    """Builds a high-converting Facebook Reels SEO caption."""
    tags = hashtags or ["#คิดให้คุ้ม", "#สรุปข่าวเศรษฐกิจ", "#ข่าวการเงิน", "#การเงินส่วนบุคคล", "#เห็นตัวเลขจริงก่อนตัดสินใจ"]
    tag_str = " ".join(tags[:5])

    points_str = "\n".join(f"• {p}" for p in math_points if p)
    if not points_str:
        points_str = "• ติดตามตัวเลขและความคุ้มค่าแบบเจาะลึกได้ในคลิปนี้"

    return (
        f"{title.strip()} 📊💡\n\n"
        f"{summary.strip()}\n\n"
        f"🔍 ตัวเลขจริงที่ต้องรู้:\n"
        f"{points_str}\n\n"
        f"คิดให้คุ้ม อยากชวนทุกคนมาแลกเปลี่ยนความคิดเห็นกันครับ คุณมองเรื่องนี้ยังไง คอมเมนต์บอกเราได้เลย!\n\n"
        f"{tag_str}"
    )


def _clean_headline_prefix(raw_title: str) -> str:
    """Removes leading timestamps like 'ด่วน 22:00 — ' or '14:00 — ' without cutting actual content."""
    t = raw_title.strip()
    t = re.sub(
        r"^(?:ข่าวด่วน|ด่วนพิเศษ|ด่วน)\s*(?:\d{1,2}[:.]\d{2}(?:\s*น\.?)?)?\s*(?:[—–\-:|•]\s*)?",
        "",
        t,
    ).strip()
    t = re.sub(r"^\d{1,2}[:.]\d{2}(?:\s*น\.?)?\s*(?:[—–\-:|•]\s*)+", "", t).strip()
    return t or raw_title.strip()


def _split_clean_clauses(text: str, max_chars: int = 66) -> list[str]:
    """Splits Thai text at natural clause/space boundaries without ever cutting a word in half."""
    raw_parts = re.split(r"[;\n•]+|\s+(?=ขณะที่|ส่วน|โดย|หลัง|แต่|รวมถึง|ส่งผลให้|ทำให้)", text)
    clauses: list[str] = []
    for part in raw_parts:
        p = part.strip(" \t\r\n•-—–")
        if not p:
            continue
        if len(p) <= max_chars:
            clauses.append(p)
        else:
            words = p.split()
            buf = ""
            for w in words:
                if not buf:
                    buf = w
                elif len(buf) + 1 + len(w) <= max_chars:
                    buf = f"{buf} {w}"
                else:
                    clauses.append(buf)
                    buf = w
            if buf:
                clauses.append(buf)
    return [c for c in clauses if len(c) >= 6]


def deterministic_news_to_explainer(news_item: dict[str, Any]) -> ExplainerTopic:
    """Transforms a verified D1/RSS news item into 5 rich, non-truncated beats using its real script & bullets."""
    raw_title = news_item.get("title", "").strip() or "สรุปข่าวเศรษฐกิจล่าสุด"
    clean_title = _clean_headline_prefix(raw_title)
    summary = news_item.get("summary", "").strip() or clean_title
    impact = news_item.get("impact", "").strip() or "ส่งผลต่อทิศทางดอกเบี้ย ต้นทุน และเงินในกระเป๋าที่ต้องวางแผนล่วงหน้า"
    raw_script = news_item.get("script", "").strip()
    raw_caption = news_item.get("caption", "").strip()
    category = news_item.get("category", "ข่าวเศรษฐกิจและการเงิน").strip()

    # Extract bullet points from caption if present
    caption_bullets = [
        line.strip(" •-\t")
        for line in raw_caption.splitlines()
        if line.strip().startswith("•") and len(line.strip(" •-\t")) >= 10
    ]

    summary_clauses = _split_clean_clauses(summary, max_chars=64)
    impact_clauses = _split_clean_clauses(impact, max_chars=64)
    all_fact_clauses = caption_bullets + summary_clauses

    # Extract all numbers/metrics with their units
    found_numbers = re.findall(
        r"([+-]?\d+(?:[.,–-]\d+)?\s*(?:%|เปอร์เซ็นต์|ดอลลาร์|บาท|สตางค์|สต\.|ล้านล้าน|แสนล้าน|หมื่นล้าน|พันล้าน|ล้าน|แสน|จุด|เท่า|ปี|เดือน))",
        f"{clean_title} {summary} {impact}",
    )
    # Deduplicate while preserving order
    unique_nums: list[str] = []
    for n in found_numbers:
        n_clean = n.strip()
        if n_clean and n_clean not in unique_nums:
            unique_nums.append(n_clean)

    num_highlight1 = unique_nums[0] if len(unique_nums) > 0 else "ตัวเลขเศรษฐกิจล่าสุด"
    num_highlight2 = unique_nums[1] if len(unique_nums) > 1 else (unique_nums[0] if unique_nums else "ผลกระทบต่อค่าครองชีพ")

    hook_doodle = select_doodle_for_text(clean_title)
    math_doodle = "calculator" if hook_doodle != "calculator" else "money_bag"

    # Build word-safe short title (never cut mid-word)
    title_clauses = _split_clean_clauses(clean_title, max_chars=38)
    short_title = title_clauses[0] if title_clauses else clean_title[:38]
    sub_hook = title_clauses[1] if len(title_clauses) > 1 else (summary_clauses[0] if summary_clauses else "สรุปตัวเลขจริงและผลกระทบ")

    # Build 5-beat spoken scripts from the real verified news script + summary + impact
    script_clauses = _split_clean_clauses(raw_script or f"{summary} {impact}", max_chars=95)
    if len(script_clauses) >= 4:
        n_sc = len(script_clauses)
        hook_spoken = f"{clean_title} {script_clauses[0]}"
        mech_spoken = " ".join(script_clauses[1 : max(2, n_sc // 2)])
        warn_spoken = f"{impact}"
        math_spoken = " ".join(script_clauses[max(2, n_sc // 2) :])
    else:
        hook_spoken = f"ประเด็นสำคัญที่ต้องจับตาครับ {clean_title}"
        mech_spoken = summary
        warn_spoken = impact
        math_spoken = raw_script if raw_script else f"ตัวเลขสำคัญในข่าวนี้คือ {num_highlight1} และ {num_highlight2}"

    c_hook_1 = all_fact_clauses[0] if len(all_fact_clauses) > 0 else clean_title
    c_hook_2 = all_fact_clauses[1] if len(all_fact_clauses) > 1 else sub_hook
    c_mech_1 = summary_clauses[0] if len(summary_clauses) > 0 else c_hook_1
    c_mech_2 = summary_clauses[1] if len(summary_clauses) > 1 else (all_fact_clauses[2] if len(all_fact_clauses) > 2 else c_hook_2)
    c_warn_1 = impact_clauses[0] if len(impact_clauses) > 0 else impact
    c_warn_2 = impact_clauses[1] if len(impact_clauses) > 1 else (summary_clauses[-1] if summary_clauses else clean_title)
    c_math_1 = caption_bullets[0] if len(caption_bullets) > 0 else f"ตัวเลขหลัก: {num_highlight1} ({c_hook_1})"
    c_math_2 = caption_bullets[1] if len(caption_bullets) > 1 else f"เทียบเกณฑ์สำคัญ: {num_highlight2}"

    checklist_items = [
        c_warn_1,
        c_math_1,
        "เช็กต้นทุน สภาพคล่อง และเปรียบเทียบตัวเลขจริงก่อนตัดสินใจ",
    ]
    check_spoken = (
        f"สรุปมุมคิดให้คุ้ม 1. {c_warn_1} "
        f"2. จับตากรอบตัวเลข {num_highlight1} ก่อนตัดสินใจทางการเงิน "
        f"คุณมองประเด็นนี้ยังไง คอมเมนต์แลกเปลี่ยนกันได้เลยครับ"
    )

    beats = [
        ExplainerBeat(
            beat_id="hook",
            doodle_name=hook_doodle,
            title=short_title,
            subtitle=sub_hook,
            callouts=[c_hook_1, c_hook_2],
            spoken_script=hook_spoken,
            marker_coords=(840, 1200),
        ),
        ExplainerBeat(
            beat_id="mechanism",
            doodle_name="chart" if hook_doodle != "chart" else "globe",
            title="เจาะลึกตัวเลขและสาเหตุหลัก",
            subtitle=f"ตัวเลขสำคัญ: {num_highlight1}",
            callouts=[c_mech_1, c_mech_2],
            spoken_script=mech_spoken,
            marker_coords=(820, 1220),
        ),
        ExplainerBeat(
            beat_id="warning",
            doodle_name="warning",
            title="ผลกระทบและจุดที่ต้องระวัง",
            subtitle=f"มุมมองต่อไทยและเงินในกระเป๋า",
            callouts=[c_warn_1, c_warn_2],
            spoken_script=warn_spoken,
            marker_coords=(840, 1210),
        ),
        ExplainerBeat(
            beat_id="math",
            doodle_name=math_doodle,
            title=f"เทียบตัวเลขชัดๆ: {num_highlight1}",
            subtitle=f"เปรียบเทียบกับ {num_highlight2}",
            callouts=[c_math_1, c_math_2],
            spoken_script=math_spoken,
            marker_coords=(820, 1220),
        ),
        ExplainerBeat(
            beat_id="checklist",
            doodle_name="checklist",
            title="3 ข้อสรุปคิดให้คุ้มก่อนตัดสินใจ",
            subtitle="เช็กตัวเลขจริงให้ครบทุกมิติ",
            callouts=checklist_items,
            spoken_script=check_spoken,
            marker_coords=(840, 1200),
        ),
    ]

    if raw_caption and len(raw_caption) >= 60:
        caption = raw_caption
    else:
        math_points = [c_hook_1, c_mech_1, c_warn_1]
        caption = build_seo_caption(clean_title, summary, math_points)

    return ExplainerTopic(
        title=clean_title,
        category=category,
        summary=summary,
        caption=caption,
        beats=beats,
    )


def call_gemini_json(system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any] | None:
    """Calls Gemini API with fallbacks across model versions."""
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt},
                    {"text": user_prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.25,
            "responseMimeType": "application/json",
        },
    }

    headers = {"Content-Type": "application/json"}
    for url in [GEMINI_PRIMARY_URL, GEMINI_FALLBACK_URL]:
        try:
            logger.info("Calling Gemini API: %s", url.split("/models/")[1].split(":")[0])
            resp = requests.post(f"{url}?key={api_key}", headers=headers, json=payload, timeout=35)
            if resp.ok:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
                return json.loads(clean_json)
            else:
                logger.warning("Gemini model %s returned HTTP %s: %s", url, resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("Gemini call error (%s): %s", url, exc)

    return None


def convert_news_to_explainer_topic(
    news_item: dict[str, Any],
    api_key: str | None = None,
) -> ExplainerTopic:
    """Converts a live news item into a 5-beat Whiteboard Explainer storyboard."""
    key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    title = news_item.get("title", "").strip()
    summary = news_item.get("summary", "").strip()
    impact = news_item.get("impact", "").strip()
    category = news_item.get("category", "ข่าวเศรษฐกิจ")

    if key:
        user_msg = (
            f"แปลงข่าวนี้เป็นบทวิดีโอ Whiteboard Explainer 5 Beats:\n"
            f"หัวข้อข่าว: {title}\n"
            f"หมวดหมู่: {category}\n"
            f"สรุปเนื้อหา: {summary}\n"
            f"ผลกระทบ: {impact}\n"
        )
        obj = call_gemini_json(NEWS_EXPLAINER_SYSTEM_PROMPT, user_msg, key)
        if obj and obj.get("beats") and len(obj["beats"]) >= 5:
            beats = []
            for b in obj.get("beats", [])[:5]:
                doodle = b.get("doodle_name", "money_bag")
                if doodle not in ["bank", "calculator", "checklist", "house", "money_bag", "refinance", "warning", "chart", "globe"]:
                    doodle = select_doodle_for_text(b.get("title", ""))

                beats.append(
                    ExplainerBeat(
                        beat_id=b.get("beat_id", "beat"),
                        doodle_name=doodle,
                        title=b.get("title", "")[:32],
                        subtitle=b.get("subtitle", "")[:42],
                        callouts=b.get("callouts", [])[:2],
                        spoken_script=b.get("spoken_script", ""),
                        marker_coords=tuple(b.get("marker_coords", [820, 1150])),
                    )
                )

            return ExplainerTopic(
                title=obj.get("title", title),
                category=obj.get("category", category),
                summary=obj.get("summary", summary),
                caption=obj.get("caption", ""),
                beats=beats,
            )

    logger.info("Using deterministic news converter for: %s", title[:40])
    return deterministic_news_to_explainer(news_item)


def get_scheduled_slot_topic() -> str:
    """Returns scheduled topic prompt aligned with Bangkok editorial calendar."""
    hour = datetime.now(ZoneInfo("Asia/Bangkok")).hour
    if 6 <= hour < 11:
        # 08:25 Morning Personal Finance & Morning Market
        return "สรุปข่าวเศรษฐกิจเช้า & การบริหารจัดการเงิน ดอกเบี้ย และเงินออม"
    elif 11 <= hour < 15:
        # 12:25 Midday Trending Newsjacking
        return "เกาะติดข่าวร้อนกระแสสังคมเที่ยงวัน ผลกระทบต่อค่าครองชีพและราคาสินค้า"
    elif 15 <= hour < 19:
        # 17:25 Evening Big Assets & Debt
        return "นโยบายการเงิน ภาษี อสังหาริมทรัพย์ และการบริหารหนี้สินอย่างคุ้มค่า"
    else:
        # 20:25 Night Global Markets & Commodities
        return "สรุปตลาดโลก ทองคำ ค่าเงิน ดัชนีหุ้น และแนวโน้มเศรษฐกิจวันพรุ่งนี้"


def generate_explainer_topic(
    topic_prompt: str | None = None,
    api_key: str | None = None,
) -> ExplainerTopic:
    """Generates an explainer topic via Gemini 2.0 Flash or returns curated topics."""
    key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    if not topic_prompt:
        topic_prompt = get_scheduled_slot_topic()
        logger.info("Auto-selected slot topic: %s", topic_prompt)

    if not key:
        logger.info("No Gemini key provided; using flagship Refinance Explainer")
        return get_curated_refinance_topic()

    user_msg = f"สร้างบทความรู้การเงิน Whiteboard Explainer 5 Beats ในหัวข้อ: {topic_prompt}"
    obj = call_gemini_json(TOPIC_EXPLAINER_SYSTEM_PROMPT, user_msg, key)
    if obj and obj.get("beats") and len(obj["beats"]) >= 5:
        beats = []
        for b in obj.get("beats", [])[:5]:
            doodle = b.get("doodle_name", "house")
            if doodle not in ["bank", "calculator", "checklist", "house", "money_bag", "refinance", "warning", "chart", "globe"]:
                doodle = select_doodle_for_text(b.get("title", ""))
            beats.append(
                ExplainerBeat(
                    beat_id=b.get("beat_id", "beat"),
                    doodle_name=doodle,
                    title=b.get("title", "")[:32],
                    subtitle=b.get("subtitle", "")[:42],
                    callouts=b.get("callouts", [])[:2],
                    spoken_script=b.get("spoken_script", ""),
                    marker_coords=tuple(b.get("marker_coords", [820, 1150])),
                )
            )

        return ExplainerTopic(
            title=obj.get("title", topic_prompt),
            category=obj.get("category", "การเงินส่วนบุคคล"),
            summary=obj.get("summary", ""),
            caption=obj.get("caption", ""),
            beats=beats,
        )

    return get_curated_refinance_topic()
