"""Vehicle types: cars and two-wheelers (spec section 5).

Every rule about vehicle types lives here, in plain functions that do not touch the
database, so routes, templates and tests all agree on them:

* A workshop declares what it serves: cars, two-wheelers, or both
  (``workshop.serves_cars`` / ``workshop.serves_two_wheelers``).
* The admin service catalog is split by ``service_catalog.vehicle_type``. A service a
  workshop offers inherits its type from its catalog entry, which is how a workshop that
  serves both has its services "classified by vehicle type".
* A workshop may only offer catalog entries whose type it serves.
* The customer picks a type first. The choice rides in the ``vehicle`` query parameter and
  is remembered in the session so later pages (workshop page, booking form) agree with it.
* There are no saved vehicle profiles: each booking records its own type and a free-text
  description (``booking.vehicle_type`` / ``booking.vehicle_description``).
"""

CAR = "car"
TWO_WHEELER = "two_wheeler"

# Canonical order: wherever types are listed, cars come first.
VEHICLE_TYPES = (CAR, TWO_WHEELER)

PLURAL_LABELS = {CAR: "Four-wheelers", TWO_WHEELER: "Two-wheelers"}
SINGULAR_LABELS = {CAR: "Four-wheeler", TWO_WHEELER: "Two-wheeler"}

DESCRIPTION_MAX = 150  # booking.vehicle_description is VARCHAR(150)

SESSION_KEY = "vehicle"

_TRUTHY = {"1", "true", "on", "yes", "y"}


def normalize(value):
    """Return a valid vehicle type for ``value``, or None when it is not one."""
    if isinstance(value, str):
        cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned in VEHICLE_TYPES:
            return cleaned
    return None


def is_truthy(value):
    """True for what an HTML checkbox sends ('on') or an explicit yes."""
    return isinstance(value, str) and value.strip().lower() in _TRUTHY


def workshop_types(serves_cars, serves_two_wheelers):
    """The vehicle types a workshop serves, in canonical order."""
    types = []
    if serves_cars:
        types.append(CAR)
    if serves_two_wheelers:
        types.append(TWO_WHEELER)
    return types


def parse_workshop_types(form):
    """Read the owner's choice from a submitted form.

    ``form`` is anything with ``.get`` (a Flask ``request.form``). Returns
    ``(serves_cars, serves_two_wheelers, error)``; ``error`` is a message for the
    owner when neither box is ticked, else None.
    """
    cars = is_truthy(form.get("serves_cars"))
    two_wheelers = is_truthy(form.get("serves_two_wheelers"))
    if not cars and not two_wheelers:
        return (
            cars,
            two_wheelers,
            "Please choose what your workshop serves: four-wheelers, two-wheelers, or both.",
        )
    return cars, two_wheelers, None


def serves(serves_cars, serves_two_wheelers, vehicle_type):
    """Does a workshop with these flags serve ``vehicle_type``?"""
    if vehicle_type == CAR:
        return bool(serves_cars)
    if vehicle_type == TWO_WHEELER:
        return bool(serves_two_wheelers)
    return False


def service_allowed(serves_cars, serves_two_wheelers, catalog_type):
    """May a workshop with these flags offer a catalog entry of ``catalog_type``?

    A car-only workshop may only use the car catalog, a two-wheeler-only workshop only
    the two-wheeler catalog, and a workshop serving both may use either.
    """
    return serves(serves_cars, serves_two_wheelers, catalog_type)


def orphaned_types(serves_cars, serves_two_wheelers, service_types):
    """Types of existing services that would no longer be allowed after an edit.

    ``service_types`` is the catalog type of each service the workshop offers today.
    The owner may not narrow what the workshop serves while services of a dropped type
    remain, so the route refuses and names the types this returns (canonical order).
    """
    present = set(service_types)
    return [
        t
        for t in VEHICLE_TYPES
        if t in present and not serves(serves_cars, serves_two_wheelers, t)
    ]


def describe(serves_cars, serves_two_wheelers):
    """'Four-wheelers', 'Two-wheelers' or 'Four-wheelers and two-wheelers' for display."""
    if serves_cars and serves_two_wheelers:
        return "Four-wheelers and two-wheelers"
    if serves_two_wheelers:
        return PLURAL_LABELS[TWO_WHEELER]
    return PLURAL_LABELS[CAR]


def clean_description(raw):
    """Tidy the free-text vehicle description typed at booking time.

    Returns ``(text, error)``. The description is required (make and model at least;
    the plate is optional and simply part of the text), whitespace is collapsed, and it
    must fit the column.
    """
    text = " ".join((raw or "").split())
    if not text:
        return "", "Please describe your vehicle, for example: Honda City 2019 (plate optional)."
    if len(text) > DESCRIPTION_MAX:
        return text, f"Please keep the vehicle description under {DESCRIPTION_MAX} characters."
    return text, None


def chosen_vehicle(remember=False):
    """The vehicle type the visitor picked, or None when they have not picked yet.

    Order of precedence: a valid ``vehicle`` query parameter, then the session. With
    ``remember=True`` a valid query parameter is stored in the session, so call it that
    way from the routes a visitor lands on and plain from helpers that only read.
    """
    # imported here so the pure helpers above stay importable without a Flask context
    from flask import request, session

    from_url = normalize(request.args.get("vehicle"))
    if from_url:
        if remember:
            session[SESSION_KEY] = from_url
        return from_url
    return normalize(session.get(SESSION_KEY))
