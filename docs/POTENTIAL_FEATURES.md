# 💡 LiftAssistant: Potential & Backlog Features

This document tracks approved potential enhancements and future roadmap items for LiftAssistant.

---

## 1. Pantry Stock Transaction History (Audit Trail Drawer)
* **Status**: Backlog / Future Enhancement
* **Underlying Engine**: Already supported in database (`stock_transactions` table) and domain service (`InventoryService`).
* **Concept**:
  * Tapping a product card in `PantryView` opens a drawer/modal displaying its transaction history like a bank account statement.
  * Shows chronological ledger entries:
    * `+36 rolls` — **Receipt Restock** (Linked to *Costco Wholesale Trip*, Nov 7)
    * `-1 roll` — **Fridge Door Pad Tap** (Nov 8, 9:30 AM)
    * `-1 roll` — **Fridge Door Pad Tap** (Nov 9, 6:20 PM)
  * **Features**:
    * 1-tap "Undo Last Decrement" button to easily reverse accidental double-taps.
    * Provenance link to jump directly to the shopping event/receipt where the batch was purchased.
