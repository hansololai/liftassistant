"""LiftAssistant 3.0 Domain Models (Pydantic v2)."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field


class Place(BaseModel):
    id: str = Field(default_factory=lambda: f"pl_{uuid4().hex[:8]}")
    name: str
    category: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    map_url: Optional[str] = None
    google_place_id: Optional[str] = None
    notes: Optional[str] = None


class ResourceClosure(BaseModel):
    id: str = Field(default_factory=lambda: f"cls_{uuid4().hex[:8]}")
    resource_id: Optional[str] = None
    resource_name: str
    start_time: datetime
    end_time: datetime
    reason: Optional[str] = None
    source: str = "AGENT_GMAIL"
    source_reference_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class HouseholdEquipment(BaseModel):
    id: str = Field(default_factory=lambda: f"eq_{uuid4().hex[:8]}")
    name: str
    category: str  # vehicle, appliance, hvac, plumbing
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    notes: Optional[str] = None



# --- Polymorphic Detail Models (Approach 2) ---

class DiningDetail(BaseModel):
    event_id: str = ""
    event_type: str = "DINING"
    rating: Optional[int] = Field(None, ge=1, le=5)
    total_amount: float = 0.0


class ShoppingDetail(BaseModel):
    event_id: str = ""
    event_type: str = "SHOPPING"
    store_name: Optional[str] = None
    merchant_name: Optional[str] = None
    merchant_address: Optional[str] = None
    receipt_id: Optional[str] = None
    receipt_image_path: Optional[str] = None
    receipt_file_url: Optional[str] = None
    original_filename: Optional[str] = None
    pantry_updated: bool = False
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: float = 0.0
    line_items: List[Dict[str, Any]] = Field(default_factory=list)


class MaintenanceDetail(BaseModel):
    event_id: str = ""
    event_type: str = "MAINTENANCE"
    equipment_id: str = ""
    service_type: Optional[str] = None
    next_due_interval_days: Optional[int] = None
    next_due_miles: Optional[int] = None


class LifeEvent(BaseModel):
    """Core temporal continuum event model."""
    id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:8]}")
    title: str
    event_type: str  # DINING, SHOPPING, MAINTENANCE, MEDICAL, TRAVEL, CUSTOM
    scheduled_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    all_day: bool = False
    place_id: Optional[str] = None
    studio: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    people_involved: List[str] = Field(default_factory=list)
    tax_amount: float = 0.0
    notes: Optional[str] = None
    source: str = "MANUAL"
    source_reference_id: Optional[str] = None
    has_conflict: bool = False
    conflict_status: Optional[str] = None
    conflict_reason: Optional[str] = None
    generator_run_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Polymorphic joined extensions (loaded via relational joins)
    dining_detail: Optional[DiningDetail] = None
    shopping_detail: Optional[ShoppingDetail] = None
    maintenance_detail: Optional[MaintenanceDetail] = None
    place: Optional[Place] = None


class EventGenerator(BaseModel):
    """Recurring rule generator for periodic obligations with deadlines."""
    id: str = Field(default_factory=lambda: f"gen_{uuid4().hex[:8]}")
    title: str
    event_type: str
    frequency: str = "YEARLY"  # YEARLY, MONTHLY, WEEKLY, DAILY
    interval: int = 1
    by_month: Optional[int] = None
    by_month_day: Optional[int] = None
    by_weekday: Optional[str] = None
    anchor_date: date
    lead_time_days: int = 14
    has_deadline: bool = True
    deadline_offset_days: int = 0
    deadline_time: str = "23:59:59"
    place_id: Optional[str] = None
    start_time: str = "09:00"
    duration_minutes: int = 60
    people_involved: List[str] = Field(default_factory=list)
    estimated_amount: float = 0.0
    notes: Optional[str] = None
    is_active: bool = True
    last_generated_date: Optional[date] = None


class GeneratorRun(BaseModel):
    """Execution run record for autonomous background generators (e.g. daily email worker)."""
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:8]}")
    generator_type: str = "EMAIL_EVENT_GENERATOR"
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"  # RUNNING, SUCCESS, FAILED
    scanned_count: int = 0
    created_count: int = 0
    error_message: Optional[str] = None
    details_json: Optional[str] = None


class GeneratorEventFeedback(BaseModel):
    """Perception review and correction record for an event produced by a generator."""
    id: str = Field(default_factory=lambda: f"fb_{uuid4().hex[:8]}")
    event_id: Optional[str] = None
    run_id: Optional[str] = None
    source_reference_id: Optional[str] = None
    email_subject: Optional[str] = None
    email_from: Optional[str] = None
    email_date: Optional[str] = None
    llm_category: Optional[str] = None
    llm_reason: Optional[str] = None
    raw_json: Optional[str] = None
    user_status: str = "PENDING"  # PENDING, ACCEPTED, MODIFIED, REMOVED
    user_correction_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Joined fields for UI convenience
    event_title: Optional[str] = None
    event_type: Optional[str] = None
    total_amount: Optional[float] = None
    scheduled_at: Optional[datetime] = None
    deadline: Optional[datetime] = None

    # Joined Facility Closure fields for preview
    closure_facility_name: Optional[str] = None
    closure_start: Optional[datetime] = None
    closure_end: Optional[datetime] = None
    closure_reason: Optional[str] = None
    closure_facility_address: Optional[str] = None


class LearnedPromptRule(BaseModel):
    """Iteratively learned prompt instruction synthesized from user correction feedback."""
    id: str = Field(default_factory=lambda: f"rule_{uuid4().hex[:8]}")
    generator_type: str = "EMAIL_EVENT_GENERATOR"
    rule_type: str = "NEGATIVE"  # NEGATIVE, POSITIVE, GENERAL
    user_feedback: str
    prompt_instruction: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)



# --- Grocy Inventory & Conversion Models ---

class Product(BaseModel):
    id: str = Field(default_factory=lambda: f"prod_{uuid4().hex[:8]}")
    name: str
    category: str
    default_location_id: Optional[str] = None
    default_place_id: Optional[str] = None
    qu_purchase_id: Optional[str] = None
    qu_stock_id: Optional[str] = None
    qu_factor: float = 1.0  # Bulk purchase multiplier
    consume_step: float = 1.0
    consume_step_label: Optional[str] = None
    is_fridge_quick_tile: bool = False
    min_stock_amount: float = 1.0
    daily_burn_rate: float = 0.0
    auto_add_to_shopping_list: bool = True
    notes: Optional[str] = None



class ProductUnitConversion(BaseModel):
    id: str = Field(default_factory=lambda: f"conv_{uuid4().hex[:8]}")
    product_id: str
    store_name: str
    receipt_raw_text: str
    purchase_unit: str
    stock_unit: str
    unit_multiplier: float


class StockBatch(BaseModel):
    id: str = Field(default_factory=lambda: f"stk_{uuid4().hex[:8]}")
    product_id: str
    amount: float
    location_id: Optional[str] = None
    purchased_event_id: Optional[str] = None
    price: Optional[float] = None
    best_before_date: Optional[date] = None


class StockTransaction(BaseModel):
    id: str = Field(default_factory=lambda: f"tx_{uuid4().hex[:8]}")
    product_id: str
    transaction_type: str  # PURCHASE_RECEIPT, FRIDGE_PAD_CONSUME, CONFIRMED_DEPLETION, RESTOCK_UNDO
    amount: float
    unit: str
    source: str
    reference_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class DepletionProposal(BaseModel):
    id: str = Field(default_factory=lambda: f"dep_{uuid4().hex[:8]}")
    product_id: str
    proposed_amount: float
    unit: str
    reason: str
    confidence_score: float = 0.9
    status: str = "PENDING"  # PENDING, CONFIRMED, DISMISSED


class ShoppingListItem(BaseModel):
    id: str = Field(default_factory=lambda: f"shop_{uuid4().hex[:8]}")
    product_id: Optional[str] = None
    item_name: str
    category: Optional[str] = None
    amount: float = 1.0
    qu_id: Optional[str] = None
    target_place_id: Optional[str] = None
    status: str = "PENDING"
    source: str = "AUTO_HORIZON"
    checked: bool = False


class Trip(BaseModel):
    id: str = Field(default_factory=lambda: f"trip_{uuid4().hex[:8]}")
    name: str
    start_date: date
    end_date: date
    budget: float = 0.0
    spent: float = 0.0
    geofence_center_lat: float = 40.6873
    geofence_center_lng: float = -80.1078
    inverted_geofence_radius_miles: float = 30.0
    notes: Optional[str] = None



class TripStop(BaseModel):
    id: str = Field(default_factory=lambda: f"stop_{uuid4().hex[:8]}")
    trip_id: str
    name: str
    stop_date: Optional[date] = None
    category: Optional[str] = None
    spent: float = 0.0
    notes: Optional[str] = None
    order_index: int = 0


class Conflict(BaseModel):
    id: str = Field(default_factory=lambda: f"cfl_{uuid4().hex[:8]}")
    event_id: str
    event_title: str
    conflict_type: str  # FACILITY_MUTEX, TRAVEL_BUFFER, PERSON_OVERLAP, POLICY_BLACKOUT
    severity: str = "HIGH"  # HIGH, MEDIUM, LOW
    title: str
    description: str
    suggested_action: str
    status: str = "DETECTED"  # DETECTED, ACKNOWLEDGED, RESOLVED


# --- CAS Receipt Ingestion Models ---

class ReceiptLineItem(BaseModel):
    id: str = Field(default_factory=lambda: f"item_{uuid4().hex[:8]}")
    receipt_id: Optional[str] = None
    raw_text: str
    clean_name: str
    category: str = "general"
    quantity: float = 1.0
    unit: str = "ea"
    unit_price: Optional[float] = None
    total_price: float
    product_id: Optional[str] = None


class StandardizedReceipt(BaseModel):
    id: str = Field(default_factory=lambda: f"rec_{uuid4().hex[:8]}")
    event_id: Optional[str] = None
    place_id: Optional[str] = None
    studio: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    file_hash: str
    file_path: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    merchant_name: str
    merchant_address: Optional[str] = None
    transaction_time: Optional[datetime] = None
    subtotal: Optional[float] = 0.0
    tax_amount: float = 0.0
    tip_amount: float = 0.0
    total_amount: float
    currency: str = "USD"
    category: Optional[str] = None  # "DINING" or "SHOPPING"
    source_channel: str = "PHOTO_CAMERA"
    source_reference_id: Optional[str] = None
    raw_ocr_json: Optional[str] = None
    parsing_status: str = "SUCCESS"
    parsing_error: Optional[str] = None
    line_items: List[ReceiptLineItem] = Field(default_factory=list)


class ReceiptJob(BaseModel):
    job_id: str = Field(default_factory=lambda: f"job_rec_{uuid4().hex[:8]}")
    event_id: Optional[str] = None
    file_hash: str
    filename: str
    status: str = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED
    progress_pct: int = 0
    progress_message: str = "Queued for processing"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    error_message: Optional[str] = None
    result: Optional[StandardizedReceipt] = None


