"""Background Document/Receipt Ingestion & SSE Broadcasting Router."""

import asyncio
import json
from typing import AsyncGenerator, Optional
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/ingest", tags=["Ingest & SSE"])

# In-memory tracking of recent ingestion jobs
_JOBS_STORE = [
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
    {
        "job_id": "job_rec_9182",
        "filename": "wholefoods_dinner_nov8.jpg",
        "status": "PROCESSING",
        "progress_pct": 65,
        "progress_message": "Extracting line items & tip with Gemini Vision...",
        "created_at": "2026-11-09T00:30:00",
        "is_confirmed": False,
    },
    {
        "job_id": "job_rec_9181",
        "filename": "costco_inwarehouse_nov7.csv",
        "status": "COMPLETED",
        "progress_pct": 100,
        "progress_message": "Complete! 14 items itemized & confirmed to ledger.",
        "created_at": "2026-11-07T14:15:00",
        "is_confirmed": True,
        "result": {
            "merchant_name": "Costco Wholesale #1024",
            "total_amount": 142.10,
            "line_items_count": 14,
        },
    },
]


def register_ingestion_job(
    filename: str,
    file_hash: str,
    event_id: Optional[str] = None,
) -> dict:
    """Register a new receipt background parsing job."""
    from uuid import uuid4
    from datetime import datetime
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
def list_ingestion_jobs():
    """List active and historical background ingestion worker jobs."""
    return _JOBS_STORE


async def sse_event_generator() -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events (SSE) for job progress updates and ledger mutations."""
    # Send initial connection handshake event
    yield f"data: {json.dumps({'event': 'CONNECTED', 'message': 'SSE live stream connected'})}\n\n"

    # Periodic heartbeat / notification simulation
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
