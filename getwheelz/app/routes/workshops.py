from flask import Blueprint, render_template, request
from app.db import get_db_connection

workshops_bp = Blueprint('workshops', __name__)

@workshops_bp.route('/search')
def search():
    service = request.args.get('service', '')
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    cur = conn.cursor()

    if service:
        cur.execute("""
            SELECT DISTINCT w.w_id, w.name, w.address, w.latitude, w.longitude
            FROM workshop w
            JOIN service s ON s.w_id = w.w_id
            WHERE s.s_name ILIKE %s
        """, (f'%{service}%',))
    else:
        cur.execute("SELECT w_id, name, address, latitude, longitude FROM workshop")

    workshops = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('workshops/search.html', workshops=workshops, service=service, user_lat=lat, user_lng=lng)

@workshops_bp.route('/<int:w_id>')
def selected(w_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM workshop WHERE w_id = %s", (w_id,))
    workshop = cur.fetchone()

    cur.execute("SELECT * FROM service WHERE w_id = %s", (w_id,))
    services = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('workshops/selected.html', workshop=workshop, services=services)