# Inventory Integration Plan: Auction Tracker + eBay Tracker

## Overview

This document outlines the phased integration of two separate Python applications—`auction_tracker` and `ebay_tracker`—into a connected workflow using a shared SQLite database. The goal is to track the full inventory lifecycle (purchase to sale) while keeping the applications separate and minimizing disruption.

**Business Objectives**:
- Track purchase source, date, lot/invoice reference, price, fees.
- Track listing status, sold price, shipping, marketplace fees, net profit.
- Enable reporting across the entire lifecycle.

**Constraints**:
- Keep repositories separate (no full merge).
- Incremental changes with backward compatibility.
- Preserve existing functionality.
- Shared SQLite database (`shared_inventory.db`) in `/home/peralese/Projects/`.

## Proposed Shared Schema

The shared database will contain a single `inventory` table as the authoritative source for inventory lifecycle data. This table combines purchase and sales data, with clear separation to avoid conflicts.

### Table Definition: `inventory`

```sql
CREATE TABLE inventory (
  item_id TEXT PRIMARY KEY,  -- Deterministic: AUC-{purchase_date}-{lot_number}-{short_hash} (see strategy below)
  sku TEXT,                  -- Optional SKU (separate from item_id for flexibility)
  title TEXT NOT NULL,
  description TEXT,
  
  -- Purchase data (populated by auction_tracker)
  purchase_source TEXT,      -- e.g., 'auction'
  purchase_date TEXT,        -- ISO date (YYYY-MM-DD)
  lot_number TEXT,           -- Auction lot or invoice reference
  purchase_price REAL,       -- Base cost
  purchase_fees REAL DEFAULT 0.0,  -- Buyer premium or other fees
  total_purchase_cost REAL,  -- Calculated: purchase_price + purchase_fees
  
  -- Sales data (populated/updated by ebay_tracker)
  listing_status TEXT DEFAULT 'purchased' CHECK (listing_status IN ('purchased', 'ready_to_list', 'listed', 'sold', 'closed')),  -- Validated status
  list_date TEXT,           -- ISO date
  list_price REAL,
  sold_price REAL,
  sold_date TEXT,           -- ISO date
  shipping_cost REAL DEFAULT 0.0,
  marketplace_fees REAL DEFAULT 0.0,
  
  -- Calculated fields
  net_profit REAL,          -- Calculated: sold_price - total_purchase_cost - shipping_cost - marketplace_fees
  
  -- Metadata
  ebay_item_id TEXT UNIQUE, -- Unique for eBay linking
  notes TEXT,
  source_file TEXT,         -- File from which data was extracted (e.g., invoice path)
  source_hash TEXT,         -- SHA256 hash of source file for deduplication
  created_at TEXT,          -- ISO timestamp when record created (auto-set)
  updated_at TEXT,          -- ISO timestamp when record last updated (auto-updated)
  
  -- Indexes
  CREATE INDEX idx_purchase_date ON inventory(purchase_date);
  CREATE INDEX idx_listing_status ON inventory(listing_status);
  CREATE INDEX idx_sku ON inventory(sku);
);
```

**Notes**:
- `item_id` is the primary key for stability.
- `sku` is separate to allow changes without affecting identity.
- Calculated fields updated on insert/update.
- Dates in ISO format (YYYY-MM-DD).

## Status Lifecycle

The `listing_status` field tracks the item through its lifecycle:

1. **purchased**: Initial state after auction purchase (set by auction_tracker).
2. **ready_to_list**: Marked when prepared for eBay listing (manual or automated).
3. **listed**: When listed on eBay (set by ebay_tracker).
4. **sold**: When sold on eBay (set by ebay_tracker).
5. **closed**: Final state (e.g., archived or returned).

Transitions are handled by the respective applications. eBay Tracker can update status based on API data.

## Item ID Strategy

