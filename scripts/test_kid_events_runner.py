"""Reproducible LLM Runner for Child & Family Obligations.

Fetches emails via EmailProvider (with promotions enabled, social excluded, and PDF attachment extraction),
filters out non-kid items (webinars, domain alerts, financial promos), and extracts top-priority family events.

Usage:
    python scripts/test_kid_events_runner.py [--date 2026-02-20] [--model qwen3.6:latest] [--save-to-db]
"""

import argparse
from datetime import date, datetime, timedelta
import json
import logging
import os
import re
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from liftassistant.llm import call_llm
from liftassistant.models.enums import PriorityLevel
from liftassistant.models.event import Event
from liftassistant.modules.runners.llm_runner import SYSTEM_EXTRACTION_PROMPT, extract_json_array
from liftassistant.providers.email_provider import EmailProvider

logger = logging.getLogger(__name__)

FAMILY_KID_PROMPT_TEMPLATE = """You are a personal family assistant reviewing incoming messages for a household.
Today's reference date is {reference_date}.

Analyze the messages below. Extract actionable upcoming events, deadlines, workshops, and school reminders for the family:

1. SCHOOL & TUITION:
   - Any tuition, registration, or fee payment invoices due.
2. CHILDREN'S WORKSHOPS & ACTIVITIES:
   - Any scheduled community, store, or youth workshops with target dates.
3. SCHOOL LUNCH & DIETARY RESTRICTIONS:
   - Read the attached weekly school lunch menu PDF.
   - For ANY weekday (Monday through Friday) where the lunch entrée contains chicken or meatballs (in any form):
     * Identify the exact weekday serving that dish strictly from the PDF text.
     * Calculate that weekday's exact calendar date (YYYY-MM-DD) based on the date range in the menu heading (Monday = week start, Tuesday = +1 day, Wednesday = +2 days, Thursday = +3 days, Friday = +4 days).
     * Create an individual reminder for that day to switch to a Sun Butter & Jelly sandwich.
     * If a day serves any other food (e.g. fish, beef, pizza, mac and cheese, vegetarian), DO NOT create a reminder for that day.

STRICT EXCLUSION RULES (DO NOT EXTRACT):
- DO NOT extract webinars, lectures, or medical seminars.
- DO NOT extract domain renewals or hosting alerts.
- DO NOT extract credit card promotional interest rate offers.
- DO NOT extract general retail sales, newsletters, or travel promos.
- DO NOT extract routine daily child sign-in/out logs or nap logs.
- DO NOT extract HOA message board discussions.

OUTPUT FORMAT:
Respond with a JSON object containing an "events" array:
{{
  "events": [
    {{
      "title": "Clear concise reminder title",
      "description": "Details, notes, and specific entrée or activity info",
      "due_date": "YYYY-MM-DD",
      "priority": "High",
      "source_citation": "Verbatim quote or subject from the source email/attachment"
    }}
  ]
}}

If no events match, return: {{"events": []}}

Here are the emails:
{data}
"""


def fetch_emails_for_date(target_date_str: str, limit: int = 60) -> list[dict]:
    """Fetch emails for a target calendar day using EmailProvider."""
    provider = EmailProvider()
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    
    # Gmail query: include day before and day after to safely cover local timezones through evening
    prev_day = (target_dt - timedelta(days=1)).strftime("%Y/%m/%d")
    next_day_after = (target_dt + timedelta(days=2)).strftime("%Y/%m/%d")
    query = f"after:{prev_day} before:{next_day_after}"

    print(f"📡 Fetching emails via EmailProvider...")
    print(f"   Query: '{query}' | Promotions: Included | Social: Excluded")
    
    items = provider.fetch(
        query=query,
        limit=limit,
        newer_than_days=0,
        unread_only=False,
        include_pdf_attachments=True,
        exclude_promotions=False,
        exclude_social=True,
    )
    print(f"   Fetched {len(items)} items from Gmail.")
    return items


