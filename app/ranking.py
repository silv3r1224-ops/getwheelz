"""How search results are ordered (spec section 7). This is the ONE place the formula lives.

Default order ("best match") blends distance and rating::

    score = 0.6 * distance_score + 0.4 * rating_score          (visitor's location known)
    score = rating_score                                         (location unknown)

* distance_score = 1 / (1 + km / 10): 1.0 at the visitor's door, 0.5 at 10 km, 0.25 at 30 km.
  A workshop with no map position gets 0 when the visitor's location is known.
* rating_score is the workshop's rating mapped onto 0..1 after a "prior" is mixed in, so one
  five-star review does not beat fifty reviews averaging 4.8:
      adjusted = (count * average + 3 * 3.5) / (count + 3)        # 3.5 = neutral rating, worth 3 reviews
      rating_score = (adjusted - 1) / 4
  A workshop with no reviews has adjusted = 3.5 (score 0.625): neither rewarded nor punished.

Ties are broken by name, so the order is stable. Change the numbers below to retune; the tests in
tests/test_ranking_contact.py pin the behaviour, not the constants.

No web or database code lives here, so the formula can be tested on its own.
"""

DISTANCE_WEIGHT = 0.6
RATING_WEIGHT = 0.4
DISTANCE_SCALE_KM = 10.0
PRIOR_RATING = 3.5
PRIOR_WEIGHT = 3

SORT_BEST, SORT_NEAREST, SORT_RATING, SORT_NAME = "best", "nearest", "rating", "name"
SORT_MODES = (SORT_BEST, SORT_NEAREST, SORT_RATING, SORT_NAME)
SORT_LABELS = {
    SORT_BEST: "Best match",
    SORT_NEAREST: "Nearest",
    SORT_RATING: "Top rated",
    SORT_NAME: "A–Z",
}


def normalize_sort(raw):
    """The sort mode from ?sort=, defaulting to best match for anything unknown."""
    raw = (raw or "").strip().lower()
    return raw if raw in SORT_MODES else SORT_BEST


def distance_score(km):
    """1.0 right here, falling towards 0 with distance. None (no map position) scores 0."""
    if km is None:
        return 0.0
    return 1.0 / (1.0 + max(km, 0.0) / DISTANCE_SCALE_KM)


def adjusted_rating(average, count):
    """The average rating pulled towards neutral when there are few reviews (1..5)."""
    if not count or average is None:
        return PRIOR_RATING
    return (count * float(average) + PRIOR_WEIGHT * PRIOR_RATING) / (count + PRIOR_WEIGHT)


def rating_score(average, count):
    """The adjusted rating mapped onto 0..1."""
    return (adjusted_rating(average, count) - 1.0) / 4.0


def blended_score(km, average, count, have_location):
    """The default score; see the module docstring."""
    rating = rating_score(average, count)
    if not have_location:
        return rating
    return DISTANCE_WEIGHT * distance_score(km) + RATING_WEIGHT * rating


def sort_workshops(workshops, mode, have_location):
    """Order dicts that have name, distance_km, rating_avg and rating_count. Sets ``rank_score``.

    ``nearest`` without a known location falls back to best match (there is nothing to measure).
    """
    mode = normalize_sort(mode)
    for w in workshops:
        w["rank_score"] = blended_score(
            w.get("distance_km"), w.get("rating_avg"), w.get("rating_count") or 0, have_location
        )

    def name(w):
        return (w.get("name") or "").lower()

    if mode == SORT_NAME:
        return sorted(workshops, key=name)
    if mode == SORT_NEAREST and have_location:
        return sorted(
            workshops,
            key=lambda w: (w.get("distance_km") is None, w.get("distance_km") or 0.0, name(w)),
        )
    if mode == SORT_RATING:
        return sorted(
            workshops,
            key=lambda w: (
                -adjusted_rating(w.get("rating_avg"), w.get("rating_count") or 0),
                -(w.get("rating_count") or 0),
                name(w),
            ),
        )
    return sorted(workshops, key=lambda w: (-w["rank_score"], name(w)))
