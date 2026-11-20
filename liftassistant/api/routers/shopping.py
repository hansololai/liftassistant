"""7-Day Rolling Horizon Shopping List API Router.
Validates requests and delegates shopping list management to InventoryService.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from liftassistant.api.deps import get_inventory_service
from liftassistant.services.inventory_service import InventoryService

router = APIRouter(prefix="/shopping", tags=["Shopping List"])


@router.get("")
@router.get("/shopping-list")
def get_shopping_list(
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Fetch 7-day rolling horizon items that have runway < 7 days."""
    return inventory_service.get_formatted_shopping_list(runway_threshold_days=7.0)


@router.post("/{item_id}/toggle")
def toggle_shopping_item(
    item_id: str,
    inventory_service: InventoryService = Depends(get_inventory_service),
):
    """Toggle checked state for a shopping list item."""
    updated = inventory_service.toggle_shopping_item(item_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shopping item '{item_id}' not found.",
        )
    return updated