**Generation for Auction Purchases**:
- `item_id` = `AUC-{purchase_date}-{lot_number}-{short_hash}` (deterministic and collision-resistant).
- `short_hash` = First 8 characters of SHA256 hash of (`source_hash` + normalized `title`).
- Example: `AUC-2026-03-21-LOT123-abc12345`.
- This ensures stability across reprocessing of the same source item, while reducing collision risk.

**SKU Handling**:
- Keep `sku` as a separate field (not tied to `item_id`).
- Auction Tracker can set `sku` if available from invoice; otherwise leave null.
- eBay Tracker can populate/update `sku` when listing.
- This preserves flexibility: SKUs can change without breaking identity.

**Linking**:
- eBay Tracker uses `item_id` to link listings to shared inventory (see Phase 3).

## Deduplication Logic

- **Item-Level**: Based on `item_id` (deterministic, so same item from same source always generates same ID). If `item_id` exists, auction_tracker skips insert or updates if data changed.
- **File-Level**: Based on `source_hash` (SHA256 of file). Prevents reprocessing identical files, but allows updates if item data changes within the same file.
- **Behavior**: auction_tracker checks both; prefers update over duplicate inserts. No silent ignores—errors raised for conflicts.

## Phased Implementation Roadmap

### Phase 1: Shared Schema Setup (1-2 days)
- Create `shared_inventory.db` in `/home/peralese/Projects/` with the above schema.
- Add a shared utility script (`shared_db.py`) in each repo for DB helpers (connect, insert, update).
- Test basic connectivity from both repos.
- **Auction Tracker Interaction**: No changes yet.
- **eBay Tracker Interaction**: No changes yet.
- **Risks**: File permissions if repos are in different environments.

### Phase 2: Auction Tracker Writes to Shared DB (2-3 days)
- Modify `auction_tracker/main.py` to write extracted items to `inventory` table **in parallel** with existing Excel export.
- Generate `item_id` as described; set `listing_status = 'purchased'`.
- Preserve Excel outputs for audit/history.
- Update deduplication: Check DB for existing `item_id` before insert.
- **Auction Tracker Interaction**: Inserts purchase records; continues Excel export.
- **eBay Tracker Interaction**: No changes.
- **Risks**: Duplicate data if not careful; ensure DB writes don't break OCR flow.

### Phase 3: eBay Tracker Incremental Integration (3-5 days)
- **Approach**: Keep `listings` table as-is for minimal disruption. Add a new column `shared_item_id` to `listings` table, linking to `inventory.item_id`.
- When syncing/updating listings, check/match against shared DB by `sku` or `ebay_item_id`.
- If match found, update `inventory` with sales data and set `shared_item_id`.
- If no match, create new `inventory` record or flag for manual linking.
- Preserve existing UI/export features.
- **Auction Tracker Interaction**: Continues as in Phase 2.
- **eBay Tracker Interaction**: Reads from shared DB for reporting; updates sales data.
- **Risks**: Potential data inconsistencies if linking fails; manual intervention needed initially.

### Phase 4: Reporting and Profit Views (1-2 days)
- Add queries/views in shared DB for lifecycle reports (e.g., profit by source).
- Update eBay Tracker UI to display purchase data from shared DB.
- Add export options for full reports.
- **Both Apps**: Use shared DB for read-only reporting.
- **Risks**: Performance if DB grows large; add indexes as needed.

## Risks and Assumptions

**Assumptions**:
- Shared DB file is accessible from both repos (same filesystem).
- No concurrent writes initially (SQLite handles single-writer).
- Manual data migration from existing storages to shared DB.
- SKUs align between apps (manual mapping if not).
- Currency is USD; single timezone.

**Risks**:
- Data integrity: Mismatched item_id could cause duplicates.
- Performance: Shared DB queries across repos.
- Rollback: Keep backups of existing data.
- Scope creep: Stick to incremental phases.

## Next Steps

- Review and approve this plan.
- Implement Phase 1.
- Test with sample data before proceeding.</content>
<parameter name="filePath">/home/peralese/Projects/ebay_tracker/docs/inventory_integration_plan.md