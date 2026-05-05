import sqlite3

conn = sqlite3.connect("data/app.db")
cur = conn.cursor()

print("Approvals (asset):")
cur.execute(
    "SELECT id, request_id, status, approval_stage FROM approvals "
    "WHERE request_type='asset' ORDER BY id DESC LIMIT 5;"
)
for row in cur.fetchall():
    print(row)

print("\nAssets:")
cur.execute("SELECT id, status, approval_stage FROM assets ORDER BY id DESC LIMIT 5;")
for row in cur.fetchall():
    print(row)

conn.close()
