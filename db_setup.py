"""
Step 1: Database setup for the Autonomous Customer Resolution Agent.

Creates a small SQLite database that simulates:
- customers
- orders
- inventory
- policies (refund/replacement rules)

This stands in for the "enterprise systems" mentioned in the problem statement.
Run this once to (re)create resolution_agent.db with fresh seed data.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "resolution_agent.db")


def create_database():
    # Start fresh every time we run this
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            loyalty_tier TEXT  -- 'standard' or 'premium'
        )
    """)

    cur.execute("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT,
            sku TEXT,
            product_name TEXT,
            price REAL,
            status TEXT,       -- 'delivered', 'shipped', 'cancelled', 'refunded', 'replaced'
            issue_type TEXT,   -- 'damaged', 'wrong_item', 'late', 'not_received', NULL if no issue
            order_date TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        )
    """)

    cur.execute("""
        CREATE TABLE inventory (
            sku TEXT PRIMARY KEY,
            product_name TEXT,
            stock_count INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE policies (
            issue_type TEXT PRIMARY KEY,
            allowed_actions TEXT,   -- comma-separated: 'refund,replacement,cancellation'
            max_days_since_order INTEGER,
            notes TEXT
        )
    """)

    # Fault injection table: lets us simulate TRANSIENT system errors
    # (e.g. a payment gateway timeout) that succeed if the agent retries the
    # SAME action, as opposed to PERMANENT blocks (out of stock, policy
    # violations) that require switching to a different action entirely.
    # This is what lets us demo two distinct kinds of "adaptation."
    cur.execute("""
        CREATE TABLE simulated_faults (
            order_id TEXT,
            fault_type TEXT,
            remaining_failures INTEGER
        )
    """)

    # --- Seed customers ---
    cur.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", [
        ("CUST001", "Riya Sharma", "riya@example.com", "premium"),
        ("CUST002", "Arjun Mehta", "arjun@example.com", "standard"),
        ("CUST003", "Priya Nair", "priya@example.com", "standard"),
    ])

    # --- Seed inventory ---
    # Note: SKU-B22 and SKU-D44 are deliberately OUT OF STOCK to trigger
    # failure/adaptation demos.
    cur.executemany("INSERT INTO inventory VALUES (?, ?, ?)", [
        ("SKU-A11", "Wireless Mouse", 50),
        ("SKU-B22", "Bluetooth Headphones", 0),   # out of stock on purpose
        ("SKU-C33", "USB-C Charger", 30),
        ("SKU-D44", "Smartwatch", 0),              # out of stock on purpose
    ])

    # --- Seed policies ---
    cur.executemany("INSERT INTO policies VALUES (?, ?, ?, ?)", [
        ("damaged", "refund,replacement", 30, "Damaged items qualify for refund or replacement within 30 days."),
        ("wrong_item", "replacement,refund", 30, "Wrong item shipped: replacement preferred, refund if unavailable."),
        ("late", "refund", 45, "Late delivery only qualifies for partial/full refund, not replacement."),
        ("not_received", "refund,cancellation", 60, "Item never arrived: refund or order cancellation."),
    ])

    # --- Seed orders ---
    cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("ORD1001", "CUST001", "SKU-B22", "Bluetooth Headphones", 2499.00, "delivered", "damaged", "2026-08-20"),
        ("ORD1002", "CUST002", "SKU-A11", "Wireless Mouse", 599.00, "delivered", "wrong_item", "2026-09-01"),
        ("ORD1003", "CUST003", "SKU-C33", "USB-C Charger", 899.00, "shipped", "not_received", "2026-08-15"),
        # ORD1004: DOUBLE-ADAPTATION demo. Replacement is permanently blocked
        # (out of stock) -> agent switches to refund -> refund hits a
        # TRANSIENT gateway timeout once -> agent retries the same action
        # -> succeeds. Two distinct kinds of adaptation in one case.
        ("ORD1004", "CUST002", "SKU-D44", "Smartwatch", 5999.00, "delivered", "damaged", "2026-09-05"),
        # ORD1005: ESCALATION demo. Order is far outside the 30-day policy
        # window for a "damaged" claim, so NO automated action is permitted
        # -- the agent must recognize this and escalate rather than act.
        ("ORD1005", "CUST003", "SKU-C33", "USB-C Charger", 899.00, "delivered", "damaged", "2026-05-01"),
    ])

    # --- Seed simulated faults ---
    # ORD1004's refund will fail with a transient error exactly once, then
    # succeed on retry.
    cur.execute(
        "INSERT INTO simulated_faults VALUES (?, ?, ?)",
        ("ORD1004", "refund_timeout", 1),
    )

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    create_database()
