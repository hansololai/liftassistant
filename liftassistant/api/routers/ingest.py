"""Background Document/Receipt Ingestion & SSE Broadcasting Router."""

import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from liftassistant.api.deps import get_db_connection
from liftassistant.db.repository import EventRepository, InventoryRepository, PlaceRepository
from liftassistant.models.domain import DiningDetail, LifeEvent, Place, ShoppingDetail
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.map_service import MapService
from liftassistant.services.receipt_parser import KNOWN_MERCHANTS, ReceiptParser
from liftassistant.services.receipt_service import ReceiptService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingest & SSE"])

# In-memory tracking of recent ingestion jobs
_JOBS_STORE: List[Dict[str, Any]] = [
    {
        "job_id": "job_rec_costco_json",
        "filename": "costco-receipts-09-30-2026-10-02-2026.json",
        "file_hash": "9e4d1f8a2c7b501...",
        "status": "COMPLETED",
        "progress_pct": 100,
        "progress_message": "Complete! 9 items extracted, place grounded to pl_costco.",
        "created_at": "2026-10-02T20:25:00",
        "is_confirmed": False,
        "result": {
            "merchant_name": "Costco Wholesale #328 (Cranberry Twp)",
            "merchant_address": "1050 CRANBERRY SQUARE DR, CRANBERRY TOWNS, PA, 16066, US",
            "place_id": "pl_costco",
            "total_amount": 125.27,
            "subtotal": 125.27,
            "tax_amount": 0.00,
            "transaction_time": "2026-10-02 20:24:00",
            "line_items_count": 9,
            "line_items": [
                {"name": "Kiwi Berries, 1 lb", "quantity": 2, "unit": "pk", "unit_price": 6.99, "total_price": 13.98},
                {"name": "KS KS PRK BELLY", "quantity": 6.78, "unit": "lb", "unit_price": 3.99, "total_price": 27.05},
                {"name": "Kirkland Signature Seasoned Chicken Wings", "quantity": 1, "unit": "ea", "unit_price": 17.51, "total_price": 17.51},
                {"name": "ORG A2 WHOLE MILK 3-PK", "quantity": 1, "unit": "ea", "unit_price": 11.79, "total_price": 11.79, "grocy_product_id": "prod_milk", "grocy_product_name": "Organic Whole Milk"},
                {"name": "KS PAPER TOWELS", "quantity": 1, "unit": "ea", "unit_price": 22.99, "total_price": 22.99},
                {"name": "CJ BULGOGI MANDU", "quantity": 1, "unit": "ea", "unit_price": 14.99, "total_price": 14.99},
                {"name": "/ 1785501 Instant Savings", "quantity": 1, "unit": "ea", "unit_price": -4.50, "total_price": -4.50},
                {"name": "HAITAI CRUNCH BON", "quantity": 1, "unit": "ea", "unit_price": 10.99, "total_price": 10.99},
                {"name": "KS CASHEWS", "quantity": 1, "unit": "ea", "unit_price": 15.47, "total_price": 15.47},
            ],
        },
    },
]


def register_ingestion_job(
    filename: str,
    file_hash: str,
    event_id: Optional[str] = None,
) -> dict:
    """Register a new receipt background parsing job."""
    job_id = f"job_rec_{uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "event_id": event_id,
        "filename": filename,
        "file_hash": file_hash,
        "status": "PROCESSING",
        "progress_pct": 25,
        "progress_message": "Scanning receipt header: Searching printed merchant name & address...",
        "created_at": datetime.now().isoformat(),
    }
    _JOBS_STORE.insert(0, job)
    return job


