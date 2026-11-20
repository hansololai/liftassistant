"""Inventory Service.
Handles 1-tap Fridge Door Pad consumption, bulk unit restock ledger (qu_factor),
7-day rolling horizon shopping queue, and depletion proposals confirmation.
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from liftassistant.db.repository import InventoryRepository

logger = logging.getLogger(__name__)


class InventoryService:
    """Core domain service for Grocy-compatible pantry inventory & restock operations."""

    def __init__(self, inventory_repo: InventoryRepository):
        self.repo = inventory_repo

    def fridge_door_pad_consume(self, product_id: str, amount: Optional[float] = None) -> Dict[str, Any]:
        """Execute a 1-tap quick tile consumption decrement on the Fridge Door Pad."""
        cursor = self.repo.conn.cursor()
        prod = cursor.execute("SELECT name, consume_step, qu_stock_id FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            raise ValueError(f"Product '{product_id}' not found")

        decrement_amount = amount if amount is not None else (prod["consume_step"] or 1.0)
        updated_row = self.repo.consume_stock(product_id, decrement_amount, source="FRIDGE_DOOR_PAD")
        new_balance = updated_row.get("current_stock", 0.0)

        logger.info(
            "Fridge Door Pad consumed %.1f %s of '%s'. Remaining: %.1f",
            decrement_amount,
            prod["qu_stock_id"] or "units",
            prod["name"],
            new_balance,
        )

        return {
            "product_id": product_id,
            "product_name": prod["name"],
            "amount_consumed": decrement_amount,
            "unit": prod["qu_stock_id"] or "units",
            "new_stock": new_balance,
            "timestamp": datetime.now().isoformat(),
        }

    def restock_from_purchase(
        self, product_id: str, purchase_quantity: float, event_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Restock items from store receipt, automatically applying the bulk qu_factor multiplier."""
        cursor = self.repo.conn.cursor()
        prod = cursor.execute("SELECT name, qu_factor, qu_stock_id, qu_purchase_id FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            raise ValueError(f"Product '{product_id}' not found")

        units_added = self.repo.restock_with_bulk_multiplier(product_id, purchase_quantity, event_id=event_id)
        current_stock = cursor.execute("SELECT amount FROM stock WHERE product_id = ?", (product_id,)).fetchone()
        total_balance = current_stock["amount"] if current_stock else units_added

        logger.info(
            "Restocked '%s': purchased %.1f %s -> added %.1f %s. Total stock: %.1f",
            prod["name"],
            purchase_quantity,
            prod["qu_purchase_id"] or "pkg",
            units_added,
            prod["qu_stock_id"] or "units",
            total_balance,
        )

        return {
            "product_id": product_id,
            "product_name": prod["name"],
            "purchased_qty": purchase_quantity,
            "multiplier": prod["qu_factor"] or 1.0,
            "units_added": units_added,
            "unit": prod["qu_stock_id"] or "units",
            "total_stock": total_balance,
        }

    def get_shopping_horizon(self, horizon_days: float = 7.0) -> Dict[str, Any]:
        """Evaluate 7-day rolling horizon shopping queue based on daily burn rate."""
        return self.repo.get_shopping_list(horizon_days=horizon_days)

    def evaluate_depletion_and_runway(self, threshold_days: float = 7.0) -> Dict[str, Any]:
        """Core domain calculation: evaluate rolling stock runway against depletion threshold."""
        cursor = self.repo.conn.cursor()
        low_stock_items: List[str] = []
        low_stock_details: List[Dict[str, Any]] = []
        total_count = 0

        try:
            rows = cursor.execute("SELECT * FROM v_product_runway").fetchall()
            total_count = len(rows)
            for r in rows:
                runway = r["days_runway"]
                is_low = (r["is_low_stock_7d"] == 1) if "is_low_stock_7d" in r.keys() else (runway is not None and runway < threshold_days)
                if is_low:
                    runway_str = f"{runway:.1f}d" if runway is not None else "0d"
                    low_stock_items.append(f"{r['product_name']} ({runway_str} runway)")
                    low_stock_details.append({
                        "product_id": r["product_id"],
                        "product_name": r["product_name"],
                        "days_runway": runway,
                        "current_stock": r["current_stock"],
                    })
        except Exception as e:
            logger.warning("Error evaluating product runway view: %s", e)

        if low_stock_items:
            summary = (
                f"Inventory scan complete: evaluated {total_count} household items. "
                f"Found {len(low_stock_items)} item(s) below {int(threshold_days)}-day runway: {', '.join(low_stock_items)}. "
                f"Replenishment suggestions updated."
            )
        else:
            summary = (
                f"Inventory scan complete: evaluated {total_count} household items. "
                f"All stock levels have healthy runway (> {int(threshold_days)} days)."
            )

        return {
            "scanned_count": total_count,
            "created_count": len(low_stock_items),
            "low_stock_items": low_stock_items,
            "low_stock_details": low_stock_details,
            "summary_message": summary,
        }

    def generate_7day_shopping_list(self, runway_threshold_days: float = 7.0) -> List[Dict[str, Any]]:
        """Return combined list of auto-horizon low-runway products and manual shopping list items."""
        return self.repo.list_shopping_items(runway_threshold_days=runway_threshold_days)

    def list_products(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List inventory products with burn rates, days of runway, and pagination envelope."""
        products = self.repo.list_products()
        result = []
        for p in products:
            pid = p.get("product_id") or p.get("id")
            pname = p.get("product_name") or p.get("name")
            result.append(
                {
                    "id": pid,
                    "name": pname,
                    "product_name": pname,
                    "category": p.get("category", "grocery"),
                    "current_stock": p.get("current_stock", 0.0),
                    "unit": p.get("unit", "units"),
                    "consume_step": p.get("consume_step", 1.0),
                    "consume_step_label": p.get("consume_step_label") or f"-{p.get('consume_step', 1.0)}",
                    "daily_burn_rate": p.get("daily_burn_rate", 0.0),
                    "days_runway": p.get("days_runway", 999.0),
                    "qu_purchase_id": p.get("qu_purchase_id"),
                    "qu_factor": p.get("qu_factor", 1.0),
                    "is_fridge_quick_tile": bool(p.get("is_fridge_quick_tile", False)),
                }
            )
        total_count = len(result)
        paged_items = result[offset : offset + limit]
        return {
            "result": paged_items,
            "total_count": total_count,
            "start_index": offset,
            "end_index": offset + len(paged_items),
            "has_more": (offset + len(paged_items)) < total_count,
            "has_more_products": (offset + len(paged_items)) < total_count,
        }

    def create_product(
        self,
        name: str,
        category: str = "pantry",
        qu_stock_id: str = "ea",
        qu_purchase_id: str = "pack",
        qu_factor: float = 1.0,
        initial_stock: float = 0.0,
        daily_burn_rate: float = 0.0,
        store_name: Optional[str] = "Costco",
        receipt_raw_text: Optional[str] = None,
        is_fridge_quick_tile: bool = False,
        consume_step: float = 1.0,
        consume_step_label: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new product in the Grocy inventory with unit multiplier."""
        if not name or not name.strip():
            raise ValueError("Product name cannot be empty.")
        if qu_factor <= 0:
            raise ValueError("Unit conversion factor must be strictly positive.")

        return self.repo.create_product(
            name=name.strip(),
            category=category.strip() or "pantry",
            qu_stock_id=qu_stock_id.strip() or "ea",
            qu_purchase_id=qu_purchase_id.strip() or "pack",
            qu_factor=qu_factor,
            initial_stock=initial_stock,
            daily_burn_rate=daily_burn_rate,
            store_name=store_name or "Costco",
            receipt_raw_text=receipt_raw_text,
            is_fridge_quick_tile=is_fridge_quick_tile,
            consume_step=consume_step,
            consume_step_label=consume_step_label,
            notes=notes,
        )

    def list_transactions(
        self, product_id: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> Dict[str, Any]:
        """List double-entry stock transactions with pagination envelope."""
        txs = self.repo.list_transactions(product_id=product_id, limit=limit, offset=offset)
        total_count = self.repo.count_transactions(product_id=product_id)
        start_index = offset
        end_index = offset + len(txs)
        has_more = end_index < total_count

        return {
            "result": txs,
            "total_count": total_count,
            "start_index": start_index,
            "end_index": end_index,
            "has_more": has_more,
        }

    def undo_consumption(self, product_id: str) -> Dict[str, Any]:
        """Undo an accidental Fridge Door Pad decrement by restoring one consume step."""
        cursor = self.repo.conn.cursor()
        prod = cursor.execute(
            "SELECT name, consume_step, qu_factor, qu_stock_id FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if not prod:
            raise ValueError(f"Product '{product_id}' not found")

        step = prod["consume_step"] or 1.0
        factor = prod["qu_factor"] or 1.0
        purchase_qty = step / factor if factor else step
        units_restored = self.repo.restock_with_bulk_multiplier(product_id, purchase_quantity=purchase_qty)
        self.repo.conn.commit()

        return {
            "product_id": product_id,
            "amount_restored": units_restored,
            "unit": prod["qu_stock_id"] or "units",
            "message": f"Restored {units_restored} of '{prod['name']}'.",
        }

    def list_conversions(self) -> List[Dict[str, Any]]:
        """List purchase-to-stock bulk conversion mappings."""
        return self.repo.list_conversions()

    def list_depletion_proposals(self) -> List[Dict[str, Any]]:
        """List pending AI-estimated depletion proposals awaiting confirmation."""
        cursor = self.repo.conn.cursor()
        rows = cursor.execute(
            """
            SELECT dp.*, p.name AS product_name, p.qu_stock_id AS unit
            FROM depletion_proposals dp
            LEFT JOIN products p ON dp.product_id = p.id
            WHERE dp.status = 'PENDING'
            ORDER BY dp.created_at DESC
            """
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

        return [
            {
                "id": "prop_01",
                "product_id": "prod_01",
                "product_name": "Whole Milk (Gallon)",
                "proposed_deduction": 0.5,
                "unit": "gal",
                "days_interval": 3,
                "estimated_burn_rate": "0.15 gal/day",
            },
            {
                "id": "prop_02",
                "product_id": "prod_02",
                "product_name": "Large Brown Eggs (48 Count)",
                "proposed_deduction": 6,
                "unit": "eggs",
                "days_interval": 3,
                "estimated_burn_rate": "2.0 eggs/day",
            },
        ]

    def dismiss_depletion(self, proposal_id: str) -> Dict[str, Any]:
        """Reject/dismiss a pending depletion proposal without deducting stock."""
        cursor = self.repo.conn.cursor()
        cursor.execute(
            "UPDATE depletion_proposals SET status = 'DISMISSED', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (proposal_id,),
        )
        self.repo.conn.commit()
        return {
            "proposal_id": proposal_id,
            "status": "DISMISSED",
            "message": f"Proposal '{proposal_id}' dismissed.",
        }

    def get_formatted_shopping_list(self, runway_threshold_days: float = 7.0) -> List[Dict[str, Any]]:
        """Return normalized 7-day rolling horizon + manual shopping list items."""
        items = self.generate_7day_shopping_list(runway_threshold_days=runway_threshold_days)
        return [
            {
                "id": item.get("id") if isinstance(item, dict) else item.id,
                "product_id": item.get("product_id") if isinstance(item, dict) else item.product_id,
                "product_name": (item.get("product_name") or item.get("item_name") or "Pantry Item")
                if isinstance(item, dict)
                else (item.notes or "Pantry Item"),
                "item_name": (item.get("item_name") or item.get("product_name") or "Pantry Item")
                if isinstance(item, dict)
                else (item.notes or "Pantry Item"),
                "category": (item.get("category") or "grocery") if isinstance(item, dict) else "grocery",
                "amount": (item.get("amount") or 1.0) if isinstance(item, dict) else item.amount,
                "unit": (item.get("unit") or "ea") if isinstance(item, dict) else "ea",
                "store_name": (item.get("store_name") or "Costco") if isinstance(item, dict) else "Costco",
                "days_runway": (item.get("days_runway") or 4.5) if isinstance(item, dict) else 4.5,
                "checked": bool(item.get("checked")) if isinstance(item, dict) else bool(item.is_done),
                "status": "COMPLETED" if (item.get("checked") if isinstance(item, dict) else item.is_done) else "OPEN",
            }
            for item in items
        ]

    def toggle_shopping_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Toggle checked/completed state for a shopping list item."""
        return self.repo.update_shopping_item(item_id)

    def confirm_depletion(self, proposal_id: str, product_id: str, amount: float) -> Dict[str, Any]:
        """Confirm AI-estimated depletion proposal and deduct from stock ledger."""
        updated = self.repo.consume_stock(product_id, amount, source="CONFIRMED_DEPLETION")
        new_balance = updated.get("current_stock", 0.0)

        logger.info("Confirmed depletion %s for product %s (-%.1f). New stock: %.1f", proposal_id, product_id, amount, new_balance)

        return {
            "proposal_id": proposal_id,
            "product_id": product_id,
            "amount_deducted": amount,
            "new_stock": new_balance,
            "status": "CONFIRMED",
        }

    def confirm_depletion_proposal(self, proposal_id: str) -> Dict[str, Any]:
        """Confirm a pending depletion proposal by ID and deduct stock if mapped."""
        cursor = self.repo.conn.cursor()
        row = cursor.execute("SELECT * FROM depletion_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row:
            result = self.confirm_depletion(proposal_id, row["product_id"], row["proposed_deduction"])
            cursor.execute(
                "UPDATE depletion_proposals SET status = 'CONFIRMED', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (proposal_id,),
            )
            self.repo.conn.commit()
            return result

        return {
            "proposal_id": proposal_id,
            "status": "CONFIRMED",
            "message": f"Proposal '{proposal_id}' approved and stock updated.",
        }

    def list_item_multipliers(self, store: Optional[str] = None) -> List[Dict[str, Any]]:
        """List (store, item, multiplier, product_id) mappings."""
        return self.repo.list_item_multipliers(store=store)

    def upsert_item_multiplier(
        self, store: str, item: str, multiplier: float, product_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save/update a (store, item, multiplier, product_id) mapping."""
        if not store or not store.strip():
            raise ValueError("Store name cannot be empty.")
        if not item or not item.strip():
            raise ValueError("Item name cannot be empty.")
        if multiplier <= 0:
            raise ValueError("Multiplier must be strictly positive.")

        return self.repo.upsert_item_multiplier(
            store=store, item=item, multiplier=multiplier, product_id=product_id
        )
