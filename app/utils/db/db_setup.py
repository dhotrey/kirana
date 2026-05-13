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

splitwise_expense_views_sql = """
CREATE VIEW IF NOT EXISTS me_expenses AS
SELECT
    *,
    CASE
        WHEN me_cents > 0 THEN cost_cents - me_cents
        ELSE -me_cents
    END AS my_share_cents
FROM splits;

CREATE VIEW IF NOT EXISTS roommate1_expenses AS
SELECT
    *,
    CASE
        WHEN roommate1_cents > 0 THEN cost_cents - roommate1_cents
        ELSE -roommate1_cents
    END AS roommate1_share_cents
FROM splits;

CREATE VIEW IF NOT EXISTS roommate2_expenses AS
SELECT
    *,
    CASE
        WHEN roommate2_cents > 0 THEN cost_cents - roommate2_cents
        ELSE -roommate2_cents
    END AS roommate2_share_cents
FROM splits;
"""

create_indexes_sql = """
CREATE INDEX IF NOT EXISTS idx_receipts_date
ON receipts(date);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id
ON receipt_items(receipt_id);

CREATE INDEX IF NOT EXISTS idx_receipt_items_name
ON receipt_items(item_name);
"""
