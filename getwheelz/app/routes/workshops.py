import math
from flask import Blueprint, render_template, request, jsonify, abort, session
from app.db import get_db_connection

workshops_bp = Blueprint('workshops', __name__)


def _distance_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in kilometres (same formula the /nearby query uses)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lng = math.radians(lng2 - lng1)
    cos_angle = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(d_lng)
    return 6371 * math.acos(max(-1.0, min(1.0, cos_angle)))


def _distance_label(km):
    """450 m, 3.2 km, 27 km (kept identical to GW.formatDistance in distance.js)."""
    if km < 1:
        return f"{max(10, round(km * 100) * 10)} m"
    if km < 10:
        return f"{km:.1f} km"
    return f"{round(km)} km"


def _like(term):
    """Turn user text into a safe ILIKE pattern (so '%' and '_' typed by the user are literal)."""
    escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


@workshops_bp.route('/search')
def search():
    service = request.args.get('service', '').strip()
    picked = [s.strip() for s in request.args.getlist('services') if s.strip()]
    terms = ([service] if service else []) + [s for s in picked if s.lower() != service.lower()]

    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None

    where, params = '', []
    if terms:
        likes = ' OR '.join(['sc2.s_name ILIKE %s'] * len(terms))
        where = f"""WHERE EXISTS (
            SELECT 1 FROM service s2 JOIN service_catalog sc2 ON sc2.sc_id = s2.sc_id
            WHERE s2.w_id = w.w_id AND ({likes}))"""
        params = [_like(t) for t in terms]

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT w.w_id, w.name, w.address, w.latitude, w.longitude, w.photo_path, w.is_open,
                       array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
                FROM workshop w
                LEFT JOIN service s ON s.w_id = w.w_id
                LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id
                {where}
                GROUP BY w.w_id, w.name, w.address, w.latitude, w.longitude, w.photo_path, w.is_open
            """, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    workshops = []
    for r in rows:
        w = dict(r)
        w['distance_km'] = w['distance_label'] = None
        if lat is not None and w['latitude'] is not None and w['longitude'] is not None:
            km = _distance_km(lat, lng, w['latitude'], w['longitude'])
            w['distance_km'] = round(km, 3)
            w['distance_label'] = _distance_label(km)
        workshops.append(w)

    # nearest first when we know where the visitor is, otherwise A to Z
    if lat is not None:
        workshops.sort(key=lambda w: (w['distance_km'] is None, w['distance_km'] or 0, w['name'].lower()))
    else:
        workshops.sort(key=lambda w: w['name'].lower())

    return render_template('workshops/search.html', workshops=workshops, service=service,
                           terms=terms, user_lat=lat, user_lng=lng)


@workshops_bp.route('/nearby')
def nearby():
    try:
        lat = float(request.args['lat'])
        lng = float(request.args['lng'])
        radius = min(float(request.args.get('radius', 25)), 200)
    except (KeyError, ValueError):
        return jsonify(error='Invalid location'), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM (
            SELECT w.w_id, w.name, w.address, w.photo_path, w.is_open,
                   6371 * acos(LEAST(1, GREATEST(-1,
                       cos(radians(%s)) * cos(radians(w.latitude))
                       * cos(radians(w.longitude) - radians(%s))
                       + sin(radians(%s)) * sin(radians(w.latitude))
                   ))) AS distance_km
            FROM workshop w
            WHERE w.latitude IS NOT NULL AND w.longitude IS NOT NULL
        ) t
        WHERE distance_km <= %s
        ORDER BY distance_km
        LIMIT 12
    """, (lat, lng, lat, radius))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        'w_id': r['w_id'],
        'name': r['name'],
        'address': r['address'],
        'photo_url': r['photo_path'],
        'is_open': r['is_open'],
        'distance_km': round(r['distance_km'], 1),
    } for r in rows])


@workshops_bp.route('/<int:w_id>')
def selected(w_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM workshop WHERE w_id = %s", (w_id,))
    workshop = cur.fetchone()
    if not workshop:
        cur.close()
        conn.close()
        abort(404)

    cur.execute("""
        SELECT s.s_id, sc.s_name, s.price_range, s.duration
        FROM service s
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        WHERE s.w_id = %s
        ORDER BY sc.s_name
    """, (w_id,))
    services = cur.fetchall()

    # extra context when a mechanic is previewing the workshop
    mech = None
    if session.get('role') == 'mechanic':
        cur.execute("SELECT m_id, w_id FROM mechanic WHERE u_id = %s", (session['user_id'],))
        m = cur.fetchone()
        if m:
            cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (w_id,))
            total = cur.fetchone()['n']
            cur.execute("SELECT 1 FROM join_request WHERE m_id = %s AND w_id = %s AND status = 'pending'",
                        (m['m_id'], w_id))
            mech = {
                'my_workshop': m['w_id'],
                'pending': cur.fetchone() is not None,
                'total': total,
                'capacity': workshop['capacity'],
                'open_slots': workshop['capacity'] - total,
            }

    cur.close()
    conn.close()

    return render_template('workshops/selected.html', workshop=workshop, services=services, mech=mech)