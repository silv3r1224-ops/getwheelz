"""Workshop opening hours: a per-day schedule that refines the owner's Open/Closed switch.

The workshop table keeps ``is_open`` as the manual Open/Closed switch. The optional
``workshop_hours`` table adds a weekly schedule (one row per weekday). The *effective*
status customers see is computed here, in Python, at every place a page or API decides
whether a workshop is open:

* manual switch off -> always closed (the schedule cannot override it);
* no schedule at all -> the manual switch decides (old behaviour);
* schedule exists -> open only inside today's window; a day with no row (or NULL times)
  means closed that day.

Rows support overnight ranges (e.g. 20:00 to 02:00). ``dow`` follows Python's weekday():
0 = Monday ... 6 = Sunday (same as the database check constraint).
"""
import datetime

# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------


def fetch_map(cur, workshop_ids):
    """Return {w_id: {dow: (open_time, close_time)}} for the given workshops.

    ``workshop_ids`` may be any iterable; an empty list returns {}. Rows with NULL
    times (closed that day) are included as (None, None).
    """
    ids = list(dict.fromkeys(workshop_ids))
    if not ids:
        return {}
    cur.execute(
        """
        SELECT workshop_id, dow, open_time, close_time
        FROM workshop_hours
        WHERE workshop_id = ANY(%s)
        """,
        (ids,),
    )
    out = {}
    for r in cur.fetchall():
        out.setdefault(r["workshop_id"], {})[r["dow"]] = (r["open_time"], r["close_time"])
    return out


# ---------------------------------------------------------------------------
# effective status
# ---------------------------------------------------------------------------


def open_now(is_open, day_map, now=None):
    """Effective 'open right now' status for one workshop.

    ``is_open`` is the manual switch; ``day_map`` is the {dow: (open, close)}
    schedule from :func:`fetch_map` (may be empty or missing days).
    """
    if not is_open:
        return False
    if not day_map:
        return True
    now = now or datetime.datetime.now()
    pair = day_map.get(now.weekday())
    if pair is None:
        return False
    op, cl = pair
    if op is None or cl is None:
        return False
    t = now.time()
    if cl <= op:  # crosses midnight: e.g. 20:00-02:00
        return t >= op or t < cl
    return op <= t < cl
