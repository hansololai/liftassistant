"""Test suite for Email Worker, Run Tracking, Event Review Feedback & Iterative Prompt Learning."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3

from liftassistant.db.connection import init_db
from liftassistant.db.repository import (
    EventRepository,
    GeneratorRunRepository,
    PlaceRepository,
)
from liftassistant.models.domain import (
    GeneratorEventFeedback,
    GeneratorRun,
    LearnedPromptRule,
    LifeEvent,
    ShoppingDetail,
)
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.email_event_generator import (
    EXTRACTION_SYSTEM_PROMPT,
    EmailEventGenerator,
)
from liftassistant.services.email_worker import EmailWorker
from liftassistant.services.event_manager import EventManager
from liftassistant.services.receipt_parser import ReceiptParser


def test_worker_and_feedback_flow():
    # 1. Setup in-memory SQLite database
    db_path = Path("data") / "test_feedback_loop.db"
    if db_path.exists():
        db_path.unlink()

    init_db(db_path=db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    place_repo = PlaceRepository(conn)
    event_repo = EventRepository(conn)
    gen_run_repo = GeneratorRunRepository(conn)
    conflict_engine = ConflictEngine(place_repo=place_repo)
    event_manager = EventManager(event_repo=event_repo, conflict_engine=conflict_engine, place_repo=place_repo)

    # 2. Verify run creation and listing
    run = GeneratorRun(
        generator_type="EMAIL_EVENT_GENERATOR",
        started_at=datetime.now(),
        status="RUNNING",
    )
    gen_run_repo.create_run(run)
    assert run.id is not None

    runs = gen_run_repo.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "RUNNING"
    print("PASS: GeneratorRun tracked successfully in database.")

    # 3. Simulate an email generated event and its audit feedback
    test_event_id = "evt_test_ad123"
    event = LifeEvent(
        id=test_event_id,
        title="Hulu Subscription: $4.99/mo",
        event_type="SHOPPING",
        scheduled_at=datetime.now(),
        notes="Generated from email",
        source="AGENT_GMAIL",
        source_reference_id="msg_hulu_ad",
    )
    event.shopping_detail = ShoppingDetail(event_id=test_event_id, total_amount=4.99)
    event_repo.create_event(event)

    feedback = GeneratorEventFeedback(
        id="fb_test1",
        event_id=test_event_id,
        run_id=run.id,
        source_reference_id="msg_hulu_ad",
        email_subject="Watch The Remarried Empress on Hulu for $4.99",
        email_from="Hulu <no-reply@hulu.com>",
        email_date="Sun, 15 Feb 2026 10:00:00 GMT",
        llm_category="RECEIPT",
        llm_reason="Extracted $4.99 purchase transaction.",
        raw_json=json.dumps({"category": "RECEIPT", "total_amount": 4.99}),
        user_status="PENDING",
    )
    gen_run_repo.create_or_update_feedback(feedback)

    feedbacks = gen_run_repo.list_feedbacks()
    assert len(feedbacks) == 1
    assert feedbacks[0].event_id == test_event_id
    assert feedbacks[0].llm_reason == "Extracted $4.99 purchase transaction."
    assert feedbacks[0].event_title == "Hulu Subscription: $4.99/mo"
    print("PASS: GeneratorEventFeedback correctly joined with LifeEvent details and AI reasoning.")

    # 4. User reviews and removes incorrect event with feedback reason
    user_reason = "This was a promotional streaming ad offering $4.99/mo, not an actual completed purchase."
    # Simulate API feedback submission
    event_repo.delete_event(test_event_id)
    gen_run_repo.update_feedback_status(test_event_id, status="REMOVED", user_reason=user_reason)

    # Check event was removed from events table
    deleted_evt = event_repo.get_event(test_event_id)
    assert deleted_evt is None, "Incorrect event should be deleted from ledger"
    print("PASS: Incorrect event removed cleanly from ledger.")

    # 5. Synthesize learned prompt rule
    prompt_instruction = f"USER CORRECTION: '{user_reason}'. Do not generate events or receipts for promotional streaming ads."
    rule = LearnedPromptRule(
        generator_type="EMAIL_EVENT_GENERATOR",
        rule_type="NEGATIVE",
        user_feedback=user_reason,
        prompt_instruction=prompt_instruction,
        is_active=True,
    )
    gen_run_repo.add_learned_rule(rule)

    rules = gen_run_repo.list_learned_rules(only_active=True)
    assert len(rules) == 1
    assert "promotional streaming ads" in rules[0].prompt_instruction
    print(f"PASS: LearnedPromptRule stored: '{rules[0].prompt_instruction}'")

    # 6. Verify EmailEventGenerator injects the learned rule into the prompt
    generator = EmailEventGenerator(
        event_manager=event_manager,
        gen_run_repo=gen_run_repo,
    )
    effective_prompt = generator.get_effective_system_prompt()
    assert "ADDITIONAL USER CORRECTIONS & LEARNED RULES" in effective_prompt
    assert user_reason in effective_prompt
    print("PASS: Dynamic system prompt successfully injects user correction rules!")

    # 7. Complete run
    run.status = "SUCCESS"
    run.scanned_count = 5
    run.created_count = 1
    run.completed_at = datetime.now()
    gen_run_repo.update_run(run)
    updated_run = gen_run_repo.get_run(run.id)
    assert updated_run.status == "SUCCESS"
    assert updated_run.scanned_count == 5
    print("PASS: GeneratorRun updated to SUCCESS with accurate message counts.")

    conn.close()
    from liftassistant.db.connection import close_connection_pool
    close_connection_pool(db_path)
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass

    print("\n================================================")
    print("ALL WORKER & FEEDBACK LOOP TESTS PASSED CLEANLY!")
    print("================================================\n")


if __name__ == "__main__":
    test_worker_and_feedback_flow()