@router.get("/jobs")
def list_ingestion_jobs(conn: sqlite3.Connection = Depends(get_db_connection)):
    """List active and historical background ingestion worker jobs."""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT r.*, e.title as event_title, p.name as p_name, p.address as p_address
        FROM receipts r
        LEFT JOIN events e ON r.event_id = e.id
        LEFT JOIN places p ON r.place_id = p.id
        ORDER BY r.created_at DESC
        LIMIT 50
    """).fetchall()

    db_jobs = []
    seen_hashes = {j.get("file_hash") for j in _JOBS_STORE if j.get("file_hash")}
    for row in rows:
        row_dict = dict(row)
        f_hash = row_dict.get("file_hash")
        if f_hash in seen_hashes:
            continue
        seen_hashes.add(f_hash)

        items = cursor.execute(
            "SELECT clean_name, quantity, unit, unit_price, total_price FROM receipt_items WHERE receipt_id = ?",
            (row_dict["id"],),
        ).fetchall()

        db_jobs.append({
            "job_id": f"job_db_{row_dict['id'][:8]}",
            "filename": row_dict.get("original_filename") or f"{row_dict['merchant_name']}.json",
            "file_hash": f_hash,
            "status": "COMPLETED",
            "progress_pct": 100,
            "progress_message": f"Recorded on ledger as '{row_dict.get('event_title') or row_dict['merchant_name']}'",
            "created_at": str(row_dict["created_at"]),
            "is_confirmed": True,
            "event_id": row_dict.get("event_id"),
            "result": {
                "merchant_name": row_dict["merchant_name"],
                "merchant_address": row_dict.get("merchant_address") or row_dict.get("p_address") or "",
                "place_id": row_dict.get("place_id"),
                "total_amount": row_dict["total_amount"],
                "subtotal": row_dict.get("subtotal") or row_dict["total_amount"],
                "tax_amount": row_dict.get("tax_amount", 0.0),
                "transaction_time": str(row_dict["transaction_time"]),
                "line_items_count": len(items),
                "line_items": [
                    {
                        "name": it["clean_name"],
                        "quantity": it["quantity"],
                        "unit": it["unit"],
                        "unit_price": it["unit_price"],
                        "total_price": it["total_price"],
                    }
                    for it in items
                ],
            },
        })
    return _JOBS_STORE + db_jobs


@router.post("/upload")
async def upload_receipt_and_create_event(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    """Upload and parse a receipt file (image, PDF, JSON, text).
    
    CRITICAL INGESTION RULE:
    An event can ONLY be created if the receipt is parsed successfully!
    If parsing fails (missing vendor, corrupt payload, or unparseable),
    an HTTP 422 error is returned and NO event is created.
    """
    event_repo = EventRepository(conn)
    inv_repo = InventoryRepository(conn)
    place_repo = PlaceRepository(conn)

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty receipt file provided.",
        )

    filename = file.filename or "receipt.json"
    file_hash = hashlib.sha256(content).hexdigest()

    # Store file in Content-Addressable Storage (CAS)
    cas = CASStorage()
    cas_meta = cas.store_file(content=content, original_filename=filename, mime_type=file.content_type)
    file_path = cas_meta["file_path"]

    parser = ReceiptParser()
    try:
        ext = Path(filename).suffix.lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            source_chan = "PHOTO_CAMERA"
        elif ext == ".json":
            source_chan = "COSTCO_APP_JSON" if "costco" in filename.lower() else "DIGITAL_RECEIPT"
        else:
            source_chan = "DIGITAL_RECEIPT"

        receipts = parser.parse_all_from_file(
            file_path=file_path,
            file_hash=file_hash,
            source_channel=source_chan,
        )
    except Exception as ex:
        logger.warning(f"Receipt parsing error for {filename}: {ex}")
        job_id = f"job_rec_{uuid4().hex[:8]}"
        _JOBS_STORE.insert(0, {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "FAILED",
            "progress_pct": 100,
            "progress_message": f"Parsing failed: {str(ex)}",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": False,
            "error_message": str(ex),
        })
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse receipt: {str(ex)}. Event was NOT created.",
        )

    if not receipts:
        job_id = f"job_rec_{uuid4().hex[:8]}"
        _JOBS_STORE.insert(0, {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "FAILED",
            "progress_pct": 100,
            "progress_message": "No valid receipt data could be parsed from file.",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": False,
            "error_message": "File could not be parsed into receipt items",
        })
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid receipt data could be extracted from file. Event was NOT created.",
        )

    receipt = receipts[0]

    # Strict Ingestion Gate:
    # A receipt is ONLY considered successfully parsed if ALL 3 core criteria are satisfied:
    # 1. Recognized Merchant Name (not null/empty/generic placeholder)
    # 2. Valid Financial Amount (> 0.00) or structured Line Items
    # 3. Valid Transaction Date & Time (not null)
    #
    # An empty or incomplete event with missing title or missing date/time will NEVER be inserted!
    merchant = (receipt.merchant_name or "").strip()
    if not merchant or merchant in ["Unknown", "General Merchant"] or len(merchant) < 2:
        job_id = f"job_rec_{uuid4().hex[:8]}"
        _JOBS_STORE.insert(0, {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "FAILED",
            "progress_pct": 100,
            "progress_message": "Receipt parsing failed: recognized merchant/store name is missing.",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": False,
            "error_message": "Missing recognized merchant name",
        })
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt could not be parsed: missing recognized merchant name. Event was NOT created.",
        )

    if receipt.total_amount <= 0.0 and not receipt.line_items:
        job_id = f"job_rec_{uuid4().hex[:8]}"
        _JOBS_STORE.insert(0, {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "FAILED",
            "progress_pct": 100,
            "progress_message": "Receipt parsing failed: total amount is zero and no line items found.",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": False,
            "error_message": "Zero monetary amount without line items",
        })
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt could not be parsed: total amount must be positive. Event was NOT created.",
        )

    if not receipt.transaction_time:
        job_id = f"job_rec_{uuid4().hex[:8]}"
        _JOBS_STORE.insert(0, {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "FAILED",
            "progress_pct": 100,
            "progress_message": "Receipt parsing failed: transaction date and time could not be determined.",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": False,
            "error_message": "Missing transaction date/time",
        })
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt could not be parsed: missing valid transaction date and time. Event was NOT created.",
        )

    clean_event_id = f"evt_{file_hash[:8]}"

    # Classify preliminary DINING vs SHOPPING keywords
    dining_keywords = [
        "olive garden", "restaurant", "cafe", "café", "bistro", "grill", "bakery",
        "diner", "pizzeria", "steakhouse", "bar & grill", "kitchen", "eatery",
        "ziosk", "table no", "server:", "chipotle", "starbucks", "mcdonald", "burger",
        "dining", "food truck", "tacos", "sushi", "mad mex",
    ]
    is_dining = any(k in merchant.lower() for k in dining_keywords)

    # Ground or resolve Place entity (MANDATORY REQUIREMENT)
    place = None
    if receipt.place_id:
        place = place_repo.get_place(receipt.place_id)
    if not place and merchant:
        for key, info in KNOWN_MERCHANTS.items():
            if key in merchant.lower() or (receipt.merchant_address and key in receipt.merchant_address.lower()):
                place = place_repo.get_place(info["place_id"])
                if not place:
                    place = Place(
                        id=info["place_id"],
                        name=info["name"],
                        category=info.get("category", "dining" if is_dining else "shopping"),
                        address=info.get("address", receipt.merchant_address or "Cranberry Twp, PA"),
                    )
                    place = place_repo.create_place(place)
                break
    if not place and merchant:
        place = place_repo.find_by_name(merchant)
    if not place and merchant:
        matches = place_repo.list_places(search=merchant, limit=1)
        if matches:
            place = matches[0]
    if not place and receipt.merchant_address and len(receipt.merchant_address.strip()) > 5:
        try:
            map_service = MapService(place_repo=place_repo)
            place = map_service.create_grounded_place(
                name=merchant,
                address=receipt.merchant_address.strip(),
                category="dining" if is_dining else "shopping",
            )
        except Exception as e:
            logger.info("Could not auto-ground place via MapService: %s", e)

    # STRICT PLACE GROUNDING GATE:
    # A receipt CANNOT be considered successfully parsed unless a place is found and grounded!
    if not place or not place.id:
        job_id = f"job_rec_{uuid4().hex[:8]}"
        _JOBS_STORE.insert(0, {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "FAILED",
            "progress_pct": 100,
            "progress_message": f"Receipt parsing failed: place '{merchant}' could not be found or grounded to a physical location.",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": False,
            "error_message": f"Place '{merchant}' could not be grounded",
        })
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Receipt could not be parsed: place '{merchant}' could not be found or grounded to a verified physical location. Event was NOT created.",
        )

    # Final category check taking grounded place into account
    if place.category == "dining":
        is_dining = True
    ev_type = "DINING" if is_dining else "SHOPPING"

    title = f"{ev_type.title()}: {place.name or merchant}"
    if receipt.total_amount > 0:
        title += f" (${receipt.total_amount:.2f})"

    # STRICT NOT-NULL GUARANTEE FOR DATABASE EVENT
    tx_dt = receipt.transaction_time
    if not title.strip() or tx_dt is None or not place.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Event title, date/time, and grounded place must not be null. Event was NOT created.",
        )

    event = LifeEvent(
        id=clean_event_id,
        title=title,
        event_type=ev_type,
        scheduled_at=tx_dt,
        scheduled_end_at=tx_dt,
        completed_at=tx_dt,
        place_id=place.id,
        people_involved=["Dad"],
        tax_amount=receipt.tax_amount or 0.0,
        notes=f"Created via receipt upload: {filename} (Grounded Place: {place.name})",
        source=source_chan,
        source_reference_id=file_hash[:16],
    )

    if ev_type == "DINING":
        event.dining_detail = DiningDetail(
            event_id=event.id,
            total_amount=receipt.total_amount,
        )
    else:
        event.shopping_detail = ShoppingDetail(
            event_id=event.id,
            total_amount=receipt.total_amount,
            pantry_updated=True,
        )

    # Commit LifeEvent to database (Idempotent: file hash or semantic receipt match)
    existing_event = event_repo.get_event(clean_event_id)

    # 2. Semantic Receipt Deduplication:
    # If the user snaps another photo of the same receipt, the camera file hash is different,
    # but the physical receipt has the same grounded place and transaction date/time (within ±20 mins).
    if not existing_event and place and place.id and tx_dt:
        cursor = conn.cursor()
        dt_start = (tx_dt - timedelta(minutes=25)).isoformat()
        dt_end = (tx_dt + timedelta(minutes=25)).isoformat()

        # Check receipts table for existing transaction at same place or similar merchant & time
        merchant_keyword = (receipt.merchant_name or "").split()[0].lower() if receipt.merchant_name else ""
        match = cursor.execute("""
            SELECT event_id FROM receipts
            WHERE (place_id = ? OR LOWER(merchant_name) LIKE ?)
              AND transaction_time BETWEEN ? AND ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (place.id, f"%{merchant_keyword}%", dt_start, dt_end)).fetchone()

        if not match:
            # Also check if same time and matching total amount
            match = cursor.execute("""
                SELECT event_id FROM receipts
                WHERE transaction_time BETWEEN ? AND ?
                  AND ABS(total_amount - ?) < 1.00
                ORDER BY created_at DESC
                LIMIT 1
            """, (dt_start, dt_end, receipt.total_amount)).fetchone()

        if match and match[0]:
            matched_evt = event_repo.get_event(match[0])
            if matched_evt:
                existing_event = matched_evt

    if existing_event:
        job_id = f"job_rec_{uuid4().hex[:8]}"
        job_entry = {
            "job_id": job_id,
            "filename": filename,
            "file_hash": file_hash,
            "status": "COMPLETED",
            "progress_pct": 100,
            "progress_message": f"Receipt already ingested on ledger as '{existing_event.title}'.",
            "created_at": datetime.now().isoformat(),
            "is_confirmed": True,
            "event_id": existing_event.id,
            "result": {
                "merchant_name": receipt.merchant_name,
                "merchant_address": receipt.merchant_address or (place.address if place else ""),
                "place_id": existing_event.place_id,
                "total_amount": receipt.total_amount,
                "subtotal": receipt.subtotal,
                "tax_amount": receipt.tax_amount,
                "tip_amount": receipt.tip_amount,
                "transaction_time": str(receipt.transaction_time),
                "line_items_count": len(receipt.line_items),
            },
        }
        _JOBS_STORE.insert(0, job_entry)
        return {
            "success": True,
            "message": f"Receipt already ingested on ledger as '{existing_event.title}'.",
            "event": existing_event.model_dump(),
            "job": job_entry,
        }

    saved_event = event_repo.create_event(event)

    # Bind receipt to event & grounded place, then persist into receipts table
    receipt.event_id = saved_event.id
    receipt.place_id = place.id
    inv_service = InventoryService(inv_repo)
    rec_service = ReceiptService(conn=conn, inventory_service=inv_service)
    rec_service.persist_receipt(receipt, auto_restock=True)

    job_id = f"job_rec_{uuid4().hex[:8]}"
    job_entry = {
        "job_id": job_id,
        "filename": filename,
        "file_hash": file_hash,
        "status": "COMPLETED",
        "progress_pct": 100,
        "progress_message": f"Complete! Event '{saved_event.title}' created and logged to ledger.",
        "created_at": datetime.now().isoformat(),
        "is_confirmed": True,
        "event_id": saved_event.id,
        "result": {
            "merchant_name": receipt.merchant_name,
            "merchant_address": receipt.merchant_address or (place.address if place else ""),
            "place_id": saved_event.place_id,
            "total_amount": receipt.total_amount,
            "subtotal": receipt.subtotal,
            "tax_amount": receipt.tax_amount,
            "transaction_time": receipt.transaction_time.isoformat() if receipt.transaction_time else datetime.now().isoformat(),
            "line_items_count": len(receipt.line_items),
            "line_items": [it.model_dump() for it in receipt.line_items],
        },
    }
    _JOBS_STORE.insert(0, job_entry)

    return {
        "success": True,
        "message": f"Receipt parsed successfully! Event '{saved_event.title}' created on ledger.",
        "event": saved_event.model_dump(),
        "receipt": receipt.model_dump(),
        "job": job_entry,
    }


async def sse_event_generator() -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events (SSE) for job progress updates and ledger mutations."""
    yield f"data: {json.dumps({'event': 'CONNECTED', 'message': 'SSE live stream connected'})}\n\n"

    try:
        while True:
            await asyncio.sleep(20)
            yield f": keep-alive heartbeat\n\n"
    except asyncio.CancelledError:
        pass


@router.get("/jobs/stream")
async def stream_ingest_progress():
    """Real-time SSE event stream for worker progress, ledger invalidations, and conflict alerts."""
    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
