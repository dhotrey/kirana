splitwise_create_table_sql = """
CREATE TABLE IF NOT EXISTS splits (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT,
    cost_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    me_cents INTEGER NOT NULL,
    roommate1_cents INTEGER NOT NULL,
    roommate2_cents INTEGER NOT NULL
);
"""

receipts_create_table_sql = """
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY,
    store_name TEXT NOT NULL,
    date TEXT,
    time TEXT,
    address TEXT,
    item_count INTEGER,
    subtotal_cents INTEGER,
    gst_cents INTEGER,
    discounts_cents INTEGER,
    total_cents INTEGER NOT NULL,
    image_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

reciept_items_create_table_sql = """
CREATE TABLE IF NOT EXISTS receipt_items (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL,
    unit_price_cents INTEGER,
    total_price_cents INTEGER NOT NULL,
    inferred_category TEXT,
    FOREIGN KEY (receipt_id)
        REFERENCES receipts(id)
        ON DELETE CASCADE
);
"""

create_indexes_sql = """
CREATE INDEX IF NOT EXISTS idx_receipts_date
ON receipts(date);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id
ON receipt_items(receipt_id);

CREATE INDEX IF NOT EXISTS idx_receipt_items_name
ON receipt_items(item_name);
"""