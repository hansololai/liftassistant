"""Deferred AI Receipt Ingestion Worker.
Enforces Decision 10, 18, 19:
1. Omnichannel pipeline: processes files stored in CAS.
2. Extracts merchant, verified address, financial totals, and line items.
3. Automatic Grocy bulk unit expansion (qu_factor, e.g. 1 Costco pack -> 36 rolls).
4. Deferred location patching on parent LifeEvent.
5. Job tracking and SSE progress broadcast.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from liftassistant.models.domain import ReceiptJob, StandardizedReceipt
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.receipt_parser import ReceiptParser
from liftassistant.services.receipt_service import ReceiptService

logger = logging.getLogger(__name__)


class ReceiptWorker:
    """Background ingestion worker for receipts and invoices."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        cas_storage: CASStorage,
        receipt_parser: ReceiptParser,
        inventory_service: InventoryService,
        receipt_service: Optional[ReceiptService] = None,
    ):
        self.conn = conn
        self.cas = cas_storage
        self.parser = receipt_parser
        self.inv_service = inventory_service
        self.receipt_service = receipt_service or ReceiptService(conn=conn, inventory_service=inventory_service)
        self.jobs: Dict[str, ReceiptJob] = {}
        self.progress_subscribers: List[Callable[[ReceiptJob], None]] = []

    def subscribe_progress(self, callback: Callable[[ReceiptJob], None]) -> None:
        """Register a callback for Server-Sent Events (SSE) or client broadcast."""
        self.progress_subscribers.append(callback)

    def _notify(self, job: ReceiptJob) -> None:
        """Broadcast job status update to all registered subscribers."""
        job.updated_at = datetime.now()
        for cb in self.progress_subscribers:
            try:
                cb(job)
            except Exception as e:
                logger.error("Error invoking progress callback: %s", e)

    def enqueue_job(
        self,
        file_hash: str,
        filename: str,
        event_id: Optional[str] = None,
    ) -> ReceiptJob:
        """Create and register a new pending ingestion job."""
        job = ReceiptJob(
            job_id=f"job_rec_{uuid4().hex[:8]}",
            event_id=event_id,
            file_hash=file_hash,
            filename=filename,
            status="PENDING",
            progress_pct=10,
            progress_message="Receipt enqueued for parsing...",
        )
        self.jobs[job.job_id] = job
        self._notify(job)
        return job

    def get_job(self, job_id: str) -> Optional[ReceiptJob]:
        """Fetch current state of an ingestion job."""
        return self.jobs.get(job_id)

    def process_receipt(
        self,
        job_id: str,
        raw_text_override: Optional[str] = None,
    ) -> StandardizedReceipt:
        """Execute full receipt ingestion pipeline."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")

        try:
            # Step 1: Processing started
            job.status = "PROCESSING"
            job.progress_pct = 25
            job.progress_message = "Scanning receipt header: Reading merchant & address..."
            self._notify(job)

            # Step 2: Read CAS file or raw text
            raw_text = raw_text_override
            if not raw_text:
                file_bytes = self.cas.read_file(job.file_hash)
                if not file_bytes:
                    raise FileNotFoundError(f"CAS file with hash '{job.file_hash}' not found on disk")
                try:
                    raw_text = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    raw_text = f"Binary receipt image: {job.filename}"

            file_path = str(self.cas.get_file_path(job.file_hash) or f"data/receipt_store/{job.file_hash}.jpg")

            # Step 3: OCR / LLM parsing
            job.progress_pct = 60
            job.progress_message = "Extracting line items, sales tax, and item quantities..."
            self._notify(job)

            if Path(file_path).suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".bmp"] or (raw_text and raw_text.startswith("Binary receipt image:")):
                receipts = [self.parser.parse_from_file(
                    file_path=file_path,
                    file_hash=job.file_hash,
                    source_channel="PHOTO_CAMERA",
                )]
            else:
                receipts = self.parser.parse_all_from_file(
                    file_path=file_path,
                    file_hash=job.file_hash,
                )

            processed_receipts: List[StandardizedReceipt] = []
            for r_idx, receipt in enumerate(receipts):
                receipt.event_id = job.event_id

                # Deduplication: Check if this receipt was already imported previously
                cursor = self.conn.cursor()
                existing = None
                if receipt.source_reference_id:
                    existing = cursor.execute(
                        "SELECT id FROM receipts WHERE source_reference_id = ?",
                        (receipt.source_reference_id,),
                    ).fetchone()
                if not existing:
                    tx_time_str = receipt.transaction_time.isoformat() if receipt.transaction_time else None
                    existing = cursor.execute(
                        "SELECT id FROM receipts WHERE merchant_name = ? AND transaction_time = ? AND total_amount = ?",
                        (receipt.merchant_name, tx_time_str, receipt.total_amount),
                    ).fetchone()

                if existing:
                    logger.info(
                        "Receipt %s (%s) already imported; skipping to prevent duplicate pantry restock",
                        receipt.source_reference_id or receipt.merchant_name,
                        existing["id"],
                    )
                    continue

                # Step 4-6: Persist receipt, bulk restock pantry, and patch location via ReceiptService
                self.receipt_service.persist_receipt(receipt, auto_restock=True)
                processed_receipts.append(receipt)

            # Step 7: Completed!
            job.status = "COMPLETED"
            job.progress_pct = 100
            total_items = sum(len(r.line_items) for r in processed_receipts)
            job.progress_message = (
                f"Complete! {len(processed_receipts)} receipt(s) with {total_items} items parsed & pantry updated."
            )
            job.result = processed_receipts[0] if processed_receipts else (receipts[0] if receipts else None)
            self._notify(job)

            return job.result

        except Exception as e:
            logger.error("Receipt ingestion error on job %s: %s", job.job_id, e, exc_info=True)
            job.status = "FAILED"
            job.progress_pct = 100
            job.progress_message = f"Parsing failed: {str(e)}"
            job.error_message = str(e)
            self._notify(job)
            raise

    def _persist_receipt_to_db(self, receipt: StandardizedReceipt) -> None:
        """Write receipt and line items into SQLite database."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO receipts (
                id, event_id, place_id, file_hash, file_path, original_filename, mime_type,
                merchant_name, merchant_address, transaction_time, subtotal, tax_amount,
                tip_amount, total_amount, currency, source_channel, source_reference_id,
                raw_ocr_json, parsing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.id,
                receipt.event_id,
                receipt.place_id,
                receipt.file_hash,
                receipt.file_path,
                receipt.original_filename,
                receipt.mime_type,
                receipt.merchant_name,
                receipt.merchant_address,
                receipt.transaction_time.isoformat(),
                receipt.subtotal,
                receipt.tax_amount,
                receipt.tip_amount,
                receipt.total_amount,
                receipt.currency,
                receipt.source_channel,
                receipt.source_reference_id,
                receipt.raw_ocr_json,
                receipt.parsing_status,
            ),
        )

        for item in receipt.line_items:
            item.receipt_id = receipt.id
            cursor.execute(
                """
                INSERT OR REPLACE INTO receipt_items (
                    id, receipt_id, raw_text, clean_name, category, quantity, unit, unit_price, total_price, product_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    receipt.id,
                    item.raw_text,
                    item.clean_name,
                    item.category,
                    item.quantity,
                    item.unit,
                    item.unit_price,
                    item.total_price,
                    item.product_id,
                ),
            )

        self.conn.commit()

    def _patch_event_location(self, receipt: StandardizedReceipt) -> None:
        """Deferred OCR address enrichment: patches parent event place & total."""
        cursor = self.conn.cursor()

        # Update event record
        cursor.execute(
            """
            UPDATE events 
            SET place_id = COALESCE(?, place_id),
                tax_amount = CASE WHEN tax_amount = 0.0 THEN ? ELSE tax_amount END,
                completed_at = COALESCE(completed_at, ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                receipt.place_id,
                receipt.tax_amount,
                receipt.transaction_time.isoformat(),
                receipt.event_id,
            ),
        )

        # Patch shopping_details or dining_details total_amount
        evt_row = cursor.execute("SELECT event_type FROM events WHERE id = ?", (receipt.event_id,)).fetchone()
        evt_type = evt_row["event_type"] if evt_row else "SHOPPING"
        if evt_type == "DINING":
            cursor.execute(
                """
                INSERT INTO dining_details (event_id, event_type, total_amount)
                VALUES (?, 'DINING', ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    total_amount = CASE WHEN dining_details.total_amount = 0.0 THEN excluded.total_amount ELSE dining_details.total_amount END
                """,
                (receipt.event_id, receipt.total_amount),
            )
        else:
            cursor.execute(
                """
                UPDATE shopping_details
                SET pantry_updated = 1,
                    receipt_image_path = ?,
                    total_amount = CASE WHEN total_amount = 0.0 THEN ? ELSE total_amount END
                WHERE event_id = ?
                """,
                (receipt.file_path, receipt.total_amount, receipt.event_id),
            )

        self.conn.commit()
