import psycopg2
import psycopg2.extras
from flask import current_app, g


def get_db_connection():
    conn = psycopg2.connect(
        host=current_app.config['DB_HOST'],
        port=current_app.config['DB_PORT'],
        database=current_app.config['DB_NAME'],
        user=current_app.config['DB_USER'],
        password=current_app.config['DB_PASSWORD'],
        cursor_factory=psycopg2.extras.DictCursor
    )
    g.setdefault('_db_conns', []).append(conn)
    return conn


def close_db_connections(exc=None):
    for conn in g.pop('_db_conns', []):
        try:
            conn.close()
        except Exception:
            pass