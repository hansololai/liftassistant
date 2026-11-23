"""Receipt Service Core Domain Engine.
Handles deterministic receipt persistence to receipts and receipt_items tables,
product catalog matching, Grocy bulk unit restock ledger (qu_factor), and parent event patching.
"""

from datetime import datetime
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional
from uuid import uuid4

from liftassistant.models.domain import StandardizedReceipt
from liftassistant.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)


class ReceiptService:
    """Core domain service for receipt storage, inventory replenishment, and event enrichment."""

    def __init__(self, conn: sqlite3.Connection, inventory_service: Optional[InventoryService] = None):
        self.conn = conn
        self.inv_service = inventory_service

    def persist_receipt(
        self, receipt: StandardizedReceipt, auto_restock: bool = True
    ) -> StandardizedReceipt:
        """Persist standardized receipt to database, apply Grocy bulk restock, and patch event location."""
        cursor = self.conn.cursor()

        # Check deduplication
        existing = None
        if receipt.source_reference_id:
            existing = cursor.execute(
                "SELECT id FROM receipts WHERE source_reference_id = ?",
                (receipt.source_reference_id,),
            ).fetchone()
        if not existing and receipt.transaction_time:
            existing = cursor.execute(
                "SELECT id FROM receipts WHERE merchant_name = ? AND transaction_time = ? AND total_amount = ?",
                (receipt.merchant_name, receipt.transaction_time.isoformat(), receipt.total_amount),
            ).fetchone()

        if existing:
            logger.info(
                "Receipt %s already exists in database (%s); skipping duplicate insertion.",
                receipt.source_reference_id or receipt.merchant_name,
                existing["id"],
            )
            return receipt

        # Write to receipts table
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
                receipt.transaction_time.isoformat() if receipt.transaction_time else datetime.now().isoformat(),
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

        # Write line items and restock pantry
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

            # Auto-restock pantry via InventoryService bulk factor (qu_factor)
            if auto_restock and self.inv_service and item.product_id:
                try:
                    self.inv_service.restock_from_purchase(
                        product_id=item.product_id,
                        purchase_quantity=item.quantity,
                        event_id=receipt.event_id,
                    )
                except Exception as ex:
                    logger.warning("Could not auto-restock pantry for item '%s': %s", item.clean_name, ex)

        self.conn.commit()

        # Patch parent LifeEvent location and details if linked
        if receipt.event_id:
            self._patch_event_location(receipt)

        logger.info(
            "Persisted receipt '%s' (%s) with %d line items to database.",
            receipt.merchant_name,
            receipt.id,
            len(receipt.line_items),
        )
        return receipt

    def _patch_event_location(self, receipt: StandardizedReceipt) -> None:
        """Deferred OCR address enrichment: patches parent event place, totals, and completion."""
        if not receipt.event_id:
            return
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
                receipt.transaction_time.isoformat() if receipt.transaction_time else datetime.now().isoformat(),
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
                    receipt_image_path = COALESCE(?, receipt_image_path),
                    total_amount = CASE WHEN total_amount = 0.0 THEN ? ELSE total_amount END
                WHERE event_id = ?
                """,
                (receipt.file_path, receipt.total_amount, receipt.event_id),
            )

        self.conn.commit()
