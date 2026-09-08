import os
from datetime import datetime

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

load_dotenv()


def fetch_recalls(limit=100, skip=0, search=None):
    url = "https://api.fda.gov/food/enforcement.json"
    params = {"limit": limit, "skip": skip}

    if search:
        params["search"] = search

    try:
        resp = requests.get(url, params=params, timeout=30)

        if resp.status_code == 404:
            return []

        resp.raise_for_status()
        return resp.json().get("results", [])

    except requests.exceptions.RequestException as e:
        print(f"Fetch failed at skip={skip}: {e}")
        return []


def fetch_all_recalls(page_size=100, search=None):
    all_records = []
    skip = 0

    while True:
        records = fetch_recalls(page_size, skip, search)

        if not records:
            break

        all_records.extend(records)

        if len(records) < page_size:
            break

        skip += page_size

    return all_records


def fetch_all_recalls_backfill(start_year=2012, page_size=100):
    all_records = []
    current_year = datetime.now().year

    for year in range(start_year, current_year + 1):
        search = f"report_date:[{year}0101 TO {year}1231]"
        year_records = fetch_all_recalls(page_size=page_size, search=search)
        print(f"{year}: {len(year_records)} records")
        all_records.extend(year_records)

    return all_records


def fetch_recalls_since(since_date, page_size=100):
    date_str = since_date.strftime("%Y%m%d")
    today_str = datetime.now().strftime("%Y%m%d")
    search = f"report_date:[{date_str} TO {today_str}]"

    return fetch_all_recalls(page_size, search)


def parse_date(s):
    return datetime.strptime(s, "%Y%m%d").date() if s else None


def upsert_recalls(conn, records):
    if not records:
        return

    rows = [
        (
            r["recall_number"],
            r.get("event_id"),
            r.get("status"),
            r.get("classification"),
            r.get("product_type"),
            r.get("recalling_firm"),
            r.get("city"),
            r.get("state"),
            r.get("country"),
            r.get("product_description"),
            r.get("reason_for_recall"),
            r.get("distribution_pattern"),
            r.get("voluntary_mandated"),
            parse_date(r.get("recall_initiation_date")),
            parse_date(r.get("report_date")),
            Json(r),
        )
        for r in records
    ]

    query = """
        INSERT INTO recalls (
            recall_id, event_id, status, classification, product_type,
            recalling_firm, city, state, country, product_description,
            reason_for_recall, distribution_pattern, voluntary_mandated,
            recall_initiation_date, report_date, raw_payload
        )
        VALUES %s
        ON CONFLICT (recall_id) DO UPDATE SET
            status = EXCLUDED.status,
            classification = EXCLUDED.classification,
            last_seen_at = now()
    """

    with conn.cursor() as cur:
        execute_values(cur, query, rows)

    conn.commit()


def get_last_polled_at(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT last_polled_at FROM poller_state WHERE id = 1")
        result = cur.fetchone()

    return result[0] if result else None


def set_last_polled_at(conn, timestamp):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE poller_state SET last_polled_at = %s WHERE id = 1",
            (timestamp,),
        )

    conn.commit()


if __name__ == "__main__":
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    last_polled = get_last_polled_at(conn)

    if last_polled is None:
        print("No previous poll found — running full backfill")
        records = fetch_all_recalls_backfill()
    else:
        print(f"Polling for records since {last_polled}")
        records = fetch_recalls_since(last_polled)

    upsert_recalls(conn, records)
    print(f"Upserted {len(records)} records")

    set_last_polled_at(conn, datetime.now())
    conn.close()