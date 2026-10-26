import sqlite3

conn = sqlite3.connect("data/jobs.db")
rows = conn.execute(
    """
    SELECT id, title, company, action, first_seen
    FROM jobs
    WHERE date(first_seen, 'localtime') = date('now', 'localtime')
    ORDER BY id
    """
).fetchall()

for r in rows:
    print(r)

if rows and input(f"\nDelete these {len(rows)} job(s)? [y/n]: ").strip().lower() == "y":
    ids = [r[0] for r in rows]
    conn.execute(f"DELETE FROM jobs WHERE id IN ({','.join('?' * len(ids))})", ids)
    conn.commit()
    print("Deleted.")
conn.close()