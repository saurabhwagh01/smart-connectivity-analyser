
import duckdb
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE = BASE_DIR / "datasets" / "ookla_mobile_2024_q4.parquet"
OUTPUT = BASE_DIR / "datasets" / "ookla_mobile_sample.csv"

if not SOURCE.exists():
    raise FileNotFoundError(f"Dataset not found: {SOURCE}")

con = duckdb.connect(":memory:")
source = str(SOURCE).replace("\\", "/").replace("'", "''")
output = str(OUTPUT).replace("\\", "/").replace("'", "''")

# Keep only records with plausible positive throughput,
# valid latency, and at least one contributing test.
# These are screening rules, not proof that every row is valid.
query = f"""
SELECT
    quadkey,
    tile_x,
    tile_y,
    avg_d_kbps / 1000.0 AS download_mbps,
    avg_u_kbps / 1000.0 AS upload_mbps,
    avg_lat_ms AS latency_ms,
    avg_lat_down_ms AS download_latency_ms,
    avg_lat_up_ms AS upload_latency_ms,
    tests,
    devices
FROM read_parquet('{source}')
WHERE avg_d_kbps > 0
  AND avg_u_kbps > 0
  AND avg_lat_ms > 0
  AND tests > 0
  AND devices > 0
"""

count = con.execute(
    f"SELECT COUNT(*) FROM ({query})"
).fetchone()[0]

print("Original rows:", con.execute(
    f"SELECT COUNT(*) FROM read_parquet('{source}')"
).fetchone()[0])
print("Rows passing screening:", count)

con.execute(
    f"COPY ({query}) TO '{output}' (HEADER, DELIMITER ',')"
)

print("Sample preparation complete.")
print("Output:", OUTPUT)
print("The original Parquet file and production database were not modified.")

con.close()
