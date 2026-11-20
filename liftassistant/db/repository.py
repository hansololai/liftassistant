"""LiftAssistant 3.0 Database Repository.
Handles CRUD and polymorphic joins across SQLite tables.
"""

from datetime import datetime
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional
from liftassistant.models.domain import (
    DiningDetail,
    EventGenerator,
    GeneratorEventFeedback,
    GeneratorRun,
    HouseholdEquipment,
    LearnedPromptRule,
    LifeEvent,
    MaintenanceDetail,
    Place,
    Product,
    ResourceClosure,
    ShoppingDetail,
    ShoppingListItem,
    StockBatch,
    Trip,
    TripStop,
)

logger = logging.getLogger(__name__)


class EventRepository:
    """Repository for universal life events with joined-table polymorphism."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_event(self, event_id: str) -> Optional[LifeEvent]:
        """Fetch single event with its joined type-specific extension table."""
        cursor = self.conn.cursor()
        query = """
            SELECT 
                e.*,
                p.name AS p_name, p.category AS p_category, p.address AS p_address,
                p.latitude AS p_lat, p.longitude AS p_lng, p.map_url AS p_map_url,
                d.event_id AS d_eid, d.rating AS d_rating, d.total_amount AS d_total_amount,
                s.event_id AS s_eid, s.receipt_image_path AS s_img, s.pantry_updated AS s_pu, s.total_amount AS s_total_amount,
                m.event_id AS m_eid, m.equipment_id AS m_eq_id, m.service_type AS m_st, 
                m.next_due_interval_days AS m_ndd, m.next_due_miles AS m_ndm
            FROM events e
            LEFT JOIN places p ON e.place_id = p.id
            LEFT JOIN dining_details d ON e.id = d.event_id AND e.event_type = d.event_type
            LEFT JOIN shopping_details s ON e.id = s.event_id AND e.event_type = s.event_type
            LEFT JOIN maintenance_details m ON e.id = m.event_id AND e.event_type = m.event_type
            WHERE e.id = ?
        """
        row = cursor.execute(query, (event_id,)).fetchone()
        if not row:
            return None
        return self._map_row_to_event(row)

    def list_events(
        self,
        event_type: Optional[str] = None,
        status: Optional[str] = None,  # 'upcoming', 'completed', 'all'
        sort_by_deadline: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LifeEvent]:
        """Query events ledger with filters and pagination. If sort_by_deadline=True, orders by closest deadline/due date."""
        cursor = self.conn.cursor()
        where_clauses = []
        params: List[Any] = []

        if event_type and event_type != "ALL":
            where_clauses.append("e.event_type = ?")
            params.append(event_type)

        if status == "upcoming":
            where_clauses.append("e.completed_at IS NULL")
        elif status == "completed":
            where_clauses.append("e.completed_at IS NOT NULL")

        where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Urgency sorting: Upcoming events sorted by closest deadline first; completed events sorted by completion date
        order_by = (
            "CASE WHEN e.completed_at IS NULL THEN COALESCE(e.deadline, e.scheduled_at) END ASC, COALESCE(e.completed_at, e.scheduled_at) DESC"
            if sort_by_deadline
            else "COALESCE(e.completed_at, e.scheduled_at) DESC"
        )

        query = f"""
            SELECT 
                e.*,
                p.name AS p_name, p.category AS p_category, p.address AS p_address,
                p.latitude AS p_lat, p.longitude AS p_lng, p.map_url AS p_map_url,
                d.event_id AS d_eid, d.rating AS d_rating, d.total_amount AS d_total_amount,
                s.event_id AS s_eid, s.receipt_image_path AS s_img, s.pantry_updated AS s_pu, s.total_amount AS s_total_amount,
                m.event_id AS m_eid, m.equipment_id AS m_eq_id, m.service_type AS m_st, 
                m.next_due_interval_days AS m_ndd, m.next_due_miles AS m_ndm
            FROM events e
            LEFT JOIN places p ON e.place_id = p.id
            LEFT JOIN dining_details d ON e.id = d.event_id AND e.event_type = d.event_type
            LEFT JOIN shopping_details s ON e.id = s.event_id AND e.event_type = s.event_type
            LEFT JOIN maintenance_details m ON e.id = m.event_id AND e.event_type = m.event_type
            {where_str}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = cursor.execute(query, params).fetchall()
        return [self._map_row_to_event(r) for r in rows]

    def count_events(
        self,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count total matching events on the ledger."""
        cursor = self.conn.cursor()
        where_clauses = []
        params: List[Any] = []

        if event_type and event_type != "ALL":
            where_clauses.append("e.event_type = ?")
            params.append(event_type)

        if status == "upcoming":
            where_clauses.append("e.completed_at IS NULL")
        elif status == "completed":
            where_clauses.append("e.completed_at IS NOT NULL")

        where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        row = cursor.execute(f"SELECT COUNT(*) FROM events e {where_str}", params).fetchone()
        return row[0] if row else 0

    def create_event(
        self,
        event: LifeEvent,
        dining: Optional[DiningDetail] = None,
        shopping: Optional[ShoppingDetail] = None,
        maintenance: Optional[MaintenanceDetail] = None,
    ) -> LifeEvent:
        """Create base event and insert matching polymorphic extension table row."""
        cursor = self.conn.cursor()

        # Fallback to detail objects embedded on the event model
        dining = dining or event.dining_detail
        shopping = shopping or event.shopping_detail
        maintenance = maintenance or event.maintenance_detail

        people_json = json.dumps(event.people_involved)

        cursor.execute(
            """
            INSERT INTO events (
                id, title, event_type, scheduled_at, scheduled_end_at, deadline, completed_at,
                all_day, place_id, studio, latitude, longitude, people_involved, tax_amount, notes,
                source, source_reference_id, has_conflict, conflict_status, conflict_reason,
                generator_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.title,
                event.event_type,
                event.scheduled_at.isoformat() if event.scheduled_at else None,
                event.scheduled_end_at.isoformat() if event.scheduled_end_at else None,
                event.deadline.isoformat() if event.deadline else None,
                event.completed_at.isoformat() if event.completed_at else None,
                int(event.all_day),
                event.place_id,
                event.studio,
                event.latitude,
                event.longitude,
                people_json,
                event.tax_amount,
                event.notes,
                event.source,
                event.source_reference_id,
                int(event.has_conflict),
                event.conflict_status,
                event.conflict_reason,
                event.generator_run_id,
            ),
        )

        # Insert into specific extension table using Approach 2 Composite Type checking
        if event.event_type == "DINING" and dining:
            cursor.execute(
                """
                INSERT INTO dining_details (event_id, event_type, rating, total_amount)
                VALUES (?, 'DINING', ?, ?)
                """,
                (event.id, dining.rating, dining.total_amount),
            )
        elif event.event_type == "SHOPPING" and shopping:
            cursor.execute(
                """
                INSERT INTO shopping_details (event_id, event_type, receipt_image_path, pantry_updated, total_amount)
                VALUES (?, 'SHOPPING', ?, ?, ?)
                """,
                (event.id, shopping.receipt_image_path, int(shopping.pantry_updated), shopping.total_amount),
            )
        elif event.event_type == "MAINTENANCE" and maintenance:
            cursor.execute(
                """
                INSERT INTO maintenance_details (event_id, event_type, equipment_id, service_type, next_due_interval_days, next_due_miles)
                VALUES (?, 'MAINTENANCE', ?, ?, ?, ?)
                """,
                (
                    event.id,
                    maintenance.equipment_id,
                    maintenance.service_type,
                    maintenance.next_due_interval_days,
                    maintenance.next_due_miles,
                ),
            )

        return self.get_event(event.id)  # type: ignore

    def update_event(self, event: LifeEvent) -> LifeEvent:
        """Persist updated fields on an existing event row."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE events
            SET title = ?,
                event_type = ?,
                scheduled_at = ?,
                scheduled_end_at = ?,
                deadline = ?,
                completed_at = ?,
                place_id = ?,
                studio = ?,
                latitude = ?,
                longitude = ?,
                people_involved = ?,
                notes = ?,
                has_conflict = ?,
                conflict_status = ?,
                conflict_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                event.title,
                event.event_type,
                event.scheduled_at.isoformat() if event.scheduled_at else None,
                event.scheduled_end_at.isoformat() if event.scheduled_end_at else None,
                event.deadline.isoformat() if event.deadline else None,
                event.completed_at.isoformat() if event.completed_at else None,
                event.place_id,
                event.studio,
                event.latitude,
                event.longitude,
                json.dumps(event.people_involved),
                event.notes,
                int(event.has_conflict),
                event.conflict_status,
                event.conflict_reason,
                event.id,
            ),
        )
        self.conn.commit()
        return self.get_event(event.id)  # type: ignore

    def delete_event(self, event_id: str) -> bool:
        """Deletes event and cascades to extension tables automatically."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_row_to_event(self, row: sqlite3.Row) -> LifeEvent:
        row_keys = set(row.keys())
        people = []
        if row["people_involved"]:
            try:
                people = json.loads(row["people_involved"])
            except Exception:
                people = [row["people_involved"]]

        # Parse Place
        place = None
        if row["place_id"]:
            place = Place(
                id=row["place_id"],
                name=row["p_name"] or "",
                category=row["p_category"],
                address=row["p_address"],
                latitude=row["p_lat"],
                longitude=row["p_lng"],
                map_url=row["p_map_url"],
            )

        # Parse Polymorphic Extension
        dining_detail = None
        if row["event_type"] == "DINING" and (
            ("d_eid" in row_keys and row["d_eid"] is not None)
            or ("d_rating" in row_keys and row["d_rating"] is not None)
            or ("d_total_amount" in row_keys and row["d_total_amount"] is not None)
        ):
            dining_detail = DiningDetail(
                event_id=row["id"],
                event_type="DINING",
                rating=row["d_rating"],
                total_amount=row["d_total_amount"] or 0.0,
            )

        shopping_detail = None
        if row["event_type"] == "SHOPPING" and (
            ("s_eid" in row_keys and row["s_eid"] is not None)
            or ("s_pu" in row_keys and row["s_pu"] is not None)
            or ("s_total_amount" in row_keys and row["s_total_amount"] is not None)
        ):
            shopping_detail = ShoppingDetail(
                event_id=row["id"],
                event_type="SHOPPING",
                receipt_image_path=row["s_img"],
                pantry_updated=bool(row["s_pu"]),
                total_amount=row["s_total_amount"] or 0.0,
            )

        maintenance_detail = None
        if row["event_type"] == "MAINTENANCE" and (
            ("m_eid" in row_keys and row["m_eid"] is not None)
            or ("m_eq_id" in row_keys and row["m_eq_id"] is not None)
        ):
            maintenance_detail = MaintenanceDetail(
                event_id=row["id"],
                event_type="MAINTENANCE",
                equipment_id=row["m_eq_id"] or "eq_odyssey",
                service_type=row["m_st"],
                next_due_interval_days=row["m_ndd"],
                next_due_miles=row["m_ndm"],
            )

        return LifeEvent(
            id=row["id"],
            title=row["title"],
            event_type=row["event_type"],
            scheduled_at=row["scheduled_at"],
            scheduled_end_at=row["scheduled_end_at"],
            deadline=row["deadline"],
            completed_at=row["completed_at"],
            all_day=bool(row["all_day"]),
            place_id=row["place_id"],
            studio=row["studio"] if "studio" in row_keys else None,
            latitude=row["latitude"] if "latitude" in row_keys else None,
            longitude=row["longitude"] if "longitude" in row_keys else None,
            people_involved=people,
            tax_amount=row["tax_amount"] or 0.0,
            notes=row["notes"],
            source=row["source"],
            source_reference_id=row["source_reference_id"],
            has_conflict=bool(row["has_conflict"]),
            conflict_status=row["conflict_status"],
            conflict_reason=row["conflict_reason"],
            generator_run_id=row["generator_run_id"] if "generator_run_id" in row_keys else None,
            place=place,
            dining_detail=dining_detail,
            shopping_detail=shopping_detail,
            maintenance_detail=maintenance_detail,
        )

    def list_events_by_run_id(self, run_id: str) -> List[LifeEvent]:
        """Fetch all LifeEvent items created during a specific generator run."""
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT e.*,
                   p.name AS p_name, p.category AS p_category, p.address AS p_address,
                   p.latitude AS p_lat, p.longitude AS p_lng, p.map_url AS p_map_url,
                   d.event_id AS d_eid, d.rating AS d_rating, d.total_amount AS d_total_amount,
                   s.event_id AS s_eid, s.receipt_image_path AS s_img, s.pantry_updated AS s_pu, s.total_amount AS s_total_amount,
                   m.event_id AS m_eid, m.equipment_id AS m_eq_id, m.service_type AS m_st,
                   m.next_due_interval_days AS m_ndd, m.next_due_miles AS m_ndm
            FROM events e
            LEFT JOIN places p ON e.place_id = p.id
            LEFT JOIN dining_details d ON e.id = d.event_id AND e.event_type = d.event_type
            LEFT JOIN shopping_details s ON e.id = s.event_id AND e.event_type = s.event_type
            LEFT JOIN maintenance_details m ON e.id = m.event_id AND e.event_type = m.event_type
            WHERE e.generator_run_id = ?
            ORDER BY COALESCE(e.scheduled_at, e.created_at) DESC
            """,
            (run_id,),
        ).fetchall()
        return [self._map_row_to_event(r) for r in rows]


class InventoryRepository:
    """Repository for Grocy stock ledger, bulk multiplier maps, and fridge pad operations."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_products(self) -> List[Dict[str, Any]]:
        """Fetch products with aggregated stock balances and days runway."""
        cursor = self.conn.cursor()
        rows = cursor.execute("SELECT * FROM v_product_runway ORDER BY product_name ASC").fetchall()
        return [dict(r) for r in rows]

    def consume_stock(self, product_id: str, amount: float, source: str = "FRIDGE_PAD") -> Dict[str, Any]:
        """Atomically decrement stock balance and log transaction."""
        cursor = self.conn.cursor()
        
        # 1. Fetch current product
        prod = cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            raise ValueError(f"Product '{product_id}' not found")

        # 2. Log double-entry transaction
        tx_id = f"tx_{product_id}_{int(sqlite3.time.time()) if hasattr(sqlite3, 'time') else 1000}"
        cursor.execute(
            """
            INSERT INTO stock_transactions (id, product_id, transaction_type, amount, unit, source)
            VALUES (?, ?, 'FRIDGE_PAD_CONSUME', ?, ?, ?)
            """,
            (tx_id, product_id, -abs(amount), prod["qu_stock_id"] or "ea", source),
        )

        # 3. Decrement from stock batch (or first batch available)
        stock_batch = cursor.execute("SELECT id, amount FROM stock WHERE product_id = ? LIMIT 1", (product_id,)).fetchone()
        if stock_batch:
            new_batch_amount = max(0.0, stock_batch["amount"] - amount)
            cursor.execute("UPDATE stock SET amount = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_batch_amount, stock_batch["id"]))
        else:
            # Insert negative or zero batch if none existed
            cursor.execute("INSERT INTO stock (id, product_id, amount) VALUES (?, ?, 0.0)", (f"stk_{product_id}", product_id))

        # 4. Fetch updated stock & runway from view
        updated = cursor.execute("SELECT * FROM v_product_runway WHERE product_id = ?", (product_id,)).fetchone()
        return dict(updated) if updated else {}

    def restock_with_bulk_multiplier(self, product_id: str, purchase_quantity: float, event_id: Optional[str] = None) -> float:
        """Apply qu_factor (e.g. Costco toilet paper 1 pack * 36 = +36 rolls)."""
        cursor = self.conn.cursor()
        prod = cursor.execute("SELECT qu_factor, qu_stock_id FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            raise ValueError(f"Product '{product_id}' not found")

        factor = prod["qu_factor"] or 1.0
        stock_units_added = purchase_quantity * factor

        # Log transaction
        tx_id = f"tx_restock_{product_id}"
        cursor.execute(
            """
            INSERT INTO stock_transactions (id, product_id, transaction_type, amount, unit, source, reference_id)
            VALUES (?, ?, 'PURCHASE_RECEIPT', ?, ?, 'RECEIPT_OCR', ?)
            """,
            (tx_id, product_id, stock_units_added, prod["qu_stock_id"] or "ea", event_id),
        )

        # Increment batch
        stock_batch = cursor.execute("SELECT id, amount FROM stock WHERE product_id = ? LIMIT 1", (product_id,)).fetchone()
        if stock_batch:
            cursor.execute("UPDATE stock SET amount = amount + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (stock_units_added, stock_batch["id"]))
        else:
            cursor.execute("INSERT INTO stock (id, product_id, amount, purchased_event_id) VALUES (?, ?, ?, ?)", (f"stk_{product_id}", product_id, stock_units_added, event_id))

        return stock_units_added

    def get_shopping_list(self, horizon_days: float = 7.0) -> Dict[str, Any]:
        """7-Day Horizon Rule: only items with runway < horizon_days are queued."""
        cursor = self.conn.cursor()
        
        # Fetch hidden sufficient items (runway >= 7)
        sufficient = cursor.execute("SELECT * FROM v_product_runway WHERE days_runway >= ? ORDER BY days_runway DESC", (horizon_days,)).fetchall()
        
        # Fetch low stock items (runway < 7)
        low_stock = cursor.execute("SELECT * FROM v_product_runway WHERE days_runway < ? ORDER BY days_runway ASC", (horizon_days,)).fetchall()

        return {
            "horizon_days": horizon_days,
            "sufficient_count": len(sufficient),
            "low_stock_count": len(low_stock),
            "sufficient_items": [dict(r) for r in sufficient],
            "queued_items": [dict(r) for r in low_stock],
        }

    def list_shopping_items(self, runway_threshold_days: float = 7.0) -> List[Dict[str, Any]]:
        """Return combined list of auto-horizon low-runway products and manual shopping list items."""
        cursor = self.conn.cursor()
        rows = cursor.execute("SELECT * FROM shopping_list ORDER BY created_at DESC").fetchall()
        manual_items = []
        for r in rows:
            d = dict(r)
            d["product_name"] = d.get("item_name", "")
            d["is_done"] = bool(d.get("checked", False))
            manual_items.append(d)

        existing_pids = {m["product_id"] for m in manual_items if m.get("product_id")}
        low_stock = cursor.execute(
            "SELECT product_id, product_name, category, current_stock, unit, days_runway FROM v_product_runway WHERE days_runway < ? ORDER BY days_runway ASC",
            (runway_threshold_days,),
        ).fetchall()

        auto_items = []
        for r in low_stock:
            if r["product_id"] not in existing_pids:
                auto_items.append({
                    "id": f"auto_{r['product_id']}",
                    "product_id": r["product_id"],
                    "product_name": r["product_name"],
                    "item_name": r["product_name"],
                    "category": r["category"],
                    "amount": 1.0,
                    "unit": r["unit"],
                    "store_name": "Costco",
                    "days_runway": r["days_runway"],
                    "checked": False,
                    "is_done": False,
                    "status": "OPEN",
                    "source": "AUTO_HORIZON",
                })
        return manual_items + auto_items

    def create_shopping_item(self, item: Any) -> Dict[str, Any]:
        """Manually add an item to the shopping list."""
        from uuid import uuid4
        cursor = self.conn.cursor()
        item_id = getattr(item, "id", None) or f"shp_{uuid4().hex[:8]}"
        prod_id = getattr(item, "product_id", None)
        item_name = getattr(item, "product_name", None) or getattr(item, "notes", None) or "Item"
        category = getattr(item, "category", "general")
        amount = getattr(item, "amount", 1.0)
        checked = bool(getattr(item, "is_done", False) or getattr(item, "checked", False))
        status = "COMPLETED" if checked else "OPEN"

        cursor.execute(
            """
            INSERT INTO shopping_list (id, product_id, item_name, category, amount, status, checked)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, prod_id, item_name, category, amount, status, int(checked)),
        )
        self.conn.commit()
        return {
            "id": item_id,
            "product_id": prod_id,
            "product_name": item_name,
            "item_name": item_name,
            "category": category,
            "amount": amount,
            "checked": checked,
            "is_done": checked,
            "status": status,
        }

    def update_shopping_item(self, item_id: str, checked: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """Update or toggle shopping item checked status."""
        cursor = self.conn.cursor()
        row = cursor.execute("SELECT * FROM shopping_list WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        current_checked = bool(row["checked"])
        new_checked = (not current_checked) if checked is None else checked
        new_status = "COMPLETED" if new_checked else "OPEN"
        cursor.execute(
            "UPDATE shopping_list SET checked = ?, status = ? WHERE id = ?",
            (int(new_checked), new_status, item_id),
        )
        self.conn.commit()
        return {
            "id": item_id,
            "product_name": row["item_name"],
            "item_name": row["item_name"],
            "checked": new_checked,
            "is_done": new_checked,
            "status": new_status,
        }

    def delete_shopping_item(self, item_id: str) -> bool:
        """Delete shopping item by id."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
        self.conn.commit()
        return cursor.rowcount > 0

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
        """Create a new product in the Grocy catalog with unit multiplier and optional initial stock."""
        from uuid import uuid4
        cursor = self.conn.cursor()

        # Ensure units exist in quantity_units to satisfy foreign key constraints
        cursor.execute("INSERT OR IGNORE INTO quantity_units (id, name, name_plural) VALUES (?, ?, ?)", (qu_stock_id, qu_stock_id, f"{qu_stock_id}s"))
        cursor.execute("INSERT OR IGNORE INTO quantity_units (id, name, name_plural) VALUES (?, ?, ?)", (qu_purchase_id, qu_purchase_id, f"{qu_purchase_id}s"))

        product_id = f"prod_{uuid4().hex[:8]}"
        step_label = consume_step_label or f"-{consume_step} {qu_stock_id}"

        cursor.execute(
            """
            INSERT INTO products (
                id, name, category, qu_purchase_id, qu_stock_id, qu_factor,
                consume_step, consume_step_label, is_fridge_quick_tile,
                min_stock_amount, daily_burn_rate, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?)
            """,
            (
                product_id,
                name.strip(),
                category.strip() or "pantry",
                qu_purchase_id,
                qu_stock_id,
                qu_factor,
                consume_step,
                step_label,
                int(is_fridge_quick_tile),
                daily_burn_rate,
                notes,
            ),
        )

        # Initial stock batch if provided
        if initial_stock > 0:
            stock_id = f"stk_{uuid4().hex[:8]}"
            cursor.execute(
                "INSERT INTO stock (id, product_id, amount) VALUES (?, ?, ?)",
                (stock_id, product_id, initial_stock),
            )
            cursor.execute(
                """
                INSERT INTO stock_transactions (id, product_id, transaction_type, amount, unit, source)
                VALUES (?, ?, 'INITIAL_INVENTORY', ?, ?, 'MANUAL_CREATE')
                """,
                (f"tx_init_{product_id}", product_id, initial_stock, qu_stock_id),
            )

        # Record unit conversion multiplier mapping
        conv_id = f"conv_{uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO product_unit_conversions (
                id, product_id, store_name, receipt_raw_text, purchase_unit, stock_unit, unit_multiplier
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conv_id,
                product_id,
                store_name or "Costco",
                receipt_raw_text or name.strip(),
                qu_purchase_id,
                qu_stock_id,
                qu_factor,
            ),
        )

        # Record in item_multipliers: (store, item, multiplier, product_id)
        cursor.execute(
            """
            INSERT INTO item_multipliers (store, item, multiplier, product_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(store, item) DO UPDATE SET 
                multiplier = excluded.multiplier,
                product_id = COALESCE(excluded.product_id, item_multipliers.product_id)
            """,
            (store_name or "Costco", receipt_raw_text or name.strip(), qu_factor, product_id),
        )

        self.conn.commit()

        row = cursor.execute("SELECT * FROM v_product_runway WHERE product_id = ?", (product_id,)).fetchone()
        if row:
            d = dict(row)
            d["id"] = d.get("product_id")
            d["name"] = d.get("product_name")
            return d

        return {
            "id": product_id,
            "product_id": product_id,
            "name": name.strip(),
            "product_name": name.strip(),
            "category": category.strip() or "pantry",
            "current_stock": initial_stock,
            "unit": qu_stock_id,
            "purchase_unit": qu_purchase_id,
            "unit_multiplier": qu_factor,
            "daily_burn_rate": daily_burn_rate,
            "days_runway": round(initial_stock / daily_burn_rate, 1) if daily_burn_rate > 0 else 999.0,
            "is_fridge_quick_tile": is_fridge_quick_tile,
        }

    def list_conversions(self) -> List[Dict[str, Any]]:
        """List bulk purchase-to-stock unit conversion rules."""
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT c.*, p.name AS product_name
            FROM product_unit_conversions c
            LEFT JOIN products p ON c.product_id = p.id
            ORDER BY c.store_name ASC, c.receipt_raw_text ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def list_item_multipliers(self, store: Optional[str] = None) -> List[Dict[str, Any]]:
        """List (store, item, multiplier, product_id) mappings joined with product name."""
        cursor = self.conn.cursor()
        base_query = """
            SELECT m.store, m.item, m.multiplier, m.product_id, p.name AS product_name
            FROM item_multipliers m
            LEFT JOIN products p ON m.product_id = p.id
        """
        if store:
            rows = cursor.execute(
                f"{base_query} WHERE m.store = ? ORDER BY m.item ASC",
                (store,),
            ).fetchall()
        else:
            rows = cursor.execute(
                f"{base_query} ORDER BY m.store ASC, m.item ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_item_multiplier(
        self, store: str, item: str, multiplier: float, product_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upsert a (store, item, multiplier, product_id) record."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO item_multipliers (store, item, multiplier, product_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(store, item) DO UPDATE SET 
                multiplier = excluded.multiplier,
                product_id = COALESCE(excluded.product_id, item_multipliers.product_id)
            """,
            (store.strip(), item.strip(), float(multiplier), product_id),
        )
        self.conn.commit()
        return {
            "store": store.strip(),
            "item": item.strip(),
            "multiplier": float(multiplier),
            "product_id": product_id,
        }

    def list_transactions(
        self,
        product_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List double-entry stock transactions with optional product filter and pagination."""
        cursor = self.conn.cursor()
        where_str = "WHERE t.product_id = ?" if product_id else ""
        params: List[Any] = [product_id] if product_id else []
        params.extend([limit, offset])

        query = f"""
            SELECT t.*, p.name AS product_name
            FROM stock_transactions t
            LEFT JOIN products p ON t.product_id = p.id
            {where_str}
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = cursor.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def count_transactions(self, product_id: Optional[str] = None) -> int:
        """Count total matching stock transactions."""
        cursor = self.conn.cursor()
        where_str = "WHERE product_id = ?" if product_id else ""
        params = [product_id] if product_id else []
        row = cursor.execute(f"SELECT COUNT(*) FROM stock_transactions {where_str}", params).fetchone()
        return row[0] if row else 0


class EventGeneratorRepository:
    """Repository for managing recurring event generators and spawning due events with deadlines."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_generator(self, gen: EventGenerator) -> EventGenerator:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO event_generators (
                id, title, event_type, frequency, interval, by_month, by_month_day,
                by_weekday, anchor_date, lead_time_days, has_deadline, deadline_offset_days,
                deadline_time, place_id, duration_minutes, people_involved, estimated_amount, notes, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gen.id,
                gen.title,
                gen.event_type,
                gen.frequency,
                gen.interval,
                gen.by_month,
                gen.by_month_day,
                gen.by_weekday,
                gen.anchor_date.isoformat(),
                gen.lead_time_days,
                int(gen.has_deadline),
                gen.deadline_offset_days,
                gen.deadline_time,
                gen.place_id,
                gen.duration_minutes,
                json.dumps(gen.people_involved),
                gen.estimated_amount,
                gen.notes,
                int(gen.is_active),
            ),
        )
        return gen

    def list_generators(self, active_only: bool = True) -> List[EventGenerator]:
        cursor = self.conn.cursor()
        where = "WHERE is_active = 1" if active_only else ""
        rows = cursor.execute(f"SELECT * FROM event_generators {where} ORDER BY title ASC").fetchall()
        result = []
        for r in rows:
            people = []
            if r["people_involved"]:
                try:
                    people = json.loads(r["people_involved"])
                except Exception:
                    pass
            result.append(
                EventGenerator(
                    id=r["id"],
                    title=r["title"],
                    event_type=r["event_type"],
                    frequency=r["frequency"],
                    interval=r["interval"],
                    by_month=r["by_month"],
                    by_month_day=r["by_month_day"],
                    by_weekday=r["by_weekday"],
                    anchor_date=r["anchor_date"],
                    lead_time_days=r["lead_time_days"],
                    has_deadline=bool(r["has_deadline"]),
                    deadline_offset_days=r["deadline_offset_days"],
                    deadline_time=r["deadline_time"],
                    place_id=r["place_id"],
                    duration_minutes=r["duration_minutes"],
                    people_involved=people,
                    estimated_amount=r["estimated_amount"] or 0.0,
                    notes=r["notes"],
                    is_active=bool(r["is_active"]),
                    last_generated_date=r["last_generated_date"],
                )
            )
        return result


class PlaceRepository:
    """Repository for first-class grounded physical places."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_place(self, place_id: str) -> Optional[Place]:
        """Fetch place by its unique ID."""
        cursor = self.conn.cursor()
        row = cursor.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
        if not row:
            return None
        return Place(**dict(row))

    def list_places(self, search: Optional[str] = None, limit: int = 50) -> List[Place]:
        """List verified places, optionally filtered by name or address substring."""
        cursor = self.conn.cursor()
        if search:
            pattern = f"%{search.strip().lower()}%"
            rows = cursor.execute(
                "SELECT * FROM places WHERE LOWER(name) LIKE ? OR LOWER(address) LIKE ? ORDER BY name ASC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        else:
            rows = cursor.execute("SELECT * FROM places ORDER BY name ASC LIMIT ?", (limit,)).fetchall()
        return [Place(**dict(r)) for r in rows]

    def find_by_name(self, name: str) -> Optional[Place]:
        """Find an existing place by exact or case-insensitive name match."""
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT * FROM places WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (name.strip(),),
        ).fetchone()
        if row:
            return Place(**dict(row))
        return None

    def find_nearest(
        self, latitude: float, longitude: float, max_distance_miles: float = 0.5, name_hint: Optional[str] = None
    ) -> Optional[Place]:
        """Find the closest existing place to the given coordinates."""
        from liftassistant.services.trip_service import calculate_haversine_distance_miles
        cursor = self.conn.cursor()
        rows = cursor.execute("SELECT * FROM places WHERE latitude IS NOT NULL AND longitude IS NOT NULL").fetchall()
        closest_place = None
        min_dist = float("inf")

        for r in rows:
            dist = calculate_haversine_distance_miles(latitude, longitude, r["latitude"], r["longitude"])
            if name_hint and name_hint.lower() in r["name"].lower():
                # Strongly prioritize name match if within range
                if dist <= max_distance_miles and dist < min_dist:
                    min_dist = dist
                    closest_place = Place(**dict(r))
            elif dist <= max_distance_miles and dist < min_dist:
                min_dist = dist
                closest_place = Place(**dict(r))

        return closest_place

    def create_place(self, place: Place) -> Place:
        """Insert a new grounded physical place."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO places (id, name, category, address, latitude, longitude, map_url, google_place_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                place.id,
                place.name,
                place.category,
                place.address,
                place.latitude,
                place.longitude,
                place.map_url,
                place.google_place_id,
                place.notes,
            ),
        )
        self.conn.commit()
        return place

    def upsert_place(self, place: Place) -> Place:
        """Insert or update a physical place."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO places (id, name, category, address, latitude, longitude, map_url, google_place_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                category=excluded.category,
                address=excluded.address,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                map_url=excluded.map_url,
                google_place_id=excluded.google_place_id,
                notes=excluded.notes,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                place.id,
                place.name,
                place.category,
                place.address,
                place.latitude,
                place.longitude,
                place.map_url,
                place.google_place_id,
                place.notes,
            ),
        )
        self.conn.commit()
        return place

    def create_closure(self, closure: ResourceClosure) -> ResourceClosure:
        """Record a resource or facility closure."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO resource_closures (id, resource_id, resource_name, start_time, end_time, reason, source, source_reference_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                closure.id,
                closure.resource_id,
                closure.resource_name,
                closure.start_time.isoformat() if isinstance(closure.start_time, datetime) else str(closure.start_time),
                closure.end_time.isoformat() if isinstance(closure.end_time, datetime) else str(closure.end_time),
                closure.reason,
                closure.source,
                closure.source_reference_id,
            ),
        )
        self.conn.commit()
        return closure

    def sync_facility_api_closures(self, closures: List[ResourceClosure]) -> int:
        """Batch insert/replace facility API closures into resource_closures table."""
        cursor = self.conn.cursor()
        saved = 0
        for closure in closures:
            cursor.execute(
                """
                INSERT OR REPLACE INTO resource_closures (id, resource_id, resource_name, start_time, end_time, reason, source, source_reference_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    closure.id,
                    closure.resource_id,
                    closure.resource_name,
                    closure.start_time.isoformat() if isinstance(closure.start_time, datetime) else str(closure.start_time),
                    closure.end_time.isoformat() if isinstance(closure.end_time, datetime) else str(closure.end_time),
                    closure.reason,
                    closure.source or "FACILITY_API",
                    closure.source_reference_id,
                ),
            )
            saved += 1
        self.conn.commit()
        return saved

    def list_closures(self, resource_id: Optional[str] = None) -> List[ResourceClosure]:
        """Fetch all resource closures, optionally filtered by resource_id."""
        cursor = self.conn.cursor()
        if resource_id:
            rows = cursor.execute(
                "SELECT * FROM resource_closures WHERE resource_id = ? ORDER BY start_time ASC",
                (resource_id,),
            ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT * FROM resource_closures ORDER BY start_time ASC"
            ).fetchall()
        return [self._map_row_to_closure(r) for r in rows]

    def find_closures_overlapping(
        self,
        start_time: datetime,
        end_time: datetime,
        resource_id: Optional[str] = None,
        resource_name: Optional[str] = None,
    ) -> List[ResourceClosure]:
        """Find any closure overlapping [start_time, end_time] for a given resource."""
        cursor = self.conn.cursor()
        start_iso = start_time.isoformat() if isinstance(start_time, datetime) else str(start_time)
        end_iso = end_time.isoformat() if isinstance(end_time, datetime) else str(end_time)

        query = """
            SELECT * FROM resource_closures
            WHERE start_time < ? AND end_time > ?
        """
        params = [end_iso, start_iso]
        if resource_id:
            query += " AND resource_id = ?"
            params.append(resource_id)
        elif resource_name:
            query += " AND LOWER(resource_name) LIKE ?"
            params.append(f"%{resource_name.strip().lower()}%")

        rows = cursor.execute(query, tuple(params)).fetchall()
        return [self._map_row_to_closure(r) for r in rows]

    def delete_closure(self, closure_id: str) -> bool:
        """Delete a resource closure by ID."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM resource_closures WHERE id = ?", (closure_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _map_row_to_closure(row: Any) -> ResourceClosure:
        from datetime import datetime
        st = datetime.fromisoformat(row["start_time"]) if isinstance(row["start_time"], str) else row["start_time"]
        et = datetime.fromisoformat(row["end_time"]) if isinstance(row["end_time"], str) else row["end_time"]
        ct = datetime.fromisoformat(row["created_at"]) if "created_at" in row.keys() and isinstance(row["created_at"], str) else datetime.now()
        return ResourceClosure(
            id=row["id"],
            resource_id=row["resource_id"],
            resource_name=row["resource_name"],
            start_time=st,
            end_time=et,
            reason=row["reason"],
            source=row["source"],
            source_reference_id=row["source_reference_id"],
            created_at=ct,
        )


class GeneratorRunRepository:
    """Repository for managing autonomous generator execution runs, event audit feedback, and iterative prompt rules."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_run(self, run: GeneratorRun) -> GeneratorRun:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO generator_runs (
                id, generator_type, started_at, completed_at, status, scanned_count, created_count, error_message, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.generator_type,
                run.started_at.isoformat() if run.started_at else datetime.now().isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
                run.status,
                run.scanned_count,
                run.created_count,
                run.error_message,
                run.details_json,
            ),
        )
        self.conn.commit()
        return run

    def update_run(self, run: GeneratorRun) -> GeneratorRun:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE generator_runs
            SET completed_at = ?,
                status = ?,
                scanned_count = ?,
                created_count = ?,
                error_message = ?,
                details_json = ?
            WHERE id = ?
            """,
            (
                run.completed_at.isoformat() if run.completed_at else datetime.now().isoformat(),
                run.status,
                run.scanned_count,
                run.created_count,
                run.error_message,
                run.details_json,
                run.id,
            ),
        )
        self.conn.commit()
        return run

    def get_run(self, run_id: str) -> Optional[GeneratorRun]:
        cursor = self.conn.cursor()
        row = cursor.execute("SELECT * FROM generator_runs WHERE id = ?", (run_id,)).fetchone()
        return self._map_row_to_run(row) if row else None

    def list_runs(
        self, generator_type: Optional[str] = None, limit: int = 50
    ) -> List[GeneratorRun]:
        cursor = self.conn.cursor()
        if generator_type and generator_type != "ALL":
            rows = cursor.execute(
                """
                SELECT * FROM generator_runs
                WHERE generator_type = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (generator_type, limit),
            ).fetchall()
        else:
            rows = cursor.execute(
                """
                SELECT * FROM generator_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._map_row_to_run(r) for r in rows]

    def get_run_feedbacks(self, run_id: str) -> List[GeneratorEventFeedback]:
        """Fetch all events and feedback items created during a specific execution run."""
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT fb.*,
                   COALESCE(e.title, rc.reason, fb.email_subject) AS event_title,
                   COALESCE(e.event_type, CASE WHEN fb.event_id LIKE 'cls_%' OR fb.llm_category = 'FACILITY_CLOSURE' THEN 'FACILITY_CLOSURE' ELSE 'CUSTOM' END) AS event_type,
                   COALESCE(e.scheduled_at, rc.start_time) AS scheduled_at,
                   COALESCE(e.deadline, rc.end_time) AS deadline,
                   COALESCE(sd.total_amount, dd.total_amount, 0.0) AS total_amount,
                   rc.resource_name AS closure_facility_name,
                   rc.start_time AS closure_start,
                   rc.end_time AS closure_end,
                   rc.reason AS closure_reason,
                   pl.address AS closure_facility_address
            FROM generator_event_feedback fb
            LEFT JOIN events e ON fb.event_id = e.id
            LEFT JOIN shopping_details sd ON e.id = sd.event_id
            LEFT JOIN dining_details dd ON e.id = dd.event_id
            LEFT JOIN resource_closures rc ON fb.event_id = rc.id
            LEFT JOIN places pl ON rc.resource_id = pl.id
            WHERE fb.run_id = ?
            ORDER BY fb.created_at DESC
            """,
            (run_id,),
        ).fetchall()
        return [self._map_row_to_feedback(r) for r in rows]


    def get_latest_run(self, generator_type: str = "EMAIL_EVENT_GENERATOR") -> Optional[GeneratorRun]:
        cursor = self.conn.cursor()
        row = cursor.execute(
            """
            SELECT * FROM generator_runs
            WHERE generator_type = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (generator_type,),
        ).fetchone()
        return self._map_row_to_run(row) if row else None

    def create_or_update_feedback(self, feedback: GeneratorEventFeedback) -> GeneratorEventFeedback:
        cursor = self.conn.cursor()
        existing = None

        target_event_id = feedback.event_id
        if feedback.user_status in ("SKIPPED",) or feedback.llm_category in ("SKIP", "PROMOTION"):
            target_event_id = None

        # Check existing feedback strictly within the SAME worker run.
        # This guarantees subsequent runs insert new feedback linked to their own run_id
        # instead of overwriting/mutating historical feedback from previous runs!
        if feedback.run_id:
            if feedback.id:
                existing = cursor.execute(
                    "SELECT id, user_correction_reason FROM generator_event_feedback WHERE id = ? AND run_id = ?",
                    (feedback.id, feedback.run_id),
                ).fetchone()
            if not existing and target_event_id:
                existing = cursor.execute(
                    "SELECT id, user_correction_reason FROM generator_event_feedback WHERE run_id = ? AND event_id = ?",
                    (feedback.run_id, target_event_id),
                ).fetchone()
            if not existing and feedback.source_reference_id:
                existing = cursor.execute(
                    "SELECT id, user_correction_reason FROM generator_event_feedback WHERE run_id = ? AND source_reference_id = ?",
                    (feedback.run_id, feedback.source_reference_id),
                ).fetchone()
        elif feedback.id:
            existing = cursor.execute(
                "SELECT id, user_correction_reason FROM generator_event_feedback WHERE id = ?",
                (feedback.id,),
            ).fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE generator_event_feedback
                SET event_id = ?,
                    run_id = COALESCE(?, run_id),
                    llm_category = ?,
                    llm_reason = ?,
                    raw_json = ?,
                    user_status = ?,
                    user_correction_reason = COALESCE(?, user_correction_reason),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    target_event_id,
                    feedback.run_id,
                    feedback.llm_category,
                    feedback.llm_reason,
                    feedback.raw_json,
                    feedback.user_status,
                    feedback.user_correction_reason,
                    existing["id"],
                ),
            )
            feedback.id = existing["id"]
            feedback.event_id = target_event_id
        else:
            feedback_id = feedback.id or f"fb_{uuid4().hex[:8]}"
            feedback.id = feedback_id
            feedback.event_id = target_event_id
            cursor.execute(
                """
                INSERT INTO generator_event_feedback (
                    id, event_id, run_id, source_reference_id, email_subject, email_from, email_date,
                    llm_category, llm_reason, raw_json, user_status, user_correction_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    feedback.id,
                    feedback.event_id,
                    feedback.run_id,
                    feedback.source_reference_id,
                    feedback.email_subject,
                    feedback.email_from,
                    feedback.email_date,
                    feedback.llm_category,
                    feedback.llm_reason,
                    feedback.raw_json,
                    feedback.user_status,
                    feedback.user_correction_reason,
                ),
            )
        self.conn.commit()
        return feedback

    def get_feedback_by_event(self, event_id: str) -> Optional[GeneratorEventFeedback]:
        cursor = self.conn.cursor()
        row = cursor.execute(
            """
            SELECT fb.*,
                   COALESCE(e.title, rc.reason, fb.email_subject) AS event_title,
                   COALESCE(e.event_type, CASE WHEN fb.event_id LIKE 'cls_%' OR fb.llm_category = 'FACILITY_CLOSURE' THEN 'FACILITY_CLOSURE' ELSE 'CUSTOM' END) AS event_type,
                   COALESCE(e.scheduled_at, rc.start_time) AS scheduled_at,
                   COALESCE(e.deadline, rc.end_time) AS deadline,
                   COALESCE(sd.total_amount, dd.total_amount, 0.0) AS total_amount,
                   rc.resource_name AS closure_facility_name,
                   rc.start_time AS closure_start,
                   rc.end_time AS closure_end,
                   rc.reason AS closure_reason,
                   pl.address AS closure_facility_address
            FROM generator_event_feedback fb
            LEFT JOIN events e ON fb.event_id = e.id
            LEFT JOIN shopping_details sd ON e.id = sd.event_id
            LEFT JOIN dining_details dd ON e.id = dd.event_id
            LEFT JOIN resource_closures rc ON fb.event_id = rc.id
            LEFT JOIN places pl ON rc.resource_id = pl.id
            WHERE fb.event_id = ?
            """,
            (event_id,),
        ).fetchone()
        return self._map_row_to_feedback(row) if row else None

    def list_feedbacks(self, limit: int = 100) -> List[GeneratorEventFeedback]:
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT fb.*,
                   COALESCE(e.title, rc.reason, fb.email_subject) AS event_title,
                   COALESCE(e.event_type, CASE WHEN fb.event_id LIKE 'cls_%' OR fb.llm_category = 'FACILITY_CLOSURE' THEN 'FACILITY_CLOSURE' ELSE 'CUSTOM' END) AS event_type,
                   COALESCE(e.scheduled_at, rc.start_time) AS scheduled_at,
                   COALESCE(e.deadline, rc.end_time) AS deadline,
                   COALESCE(sd.total_amount, dd.total_amount, 0.0) AS total_amount,
                   rc.resource_name AS closure_facility_name,
                   rc.start_time AS closure_start,
                   rc.end_time AS closure_end,
                   rc.reason AS closure_reason,
                   pl.address AS closure_facility_address
            FROM generator_event_feedback fb
            LEFT JOIN events e ON fb.event_id = e.id
            LEFT JOIN shopping_details sd ON e.id = sd.event_id
            LEFT JOIN dining_details dd ON e.id = dd.event_id
            LEFT JOIN resource_closures rc ON fb.event_id = rc.id
            LEFT JOIN places pl ON rc.resource_id = pl.id
            WHERE fb.id IN (
                SELECT f2.id
                FROM generator_event_feedback f2
                GROUP BY COALESCE(f2.source_reference_id, f2.id)
                HAVING f2.updated_at = MAX(f2.updated_at)
            )
            ORDER BY fb.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._map_row_to_feedback(r) for r in rows]

    def update_feedback_status(
        self,
        event_id: str,
        status: str,
        user_reason: Optional[str] = None,
        append_reason: bool = True,
        feedback_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Optional[GeneratorEventFeedback]:
        cursor = self.conn.cursor()

        # Locate target feedback row(s) to update/append
        if feedback_id:
            rows = cursor.execute(
                "SELECT id, user_correction_reason FROM generator_event_feedback WHERE id = ?",
                (feedback_id,),
            ).fetchall()
        elif run_id:
            rows = cursor.execute(
                "SELECT id, user_correction_reason FROM generator_event_feedback WHERE run_id = ? AND (event_id = ? OR source_reference_id = ?)",
                (run_id, event_id, event_id),
            ).fetchall()
            if not rows:
                rows = cursor.execute(
                    "SELECT id, user_correction_reason FROM generator_event_feedback WHERE event_id = ? OR source_reference_id = ?",
                    (event_id, event_id),
                ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT id, user_correction_reason FROM generator_event_feedback WHERE event_id = ? OR source_reference_id = ?",
                (event_id, event_id),
            ).fetchall()

        for r in rows:
            existing_reason = r["user_correction_reason"]
            final_reason = user_reason
            if append_reason and existing_reason and user_reason and user_reason not in existing_reason:
                final_reason = f"{existing_reason} | {user_reason}"
            elif not final_reason:
                final_reason = existing_reason

            cursor.execute(
                """
                UPDATE generator_event_feedback
                SET user_status = ?,
                    user_correction_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, final_reason, r["id"]),
            )
        self.conn.commit()
        return self.get_feedback_by_event(event_id)

    def add_learned_rule(self, rule: LearnedPromptRule) -> LearnedPromptRule:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO learned_prompt_rules (
                id, generator_type, rule_type, user_feedback, prompt_instruction, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                rule.id,
                rule.generator_type,
                rule.rule_type,
                rule.user_feedback,
                rule.prompt_instruction,
                int(rule.is_active),
            ),
        )
        self.conn.commit()
        return rule

    def list_learned_rules(
        self, generator_type: str = "EMAIL_EVENT_GENERATOR", only_active: bool = False
    ) -> List[LearnedPromptRule]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM learned_prompt_rules WHERE generator_type = ?"
        params: List[Any] = [generator_type]
        if only_active:
            query += " AND is_active = 1"
        query += " ORDER BY created_at ASC"
        rows = cursor.execute(query, tuple(params)).fetchall()
        return [self._map_row_to_rule(r) for r in rows]

    def delete_learned_rule(self, rule_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM learned_prompt_rules WHERE id = ?", (rule_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def toggle_learned_rule(self, rule_id: str, is_active: bool) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE learned_prompt_rules SET is_active = ? WHERE id = ?",
            (int(is_active), rule_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _map_row_to_run(row: Any) -> GeneratorRun:
        st = datetime.fromisoformat(row["started_at"]) if isinstance(row["started_at"], str) else row["started_at"]
        ct = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] and isinstance(row["completed_at"], str) else None
        return GeneratorRun(
            id=row["id"],
            generator_type=row["generator_type"],
            started_at=st,
            completed_at=ct,
            status=row["status"],
            scanned_count=row["scanned_count"],
            created_count=row["created_count"],
            error_message=row["error_message"],
            details_json=row["details_json"],
        )

    @staticmethod
    def _map_row_to_feedback(row: Any) -> GeneratorEventFeedback:
        row_keys = set(row.keys())
        cat = datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"]
        uat = datetime.fromisoformat(row["updated_at"]) if isinstance(row["updated_at"], str) else row["updated_at"]

        sched_dt = None
        if "scheduled_at" in row_keys and row["scheduled_at"]:
            sched_dt = datetime.fromisoformat(row["scheduled_at"]) if isinstance(row["scheduled_at"], str) else row["scheduled_at"]

        due_dt = None
        if "deadline" in row_keys and row["deadline"]:
            due_dt = datetime.fromisoformat(row["deadline"]) if isinstance(row["deadline"], str) else row["deadline"]

        cl_start = None
        if "closure_start" in row_keys and row["closure_start"]:
            cl_start = datetime.fromisoformat(row["closure_start"]) if isinstance(row["closure_start"], str) else row["closure_start"]

        cl_end = None
        if "closure_end" in row_keys and row["closure_end"]:
            cl_end = datetime.fromisoformat(row["closure_end"]) if isinstance(row["closure_end"], str) else row["closure_end"]

        cl_name = row["closure_facility_name"] if "closure_facility_name" in row_keys else None
        cl_reason = row["closure_reason"] if "closure_reason" in row_keys else None
        cl_address = row["closure_facility_address"] if "closure_facility_address" in row_keys else None

        # Fallback to parsing raw_json if closure fields are empty
        if not cl_name and row["raw_json"]:
            try:
                parsed = json.loads(row["raw_json"])
                is_closure = parsed.get("category") in ["FACILITY_CLOSURE", "CLOSURE"] or (row["event_id"] and str(row["event_id"]).startswith("cls_"))
                if is_closure:
                    cl_name = parsed.get("facility_name") or parsed.get("merchant_name")
                    cl_reason = parsed.get("reason") or parsed.get("event_title")
                    if parsed.get("closure_start") and not cl_start:
                        try:
                            cl_start = datetime.fromisoformat(parsed["closure_start"])
                        except Exception:
                            pass
                    if parsed.get("closure_end") and not cl_end:
                        try:
                            cl_end = datetime.fromisoformat(parsed["closure_end"])
                        except Exception:
                            pass
            except Exception:
                pass

        return GeneratorEventFeedback(
            id=row["id"],
            event_id=row["event_id"],
            run_id=row["run_id"],
            source_reference_id=row["source_reference_id"],
            email_subject=row["email_subject"],
            email_from=row["email_from"],
            email_date=row["email_date"],
            llm_category=row["llm_category"],
            llm_reason=row["llm_reason"],
            raw_json=row["raw_json"],
            user_status=row["user_status"],
            user_correction_reason=row["user_correction_reason"],
            created_at=cat,
            updated_at=uat,
            event_title=row["event_title"] if "event_title" in row_keys else None,
            event_type=row["event_type"] if "event_type" in row_keys else None,
            total_amount=float(row["total_amount"]) if "total_amount" in row_keys and row["total_amount"] is not None else 0.0,
            scheduled_at=sched_dt,
            deadline=due_dt,
            closure_facility_name=cl_name,
            closure_start=cl_start,
            closure_end=cl_end,
            closure_reason=cl_reason,
            closure_facility_address=cl_address,
        )

    @staticmethod
    def _map_row_to_rule(row: Any) -> LearnedPromptRule:
        cat = datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"]
        return LearnedPromptRule(
            id=row["id"],
            generator_type=row["generator_type"],
            rule_type=row["rule_type"],
            user_feedback=row["user_feedback"],
            prompt_instruction=row["prompt_instruction"],
            is_active=bool(row["is_active"]),
            created_at=cat,
        )

