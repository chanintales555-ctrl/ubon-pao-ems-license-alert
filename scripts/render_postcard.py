#!/usr/bin/env python3
"""
Postcard PNG renderer for Ubon Ratchathani PAO EMS License Alert System.
Renders 1080x1080 crisp institutional postcards (Green 9m / Yellow 6m / Red 3m / Expired)
using local IBM Plex Sans Thai fonts + headless Chromium/Chrome/Edge for 100% accurate Thai shaping.
"""

from __future__ import annotations

import base64
import html
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
EMBLEM_PATH = ASSETS_DIR / "ubon-pao-emblem.png"

QUAL_LABELS = {
    "ENP": "ENP · พยาบาลเวชปฏิบัติฉุกเฉิน",
    "PMD": "PMD · นักปฏิบัติการฉุกเฉินการแพทย์",
    "พว.": "พว. · พยาบาลวิชาชีพ",
    "พฉพพ": "พฉพพ · พนักงานฉุกเฉินการแพทย์",
    "EMT": "EMT · พนักงานฉุกเฉินการแพทย์",
    "EMR": "EMR · อาสาสมัครฉุกเฉินการแพทย์",
    "-": "ไม่ระบุคุณวุฒิ",
}

ROLE_LABELS = {
    "หัวหน้าชุด": "หัวหน้าชุดปฏิบัติการ",
    "ผช.หัวหน้าชุด": "ผู้ช่วยหัวหน้าชุดปฏิบัติการ",
    "พขร": "พขร. (พนักงานขับรถปฏิบัติการ)",
    "บุคลากรสนับสนุน": "บุคลากรสนับสนุน",
    "ผู้บริหาร": "ผู้บริหารหน่วยปฏิบัติการ",
}

THAI_MONTHS_FULL = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

THEMES = {
    "ok": {
        "band": "#176B4B",
        "accent": "#135D41",
        "tint": "#EDF7F2",
        "border": "#9DCDB9",
        "badge_bg": "#176B4B",
        "badge_text": "#F8FCF9",
        "badge_label": "ทดสอบระบบแจ้งเตือน · สถานะปกติ",
        "headline": "เอกสารใช้งานได้ปกติ",
        "subline": "ยังไม่ถึงรอบแจ้งเตือนล่วงหน้า (9 / 6 / 3 เดือน) — ส่งเพื่อทดสอบระบบ",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="square" stroke-linejoin="miter">'
            '<circle cx="12" cy="12" r="9"/>'
            '<polyline points="8.5 12.5 11 15 15.5 9.5"/>'
            "</svg>"
        ),
    },
    "9m": {
        "band": "#176B4B",
        "accent": "#135D41",
        "tint": "#EDF7F2",
        "border": "#9DCDB9",
        "badge_bg": "#176B4B",
        "badge_text": "#F8FCF9",
        "badge_label": "แจ้งเตือนรอบที่ 1 · ล่วงหน้า 9 เดือน",
        "headline": "อีก 9 เดือนจะหมดอายุ",
        "subline": "ระดับปกติ — แจ้งเตือนล่วงหน้าเพื่อวางแผนการต่ออายุเอกสาร",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="square" stroke-linejoin="miter">'
            '<circle cx="12" cy="12" r="9"/>'
            '<polyline points="8.5 12.5 11 15 15.5 9.5"/>'
            "</svg>"
        ),
    },
    "6m": {
        "band": "#C98200",
        "accent": "#945B00",
        "tint": "#FDF6E6",
        "border": "#E5C175",
        "badge_bg": "#C98200",
        "badge_text": "#FFFDF8",
        "badge_label": "แจ้งเตือนรอบที่ 2 · ล่วงหน้า 6 เดือน",
        "headline": "อีก 6 เดือนจะหมดอายุ",
        "subline": "ระดับเฝ้าระวัง — กรุณาเริ่มรวบรวมและเตรียมเอกสารเพื่อต่ออายุ",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="square" stroke-linejoin="miter">'
            '<circle cx="12" cy="12" r="9"/>'
            '<polyline points="12 7 12 12 15.5 14"/>'
            "</svg>"
        ),
    },
    "3m": {
        "band": "#B01E28",
        "accent": "#991720",
        "tint": "#FDF0F1",
        "border": "#E2A2A7",
        "badge_bg": "#B01E28",
        "badge_text": "#FFF9F9",
        "badge_label": "แจ้งเตือนเร่งด่วน · ล่วงหน้า 3 เดือน",
        "headline": "อีก 3 เดือนจะหมดอายุ",
        "subline": "ระดับเร่งด่วน — ใกล้ครบกำหนด กรุณาดำเนินการต่ออายุโดยทันที",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="square" stroke-linejoin="miter">'
            '<path d="M12 3L2 20h20L12 3z"/>'
            '<line x1="12" y1="9.5" x2="12" y2="14"/>'
            '<line x1="12" y1="17.2" x2="12.01" y2="17.2"/>'
            "</svg>"
        ),
    },
    "expired": {
        "band": "#7D1018",
        "accent": "#7D1018",
        "tint": "#FCEAEA",
        "border": "#D98C91",
        "badge_bg": "#7D1018",
        "badge_text": "#FFF9F9",
        "badge_label": "แจ้งเตือนด่วนที่สุด · หมดอายุแล้ว",
        "headline": "เอกสารหมดอายุแล้ว",
        "subline": "เลยกำหนดวันหมดอายุ — กรุณาตรวจสอบและดำเนินการต่ออายุทันที",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="square" stroke-linejoin="miter">'
            '<circle cx="12" cy="12" r="9"/>'
            '<line x1="15" y1="9" x2="9" y2="15"/>'
            '<line x1="9" y1="9" x2="15" y2="15"/>'
            "</svg>"
        ),
    },
}


