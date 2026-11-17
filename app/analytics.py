"""Owner analytics (spec section 10). Pure Python: no Flask, no database.

The owner dashboard feeds these functions the rows it already loaded (the owner's OWN workshop's
bookings with their payment, and its reviews), so every figure on the page is computed from the same
rows the bookings table shows. DEFINITIONS (shown to the owner under each chart):

* Earnings    = money from bookings that are COMPLETED and PAID (a payment row exists), counted in the
                month the payment was made. Completed-but-unpaid work is "awaiting payment", not earnings.
* Ratings     = the average star rating of reviews, per month the review was written, plus the overall
                average, the number of reviews and how many of each star.
* Busiest days = how many bookings fall on each weekday (by appointment day). Cancelled bookings are not
                counted: they never became work.
* Top services = services ranked by number of bookings (cancelled excluded), with the earnings each
                one brought in.

Vehicle split (workshops serving both cars and two-wheelers): every function takes rows that were
already filtered with ``filter_vehicle``. Bookings with no recorded vehicle type are cars (the default
for older bookings, spec section 5).
"""
from collections import defaultdict
from decimal import Decimal

VEHICLE_ALL, VEHICLE_CAR, VEHICLE_TWO_WHEELER = "all", "car", "two_wheeler"
VEHICLE_FILTERS = (VEHICLE_ALL, VEHICLE_CAR, VEHICLE_TWO_WHEELER)
VEHICLE_LABELS = {VEHICLE_ALL: "All vehicles", VEHICLE_CAR: "Four-wheelers", VEHICLE_TWO_WHEELER: "Two-wheelers"}

RANGES = (3, 6, 12)  # months shown in the over-time charts
DEFAULT_RANGE = 6
TOP_SERVICES = 5
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# ---------------------------------------------------------------- query parameters
def clean_vehicle(raw, serves_cars, serves_two_wheelers):
    """The vehicle filter from ?vehicle=. A workshop serving only one type has nothing to split, and an
    unknown value means "all"."""
    raw = (raw or "").strip().lower()
    if not (serves_cars and serves_two_wheelers):
        return VEHICLE_ALL
    return raw if raw in VEHICLE_FILTERS else VEHICLE_ALL


