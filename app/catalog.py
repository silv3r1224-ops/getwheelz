import logging
import time

from app.db import get_db_connection

_TTL_SECONDS = 30
# one cached list per key: 'car', 'two_wheeler', or 'all' (every type, same names merged)
_cache = {}


def get_catalog_services(vehicle_type=None):
    """Return [{'name': 'Engine Repair', 'count': 3}, ...] sorted by name.

    'count' is how many approved workshops currently offer that service (pending and rejected
    listings are hidden from customers, so they are not counted either).

    With a vehicle type ('car' or 'two_wheeler') only that catalog is listed. With None the
    two catalogs are merged, so a name that exists in both appears once (counts added up).
    """
    key = vehicle_type or "all"
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is not None and now - entry["at"] < _TTL_SECONDS:
        return entry["rows"]

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        where, params = "", ()
        if vehicle_type:
            where, params = "WHERE sc.vehicle_type = %s", (vehicle_type,)
        cur.execute(
            f"""
            SELECT sc.s_name AS name, COUNT(w.w_id) AS workshop_count
            FROM service_catalog sc
            LEFT JOIN service s ON s.sc_id = sc.sc_id
            LEFT JOIN workshop w ON w.w_id = s.w_id AND w.status = 'approved'
            {where}
            GROUP BY sc.s_name
            ORDER BY sc.s_name
        """,
            params,
        )
        rows = [{"name": r["name"], "count": r["workshop_count"]} for r in cur.fetchall()]
        cur.close()
        _cache[key] = {"at": now, "rows": rows}
        return rows
    except Exception:
        # never break a page because the navbar list failed: fall back to the last good list
        logging.exception("Could not load the service catalog")
        return entry["rows"] if entry is not None else []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def clear_catalog_cache():
    _cache.clear()