def find_browser_executable() -> str:
    env_bin = os.environ.get("CHROME_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    raise RuntimeError("No Chrome/Chromium/Edge executable found for PNG rendering.")


def format_thai_date(iso_date: str) -> str:
    y, m, d = [int(x) for x in iso_date.split("-")]
    return f"{d} {THAI_MONTHS_FULL[m - 1]} {y + 543}"


def load_data_uri(path: Path, mime: str) -> str:
    raw = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def build_postcard_html(
    *,
    person: dict[str, Any],
    tier: str,
    doc_type: str,
    expiry_iso: str,
    expiry_raw: str | None,
    days_remaining_text: str,
) -> str:
    t = THEMES[tier]
    emblem_uri = load_data_uri(EMBLEM_PATH, "image/png")

    font_regular = (FONTS_DIR / "IBMPlexSansThai-Regular.ttf").as_uri()
    font_medium = (FONTS_DIR / "IBMPlexSansThai-Medium.ttf").as_uri()
    font_semibold = (FONTS_DIR / "IBMPlexSansThai-SemiBold.ttf").as_uri()
    font_bold = (FONTS_DIR / "IBMPlexSansThai-Bold.ttf").as_uri()

    reg_no = f"{int(person['id']):02d}"
    name = html.escape(person["name"])
    qual = html.escape(QUAL_LABELS.get(person.get("qualification", "-"), person.get("qualification", "-")))
    role = html.escape(ROLE_LABELS.get(person.get("role", "-"), person.get("role", "-")))
    doc_type_esc = html.escape(doc_type)
    expiry_full = html.escape(format_thai_date(expiry_iso))
    expiry_raw_line = f"ตามเอกสารทะเบียน: {html.escape(expiry_raw)}" if expiry_raw else "ตามเอกสารทะเบียนบุคลากร"
    days_esc = html.escape(days_remaining_text)

    return f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8" />
<style>
  @font-face {{
    font-family: 'IBM Plex Sans Thai';
    src: url('{font_regular}') format('truetype');
    font-weight: 400;
    font-style: normal;
  }}
  @font-face {{
    font-family: 'IBM Plex Sans Thai';
    src: url('{font_medium}') format('truetype');
    font-weight: 500;
    font-style: normal;
  }}
  @font-face {{
    font-family: 'IBM Plex Sans Thai';
    src: url('{font_semibold}') format('truetype');
    font-weight: 600;
    font-style: normal;
  }}
  @font-face {{
    font-family: 'IBM Plex Sans Thai';
    src: url('{font_bold}') format('truetype');
    font-weight: 700;
    font-style: normal;
  }}

  :root {{
    --paper: #F8F6F4;
    --surface: #FFFDFC;
    --surface-sub: #F2EFEC;
    --rule: #DDD7D1;
    --rule-strong: #C6BEB6;
    --ink: #1D1917;
    --ink-2: #4E4742;
    --ink-3: #706862;
    --band: {t['band']};
    --accent: {t['accent']};
    --tint: {t['tint']};
    --tint-border: {t['border']};
    --badge-bg: {t['badge_bg']};
    --badge-text: {t['badge_text']};
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  html, body {{
    width: 1080px;
    height: 1080px;
    overflow: hidden;
    background: var(--paper);
    color: var(--ink);
    font-family: 'IBM Plex Sans Thai', sans-serif;
    -webkit-font-smoothing: antialiased;
  }}

  .card {{
    width: 1080px;
    height: 1080px;
    display: flex;
    flex-direction: column;
    background: var(--paper);
    position: relative;
  }}

  /* Top institutional color band */
  .top-band {{
    height: 22px;
    width: 100%;
    background: var(--band);
    flex-shrink: 0;
  }}

  /* Header */
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding: 36px 56px 30px;
    background: var(--surface);
    border-bottom: 1.5px solid var(--rule);
  }}

  .brand {{
    display: flex;
    align-items: center;
    gap: 20px;
  }}

  .emblem {{
    width: 88px;
    height: 82px;
    object-fit: contain;
    flex-shrink: 0;
  }}

  .org-main {{
    font-size: 25px;
    font-weight: 700;
    color: var(--ink);
    line-height: 1.25;
  }}

  .org-sub {{
    font-size: 20px;
    font-weight: 500;
    color: var(--ink-2);
    margin-top: 3px;
  }}

  .tier-badge {{
    display: inline-flex;
    align-items: center;
    padding: 11px 20px;
    border-radius: 4px;
    background: var(--badge-bg);
    color: var(--badge-text);
    font-size: 20px;
    font-weight: 600;
    white-space: nowrap;
    letter-spacing: 0.01em;
  }}

  /* Main body */
  .body {{
    flex: 1;
    padding: 38px 56px 34px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 28px;
  }}

  /* Alert Banner */
  .alert-box {{
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 28px 32px;
    background: var(--tint);
    border: 2px solid var(--tint-border);
    border-radius: 5px;
  }}

  .alert-icon {{
    width: 68px;
    height: 68px;
    border-radius: 4px;
    background: var(--band);
    color: var(--badge-text);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}

  .alert-icon svg {{
    width: 38px;
    height: 38px;
  }}

  .alert-headline {{
    font-size: 44px;
    font-weight: 700;
    color: var(--accent);
    line-height: 1.18;
  }}

  .alert-subline {{
    font-size: 22px;
    font-weight: 500;
    color: var(--ink-2);
    margin-top: 6px;
  }}

  /* Personnel Profile Box */
  .profile-box {{
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    background: var(--surface);
    border: 1.5px solid var(--rule-strong);
    border-radius: 5px;
    padding: 36px 40px;
  }}

  .profile-top-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }}

  .profile-label {{
    font-size: 20px;
    font-weight: 600;
    color: var(--ink-3);
  }}

  .reg-tag {{
    font-size: 19px;
    font-weight: 600;
    color: var(--ink-2);
    background: var(--surface-sub);
    border: 1px solid var(--rule);
    padding: 5px 14px;
    border-radius: 3px;
    font-variant-numeric: tabular-nums;
  }}

  .person-name {{
    font-size: 52px;
    font-weight: 700;
    color: var(--ink);
    line-height: 1.22;
    margin-bottom: 22px;
  }}

  .meta-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    padding-bottom: 26px;
    border-bottom: 1.5px solid var(--rule);
  }}

  .meta-key {{
    font-size: 18px;
    font-weight: 500;
    color: var(--ink-3);
    margin-bottom: 4px;
  }}

  .meta-val {{
    font-size: 24px;
    font-weight: 600;
    color: var(--ink);
    line-height: 1.3;
  }}

  /* Expiration section */
  .expiry-grid {{
    display: grid;
    grid-template-columns: 1fr 1.2fr;
    gap: 20px;
    padding-top: 26px;
  }}

  .expiry-col {{
    padding: 20px 24px;
    border-radius: 4px;
    border: 1.5px solid var(--rule);
    background: var(--paper);
  }}

  .expiry-col.highlight {{
    background: var(--tint);
    border-color: var(--tint-border);
  }}

  .expiry-label {{
    font-size: 18px;
    font-weight: 600;
    color: var(--ink-3);
    margin-bottom: 8px;
  }}

  .expiry-col.highlight .expiry-label {{
    color: var(--accent);
  }}

  .expiry-doc {{
    font-size: 28px;
    font-weight: 700;
    color: var(--ink);
    line-height: 1.25;
  }}

  .expiry-date {{
    font-size: 38px;
    font-weight: 700;
    color: var(--accent);
    line-height: 1.2;
    font-variant-numeric: tabular-nums;
  }}

  .expiry-note {{
    font-size: 19px;
    font-weight: 500;
    color: var(--ink-2);
    margin-top: 8px;
    font-variant-numeric: tabular-nums;
  }}

  /* Footer */
  .footer {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 22px 56px;
    background: var(--surface);
    border-top: 1.5px solid var(--rule);
    font-size: 19px;
    font-weight: 500;
    color: var(--ink-3);
  }}

  .footer-accent {{
    color: var(--accent);
    font-weight: 600;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="top-band"></div>

    <header class="header">
      <div class="brand">
        <img class="emblem" src="{emblem_uri}" alt="ตรา อบจ.อุบลราชธานี" />
        <div>
          <div class="org-main">องค์การบริหารส่วนจังหวัดอุบลราชธานี</div>
          <div class="org-sub">หน่วยปฏิบัติการแพทย์กู้ชีพระดับสูง (EMS)</div>
        </div>
      </div>
      <div class="tier-badge">{t['badge_label']}</div>
    </header>

    <main class="body">
      <section class="alert-box">
        <div class="alert-icon">{t['icon_svg']}</div>
        <div>
          <div class="alert-headline">{t['headline']}</div>
          <div class="alert-subline">{t['subline']}</div>
        </div>
      </section>

      <section class="profile-box">
        <div>
          <div class="profile-top-row">
            <span class="profile-label">ข้อมูลบุคลากรผู้ปฏิบัติการ</span>
          </div>
          <div class="person-name">{name}</div>

          <div class="meta-grid">
            <div>
              <div class="meta-key">คุณวุฒิวิชาชีพ</div>
              <div class="meta-val">{qual}</div>
            </div>
            <div>
              <div class="meta-key">ตำแหน่งในหน่วยปฏิบัติการแพทย์</div>
              <div class="meta-val">{role}</div>
            </div>
          </div>
        </div>

        <div class="expiry-grid">
          <div class="expiry-col">
            <div class="expiry-label">เอกสารที่ครบกำหนดแจ้งเตือน</div>
            <div class="expiry-doc">{doc_type_esc}</div>
            <div class="expiry-note">{expiry_raw_line}</div>
          </div>
          <div class="expiry-col highlight">
            <div class="expiry-label">วันหมดอายุ</div>
            <div class="expiry-date">{expiry_full}</div>
            <div class="expiry-note">{days_esc}</div>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      <span>ระบบแจ้งเตือนวันหมดอายุอัตโนมัติ · อบจ.อุบลราชธานี</span>
    </footer>
  </div>
</body>
</html>
"""


def render_postcard_png(
    *,
    person: dict[str, Any],
    tier: str,
    doc_type: str,
    expiry_iso: str,
    expiry_raw: str | None,
    days_remaining_text: str,
    output_path: Path,
) -> Path:
    html_str = build_postcard_html(
        person=person,
        tier=tier,
        doc_type=doc_type,
        expiry_iso=expiry_iso,
        expiry_raw=expiry_raw,
        days_remaining_text=days_remaining_text,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    browser_bin = find_browser_executable()

    with tempfile.TemporaryDirectory() as tmpdir:
        html_file = Path(tmpdir) / "card.html"
        html_file.write_text(html_str, encoding="utf-8")

        cmd = [
            browser_bin,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--window-size=1080,1080",
            "--force-device-scale-factor=1",
            f"--screenshot={output_path.resolve()}",
            html_file.as_uri(),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Headless render failed (rc={res.returncode}): {res.stderr}")

    return output_path


if __name__ == "__main__":
    samples_dir = ROOT_DIR / "samples"
    samples = [
        (
            "9m",
            {
                "id": 3,
                "name": "น.ส.พัชรี พลกันยา",
                "qualification": "PMD",
                "role": "หัวหน้าชุด",
            },
            "ใบประกอบวิชาชีพ",
            "2027-07-04",
            "๔ ก.ค. ๗๐",
            "เหลือเวลาประมาณ 9 เดือน (270 วัน)",
            samples_dir / "sample_9m_green.png",
        ),
        (
            "6m",
            {
                "id": 2,
                "name": "นางนิตยา พันธ์สุวรรณ",
                "qualification": "ENP",
                "role": "หัวหน้าชุด",
            },
            "ใบประกอบวิชาชีพ",
            "2028-03-29",
            "๒๙ มี.ค. ๗๑",
            "เหลือเวลาประมาณ 6 เดือน (180 วัน)",
            samples_dir / "sample_6m_yellow.png",
        ),
        (
            "3m",
            {
                "id": 12,
                "name": "นายธนิต แซ่ลอ",
                "qualification": "EMT",
                "role": "พขร",
            },
            "บัตรประจำตัวผู้ปฏิบัติการ",
            "2027-02-12",
            "๑๒ ก.พ. ๗๐",
            "เหลือเวลาอีก 85 วัน (เข้าเกณฑ์ 3 เดือน)",
            samples_dir / "sample_3m_red.png",
        ),
    ]

    for tier, person, doc_type, exp_iso, exp_raw, days_txt, out_path in samples:
        render_postcard_png(
            person=person,
            tier=tier,
            doc_type=doc_type,
            expiry_iso=exp_iso,
            expiry_raw=exp_raw,
            days_remaining_text=days_txt,
            output_path=out_path,
        )
        print(f"Rendered {out_path} ({out_path.stat().st_size:,} bytes)")
