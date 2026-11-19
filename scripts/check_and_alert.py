#!/usr/bin/env python3
"""
Automated License & Operator Card Expiration Alert Engine for Ubon Ratchathani PAO EMS.

2-Phase GitHub Actions flow (eliminates image-URL 404 race conditions):
  Phase 1 (--prepare): Evaluate personnel dates -> render 1080x1080 PNG postcards -> write pending queue.
  (Workflow commits & pushes cards/*.png to GitHub so raw HTTPS URLs are publicly reachable.)
  Phase 2 (--send): Verify raw HTTPS URLs return HTTP 200 -> push images to LINE Group via Messaging API -> update sent_log.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from render_postcard import ROOT_DIR, format_thai_date, render_postcard_png

DATA_DIR = ROOT_DIR / "data"
PERSONNEL_PATH = DATA_DIR / "personnel.json"
SENT_LOG_PATH = DATA_DIR / "sent_log.json"
CARDS_DIR = ROOT_DIR / "cards"
PENDING_QUEUE_PATH = CARDS_DIR / "_pending_queue.json"

BANGKOK_TZ = dt.timezone(dt.timedelta(hours=7))
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"


def today_bangkok() -> dt.date:
    return dt.datetime.now(BANGKOK_TZ).date()


def classify_tier(days_left: int) -> str | None:
    if days_left < 0:
        return "expired"
    if days_left <= 90:
        return "3m"
    if days_left <= 180:
        return "6m"
    if days_left <= 270:
        return "9m"
    return None


def format_remaining_thai(days_left: int) -> str:
    if days_left < 0:
        overdue = abs(days_left)
        return f"หมดอายุมาแล้ว {overdue:,} วัน"
    if days_left == 0:
        return "หมดอายุวันนี้"
    years = days_left // 365
    rem_after_years = days_left % 365
    months = rem_after_years // 30
    rem_days = rem_after_years % 30
    parts: list[str] = []
    if years > 0:
        parts.append(f"{years} ปี")
    if months > 0:
        parts.append(f"{months} เดือน")
    if years == 0 and rem_days > 0:
        parts.append(f"{rem_days} วัน")
    return f"เหลือเวลาอีก {' '.join(parts)} ({days_left:,} วัน)"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_due_alerts(personnel: list[dict[str, Any]], sent_log: dict[str, Any], today: dt.date) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    doc_fields = [
        ("licenseExpiry", "licenseExpiryRaw", "ใบประกอบวิชาชีพ"),
        ("cardExpiry", "cardExpiryRaw", "บัตรประจำตัวผู้ปฏิบัติการ"),
    ]

    for p in personnel:
        for iso_key, raw_key, doc_label in doc_fields:
            iso_val = p.get(iso_key)
            if not iso_val:
                continue
            exp_date = dt.date.fromisoformat(iso_val)
            days_left = (exp_date - today).days
            tier = classify_tier(days_left)
            if not tier:
                continue

            log_key = f"p{p['id']}_{iso_key}_{iso_val}_{tier}"
            if log_key in sent_log:
                continue

            alerts.append(
                {
                    "logKey": log_key,
                    "person": p,
                    "tier": tier,
                    "docType": doc_label,
                    "expiryIso": iso_val,
                    "expiryRaw": p.get(raw_key),
                    "daysLeft": days_left,
                    "daysText": format_remaining_thai(days_left),
                }
            )
    return alerts


def build_test_alerts(
    personnel: list[dict[str, Any]],
    mode: str,
    today: dt.date,
    person_id: int | None = None,
) -> list[dict[str, Any]]:
    by_id = {p["id"]: p for p in personnel}
    if mode == "test_person":
        target_id = person_id if person_id is not None else 2
        p = by_id.get(target_id)
        if not p:
            raise RuntimeError(f"Person ID {target_id} not found in data/personnel.json")
        if p.get("licenseExpiry"):
            doc_type = "ใบประกอบวิชาชีพ"
            iso_val = p["licenseExpiry"]
            raw_val = p.get("licenseExpiryRaw")
        elif p.get("cardExpiry"):
            doc_type = "บัตรประจำตัวผู้ปฏิบัติการ"
            iso_val = p["cardExpiry"]
            raw_val = p.get("cardExpiryRaw")
        else:
            raise RuntimeError(f"Person ID {target_id} ({p['name']}) has no expiry date recorded")
        exp_date = dt.date.fromisoformat(iso_val)
        days_left = (exp_date - today).days
        tier = classify_tier(days_left) or "ok"
        return [
            {
                "logKey": None,
                "person": p,
                "tier": tier,
                "docType": doc_type,
                "expiryIso": iso_val,
                "expiryRaw": raw_val,
                "daysLeft": days_left,
                "daysText": format_remaining_thai(days_left),
            }
        ]
    if mode == "test_red":
        p = by_id.get(12, personnel[0])
        return [
            {
                "logKey": None,
                "person": p,
                "tier": "3m",
                "docType": "บัตรประจำตัวผู้ปฏิบัติการ",
                "expiryIso": p.get("cardExpiry") or "2027-02-12",
                "expiryRaw": p.get("cardExpiryRaw") or "๑๒ ก.พ. ๗๐",
                "daysLeft": 85,
                "daysText": "ทดสอบระบบแจ้งเตือนรอบ 3 เดือน (สีแดง)",
            }
        ]
    if mode == "test_all_colors":
        p9 = by_id.get(3, personnel[0])
        p6 = by_id.get(2, personnel[0])
        p3 = by_id.get(12, personnel[0])
        return [
            {
                "logKey": None,
                "person": p9,
                "tier": "9m",
                "docType": "ใบประกอบวิชาชีพ",
                "expiryIso": p9.get("licenseExpiry") or "2027-07-04",
                "expiryRaw": p9.get("licenseExpiryRaw") or "๔ ก.ค. ๗๐",
                "daysLeft": 270,
                "daysText": "ทดสอบแจ้งเตือนรอบ 9 เดือน (สีเขียว)",
            },
            {
                "logKey": None,
                "person": p6,
                "tier": "6m",
                "docType": "ใบประกอบวิชาชีพ",
                "expiryIso": p6.get("licenseExpiry") or "2028-03-29",
                "expiryRaw": p6.get("licenseExpiryRaw") or "๒๙ มี.ค. ๗๑",
                "daysLeft": 180,
                "daysText": "ทดสอบแจ้งเตือนรอบ 6 เดือน (สีเหลือง)",
            },
            {
                "logKey": None,
                "person": p3,
                "tier": "3m",
                "docType": "บัตรประจำตัวผู้ปฏิบัติการ",
                "expiryIso": p3.get("cardExpiry") or "2027-02-12",
                "expiryRaw": p3.get("cardExpiryRaw") or "๑๒ ก.พ. ๗๐",
                "daysLeft": 85,
                "daysText": "ทดสอบแจ้งเตือนรอบ 3 เดือน (สีแดง)",
            },
        ]
    return []


def phase_prepare(mode: str, dry_run: bool, person_id: int | None = None) -> int:
    data = load_json(PERSONNEL_PATH, {"personnel": []})
    personnel = data.get("personnel", [])
    sent_log = load_json(SENT_LOG_PATH, {})
    today = today_bangkok()

    if mode in ("test_red", "test_all_colors", "test_person"):
        alerts = build_test_alerts(personnel, mode, today, person_id=person_id)
    else:
        alerts = build_due_alerts(personnel, sent_log, today)

    print(f"[prepare] Date (ICT): {today.isoformat()} | Mode: {mode} | Pending alerts: {len(alerts)}")
    for item in alerts:
        p = item["person"]
        print(f"  - [{item['tier']}] {p['name']} | {item['docType']} | {item['expiryIso']} ({item['daysText']})")

    if dry_run:
        print("[prepare] Dry-run enabled — no images rendered or queued.")
        return 0

    if not alerts:
        if PENDING_QUEUE_PATH.exists():
            PENDING_QUEUE_PATH.unlink()
        return 0

    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    queue: list[dict[str, Any]] = []

    for item in alerts:
        # Randomized UUID filename for URL privacy
        filename = f"{uuid.uuid4().hex}.png"
        out_path = CARDS_DIR / filename
        render_postcard_png(
            person=item["person"],
            tier=item["tier"],
            doc_type=item["docType"],
            expiry_iso=item["expiryIso"],
            expiry_raw=item["expiryRaw"],
            days_remaining_text=item["daysText"],
            output_path=out_path,
        )
        print(f"[prepare] Rendered {out_path.name} ({out_path.stat().st_size:,} bytes)")
        queue.append(
            {
                "logKey": item["logKey"],
                "filename": filename,
                "personName": item["person"]["name"],
                "tier": item["tier"],
                "docType": item["docType"],
                "expiryIso": item["expiryIso"],
                "expiryThai": format_thai_date(item["expiryIso"]),
                "daysText": item["daysText"],
            }
        )

    save_json(PENDING_QUEUE_PATH, {"createdAt": dt.datetime.now(BANGKOK_TZ).isoformat(), "items": queue})
    print(f"[prepare] Queued {len(queue)} postcard(s) in {PENDING_QUEUE_PATH.name}")
    return 0


def wait_for_url_ready(url: str, timeout_sec: int = 45) -> None:
    deadline = time.time() + timeout_sec
    last_err = ""
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "UbonPAO-EMS-Alert/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last_err = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Image URL not reachable after {timeout_sec}s: {url} ({last_err})")


def push_line_messages(token: str, target_id: str, messages: list[dict[str, Any]]) -> None:
    payload = json.dumps({"to": target_id, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        LINE_PUSH_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            print(f"[send] LINE Push HTTP {resp.status}: {body}")
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LINE Push failed HTTP {err.code}: {err_body}") from err


def phase_send(repo: str, branch: str) -> int:
    if not PENDING_QUEUE_PATH.exists():
        print("[send] No pending queue found — nothing to send.")
        return 0

    queue_data = load_json(PENDING_QUEUE_PATH, {"items": []})
    items = queue_data.get("items", [])
    if not items:
        PENDING_QUEUE_PATH.unlink(missing_ok=True)
        print("[send] Pending queue empty — nothing to send.")
        return 0

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    group_id = os.environ.get("LINE_GROUP_ID", "").strip()

    if not token:
        raise RuntimeError("Missing environment variable LINE_CHANNEL_ACCESS_TOKEN.")
    if not group_id:
        raise RuntimeError("Missing environment variable LINE_GROUP_ID. Please add LINE_GROUP_ID to GitHub Actions Secrets.")

    sent_log = load_json(SENT_LOG_PATH, {})
    now_iso = dt.datetime.now(BANGKOK_TZ).isoformat()

    # LINE Messaging API allows up to 5 message objects per Push call (saves quota!)
    batch_size = 5
    for idx in range(0, len(items), batch_size):
        batch = items[idx : idx + batch_size]
        messages: list[dict[str, Any]] = []
        for item in batch:
            image_url = f"https://raw.githubusercontent.com/{repo}/{branch}/cards/{item['filename']}"
            print(f"[send] Checking public URL: {image_url}")
            wait_for_url_ready(image_url)
            messages.append(
                {
                    "type": "image",
                    "originalContentUrl": image_url,
                    "previewImageUrl": image_url,
                }
            )

        push_line_messages(token, group_id, messages)

        for item in batch:
            if item.get("logKey"):
                sent_log[item["logKey"]] = {
                    "sentAt": now_iso,
                    "personName": item["personName"],
                    "tier": item["tier"],
                    "docType": item["docType"],
                    "expiryIso": item["expiryIso"],
                    "cardFile": item["filename"],
                }

    save_json(SENT_LOG_PATH, sent_log)
    PENDING_QUEUE_PATH.unlink(missing_ok=True)
    print(f"[send] Successfully pushed {len(items)} postcard(s) to LINE group and updated sent_log.json.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ubon PAO EMS License Alert Engine")
    parser.add_argument("--prepare", action="store_true", help="Phase 1: check due dates and render PNG postcards")
    parser.add_argument("--send", action="store_true", help="Phase 2: push rendered PNG postcards to LINE group")
    parser.add_argument(
        "--mode",
        choices=["check", "test_red", "test_all_colors", "test_person", "dry_run"],
        default="check",
        help="Execution mode",
    )
    parser.add_argument("--person-id", type=int, default=None, help="Person ID for test_person mode")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "chanintales555-ctrl/ubon-pao-ems-license-alert"))
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()

    if args.prepare:
        return phase_prepare(mode=args.mode, dry_run=(args.mode == "dry_run"), person_id=args.person_id)
    if args.send:
        return phase_send(repo=args.repo, branch=args.branch)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
