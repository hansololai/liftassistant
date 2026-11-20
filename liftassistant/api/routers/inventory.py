"""Grocy Inventory & Fridge Door Pad API Router.
Validates requests and delegates all business logic to InventoryService.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from liftassistant.api.deps import get_inventory_service
from liftassistant.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["Inventory"])


class ConsumeRequest(BaseModel):
    amount: Optional[float] = Field(None, gt=0, description="Optional positive override consumption amount")


class CreateProductRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Product display name")
    category: str = Field("pantry", description="Category: dairy, produce, meat, household, pantry, etc.")
    qu_stock_id: str = Field("ea", description="Stock / consumption unit, e.g. roll, gal, egg, item, can")
    qu_purchase_id: str = Field("pack", description="Store purchase unit, e.g. pack, box, case, tub")
    qu_factor: float = Field(1.0, gt=0, description="Multiplier: 1 purchase unit = qu_factor stock units")
    initial_stock: float = Field(0.0, ge=0, description="Initial stock in stock units")
    daily_burn_rate: float = Field(0.0, ge=0, description="Estimated daily consumption rate")
    store_name: Optional[str] = Field("Costco", description="Preferred purchase store")
    receipt_raw_text: Optional[str] = Field(None, description="Receipt line-item text for auto-matching")
    is_fridge_quick_tile: bool = Field(False, description="Pin to Fridge Door Pad")
    consume_step: float = Field(1.0, gt=0, description="Fridge pad decrement amount per tap")
    consume_step_label: Optional[str] = None
    notes: Optional[str] = None


@router.get("/products")
def list_products(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """List inventory products with burn rates and computed days of runway (envelope format)."""
    return inventory_service.list_products(limit=limit, offset=offset)


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(
    payload: CreateProductRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Create a new product in pantry inventory with Grocy bulk unit multiplier."""
    try:
        return inventory_service.create_product(
            name=payload.name,
            category=payload.category,
            qu_stock_id=payload.qu_stock_id,
            qu_purchase_id=payload.qu_purchase_id,
            qu_factor=payload.qu_factor,
            initial_stock=payload.initial_stock,
            daily_burn_rate=payload.daily_burn_rate,
            store_name=payload.store_name,
            receipt_raw_text=payload.receipt_raw_text,
            is_fridge_quick_tile=payload.is_fridge_quick_tile,
            consume_step=payload.consume_step,
            consume_step_label=payload.consume_step_label,
            notes=payload.notes,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get("/transactions")
def list_transactions(
    product_id: Optional[str] = Query(None, description="Optional product filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """List double-entry stock transactions with pagination envelope (result, total_count, start_index, end_index, has_more)."""
    return inventory_service.list_transactions(product_id=product_id, limit=limit, offset=offset)


@router.post("/products/{product_id}/consume")
def consume_product_stock(
    product_id: str,
    payload: ConsumeRequest = ConsumeRequest(),
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """1-Tap Fridge Door Pad decrement via InventoryService."""
    try:
        return inventory_service.fridge_door_pad_consume(product_id, amount=payload.amount)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))


@router.post("/products/{product_id}/undo-consume")
def undo_product_consumption(
    product_id: str,
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Undo accidental fridge pad tap via InventoryService."""
    try:
        return inventory_service.undo_consumption(product_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))


class ItemMultiplierRequest(BaseModel):
    store: str = Field(..., min_length=1, description="Store name, e.g. Costco")
    item: str = Field(..., min_length=1, description="Receipt item or product name")
    multiplier: float = Field(..., gt=0, description="Stock units per purchase package")
    product_id: Optional[str] = Field(None, description="Optional foreign key to products table")


@router.get("/multipliers")
def list_multipliers(
    store: Optional[str] = Query(None, description="Optional store filter"),
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """List (store, item, multiplier, product_id) mappings."""
    return inventory_service.list_item_multipliers(store=store)


@router.post("/multipliers")
def upsert_multiplier(
    payload: ItemMultiplierRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Save or update (store, item, multiplier, product_id) packaging rule."""
    try:
        return inventory_service.upsert_item_multiplier(
            store=payload.store,
            item=payload.item,
            multiplier=payload.multiplier,
            product_id=payload.product_id,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get("/conversions")
def list_conversions(inventory_service: InventoryService = Depends(get_inventory_service)):
    """List purchase-to-stock bulk multipliers (e.g. Costco 1 pack = 36 rolls)."""
    return inventory_service.list_conversions()


@router.get("/proposals")
def list_depletion_proposals(inventory_service: InventoryService = Depends(get_inventory_service)):
    """List pending depletion proposals awaiting approval at the Confirmation Gate."""
    return inventory_service.list_depletion_proposals()


@router.post("/proposals/{proposal_id}/confirm")
def confirm_proposal(
    proposal_id: str,
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Approve depletion proposal and deduct from stock ledger."""
    return inventory_service.confirm_depletion_proposal(proposal_id)


@router.post("/proposals/{proposal_id}/dismiss")
def dismiss_proposal(
    proposal_id: str,
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Reject/dismiss depletion proposal without deducting stock."""
    return inventory_service.dismiss_depletion(proposal_id)