def format_items_for_prompt(items: list[dict]) -> str:
    """Format raw items and PDF text into LLM prompt text block."""
    formatted = []
    for idx, it in enumerate(items, 1):
        subj = it.get("subject", "").strip()
        sender = it.get("from", "").strip()
        dt = it.get("date", "").strip()
        snippet = it.get("snippet", "").strip()

        block = [
            f"--- Item {idx} ---",
            f"Subject: {subj}",
            f"From: {sender}",
            f"Date: {dt}",
            f"Content: {snippet}",
        ]

        for att in it.get("attachments", []):
            att_name = att.get("filename", "")
            att_text = att.get("text", "").strip()
            if att_text:
                block.append(f"\n[Attachment: {att_name}]\n--- BEGIN PDF CONTENT ---\n{att_text}\n--- END PDF CONTENT ---")

        formatted.append("\n".join(block))
    return "\n\n".join(formatted)


def run_kid_events_pipeline(
    target_date: str = "2026-02-20",
    model: str = "qwen3.6:latest",
    save_to_db: bool = False,
    cache_file: str = None,
) -> list[dict]:
    """Execute the full reproducible end-to-end extraction pipeline."""
    # 1. Fetch or load from cache
    if cache_file and os.path.exists(cache_file):
        print(f"📂 Loading cached emails from {cache_file}...")
        with open(cache_file, "r", encoding="utf-8") as f:
            items = json.load(f)
    else:
        items = fetch_emails_for_date(target_date)
        if cache_file:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
            print(f"💾 Cached {len(items)} emails to {cache_file}")

    # 2. Format items
    data_text = format_items_for_prompt(items)
    target_dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    ref_date_human = target_dt_obj.strftime("%A, %B %d, %Y")

    prompt = FAMILY_KID_PROMPT_TEMPLATE.format(
        reference_date=ref_date_human,
        data=data_text,
    )

    # 3. Call local Ollama
    print(f"\n🤖 Running extraction via Ollama (model: {model})...")
    resp = call_llm(
        prompt=prompt,
        system_prompt=SYSTEM_EXTRACTION_PROMPT,
        model=model,
        json_mode=True,
        timeout=180,
    )

    # 4. Extract and parse JSON
    parsed_events = extract_json_array(resp)
    print(f"\n✅ Extracted {len(parsed_events)} actionable kid & family events:")

    for i, ev in enumerate(parsed_events, 1):
        print(f"\n------------------------------------------------------------")
        print(f"Event {i}: {ev.get('title')}")
        print(f"  Due Date: {ev.get('due_date')} | Priority: {ev.get('priority')}")
        print(f"  Citation: {ev.get('source_citation')}")
        print(f"  Details:  {ev.get('description')}")
    print(f"------------------------------------------------------------\n")

    # 5. Optionally save to SQLite database
    if save_to_db:
        from liftassistant.db.repository import DatabaseRepository
        db = DatabaseRepository()
        saved_count = 0
        module_id = "primrose_lunch"

        for ev in parsed_events:
            raw_due = ev.get("due_date", target_date)
            try:
                due_d = date.fromisoformat(str(raw_due)[:10])
            except Exception:
                due_d = target_dt_obj.date()

            # Same-day deduplication check
            existing = db.get_events_by_module_and_date(module_id, due_d)
            if existing:
                print(f"ℹ️ Skipping event on {due_d} (already exists in DB: '{existing[0].title}')")
                continue

            event_obj = Event(
                module_id=module_id,
                title=str(ev.get("title", "Family Reminder")),
                description=str(ev.get("description", "")),
                original_due_date=due_d,
                current_due_date=due_d,
                priority=PriorityLevel.HIGH,
                dedup_hash=f"{module_id}:{due_d.isoformat()}",
                citation={
                    "source_provider": "email",
                    "source_citation": ev.get("source_citation", ""),
                },
            )
            saved, is_new = db.create_event(event_obj)
            if is_new:
                saved_count += 1
                print(f"💾 Saved to SQLite: '{saved.title}' on {due_d}")

        print(f"Successfully saved {saved_count} new events to SQLite.")

    return parsed_events


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test LLM Runner for Family & Kid Events")
    parser.add_argument("--date", default="2026-02-20", help="Target reference date (YYYY-MM-DD)")
    parser.add_argument("--model", default="qwen3.6:latest", help="Ollama model string")
    parser.add_argument("--save-to-db", action="store_true", help="Persist extracted events to SQLite database")
    parser.add_argument("--cache-file", default=None, help="Optional local JSON file to load/save emails")
    args = parser.parse_args()

    run_kid_events_pipeline(
        target_date=args.date,
        model=args.model,
        save_to_db=args.save_to_db,
        cache_file=args.cache_file,
    )
