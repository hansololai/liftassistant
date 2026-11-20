-- =========================================================================
-- LiftAssistant 3.0: Unified Life Event Ledger & Personal OS Schema
-- Strictly implements Decision 7, 18, 21, and Approach 2 Composite Type Checking
-- =========================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- =========================================================================
-- 1. FIRST-CLASS PLACES & VENUES
-- =========================================================================
CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                  -- e.g. "Rose E. Schneider Family YMCA", "Mad Mex"
    category TEXT,                       -- 'restaurant', 'supermarket', 'gym', 'school', 'medical', 'service'
    address TEXT,                        -- Full formatted street address
    latitude REAL,
    longitude REAL,
    map_url TEXT,                        -- Google Maps / Apple Maps link
    google_place_id TEXT,                -- Google Place ID / Nominatim OSM ID
    notes TEXT,                          -- Entrance tips, parking notes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_places_name ON places(name);
CREATE INDEX IF NOT EXISTS idx_places_category ON places(category);

-- =========================================================================
-- 2. FAMILY MEMBERS & ATTENDEES
-- =========================================================================
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,           -- 'Dad', 'Mom', 'Marcus'
    role TEXT DEFAULT 'family',          -- 'parent', 'child', 'guest'
    color TEXT,                          -- UI badge color
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- 3. BASE EVENTS TABLE (Universal Temporal Continuum)
-- =========================================================================
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL,            -- 'DINING', 'SHOPPING', 'MAINTENANCE', 'KID_ACTIVITY', 'MEDICAL', 'TRAVEL', 'CUSTOM'
    
    -- Temporal Continuum: Past vs Future
    scheduled_at TIMESTAMP,              -- Start datetime (when planned or started)
    scheduled_end_at TIMESTAMP,          -- Computed or explicitly set end time
    deadline TIMESTAMP,                  -- Hard cutoff: When it MUST be done by (for urgency sorting)
    completed_at TIMESTAMP,              -- When fulfilled / recorded (NULL if upcoming task)
    all_day BOOLEAN DEFAULT FALSE,
    
    -- Place Relationship & Geolocation
    place_id TEXT REFERENCES places(id) ON DELETE SET NULL,
    latitude REAL,
    longitude REAL,
    
    -- People Involved (stored as JSON array of names, e.g. ["Dad", "Mom", "Leo"])
    people_involved TEXT DEFAULT '[]',
    
    -- Financials & Notes
    tax_amount REAL DEFAULT 0.0,
    notes TEXT,
    
    -- Source & Ingestion Audit
    source TEXT NOT NULL DEFAULT 'MANUAL', -- 'MANUAL', 'QUICK_PRESET', 'RECEIPT_OCR', 'AGENT_GMAIL', 'AGENT_YMCA'
    source_reference_id TEXT,             -- e.g. file_hash, email_msg_id, or template_id
    
    -- Soft-Conflict Tolerance
    has_conflict BOOLEAN DEFAULT FALSE,
    conflict_status TEXT,                -- 'DETECTED', 'ACKNOWLEDGED', 'RESOLVED'
    conflict_reason TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Approach 2: Composite Unique constraint required for Composite Foreign Keys
    UNIQUE (id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_events_scheduled ON events(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_events_deadline ON events(deadline);
CREATE INDEX IF NOT EXISTS idx_events_completed ON events(completed_at);
CREATE INDEX IF NOT EXISTS idx_events_place ON events(place_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_has_conflict ON events(has_conflict);

-- =========================================================================
-- 3.1 EVENT GENERATORS (Recurring Rule Engine for Annual / Periodic Obligations)
-- =========================================================================
CREATE TABLE IF NOT EXISTS event_generators (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,                     -- e.g. "Annual Honda Inspection", "Leo Birthday", "Property Tax"
    event_type TEXT NOT NULL,                -- 'MAINTENANCE', 'KID_ACTIVITY', 'CUSTOM', etc.
    
    -- Recurrence Schedule (RFC 5545 standard)
    frequency TEXT NOT NULL,                 -- 'YEARLY', 'MONTHLY', 'WEEKLY', 'DAILY'
    interval INTEGER DEFAULT 1,              -- e.g. every 1 year, every 3 months
    by_month INTEGER,                        -- 1-12 (e.g. 11 for November)
    by_month_day INTEGER,                    -- 1-31 (e.g. 15 for 15th)
    by_weekday TEXT,                         -- 'MO', 'TU', 'WE', etc.
    anchor_date DATE NOT NULL,               -- Base/first recurrence date (e.g. '2026-11-15')
    
    -- Lead Time Window (when to spawn into upcoming schedule)
    lead_time_days INTEGER DEFAULT 14,       -- How many days in advance to spawn the event
    
    -- Deadline Handling: when spawned, deadline is automatically assigned
    has_deadline BOOLEAN DEFAULT TRUE,       -- Whether spawned events carry a hard deadline
    deadline_offset_days INTEGER DEFAULT 0,  -- Offset from the recurrence target date (0 = target date is deadline)
    deadline_time TEXT DEFAULT '23:59:59',   -- Cutoff time of day
    
    -- Template Payload for Spawned Events
    place_id TEXT REFERENCES places(id) ON DELETE SET NULL,
    duration_minutes INTEGER DEFAULT 60,
    people_involved TEXT DEFAULT '[]',       -- JSON list: ["Dad", "Leo"]
    estimated_amount REAL DEFAULT 0.0,
    notes TEXT,
    
    -- Lifecycle State
    is_active BOOLEAN DEFAULT TRUE,
    last_generated_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_generators_active ON event_generators(is_active);

-- =========================================================================
-- 4. TYPE-SPECIFIC EXTENSION TABLES (Approach 2: Relational Joined Polymorphism)
--    Each table enforces event_id PK + CHECK (event_type = '...') + Composite FK
--    guaranteeing that an event CANNOT belong to multiple detail tables!
-- =========================================================================

-- 4.1 Dining Extension
CREATE TABLE IF NOT EXISTS dining_details (
    event_id TEXT PRIMARY KEY,
    event_type TEXT DEFAULT 'DINING' CHECK (event_type = 'DINING'),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    total_amount REAL DEFAULT 0.0,
    FOREIGN KEY (event_id, event_type) REFERENCES events(id, event_type) ON DELETE CASCADE
);

-- 4.2 Shopping Extension
CREATE TABLE IF NOT EXISTS shopping_details (
    event_id TEXT PRIMARY KEY,
    event_type TEXT DEFAULT 'SHOPPING' CHECK (event_type = 'SHOPPING'),
    receipt_image_path TEXT,
    pantry_updated BOOLEAN DEFAULT FALSE,
    total_amount REAL DEFAULT 0.0,
    FOREIGN KEY (event_id, event_type) REFERENCES events(id, event_type) ON DELETE CASCADE
);

-- 4.3 Household & Vehicle Equipment Catalog
CREATE TABLE IF NOT EXISTS household_equipment (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                  -- "Honda Odyssey EX-L (2022)", "Kitchen Refrigerator", "HVAC Lennox"
    category TEXT NOT NULL,              -- 'vehicle', 'appliance', 'hvac', 'plumbing'
    model_number TEXT,
    serial_number TEXT,
    purchase_date DATE,
    warranty_expiry DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4.4 Maintenance Extension (Foreign Key to household_equipment)
CREATE TABLE IF NOT EXISTS maintenance_details (
    event_id TEXT PRIMARY KEY,
    event_type TEXT DEFAULT 'MAINTENANCE' CHECK (event_type = 'MAINTENANCE'),
    equipment_id TEXT NOT NULL REFERENCES household_equipment(id) ON DELETE CASCADE,
    service_type TEXT,                   -- 'oil_change', 'tire_rotation', 'filter_replacement', 'inspection'
    next_due_interval_days INTEGER,
    next_due_miles INTEGER,
    FOREIGN KEY (event_id, event_type) REFERENCES events(id, event_type) ON DELETE CASCADE
);


-- =========================================================================
-- 5. GROCY INVENTORY ENGINE & BULK PACKAGE CONVERSIONS
-- =========================================================================

-- 5.1 Storage Locations
CREATE TABLE IF NOT EXISTS storage_locations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,           -- 'Kitchen Fridge', 'Main Pantry', 'Freezer', 'Master Bath Closet'
    description TEXT
);

-- 5.2 Quantity Units
CREATE TABLE IF NOT EXISTS quantity_units (
    id TEXT PRIMARY KEY,                 -- 'ea', 'pack', 'roll', 'gal', 'egg', 'pod', 'lb', 'box', 'case', 'tub'
    name TEXT NOT NULL,
    name_plural TEXT NOT NULL
);

-- 5.3 Products Catalog with Bulk Conversion Factor (qu_factor)
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,              -- 'dairy', 'produce', 'meat', 'household', 'pantry'
    default_location_id TEXT REFERENCES storage_locations(id) ON DELETE SET NULL,
    default_place_id TEXT REFERENCES places(id) ON DELETE SET NULL, -- Target store (e.g. Costco)
    
    -- Grocy Stock Unit Conversion Factor: 1 Purchase Unit = qu_factor Stock Units
    qu_purchase_id TEXT REFERENCES quantity_units(id) ON DELETE SET NULL, -- e.g. 'pack', 'case', 'tub'
    qu_stock_id TEXT REFERENCES quantity_units(id) ON DELETE SET NULL,    -- e.g. 'roll', 'egg', 'gal', 'pod'
    qu_factor REAL NOT NULL DEFAULT 1.0,  -- e.g. 36 (toilet paper), 48 (eggs), 2 (milk), 90 (pods)
    
    -- Fridge Door Pad 1-Tap Consumption Step
    consume_step REAL NOT NULL DEFAULT 1.0,
    consume_step_label TEXT,             -- e.g. '-1 Roll', '-0.5 Gal', '-2 Eggs', '-1 Pod'
    is_fridge_quick_tile BOOLEAN DEFAULT FALSE,
    
    -- Burn Rate & Auto-Replenishment
    min_stock_amount REAL DEFAULT 1.0,
    daily_burn_rate REAL NOT NULL DEFAULT 0.0, -- Used for runway calculation: R = stock / daily_burn_rate
    auto_add_to_shopping_list BOOLEAN DEFAULT TRUE,
    
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_store ON products(default_place_id);

-- 5.4 Bulk Receipt Line-Item Mapping Table
CREATE TABLE IF NOT EXISTS product_unit_conversions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    store_name TEXT NOT NULL,            -- e.g. 'Costco', "Sam's Club"
    receipt_raw_text TEXT NOT NULL,      -- e.g. 'KS BATH TISSUE 36/PK #1500'
    purchase_unit TEXT NOT NULL,         -- 'pack'
    stock_unit TEXT NOT NULL,            -- 'rolls'
    unit_multiplier REAL NOT NULL,       -- 36
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversions_lookup ON product_unit_conversions(store_name, receipt_raw_text);

-- 5.4.1 Store Item Multipliers & Product Linking Table: (store, item, multiplier, product_id)
CREATE TABLE IF NOT EXISTS item_multipliers (
    store TEXT NOT NULL,
    item TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
    PRIMARY KEY (store, item)
);

CREATE INDEX IF NOT EXISTS idx_item_multipliers_lookup ON item_multipliers(store, item);
CREATE INDEX IF NOT EXISTS idx_item_multipliers_product ON item_multipliers(product_id);

-- 5.5 Stock Inventory Batches
CREATE TABLE IF NOT EXISTS stock (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    amount REAL NOT NULL DEFAULT 0.0,    -- Balance in stock units (e.g. 14 rolls)
    location_id TEXT REFERENCES storage_locations(id) ON DELETE SET NULL,
    purchased_event_id TEXT REFERENCES events(id) ON DELETE SET NULL,
    price REAL,
    best_before_date DATE,
    opened BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_product ON stock(product_id);

-- 5.6 Double-Entry Stock Movement Ledger (Audit Trail)
CREATE TABLE IF NOT EXISTS stock_transactions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    transaction_type TEXT NOT NULL,      -- 'PURCHASE_RECEIPT', 'FRIDGE_PAD_CONSUME', 'CONFIRMED_DEPLETION', 'RESTOCK_UNDO'
    amount REAL NOT NULL,                -- Positive for additions (+36), negative for depletions (-1)
    unit TEXT NOT NULL,
    source TEXT NOT NULL,                -- 'RECEIPT_OCR', 'FRIDGE_PAD', 'CONFIRMATION_GATE', 'MANUAL'
    reference_id TEXT,                   -- event_id or receipt_id
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_tx_product ON stock_transactions(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_tx_time ON stock_transactions(created_at);

-- 5.7 Confirmation Gate Proposals
CREATE TABLE IF NOT EXISTS depletion_proposals (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    proposed_amount REAL NOT NULL,       -- e.g. 0.5 gal
    unit TEXT NOT NULL,
    reason TEXT NOT NULL,                -- e.g. 'Estimated toddler milk consumption'
    confidence_score REAL DEFAULT 0.9,
    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'CONFIRMED', 'DISMISSED'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- 6. CONTENT-ADDRESSABLE RECEIPT STORAGE (CAS) & LINE ITEMS
-- =========================================================================
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    event_id TEXT REFERENCES events(id) ON DELETE CASCADE,
    place_id TEXT REFERENCES places(id) ON DELETE SET NULL,
    
    -- Content-Addressable Storage (CAS)
    file_hash TEXT NOT NULL,             -- SHA-256 hash of raw file bytes in CAS
    file_path TEXT NOT NULL,             -- data/receipt_store/YYYY-MM/{hash}.{ext}
    original_filename TEXT,
    mime_type TEXT,
    file_size_bytes INTEGER,
    
    -- Extracted Merchant Metadata
    merchant_name TEXT NOT NULL,
    merchant_address TEXT,
    transaction_time TIMESTAMP NOT NULL,
    
    -- Financial Totals
    subtotal REAL,
    tax_amount REAL DEFAULT 0.0,
    tip_amount REAL DEFAULT 0.0,
    total_amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    
    -- Ingestion Origin & Reprocessing Audit
    source_channel TEXT NOT NULL,        -- 'PHOTO_CAMERA', 'GMAIL_BODY', 'PDF_INBOX', 'MANUAL'
    source_reference_id TEXT,
    raw_ocr_json TEXT,                   -- Raw LLM/OCR JSON
    parsing_status TEXT DEFAULT 'SUCCESS', -- 'SUCCESS', 'PROCESSING', 'FAILED', 'NEEDS_REVIEW'
    parsing_error TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_receipts_hash ON receipts(file_hash);
CREATE INDEX IF NOT EXISTS idx_receipts_event ON receipts(event_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_source_ref ON receipts(source_reference_id) WHERE source_reference_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_receipts_lookup ON receipts(merchant_name, transaction_time, total_amount);

-- 6.1 Itemized Receipt Line Items
CREATE TABLE IF NOT EXISTS receipt_items (
    id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    clean_name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity REAL DEFAULT 1.0,
    unit TEXT DEFAULT 'ea',
    unit_price REAL,
    total_price REAL NOT NULL,
    product_id TEXT REFERENCES products(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt ON receipt_items(receipt_id);
CREATE INDEX IF NOT EXISTS idx_receipt_items_product ON receipt_items(product_id);

-- =========================================================================
-- 7. 7-DAY ROLLING HORIZON SMART SHOPPING LIST
-- =========================================================================
CREATE TABLE IF NOT EXISTS shopping_list (
    id TEXT PRIMARY KEY,
    product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
    item_name TEXT NOT NULL,
    category TEXT,
    amount REAL DEFAULT 1.0,
    qu_id TEXT REFERENCES quantity_units(id) ON DELETE SET NULL,
    target_place_id TEXT REFERENCES places(id) ON DELETE SET NULL, -- Target store grouping (e.g. Costco tab)
    status TEXT DEFAULT 'PENDING',       -- 'PENDING', 'IN_CART', 'PURCHASED'
    source TEXT DEFAULT 'AUTO_HORIZON',  -- 'AUTO_HORIZON', 'MANUAL', 'CONFIRMATION_GATE'
    checked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shopping_list_target ON shopping_list(target_place_id);
CREATE INDEX IF NOT EXISTS idx_shopping_list_status ON shopping_list(status);

-- =========================================================================
-- 8. TRAVEL & MULTI-STOP TRIPS ENGINE (Inverted Geofence)
-- =========================================================================
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                  -- e.g. "Disney World Family Road Trip"
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    budget REAL DEFAULT 0.0,
    spent REAL DEFAULT 0.0,
    
    -- Home Base Inverted Geofence Anchor (Cranberry Twp, PA)
    geofence_center_lat REAL DEFAULT 40.6873,
    geofence_center_lng REAL DEFAULT -80.1078,
    inverted_geofence_radius_miles REAL DEFAULT 30.0,
    
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trip_stops (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                  -- e.g. "Buc-ee's Florence, SC (Fuel & Snacks)"
    stop_date DATE,
    category TEXT,                       -- 'Lodging', 'Fuel', 'Dining', 'Activities'
    spent REAL DEFAULT 0.0,
    notes TEXT,
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trip_stops_trip ON trip_stops(trip_id);

-- =========================================================================
-- 9. ANALYTIC VIEWS
-- =========================================================================

-- 9.1 Product Stock Summary View (Aggregated Stock Balance)
CREATE VIEW IF NOT EXISTS v_product_stock AS
SELECT 
    p.id AS product_id,
    p.name AS product_name,
    p.category,
    COALESCE(SUM(s.amount), 0.0) AS current_stock,
    p.qu_stock_id AS unit,
    p.daily_burn_rate,
    p.qu_purchase_id,
    p.qu_factor,
    p.consume_step,
    p.consume_step_label,
    p.is_fridge_quick_tile,
    pl.name AS preferred_store,
    loc.name AS location_name
FROM products p
LEFT JOIN stock s ON p.id = s.product_id
LEFT JOIN places pl ON p.default_place_id = pl.id
LEFT JOIN storage_locations loc ON p.default_location_id = loc.id
GROUP BY p.id;

-- 9.2 7-Day Rolling Horizon Runway View
CREATE VIEW IF NOT EXISTS v_product_runway AS
SELECT 
    v.*,
    CASE 
        WHEN v.daily_burn_rate <= 0 THEN 999.0
        ELSE ROUND(v.current_stock / v.daily_burn_rate, 1)
    END AS days_runway,
    CASE 
        WHEN v.daily_burn_rate > 0 AND (v.current_stock / v.daily_burn_rate) < 7.0 THEN 1
        ELSE 0
    END AS is_low_stock_7d
FROM v_product_stock v;

-- =========================================================================
-- 10. AUTHORIZED DEVICES & ZERO-FRICTION MAGIC LINK AUTH
-- =========================================================================
CREATE TABLE IF NOT EXISTS authorized_devices (
    id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,         -- e.g. "Dad's Phone", "Mom's Phone"
    enroll_token TEXT UNIQUE NOT NULL, -- secret token used to enroll
    session_token TEXT UNIQUE,         -- 10-year session token once enrolled
    is_enrolled INTEGER DEFAULT 0,     -- 0 = pending, 1 = enrolled
    enrolled_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    user_agent TEXT,
    ip_address TEXT,
    is_revoked INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_devices_session ON authorized_devices(session_token);
CREATE INDEX IF NOT EXISTS idx_devices_enroll ON authorized_devices(enroll_token);

-- =========================================================================
-- 11. RESOURCE & FACILITY CLOSURES
-- =========================================================================
CREATE TABLE IF NOT EXISTS resource_closures (
    id TEXT PRIMARY KEY,
    resource_id TEXT,                    -- e.g. 'pl_ymca' or NULL
    resource_name TEXT NOT NULL,          -- e.g. 'Rose E. Schneider Family YMCA'
    start_time TIMESTAMP NOT NULL,        -- ISO start datetime of closure
    end_time TIMESTAMP NOT NULL,          -- ISO end datetime of closure
    reason TEXT,                          -- e.g. 'Thanksgiving 2026 Closure'
    source TEXT DEFAULT 'AGENT_GMAIL',    -- 'AGENT_GMAIL', 'MANUAL'
    source_reference_id TEXT,             -- Gmail message ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (resource_id) REFERENCES places(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_closures_res ON resource_closures(resource_id, start_time, end_time);

-- =========================================================================
-- 12. GENERATOR RUNS, AUDIT TRAIL & ITERATIVE FEEDBACK
-- =========================================================================
CREATE TABLE IF NOT EXISTS generator_runs (
    id TEXT PRIMARY KEY,
    generator_type TEXT NOT NULL DEFAULT 'EMAIL_EVENT_GENERATOR',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'RUNNING', -- 'RUNNING', 'SUCCESS', 'FAILED'
    scanned_count INTEGER DEFAULT 0,
    created_count INTEGER DEFAULT 0,
    error_message TEXT,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_gen_runs_type ON generator_runs(generator_type, started_at);

CREATE TABLE IF NOT EXISTS generator_event_feedback (
    id TEXT PRIMARY KEY,
    event_id TEXT,
    run_id TEXT REFERENCES generator_runs(id) ON DELETE SET NULL,
    source_reference_id TEXT,             -- e.g. Gmail msg_id
    email_subject TEXT,
    email_from TEXT,
    email_date TEXT,
    llm_category TEXT,
    llm_reason TEXT,
    raw_json TEXT,
    user_status TEXT DEFAULT 'PENDING',  -- 'PENDING', 'ACCEPTED', 'MODIFIED', 'REMOVED'
    user_correction_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gen_feedback_event ON generator_event_feedback(event_id);
CREATE INDEX IF NOT EXISTS idx_gen_feedback_run ON generator_event_feedback(run_id);
CREATE INDEX IF NOT EXISTS idx_gen_feedback_source ON generator_event_feedback(source_reference_id);

CREATE TABLE IF NOT EXISTS learned_prompt_rules (
    id TEXT PRIMARY KEY,
    generator_type TEXT NOT NULL DEFAULT 'EMAIL_EVENT_GENERATOR',
    rule_type TEXT NOT NULL DEFAULT 'NEGATIVE', -- 'NEGATIVE', 'POSITIVE', 'GENERAL'
    user_feedback TEXT NOT NULL,
    prompt_instruction TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prompt_rules_active ON learned_prompt_rules(generator_type, is_active);

