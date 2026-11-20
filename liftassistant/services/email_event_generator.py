"""Email Event Generator Service.
Connects to Gmail API, sends emails to LLM for perception/extraction,
writes standardized JSON files to data/receipts_inbox/{event_id}.json for deduplication,
and triggers the ReceiptParser to deterministically ingest the events and receipts.
"""

from datetime import datetime, date, timedelta
import email.utils
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

from liftassistant.config import settings
from liftassistant.db.repository import GeneratorRunRepository, InventoryRepository, PlaceRepository
from liftassistant.llm import call_llm
from liftassistant.models.domain import (
    DiningDetail,
    GeneratorEventFeedback,
    GeneratorRun,
    LifeEvent,
    MaintenanceDetail,
    Place,
    ResourceClosure,
    ShoppingDetail,
    StandardizedReceipt,
)
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.event_manager import EventManager
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.receipt_parser import KNOWN_MERCHANTS, ReceiptParser
from liftassistant.services.receipt_service import ReceiptService

logger = logging.getLogger(__name__)

RECEIPTS_INBOX_DIR = Path("data") / "receipts_inbox"

SUBJECT_INCLUDE_PATTERNS = [
    r"\breceipt\b",
    r"\border\b",
    r"\bbill\b",
    r"\binvoice\b",
    r"\bpayment\b",
    r"\bstatement\b",
    r"\btuition\b",
    r"\bymca\b",
    r"\bworkshop\b",
    r"\bappointment\b",
    r"\bschedule\b",
    r"\bclass\b",
    r"\blesson\b",
    r"\bclosure\b",
    r"\bclosed\b",
]

SUBJECT_EXCLUDE_PATTERNS = [
    r"streaming",
    r"stream",
    r"digest",
    r"daily summary",
    r"password reset",
    r"newsletter",
    r"points",
    r"cash back",
    r"\boffer\b",
    r"\bdeal\b",
    r"\bdeals\b",
    r"\bdiscount\b",
    r"\bpromo\b",
    r"\bpromotion\b",
    r"\bpromotional\b",
    r"\bsale\b",
    r"\bcoupon\b",
    r"fare",
    r"flight",
    r"price drop",
    r"discussion",
    r"happy birthday",
]

EXTRACTION_SYSTEM_PROMPT = """You are an intelligent email extraction assistant for a Personal Life Operating System.
Your job is to analyze incoming emails and classify them.

CATEGORIES:
1. "RECEIPT" - An actual completed payment receipt or order confirmation for a purchase already made.
   - MUST have an actual vendor, transaction date/time, and a completed payment amount > $0.00.
   - MUST show proof of a completed charge (e.g. "Your order is confirmed", "Payment processed", "Thank you for your payment", "Amount charged", "Billed to card", "Order #").
2. "BILL" - An upcoming bill, statement, tuition, invoice, or payment due.
   - MUST have a vendor, an actual amount due, and a due date or payment deadline.
   - Set "is_autopay": true if the email indicates auto-pay or automatic deduction is already setup. Set "is_autopay": false if manual action is required.
3. "ACTIVITY" - An activity, workshop, lesson, or class that the family or kid has signed up for (e.g. Lowe's Kids Workshop, swimming lessons, sports practice, daycare classes).
   - MUST set "event_type": "KID_ACTIVITY" and include "Marcus" and "Dad" in "people_involved".
   - This represents an actual kid activity on the calendar, NOT a facility closure or resource blackout.
4. "FACILITY_CLOSURE" - Notice that an external facility or resource (such as YMCA, gym, pool, school, or community center) is closed for a holiday, maintenance, or weather (e.g. "Thanksgiving Closure", "Pool closed for repairs").
   - Specify "facility_name", "closure_start", and "closure_end".
5. "SKIP" - IGNORE ALL OF THE FOLLOWING:
   - PROMOTIONS & MARKETING: Sales pitches, offers, discounts, coupons, streaming ads ("Now Streaming on...", "Watch now"), promotional prices ("Get X for $4.99/mo", "Plans starting at $9.99", "$20 off", "Buy one get one"), credit card offers, airfare deals, or rewards announcements. Even if a promotional email contains dollar amounts or prices, it is a PROMOTION, NOT A RECEIPT or BILL!
   - NON-ACTIONABLE: Test emails ("Receipt test", "Sent from my iPhone"), generic chat, password resets, daily summaries, newsletters, digests, notifications with no transaction.

STRICT RULES:
- ALWAYS classify promotional emails, marketing ads, subscription pitches, and sales as "SKIP" with "is_event": false.
- A "RECEIPT" is only valid if an actual transaction occurred and payment was already completed. Solicitations or advertisements to buy something are NEVER receipts.
- If category is RECEIPT, BILL, ACTIVITY, or FACILITY_CLOSURE, you MUST set "is_event": true.
- If category is SKIP, you MUST set "is_event": false and total_amount to 0.0.
- Never return an empty JSON object. Always return valid JSON matching this schema:

{
  "is_event": true,
  "category": "RECEIPT" | "BILL" | "ACTIVITY" | "FACILITY_CLOSURE" | "SKIP",
  "reason": "Brief explanation of why this category was chosen",
  "is_autopay": false,
  "merchant_name": "Store, School, or Service Provider",
  "facility_name": "Facility name if category is FACILITY_CLOSURE or empty string",
  "closure_start": "YYYY-MM-DDTHH:MM:SS or null",
  "closure_end": "YYYY-MM-DDTHH:MM:SS or null",
  "merchant_address": "Street address or City, State if mentioned, or empty string",
  "transaction_time": "YYYY-MM-DDTHH:MM:SS",
  "due_date": "YYYY-MM-DDTHH:MM:SS or null",
  "total_amount": 0.00,
  "tax_amount": 0.00,
  "tip_amount": 0.00,
  "event_title": "Descriptive title for the event",
  "event_type": "SHOPPING" | "DINING" | "KID_ACTIVITY" | "CUSTOM",
  "people_involved": ["Marcus", "Dad"],
  "line_items": [
    {
      "name": "Item or service name",
      "quantity": 1.0,
      "total_price": 0.00,
      "category": "groceries" | "dining" | "services" | "general"
    }
  ]
}
"""


