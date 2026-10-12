
import duckdb
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATASET = BASE_DIR / "datasets" / "ookla_mobile_2024_q4.parquet"

if not DATASET.exists():
    raise FileNotFoundError(f"Dataset not found: {DATASET}")

con = duckdb.connect(":memory:")
path = str(DATASET).replace("\\", "/").replace("'", "''")
source = f"read_parquet('{path}')"

print("=" * 60)
print("OOKLA MOBILE DATASET QUALITY CHECK")
print("=" * 60)

print("\n1. DATASET SIZE")
print("Rows:", con.execute(
    f"SELECT COUNT(*) FROM {source}"
).fetchone()[0])

print("\n2. MISSING VALUES")
query = f"""
SELECT
    COUNT(*) FILTER (WHERE avg_d_kbps IS NULL),
    COUNT(*) FILTER (WHERE avg_u_kbps IS NULL),
    COUNT(*) FILTER (WHERE avg_lat_ms IS NULL),
    COUNT(*) FILTER (WHERE tests IS NULL),
    COUNT(*) FILTER (WHERE devices IS NULL)
FROM {source}
"""
print("download, upload, latency, tests, devices")
print(con.execute(query).fetchone())

print("\n3. NUMERIC SUMMARY")
query = f"""
SELECT
    MIN(avg_d_kbps), MAX(avg_d_kbps),
    MIN(avg_u_kbps), MAX(avg_u_kbps),
    MIN(avg_lat_ms), MAX(avg_lat_ms),
    MIN(tests), MAX(tests)
FROM {source}
"""
print("min_download, max_download, min_upload, max_upload,")
print("min_latency, max_latency, min_tests, max_tests")
print(con.execute(query).fetchone())

print("\n4. DUPLICATE TILE COUNTS")
query = f"""
SELECT COUNT(*)
FROM (
    SELECT quadkey
    FROM {source}
    GROUP BY quadkey
    HAVING COUNT(*) > 1
)
"""
print("Quadkeys appearing in multiple rows:",
      con.execute(query).fetchone()[0])

print("\n5. SAMPLE RECORDS")
query = f"""
SELECT quadkey, avg_d_kbps, avg_u_kbps,
       avg_lat_ms, tests, devices
FROM {source}
LIMIT 5
"""
for row in con.execute(query).fetchall():
    print(row)

print("\nInspection complete. Original dataset was not modified.")
con.close()
