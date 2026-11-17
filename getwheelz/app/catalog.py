import logging
import time

from app.db import get_db_connection

_TTL_SECONDS = 30
_cache = {'at': None, 'rows': []}


def get_catalog_services():
    """Return [{'name': 'Engine Repair', 'count': 3}, ...] sorted by name.

    'count' is how many workshops currently offer that service.
    """
    now = time.monotonic()
    if _cache['at'] is not None and now - _cache['at'] < _TTL_SECONDS:
        return _cache['rows']

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT sc.s_name AS name, COUNT(s.s_id) AS workshop_count
            FROM service_catalog sc
            LEFT JOIN service s ON s.sc_id = sc.sc_id
            GROUP BY sc.sc_id, sc.s_name
            ORDER BY sc.s_name
        """)
        rows = [{'name': r['name'], 'count': r['workshop_count']} for r in cur.fetchall()]
        cur.close()
        _cache['at'] = now
        _cache['rows'] = rows
        return rows
    except Exception:
        # never break a page because the navbar list failed: fall back to the last good list
        logging.exception('Could not load the service catalog')
        return _cache['rows']
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def clear_catalog_cache():
    _cache['at'] = None