"""GDELT 2.0 events ingest.

GDELT publishes a tab-separated events file every 15 minutes at a
deterministic URL (YYYYMMDDHHMMSS.export.CSV.zip). The watermark is the
timestamp of the last processed file; each run walks forward in 15-minute
steps until it reaches the newest published file, capped per run so
catch-up after downtime happens gradually. Missing files (GDELT hiccups)
are skipped. Idempotent via upsert on external_id.

occurred_at uses DATEADDED (when the event hit media) because GDELT's
SQLDATE is parsed from article text and frequently lands on the wrong day.
"""

import csv
import io
import os
import zipfile
from datetime import datetime, timedelta, timezone
from math import log1p

import httpx
import psycopg

from ingest.fips import fips_to_iso

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
FILE_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"

CAMEO_ROOT_NAMES = {
    "01": "public_statement", "02": "appeal", "03": "intent_to_cooperate",
    "04": "consult", "05": "diplomatic_cooperation", "06": "material_cooperation",
    "07": "provide_aid", "08": "yield", "09": "investigate", "10": "demand",
    "11": "disapprove", "12": "reject", "13": "threaten", "14": "protest",
    "15": "force_posture", "16": "reduce_relations", "17": "coerce",
    "18": "assault", "19": "fight", "20": "mass_violence",
}

# Column indices in the 61-column export file (0-based)
COL_ID, COL_A1, COL_A2 = 0, 6, 16
COL_ROOTCODE, COL_CAMEO, COL_GOLDSTEIN = 28, 27, 30
COL_NUM_ARTICLES, COL_TONE = 33, 34
COL_GEO_CC, COL_GEO_ADM1, COL_GEO_LAT, COL_GEO_LON = 53, 54, 56, 57
COL_DATEADDED, COL_URL = 59, 60

UPSERT_SQL = """
INSERT INTO events (external_id, event_type, cameo_code, actor1, actor2,
                    lat, lon, country_iso, admin1, tone, goldstein,
                    importance, occurred_at, payload)
VALUES (%(external_id)s, %(event_type)s, %(cameo_code)s, %(actor1)s, %(actor2)s,
        %(lat)s, %(lon)s, %(country_iso)s, %(admin1)s, %(tone)s, %(goldstein)s,
        %(importance)s, %(occurred_at)s, %(payload)s)
ON CONFLICT (external_id) DO UPDATE SET
    importance = EXCLUDED.importance,
    tone = EXCLUDED.tone,
    payload = EXCLUDED.payload
"""


def importance_for(num_articles: int, goldstein: float) -> float:
    """Coverage (log-scaled article count) shaped by Goldstein magnitude.

    Multiplicative with a floor so a widely covered mild event still
    registers, but intensity is what pushes scores toward 1.
    """
    coverage = min(1.0, log1p(num_articles) / log1p(100))
    intensity = min(1.0, abs(goldstein) / 10.0)
    return round(coverage * (0.3 + 0.7 * intensity), 4)


def _stamp_to_dt(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _latest_available(client: httpx.Client) -> datetime:
    text = client.get(LASTUPDATE_URL, timeout=30).text
    for line in text.splitlines():
        url = line.split()[-1]
        if url.endswith(".export.CSV.zip"):
            return _stamp_to_dt(url.rsplit("/", 1)[1].split(".")[0])
    raise RuntimeError("no export file in lastupdate.txt")


def _parse_file(content: bytes, min_importance: float) -> list[dict]:
    rows = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        raw = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    for cols in csv.reader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(cols) < 61 or not cols[COL_GEO_LAT] or not cols[COL_GEO_LON]:
            continue
        try:
            goldstein = float(cols[COL_GOLDSTEIN] or 0)
            num_articles = int(cols[COL_NUM_ARTICLES] or 0)
            lat, lon = float(cols[COL_GEO_LAT]), float(cols[COL_GEO_LON])
            tone = float(cols[COL_TONE] or 0)
            occurred_at = _stamp_to_dt(cols[COL_DATEADDED])
        except ValueError:
            continue
        importance = importance_for(num_articles, goldstein)
        if importance < min_importance:
            continue
        root = cols[COL_ROOTCODE]
        rows.append(
            {
                "external_id": f"gdelt:{cols[COL_ID]}",
                "event_type": CAMEO_ROOT_NAMES.get(root, f"cameo_{root}"),
                "cameo_code": cols[COL_CAMEO] or None,
                "actor1": cols[COL_A1] or None,
                "actor2": cols[COL_A2] or None,
                "lat": lat,
                "lon": lon,
                "country_iso": fips_to_iso(cols[COL_GEO_CC]),
                "admin1": cols[COL_GEO_ADM1] or None,
                "tone": tone,
                "goldstein": goldstein,
                "importance": importance,
                "occurred_at": occurred_at,
                "payload": psycopg.types.json.Jsonb(
                    {"num_articles": num_articles, "url": cols[COL_URL] or None}
                ),
            }
        )
    return rows


def run(conn: psycopg.Connection) -> None:
    min_importance = float(os.environ.get("GDELT_MIN_IMPORTANCE", "0.25"))
    max_files = int(os.environ.get("GDELT_MAX_FILES_PER_RUN", "12"))

    row = conn.execute(
        "SELECT watermark_ts FROM ingest_watermarks WHERE source = 'gdelt'"
    ).fetchone()

    with httpx.Client() as client:
        latest = _latest_available(client)
        # First run: just the latest file. After that: walk forward from watermark.
        cursor = row[0] if row else latest - timedelta(minutes=15)

        files_done = 0
        total_upserts = 0
        while cursor < latest and files_done < max_files:
            cursor += timedelta(minutes=15)
            stamp = cursor.strftime("%Y%m%d%H%M%S")
            resp = client.get(FILE_URL.format(stamp=stamp), timeout=60)
            if resp.status_code == 404:
                continue  # GDELT skipped this slot; move on, watermark still advances
            resp.raise_for_status()
            rows = _parse_file(resp.content, min_importance)
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
            total_upserts += len(rows)
            files_done += 1

        conn.execute(
            """
            INSERT INTO ingest_watermarks (source, watermark_ts, updated_at)
            VALUES ('gdelt', %s, now())
            ON CONFLICT (source) DO UPDATE
                SET watermark_ts = EXCLUDED.watermark_ts, updated_at = now()
            """,
            (cursor,),
        )
    conn.commit()
    print(
        f"gdelt: {files_done} file(s), {total_upserts} events >= {min_importance}, "
        f"watermark {cursor.isoformat()}"
    )