class EmailEventGenerator:
    """Orchestrates Gmail reading and event generation:
    1. Sends email snippet/body to LLM for perception & extraction into standard JSON.
    2. Writes standard JSON to data/receipts_inbox/{event_id}.json (deduplicated by message/event ID).
    3. Triggers ReceiptParser to deterministically parse and ingest the standard JSON into the ledger.
    """

    def __init__(
        self,
        event_manager: EventManager,
        receipt_parser: Optional[ReceiptParser] = None,
        place_repo: Optional[PlaceRepository] = None,
        cas_storage: Optional[CASStorage] = None,
        gen_run_repo: Optional[GeneratorRunRepository] = None,
        receipt_service: Optional[ReceiptService] = None,
        inbox_dir: Optional[Path] = None,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None,
    ):
        self.event_manager = event_manager
        self.receipt_parser = receipt_parser or ReceiptParser()
        self.place_repo = place_repo or getattr(event_manager, "place_repo", None) or PlaceRepository(event_manager.repo.conn)
        self.cas = cas_storage or CASStorage()
        self.gen_run_repo = gen_run_repo or GeneratorRunRepository(event_manager.repo.conn)
        
        # Core domain receipt engine
        if receipt_service:
            self.receipt_service = receipt_service
        elif hasattr(event_manager, "repo") and hasattr(event_manager.repo, "conn") and event_manager.repo.conn:
            conn = event_manager.repo.conn
            inv_service = InventoryService(InventoryRepository(conn))
            self.receipt_service = ReceiptService(conn=conn, inventory_service=inv_service)
        else:
            self.receipt_service = None

        self.inbox_dir = inbox_dir or RECEIPTS_INBOX_DIR
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_file = credentials_file or settings.gmail_credentials_file
        self.token_file = token_file or settings.gmail_token_file
        self._gmail_service = None

    def get_effective_system_prompt(self) -> str:
        """Assemble base system prompt with dynamically injected learned user feedback rules."""
        prompt = EXTRACTION_SYSTEM_PROMPT
        try:
            if self.gen_run_repo:
                rules = self.gen_run_repo.list_learned_rules(
                    generator_type="EMAIL_EVENT_GENERATOR", only_active=True
                )
                if rules:
                    rules_text = "\n".join(f"- {r.prompt_instruction}" for r in rules)
                    prompt += (
                        f"\n\nADDITIONAL USER CORRECTIONS & LEARNED RULES (MANDATORY TO FOLLOW):\n{rules_text}\n"
                    )
        except Exception as e:
            logger.warning(f"Error reading learned prompt rules: {e}")
        return prompt


    def get_gmail_service(self):
        """Lazily initialize and return authenticated Google Gmail API service."""
        if self._gmail_service is not None:
            return self._gmail_service

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not os.path.exists(self.token_file):
            raise FileNotFoundError(
                f"Gmail token file '{self.token_file}' not found. Run scripts/auth_gmail.py to authenticate."
            )

        with open(self.token_file, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        creds = Credentials.from_authorized_user_info(token_data)
        self._gmail_service = build("gmail", "v1", credentials=creds)
        return self._gmail_service

    @staticmethod
    def extract_text_from_html(html_body: str) -> str:
        """Strip HTML markup, scripts, and styling to retrieve clean plain-text."""
        if not html_body:
            return ""
        if "<" not in html_body:
            return html_body.strip()
        soup = BeautifulSoup(html_body, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
        return "\n".join(line for line in lines if line)

    def extract_event_via_llm(self, email_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send email subject, sender, date, and text to LLM to produce a standardized event JSON."""
        subject = email_data.get("subject", "")
        sender = email_data.get("from", "")
        date_str = email_data.get("date", "")
        snippet = email_data.get("snippet", "")
        html_body = email_data.get("body", "")

        extracted_body = self.extract_text_from_html(html_body)
        # Use extracted body if substantial, otherwise fallback to snippet
        body_text = extracted_body if len(extracted_body) > len(snippet) else snippet
        truncated_body = body_text[:1500] if body_text else snippet

        user_prompt = f"""Analyze this email and return the JSON schema:
Subject: {subject}
From: {sender}
Date: {date_str}
Snippet: {snippet}
Email Text:
{truncated_body}
"""
        for attempt in range(2):
            try:
                raw_resp = call_llm(
                    prompt=user_prompt,
                    system_prompt=self.get_effective_system_prompt(),
                    model="gemma3:latest",
                    json_mode=False,
                    timeout=45,
                )
                clean_resp = raw_resp.strip()
                if "```json" in clean_resp:
                    clean_resp = clean_resp.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_resp:
                    clean_resp = clean_resp.split("```")[1].split("```")[0].strip()
                else:
                    # Find outermost curly braces
                    start_idx = clean_resp.find("{")
                    end_idx = clean_resp.rfind("}")
                    if start_idx != -1 and end_idx != -1:
                        clean_resp = clean_resp[start_idx : end_idx + 1]

                try:
                    parsed_json = json.loads(clean_resp, strict=False)
                except Exception:
                    # Clean up common small LLM formatting quirks
                    fixed = re.sub(r",\s*([}\]])", r"\1", clean_resp)
                    parsed_json = json.loads(fixed, strict=False)

                if parsed_json and any(k in parsed_json for k in ["category", "is_event"]):
                    return parsed_json
            except Exception as err:
                logger.warning(f"LLM extraction attempt {attempt+1} failed for email '{subject}' ({err})")
        return None

    def store_receipt_json(self, event_id: str, payload: Dict[str, Any]) -> Path:
        """Save standard JSON in receipts_inbox/{event_id}.json for auditability and deduplication."""
        file_path = self.inbox_dir / f"{event_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return file_path

    @classmethod
    def is_subject_relevant(cls, subject: str, sender: str = "") -> bool:
        """Pre-filter subjects to focus on receipts, bill paying, and facility/community schedules."""
        s = subject.lower()
        combined = f"{subject} {sender}".lower()
        for exc in SUBJECT_EXCLUDE_PATTERNS:
            if re.search(exc, s):
                return False
        for inc in SUBJECT_INCLUDE_PATTERNS:
            if re.search(inc, combined):
                return True
        return False

    def resolve_or_create_place(self, facility_name: str, address: Optional[str] = None) -> Place:
        """Resolve a facility or merchant string into a grounded physical Place entity."""
        from uuid import uuid4
        clean_name = (facility_name or "").strip()
        name_lower = clean_name.lower()

        # 1. Direct name lookup in places table
        existing = self.place_repo.find_by_name(clean_name)
        if existing:
            return existing

        # 2. Known merchants lookup (e.g. YMCA, Costco, Primrose, Lowe's)
        for key, info in KNOWN_MERCHANTS.items():
            if key in name_lower:
                known_place = self.place_repo.get_place(info["place_id"])
                if known_place:
                    return known_place
                created = Place(
                    id=info["place_id"],
                    name=info["name"],
                    category=info.get("category", "facility"),
                    address=info.get("address", address or "Cranberry Twp, PA"),
                )
                return self.place_repo.create_place(created)

        # 3. Substring match in existing places
        candidates = self.place_repo.list_places(search=clean_name[:10])
        for cand in candidates:
            if clean_name.lower() in cand.name.lower() or cand.name.lower() in clean_name.lower():
                return cand

        # 4. If not found, dynamically create and ground a new Place in SQLite
        new_place = Place(
            id=f"pl_{uuid4().hex[:8]}",
            name=clean_name or "Local Facility",
            category="facility",
            address=address or "",
        )
        return self.place_repo.create_place(new_place)

    def process_email_message(
        self, email_data: Dict[str, Any], run_id: Optional[str] = None
    ) -> Optional[LifeEvent]:
        """Process a single email:
        1. Pre-filter subject (must indicate receipt, bill, or facility schedule).
        2. Check idempotency (skip if msg_id already in events table).
        3. Send email to LLM -> return standardized event JSON.
        4. If not an event or SKIP, discard.
        5. Store JSON in data/receipts_inbox/{event_id}.json.
        6. Trigger ReceiptParser to deterministically parse and commit to the database.
        """
        subject = email_data.get("subject", "")
        sender = email_data.get("from", "")

        # 1. Subject relevance filter
        if not self.is_subject_relevant(subject, sender):
            logger.info(f"Subject '{subject}' is not a relevant receipt, bill, or facility schedule. Skipping.")
            return None

        msg_id = email_data.get("id") or f"msg_{datetime.now().timestamp()}"

        # 2. Deduplication check via database natural key
        cursor = self.event_manager.repo.conn.cursor()
        existing = cursor.execute(
            "SELECT id, title FROM events WHERE source_reference_id = ?", (msg_id,)
        ).fetchone()
        if existing:
            logger.info(f"Skipping already ingested email message: {msg_id} ('{existing[1]}')")
            return None

        # 2. Call LLM for perception & structured extraction
        extracted = self.extract_event_via_llm(email_data)
        if not extracted:
            logger.info(f"LLM returned no extraction data for '{email_data.get('subject')}'. Skipping.")
            return None

        cat = str(extracted.get("category") or "SKIP").upper()
        is_event = bool(extracted.get("is_event", False))

        feedback = GeneratorEventFeedback(
            event_id=None,
            run_id=run_id,
            source_reference_id=msg_id,
            email_subject=subject,
            email_from=sender,
            email_date=email_data.get("date"),
            llm_category=cat,
            llm_reason=extracted.get("reason"),
            raw_json=json.dumps(extracted, ensure_ascii=False),
            user_status="PENDING",
        )

        # Filter out non-events and explicit SKIP categories
        valid_cats = ["RECEIPT", "BILL", "FACILITY", "ACTIVITY", "KID_ACTIVITY", "FACILITY_CLOSURE"]
        if cat == "SKIP" or (not is_event and cat not in valid_cats):
            logger.info(f"Skipping non-event email '{email_data.get('subject')}': {extracted.get('reason')}")
            feedback.user_status = "SKIPPED"
            if self.gen_run_repo:
                try:
                    self.gen_run_repo.create_or_update_feedback(feedback)
                except Exception as e:
                    logger.warning(f"Could not save feedback for skipped email: {e}")
            return None

        # Extract amount with fallback to regex if LLM missed it
        total_amt = float(extracted.get("total_amount") or 0.0)
        if total_amt <= 0.0:
            full_text = f"{email_data.get('subject', '')} {email_data.get('snippet', '')}"
            dollar_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]{2})?)", full_text)
            if dollar_match:
                try:
                    total_amt = float(dollar_match.group(1))
                except Exception:
                    pass

        # Validation: Receipts must have a non-zero amount
        if cat == "RECEIPT" and total_amt <= 0.0:
            logger.info(f"Skipping receipt with no monetary amount: '{email_data.get('subject')}'")
            feedback.user_status = "SKIPPED"
            if self.gen_run_repo:
                try:
                    self.gen_run_repo.create_or_update_feedback(feedback)
                except Exception as e:
                    logger.warning(f"Could not save feedback for skipped receipt: {e}")
            return None


        merchant_name = extracted.get("merchant_name") or "General Merchant"
        if not merchant_name or merchant_name.lower() in ["none", "n/a", "unknown"]:
            merchant_name = email_data.get("from", "").split("<")[0].strip().strip('"') or "General Merchant"

        # 3. Generate deterministic event_id
        clean_event_id = f"evt_{hashlib.sha256(msg_id.encode('utf-8')).hexdigest()[:8]}"

        # Standardize event_type & kid activity classification
        is_kid_activity = (
            cat in ["ACTIVITY", "KID_ACTIVITY"]
            or extracted.get("event_type") == "KID_ACTIVITY"
            or any(w in subject.lower() for w in ["kids workshop", "workshop", "swim lesson", "kid activity", "kids club"])
        )
        if is_kid_activity:
            cat = "KID_ACTIVITY"
            extracted_event_type = "KID_ACTIVITY"
        else:
            extracted_event_type = extracted.get("event_type") or ("SHOPPING" if cat == "RECEIPT" else "CUSTOM")

        title = extracted.get("event_title")
        if not title or title.lower() in ["null", "none"]:
            if cat == "BILL":
                title = f"Pay Bill: {merchant_name}"
            else:
                title = f"{cat.title()}: {merchant_name}"
            if total_amt > 0:
                title += f" (${total_amt:.2f})"

        people = extracted.get("people_involved") or []
        if is_kid_activity and "Marcus" not in people:
            people = ["Marcus", "Dad"]
        elif not people:
            people = ["Dad"]

        # Standardize payload fields for ReceiptParser
        payload = {
            "event_id": clean_event_id,
            "source_reference_id": msg_id,
            "source_channel": "EMAIL_BODY",
            "category": cat,
            "is_autopay": bool(extracted.get("is_autopay", False)),
            "merchant_name": merchant_name,
            "facility_name": extracted.get("facility_name") or merchant_name,
            "closure_start": extracted.get("closure_start"),
            "closure_end": extracted.get("closure_end"),
            "merchant_address": extracted.get("merchant_address") or "",
            "transaction_time": extracted.get("transaction_time") or datetime.now().isoformat(),
            "due_date": extracted.get("due_date"),
            "total_amount": total_amt,
            "tax_amount": float(extracted.get("tax_amount") or 0.0),
            "tip_amount": float(extracted.get("tip_amount") or 0.0),
            "event_title": title,
            "event_type": extracted_event_type,
            "people_involved": people,
            "line_items": extracted.get("line_items") or [],
            "email_subject": email_data.get("subject", ""),
            "email_from": email_data.get("from", ""),
            "email_date": email_data.get("date", ""),
        }

        # 4. Store JSON in data/receipts_inbox/{event_id}.json (deduped by key)
        json_file_path = self.store_receipt_json(clean_event_id, payload)
        file_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

        # BRANCH 1: Facility / Resource Closure (e.g. YMCA Thanksgiving Closure)
        if cat in ["FACILITY_CLOSURE", "CLOSURE"] or any(k in subject.lower() for k in ["closure", "closed"]):
            closure_start_str = payload.get("closure_start") or payload.get("due_date") or payload.get("transaction_time") or datetime.now().isoformat()
            closure_end_str = payload.get("closure_end") or payload.get("due_date") or closure_start_str
            try:
                cl_start = datetime.fromisoformat(closure_start_str)
            except Exception:
                cl_start = datetime.now()
            try:
                cl_end = datetime.fromisoformat(closure_end_str)
            except Exception:
                cl_end = cl_start.replace(hour=23, minute=59, second=59)

            facility_name = payload.get("facility_name") or merchant_name
            # Ground the facility string into a first-class Place entity
            place = self.resolve_or_create_place(facility_name, payload.get("merchant_address"))

            closure = ResourceClosure(
                id=f"cls_{clean_event_id.replace('evt_', '')}",
                resource_id=place.id,
                resource_name=place.name,
                start_time=cl_start,
                end_time=cl_end,
                reason=extracted.get("reason") or extracted.get("event_title") or subject,
                source="AGENT_GMAIL",
                source_reference_id=msg_id,
            )
            self.place_repo.create_closure(closure)
            feedback.event_id = closure.id
            if self.gen_run_repo:
                try:
                    self.gen_run_repo.create_or_update_feedback(feedback)
                except Exception as e:
                    logger.warning(f"Could not save feedback for closure: {e}")

            # Immediately synchronize conflict state across all calendar events
            try:
                self.event_manager.evaluate_all_conflicts(persist_sync=True)
            except Exception as ex:
                logger.warning(f"Could not sync conflicts after recording closure: {ex}")

            logger.info(f"Recorded resource closure for Place '{place.name}' ({place.id}): {cl_start} to {cl_end} ({closure.reason})")
            return None

        # BRANCH 2: Bills (Check Auto-Pay setup)
        if cat == "BILL":
            full_text = f"{subject} {email_data.get('snippet', '')} {email_data.get('body', '')}".lower()
            is_autopay = payload.get("is_autopay") or bool(
                re.search(r"\b(auto-?pay|automatic payment|automatically (debited|deducted|charged)|scheduled for auto)\b", full_text)
            )
            if is_autopay:
                logger.info(f"Bill '{subject}' has auto-pay setup. Skipping event generation.")
                feedback.user_status = "AUTOPAY_SKIPPED"
                if self.gen_run_repo:
                    try:
                        self.gen_run_repo.create_or_update_feedback(feedback)
                    except Exception as e:
                        logger.warning(f"Could not save feedback for autopay bill: {e}")
                return None

            # No auto-pay: start time and end time is email received time, and deadline is bill due date
            received_dt = datetime.now()
            if email_data.get("date"):
                try:
                    received_dt = email.utils.parsedate_to_datetime(email_data["date"])
                    if received_dt.tzinfo is not None:
                        received_dt = received_dt.astimezone().replace(tzinfo=None)
                except Exception:
                    received_dt = datetime.now()

            due_dt = None
            if payload.get("due_date"):
                try:
                    due_dt = datetime.fromisoformat(payload["due_date"])
                except Exception:
                    due_dt = None

            event = LifeEvent(
                id=clean_event_id,
                title=payload["event_title"],
                event_type="CUSTOM",
                scheduled_at=received_dt,
                scheduled_end_at=received_dt,
                deadline=due_dt,
                completed_at=None,
                people_involved=payload["people_involved"],
                notes=f"Bill payment action required (No auto-pay).\nDue by: {due_dt}\nReceipt JSON: {json_file_path}",
                source="AGENT_GMAIL",
                source_reference_id=msg_id,
            )
            saved = self.event_manager.repo.create_event(event)
            feedback.event_id = saved.id
            if self.gen_run_repo:
                try:
                    self.gen_run_repo.create_or_update_feedback(feedback)
                except Exception as e:
                    logger.warning(f"Could not save feedback for manual bill: {e}")
            logger.info(f"Committed manual bill payment event '{saved.title}' ({saved.id}) with deadline {saved.deadline}")
            return saved

        # BRANCH 3: Receipts and Activities
        # 5. Trigger ReceiptParser to deterministically parse the JSON (zero LLM calls inside parser)
        std_receipt = self.receipt_parser.parse_from_json(
            json_data=payload,
            file_hash=file_hash,
            file_path=str(json_file_path),
            original_filename=f"{clean_event_id}.json",
            source_channel="EMAIL_BODY",
        )

        # 6. Build and commit LifeEvent to the database via EventManager
        tx_dt = std_receipt.transaction_time or datetime.now()
        due_dt = None
        if payload.get("due_date"):
            try:
                due_dt = datetime.fromisoformat(payload["due_date"])
            except Exception:
                due_dt = None

        is_completed = (cat == "RECEIPT")
        if is_kid_activity:
            sched_dt = tx_dt
            sched_end = tx_dt + timedelta(minutes=60)
            comp_dt = None
        else:
            sched_dt = tx_dt if is_completed else (due_dt or tx_dt)
            sched_end = sched_dt
            comp_dt = tx_dt if is_completed else None

        event = LifeEvent(
            id=clean_event_id,
            title=payload["event_title"],
            event_type=payload["event_type"],
            scheduled_at=sched_dt,
            scheduled_end_at=sched_end,
            deadline=due_dt,
            completed_at=comp_dt,
            place_id=std_receipt.place_id,
            people_involved=payload["people_involved"],
            tax_amount=std_receipt.tax_amount,
            notes=f"Ingested from email '{email_data.get('subject')}' ({email_data.get('from')})\nReceipt JSON: {json_file_path}",
            source="AGENT_GMAIL",
            source_reference_id=msg_id,
        )

        if payload["event_type"] == "SHOPPING":
            event.shopping_detail = ShoppingDetail(
                event_id=event.id,
                total_amount=std_receipt.total_amount,
                pantry_updated=False,
            )
        elif payload["event_type"] == "DINING":
            event.dining_detail = DiningDetail(
                event_id=event.id,
                total_amount=std_receipt.total_amount,
            )

        saved = self.event_manager.repo.create_event(event)

        # 7. Directly persist to receipts table and restock pantry via ReceiptService
        if cat == "RECEIPT" and self.receipt_service:
            try:
                std_receipt.event_id = saved.id
                self.receipt_service.persist_receipt(std_receipt, auto_restock=True)
                if event.shopping_detail:
                    event.shopping_detail.pantry_updated = True
            except Exception as ex:
                logger.warning(f"Could not persist receipt or restock pantry: {ex}")

        feedback.event_id = saved.id
        if self.gen_run_repo:
            try:
                self.gen_run_repo.create_or_update_feedback(feedback)
            except Exception as e:
                logger.warning(f"Could not save feedback for event: {e}")
        logger.info(f"Committed event '{saved.title}' ({saved.id}) from receipt JSON {json_file_path}")
        return saved


    def sync_recent_emails(
        self,
        max_results: int = 25,
        query: str = "receipt OR order OR bill OR payment OR invoice OR YMCA OR workshop",
        run_id: Optional[str] = None,
    ) -> List[LifeEvent]:
        """Fetch emails from live Gmail API, process via LLM -> receipt JSON -> ReceiptParser."""
        run = None
        if self.gen_run_repo:
            if run_id:
                run = self.gen_run_repo.get_run(run_id)
            if not run:
                run = GeneratorRun(
                    generator_type="EMAIL_EVENT_GENERATOR",
                    started_at=datetime.now(),
                    status="RUNNING",
                    details_json=json.dumps({"query": query, "max_results": max_results}),
                )
                self.gen_run_repo.create_run(run)

        generated_events: List[LifeEvent] = []
        try:
            service = self.get_gmail_service()
            logger.info(f"Scanning Gmail with query: '{query}', max_results={max_results}")

            res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            messages = res.get("messages", [])
            logger.info(f"Found {len(messages)} matching email messages in Gmail inbox.")

            for m in messages:
                msg = service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()

                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                subject = headers.get("Subject", "")
                sender = headers.get("From", "")
                date_str = headers.get("Date", "")

                # Extract body text from parts
                body_text = ""
                payload = msg.get("payload", {})
                parts = payload.get("parts", [])
                if not parts and "body" in payload:
                    body_text = payload["body"].get("data", "")
                else:
                    for part in parts:
                        if part.get("mimeType") in ["text/plain", "text/html"]:
                            body_text = part.get("body", {}).get("data", "")
                            if body_text:
                                break

                import base64
                decoded_body = ""
                if body_text:
                    try:
                        decoded_body = base64.urlsafe_b64decode(body_text.encode("utf-8")).decode("utf-8", errors="ignore")
                    except Exception:
                        decoded_body = msg.get("snippet", "")
                else:
                    decoded_body = msg.get("snippet", "")

                email_dict = {
                    "id": m["id"],
                    "subject": subject,
                    "from": sender,
                    "date": date_str,
                    "body": decoded_body,
                    "snippet": msg.get("snippet", ""),
                }

                created_event = self.process_email_message(email_dict, run_id=run.id if run else None)
                if created_event:
                    generated_events.append(created_event)

            if run and self.gen_run_repo:
                run.status = "SUCCESS"
                run.scanned_count = len(messages)
                run.created_count = len(generated_events)
                run.completed_at = datetime.now()
                self.gen_run_repo.update_run(run)

        except Exception as e:
            if run and self.gen_run_repo:
                run.status = "FAILED"
                run.error_message = str(e)
                run.completed_at = datetime.now()
                self.gen_run_repo.update_run(run)
            raise

        return generated_events