def clean_range(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RANGE
    return value if value in RANGES else DEFAULT_RANGE


def vehicle_of(row):
    return row.get("vehicle_type") or VEHICLE_CAR


def filter_vehicle(rows, vehicle):
    if vehicle == VEHICLE_ALL:
        return list(rows)
    return [r for r in rows if vehicle_of(r) == vehicle]


# ---------------------------------------------------------------- months
def month_buckets(today, count):
    """The last ``count`` calendar months ending with today's month, oldest first, as (year, month)."""
    year, month = today.year, today.month
    months = []
    for _ in range(count):
        months.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def month_label(ym):
    return f"{MONTH_NAMES[ym[1] - 1]} {str(ym[0])[2:]}"


def _month_of(moment):
    return (moment.year, moment.month)


# ---------------------------------------------------------------- earnings
def is_earning(booking):
    """Completed AND paid."""
    return booking.get("status") == "completed" and booking.get("paid_amount") is not None


def earnings(bookings, today, months):
    """Earnings per month and in total.

    Returns ``{"months": [{"label", "amount", "count"}...], "total", "count", "average", "this_month",
    "last_month", "awaiting", "awaiting_count"}`` with Decimal amounts. ``total`` covers ALL time (not
    just the months charted), so it matches the sum of the paid column in the bookings table.
    """
    by_month = defaultdict(lambda: [Decimal(0), 0])
    total, count = Decimal(0), 0
    awaiting, awaiting_count = Decimal(0), 0
    for b in bookings:
        if is_earning(b):
            amount = Decimal(b["paid_amount"])
            total += amount
            count += 1
            moment = b.get("paid_at") or b.get("requested_time")
            if moment is not None:
                by_month[_month_of(moment)][0] += amount
                by_month[_month_of(moment)][1] += 1
        elif b.get("status") == "completed" and b.get("paid_amount") is None:
            due = b.get("due")
            if due is not None:
                awaiting += Decimal(due)
                awaiting_count += 1
    buckets = month_buckets(today, months)
    series = [{"label": month_label(ym), "amount": by_month[ym][0], "count": by_month[ym][1]} for ym in buckets]
    this_month = by_month[_month_of(today)][0]
    previous = month_buckets(today, 2)[0]
    return {
        "months": series,
        "total": total,
        "count": count,
        "average": (total / count) if count else Decimal(0),
        "this_month": this_month,
        "last_month": by_month[previous][0],
        "awaiting": awaiting,
        "awaiting_count": awaiting_count,
    }


# ---------------------------------------------------------------- ratings over time
def ratings(reviews, today, months):
    """Ratings per month, overall, and the star distribution.

    ``{"months": [{"label", "avg", "count"}...] (avg None for a month with no reviews), "overall",
    "count", "distribution": {5: n, ..., 1: n}}``.
    """
    by_month = defaultdict(list)
    distribution = {star: 0 for star in (5, 4, 3, 2, 1)}
    total = 0
    for r in reviews:
        rating = int(r["rating"])
        total += rating
        distribution[rating] += 1
        by_month[_month_of(r["created_at"])].append(rating)
    series = []
    for ym in month_buckets(today, months):
        values = by_month.get(ym, [])
        series.append({
            "label": month_label(ym),
            "avg": (sum(values) / len(values)) if values else None,
            "count": len(values),
        })
    count = len(reviews)
    return {"months": series, "overall": (total / count) if count else None, "count": count,
            "distribution": distribution}


# ---------------------------------------------------------------- busiest days and top services
def counts_as_work(booking):
    return booking.get("status") != "cancelled"


def busiest_days(bookings):
    """Bookings per weekday (Mon..Sun), cancelled excluded.

    ``{"days": [{"label", "name", "count"}...7], "busiest": [names with the highest count], "total"}``.
    ``busiest`` is empty when there are no bookings, and lists every tied weekday otherwise.
    """
    counts = [0] * 7
    for b in bookings:
        if counts_as_work(b):
            counts[b["requested_time"].weekday()] += 1
    top = max(counts)
    return {
        "days": [{"label": WEEKDAYS[i], "name": WEEKDAY_NAMES[i], "count": counts[i]} for i in range(7)],
        "busiest": [WEEKDAY_NAMES[i] for i in range(7) if counts[i] == top] if top else [],
        "total": sum(counts),
    }


def top_services(bookings, limit=TOP_SERVICES):
    """Services ranked by bookings (cancelled excluded), then by earnings, then by name.

    ``[{"name", "count", "earned"} ...]``. ``earned`` is money from completed AND paid bookings only.
    """
    stats = defaultdict(lambda: [0, Decimal(0)])
    for b in bookings:
        if not counts_as_work(b):
            continue
        entry = stats[b["s_name"]]
        entry[0] += 1
        if is_earning(b):
            entry[1] += Decimal(b["paid_amount"])
    rows = [{"name": name, "count": c, "earned": e} for name, (c, e) in stats.items()]
    rows.sort(key=lambda r: (-r["count"], -r["earned"], r["name"].lower()))
    return rows[:limit]


def vehicle_split(bookings, reviews):
    """Totals for each vehicle type, for workshops serving both: earnings, bookings, reviews and average."""
    out = {}
    for vehicle in (VEHICLE_CAR, VEHICLE_TWO_WHEELER):
        mine = [b for b in bookings if vehicle_of(b) == vehicle]
        rated = [r for r in reviews if vehicle_of(r) == vehicle]
        out[vehicle] = {
            "label": VEHICLE_LABELS[vehicle],
            "earned": sum((Decimal(b["paid_amount"]) for b in mine if is_earning(b)), Decimal(0)),
            "bookings": sum(1 for b in mine if counts_as_work(b)),
            "reviews": len(rated),
            "avg_rating": (sum(int(r["rating"]) for r in rated) / len(rated)) if rated else None,
        }
    return out


# ---------------------------------------------------------------- chart geometry
def bar_heights(values):
    """Each value as a percentage of the tallest (0..100). All zero (or empty) gives all zeros."""
    top = max((float(v) for v in values), default=0.0)
    if top <= 0:
        return [0.0 for _ in values]
    return [round(float(v) / top * 100, 1) for v in values]


def line_segments(values, width=300, height=120, low=1.0, high=5.0, pad=10):
    """SVG points for a line chart. ``values`` may contain None (a month with no data), which BREAKS the
    line instead of drawing a false zero: returns ``(segments, dots)`` where segments is a list of
    "x,y x,y ..." strings (runs of two or more points) and dots a list of (x, y) for every real point."""
    n = len(values)
    span = high - low
    xs = [pad + (width - 2 * pad) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]

    def y_of(v):
        clamped = min(max(float(v), low), high)
        return round(pad + (height - 2 * pad) * (1 - (clamped - low) / span), 1)

    segments, run, dots = [], [], []
    for x, v in zip(xs, values):
        if v is None:
            if len(run) > 1:
                segments.append(" ".join(run))
            run = []
            continue
        point = (round(x, 1), y_of(v))
        dots.append(point)
        run.append(f"{point[0]},{point[1]}")
    if len(run) > 1:
        segments.append(" ".join(run))
    return segments, dots


def has_any_data(bookings, reviews):
    """False for a brand new workshop: the dashboard then shows one clear empty state."""
    return bool(bookings) or bool(reviews)


def build(bookings, reviews, today, vehicle, months, serves_both):
    """Everything the dashboard section shows, from the owner's own bookings and reviews.

    ``serves_both``: the workshop serves cars AND two-wheelers, so the vehicle split is offered. For any
    other workshop the filter is ignored (there is nothing to split).
    """
    vehicle = vehicle if serves_both and vehicle in VEHICLE_FILTERS else VEHICLE_ALL
    shown_bookings = filter_vehicle(bookings, vehicle)
    shown_reviews = filter_vehicle(reviews, vehicle)

    earn = earnings(shown_bookings, today, months)
    rate = ratings(shown_reviews, today, months)
    segments, dots = line_segments([m["avg"] for m in rate["months"]])
    return {
        "vehicle": vehicle,
        "months": months,
        "split_available": bool(serves_both),
        "split": vehicle_split(bookings, reviews) if serves_both else None,
        "has_data": has_any_data(shown_bookings, shown_reviews),
        "earnings": earn,
        "earn_bars": bar_heights([m["amount"] for m in earn["months"]]),
        "ratings": rate,
        "rating_segments": segments,
        "rating_dots": dots,
        "rating_labels": [m["label"] for m in rate["months"]],
        "busiest_days": busiest_days(shown_bookings),
        "day_bars": bar_heights([d["count"] for d in busiest_days(shown_bookings)["days"]]),
        "top_services": top_services(shown_bookings),
    }
