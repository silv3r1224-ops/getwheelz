from flask import Blueprint, render_template, request, jsonify, abort, session
from app.db import get_db_connection

workshops_bp = Blueprint('workshops', __name__)


@workshops_bp.route('/search')
def search():
    service = request.args.get('service', '').strip()
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    cur = conn.cursor()

    if service:
        cur.execute("""
            SELECT DISTINCT w.w_id, w.name, w.address, w.latitude, w.longitude
            FROM workshop w
            JOIN service s ON s.w_id = w.w_id
            JOIN service_catalog sc ON sc.sc_id = s.sc_id
            WHERE sc.s_name ILIKE %s
        """, (f'%{service}%',))
    else:
        cur.execute("SELECT w_id, name, address, latitude, longitude FROM workshop")

    workshops = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('workshops/search.html', workshops=workshops,
                           service=service, user_lat=lat, user_lng=lng)


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
            SELECT w.w_id, w.name, w.address, w.photo_path,
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