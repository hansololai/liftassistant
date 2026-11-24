"""School Menu Service.
Checks weekly lunch menus from Primrose School (via Gmail email bodies or PDF attachments),
uses LLM with dietary restriction prompts (chicken/meatballs -> switch to Sun Butter and Jelly),
and creates actionable LifeEvent reminders grounded to Primrose School of Wexford.
"""

from datetime import date, datetime, timedelta
import email.utils
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4
from bs4 import BeautifulSoup

from liftassistant.config import settings
from liftassistant.db.repository import EventRepository, GeneratorRunRepository, PlaceRepository
from liftassistant.llm import call_llm
from liftassistant.models.domain import GeneratorEventFeedback, GeneratorRun, LifeEvent, Place

logger = logging.getLogger(__name__)

# Primrose Grounded Place details
PRIMROSE_PLACE_ID = "pl_primrose"
PRIMROSE_PLACE_NAME = "Primrose School of Wexford"
PRIMROSE_PLACE_ADDRESS = "2598 Wexford Bayne Rd, Sewickley, PA 15143"
PRIMROSE_PLACE_CATEGORY = "education"


class SchoolMenuService:
    """Core domain engine for school lunch menu inspection and meal switch reminders."""

    def __init__(
        self,
        event_repo: EventRepository,
        place_repo: PlaceRepository,
        gen_run_repo: GeneratorRunRepository,
        token_file: Optional[str] = None,
        prompt_path: Optional[Path] = None,
        llm_caller: Optional[Callable[..., str]] = None,
    ):
        self.event_repo = event_repo
        self.place_repo = place_repo
        self.gen_run_repo = gen_run_repo
        self.token_file = token_file or getattr(settings, "effective_gmail_token_file", settings.gmail_token_file)
        self.prompt_path = prompt_path or (Path("prompts") / "school_lunch_menu.txt")
        self._llm_caller = llm_caller or call_llm
        self._gmail_service = None

    def get_gmail_service(self):
        """Lazily initialize authenticated Google Gmail API service."""
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
        """Strip HTML tags and styling to get clean plain text."""
        if not html_body:
            return ""
        if "<" not in html_body:
            return html_body.strip()
        soup = BeautifulSoup(html_body, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
        """Extract plain text from PDF bytes using PyMuPDF (fitz)."""
        if not pdf_bytes:
            return ""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_text = [page.get_text() for page in doc]
            return "\n".join(pages_text).strip()
        except Exception as exc:
            logger.warning("Failed to extract text from PDF attachment: %s", exc)
            return ""

    def load_prompt_template(self) -> str:
        """Load refined dietary prompt template."""
        if self.prompt_path and self.prompt_path.exists():
            try:
                with open(self.prompt_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning("Failed to read prompt file %s: %s", self.prompt_path, e)

        # Fallback template
        return """You are a dietary assistant monitoring a school lunch menu for a child who cannot eat chicken or meatballs.
MEAL EXTRACTION RULES:
1. ONLY generate a reminder if the lunch entrée contains "chicken" or "meatball" / "meatballs".
2. DO NOT generate reminders for any other meals (e.g., skip pizza, mac and cheese, grilled cheese, turkey, veggies, snacks).
3. MENU STRUCTURE & DAY ALIGNMENT: Each weekday heading ("Monday", "Tuesday", etc.) comes BEFORE its meals.
4. DATE CALCULATION: Calculate exact date (YYYY-MM-DD) starting from Monday's date in heading:
   - Monday = Week start date, Tuesday = +1, Wednesday = +2, Thursday = +3, Friday = +4.

OUTPUT FORMAT:
Respond with JSON object containing an "events" list:
{
  "events": [
    {
      "title": "Primrose Lunch: Switch to Sun Butter and Jelly Sandwich (Entrée name)",
      "description": "Day lunch serves Entrée name.",
      "due_date": "YYYY-MM-DD",
      "priority": "Medium",
      "source_citation": "Verbatim entrée text from menu"
    }
  ]
}
If no meals match chicken or meatballs, return: {"events": []}

{data}
"""

    def parse_menu_content(self, menu_text: str, reference_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Send menu text to LLM using prompt template to extract chicken/meatball meal reminders."""
        template = self.load_prompt_template()
        header_info = ""
        if reference_date:
            header_info = f"[Reference Date Context: {reference_date}]\n"

        full_prompt = template.replace("{data}", f"{header_info}{menu_text}")

        system_instruction = (
            "You are a dietary assistant extracting school lunch switch reminders from menus. "
            "Only generate reminders for days serving chicken or meatballs."
        )

        try:
            raw_resp = self._llm_caller(
                prompt=full_prompt,
                system_prompt=system_instruction,
                json_mode=True,
                timeout=60,
            )
            return self._extract_events_from_response(raw_resp)
        except Exception as exc:
            logger.error("LLM school menu extraction failed: %s", exc)
            return []

    @staticmethod
    def _extract_events_from_response(raw_resp: str) -> List[Dict[str, Any]]:
        """Parse JSON response from LLM."""
        if not raw_resp:
            return []

        clean = raw_resp.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        else:
            start_brace = clean.find("{")
            start_bracket = clean.find("[")
            if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
                end_brace = clean.rfind("}")
                if end_brace != -1:
                    clean = clean[start_brace : end_brace + 1]
            elif start_bracket != -1:
                end_bracket = clean.rfind("]")
                if end_bracket != -1:
                    clean = clean[start_bracket : end_bracket + 1]

        try:
            data = json.loads(clean)
        except Exception:
            fixed = re.sub(r",\s*([}\]])", r"\1", clean)
            try:
                data = json.loads(fixed)
            except Exception:
                return []

        if isinstance(data, dict):
            return data.get("events", [])
        elif isinstance(data, list):
            return data
        return []

    def ensure_primrose_place(self) -> Place:
        """Resolve or initialize grounded Place entity for Primrose School."""
        existing = self.place_repo.get_place(PRIMROSE_PLACE_ID)
        if existing:
            return existing

        created = Place(
            id=PRIMROSE_PLACE_ID,
            name=PRIMROSE_PLACE_NAME,
            category=PRIMROSE_PLACE_CATEGORY,
            address=PRIMROSE_PLACE_ADDRESS,
        )
        return self.place_repo.create_place(created)

    def create_switch_reminders(
        self,
        events_data: List[Dict[str, Any]],
        email_info: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> List[LifeEvent]:
        """Ingest extracted lunch switch reminders into the LifeEvent ledger with deduplication."""
        self.ensure_primrose_place()
        created_events: List[LifeEvent] = []

        email_subj = (email_info or {}).get("subject", "Primrose Weekly Menu")
        email_from = (email_info or {}).get("from", "Primrose School of Wexford")
        email_date = (email_info or {}).get("date", datetime.now().isoformat())

        cursor = self.event_repo.conn.cursor()

        for item in events_data:
            raw_due = str(item.get("due_date", "")).strip()[:10]
            try:
                due_d = date.fromisoformat(raw_due)
            except Exception:
                logger.warning("Invalid due_date '%s' in LLM menu output: skipping", raw_due)
                continue

            dedup_hash = f"primrose_lunch:{due_d.isoformat()}"

            # Check for existing event with this dedup_hash or matching date at Primrose
            existing = cursor.execute(
                "SELECT id, title FROM events WHERE source_reference_id = ? OR (place_id = ? AND date(scheduled_at) = ?)",
                (dedup_hash, PRIMROSE_PLACE_ID, due_d.isoformat()),
            ).fetchone()

            if existing:
                ex_id = existing["id"] if isinstance(existing, dict) or hasattr(existing, "__getitem__") else existing[0]
                logger.info("Reminder already exists on %s (ID: %s); skipping duplicate creation.", due_d, ex_id)

                # Record existing feedback audit
                feedback = GeneratorEventFeedback(
                    event_id=ex_id,
                    run_id=run_id,
                    source_reference_id=dedup_hash,
                    email_subject=email_subj,
                    email_from=email_from,
                    email_date=email_date,
                    llm_category="EXISTING",
                    llm_reason=f"Lunch switch reminder already exists on {due_d}.",
                    user_status="EXISTING",
                )
                self.gen_run_repo.create_or_update_feedback(feedback)
                continue

            # Target morning drop-off schedule: 8:00 AM - 8:30 AM with 9:00 AM deadline
            sched_at = datetime.combine(due_d, datetime.min.time()).replace(hour=8, minute=0)
            sched_end = datetime.combine(due_d, datetime.min.time()).replace(hour=8, minute=30)
            deadline_at = datetime.combine(due_d, datetime.min.time()).replace(hour=9, minute=0)

            title = item.get("title") or "Primrose Lunch: Switch to Sun Butter and Jelly Sandwich"
            description = item.get("description", "")
            citation = item.get("source_citation", "")
            notes = f"{description}" + (f" (Citation: {citation})" if citation else "")

            new_event = LifeEvent(
                id=f"evt_lunch_{uuid4().hex[:8]}",
                title=title,
                event_type="KID_ACTIVITY",
                scheduled_at=sched_at,
                scheduled_end_at=sched_end,
                deadline=deadline_at,
                place_id=PRIMROSE_PLACE_ID,
                people_involved=["Marcus", "Dad"],
                source="AGENT_GMAIL",
                source_reference_id=dedup_hash,
                notes=notes,
                generator_run_id=run_id,
            )

            saved = self.event_repo.create_event(new_event)
            created_events.append(saved)

            # Record feedback review row for UI review
            feedback = GeneratorEventFeedback(
                event_id=saved.id,
                run_id=run_id,
                source_reference_id=dedup_hash,
                email_subject=email_subj,
                email_from=email_from,
                email_date=email_date,
                llm_category="SCHOOL_LUNCH",
                llm_reason=citation or description or "Chicken or meatball entrée on menu; reminder to switch to Sun Butter and Jelly.",
                raw_json=json.dumps(item),
                user_status="PENDING",
                event_title=title,
                event_type="KID_ACTIVITY",
                scheduled_at=sched_at,
                deadline=deadline_at,
            )
            self.gen_run_repo.create_or_update_feedback(feedback)
            logger.info("Created school lunch switch reminder: '%s' on %s", title, due_d)

        return created_events

    def process_raw_menu_text(
        self,
        raw_text: str,
        reference_date: Optional[str] = None,
        run_id: Optional[str] = None,
        source_label: str = "Direct Menu Ingestion",
    ) -> List[LifeEvent]:
        """Directly parse menu text or PDF string and create events."""
        events_data = self.parse_menu_content(raw_text, reference_date=reference_date)
        email_info = {
            "subject": source_label,
            "from": PRIMROSE_PLACE_NAME,
            "date": reference_date or datetime.now().isoformat(),
        }
        return self.create_switch_reminders(events_data, email_info=email_info, run_id=run_id)

    def process_menu_email(
        self,
        email_data: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> List[LifeEvent]:
        """Extract menu from a single email dictionary (body + optional PDF attachment)."""
        subject = email_data.get("subject", "")
        sender = email_data.get("from", "")
        date_str = email_data.get("date", "")
        snippet = email_data.get("snippet", "")
        html_body = email_data.get("body", "")

        extracted_body = self.extract_text_from_html(html_body)
        body_text = extracted_body if len(extracted_body) > len(snippet) else snippet

        pdf_texts = []
        for att in email_data.get("attachments", []):
            att_bytes = att.get("bytes")
            if att_bytes:
                pdf_t = self.extract_text_from_pdf_bytes(att_bytes)
                if pdf_t:
                    pdf_texts.append(pdf_t)
            elif att.get("text"):
                pdf_texts.append(att.get("text"))

        combined_text = f"Subject: {subject}\nFrom: {sender}\nDate: {date_str}\n\n{body_text}"
        if pdf_texts:
            combined_text += "\n\n[Attached Menu PDF Content]:\n" + "\n---\n".join(pdf_texts)

        events_data = self.parse_menu_content(combined_text, reference_date=date_str)
        email_info = {
            "subject": subject,
            "from": sender,
            "date": date_str,
        }
        return self.create_switch_reminders(events_data, email_info=email_info, run_id=run_id)

    def sync_recent_menus(
        self,
        max_results: int = 10,
        query: str = "from:(procaresoftware.com OR primrose) OR subject:(menu OR lunch OR primrose)",
        run_id: Optional[str] = None,
    ) -> List[LifeEvent]:
        """Scan Gmail API for recent Primrose emails/PDFs, extract menus, and generate switch reminders."""
        import base64

        run = None
        if self.gen_run_repo and run_id:
            run = self.gen_run_repo.get_run(run_id)

        all_created: List[LifeEvent] = []
        scanned_count = 0

        try:
            service = self.get_gmail_service()
            logger.info("Scanning Gmail for school menus with query: '%s', max_results=%d", query, max_results)

            res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            messages = res.get("messages", [])
            logger.info("Found %d matching messages in Gmail.", len(messages))

            for m in messages:
                scanned_count += 1
                msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                subject = headers.get("Subject", "")
                sender = headers.get("From", "")
                date_str = headers.get("Date", "")

                # Fast filter: sender or subject should relate to primrose, menu, or lunch
                s_lower = f"{subject} {sender}".lower()
                if not any(k in s_lower for k in ["primrose", "procare", "menu", "lunch"]):
                    continue

                # Extract body
                body_text = ""
                payload = msg.get("payload", {})
                parts = payload.get("parts", [])
                pdf_attachments = []

                def _extract_parts(part_list):
                    nonlocal body_text
                    for p in part_list:
                        m_type = p.get("mimeType", "")
                        if m_type in ["text/plain", "text/html"] and not body_text:
                            data = p.get("body", {}).get("data", "")
                            if data:
                                try:
                                    body_text = base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                        elif "pdf" in m_type or (p.get("filename", "").lower().endswith(".pdf")):
                            att_id = p.get("body", {}).get("attachmentId")
                            if att_id:
                                try:
                                    att_res = service.users().messages().attachments().get(
                                        userId="me", messageId=m["id"], id=att_id
                                    ).execute()
                                    att_b64 = att_res.get("data", "")
                                    if att_b64:
                                        pdf_bytes = base64.urlsafe_b64decode(att_b64.encode("utf-8"))
                                        pdf_attachments.append({"bytes": pdf_bytes, "filename": p.get("filename", "")})
                                except Exception as att_err:
                                    logger.warning("Failed to fetch attachment %s: %s", att_id, att_err)
                        if "parts" in p:
                            _extract_parts(p["parts"])

                if parts:
                    _extract_parts(parts)
                elif "body" in payload and payload["body"].get("data"):
                    try:
                        body_text = base64.urlsafe_b64decode(payload["body"]["data"].encode("utf-8")).decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                email_dict = {
                    "id": m["id"],
                    "subject": subject,
                    "from": sender,
                    "date": date_str,
                    "snippet": msg.get("snippet", ""),
                    "body": body_text or msg.get("snippet", ""),
                    "attachments": pdf_attachments,
                }

                created = self.process_menu_email(email_dict, run_id=run_id)
                all_created.extend(created)

        except Exception as exc:
            logger.error("Error during school menu Gmail sync: %s", exc)
            if run:
                run.status = "FAILED"
                run.error_message = str(exc)
                self.gen_run_repo.update_run(run)
            raise

        if run:
            run.scanned_count = scanned_count
            run.created_count = len(all_created)
            self.gen_run_repo.update_run(run)

        return all_created
