from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db_connection
import logging

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form.get('role', 'customer')

        allowed_roles = ('customer', 'owner', 'mechanic')
        if role not in allowed_roles:
            flash('Invalid role selected')
            return redirect(url_for('main.index'))

        if password != confirm_password:
            flash('Passwords do not match')
            return redirect(url_for('main.index'))

        password_hash = generate_password_hash(password)

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                        "INSERT INTO users (name, email, password, role,created_at) VALUES (%s, %s, %s, %s, NOW()) RETURNING u_id",
                        (name, email, password_hash, role)
                )
                user_id = cur.fetchone()['u_id']

                role_table = {
                    'customer': 'customer',
                    'owner': 'owner',
                    'mechanic': 'mechanic',
                    'admin': 'admin'
                }

                cur.execute(
                    f"INSERT INTO {role_table[role]} (u_id) VALUES (%s)",
                    (user_id,)
                )
            conn.commit()
            flash('Account created successfully. Please log in.')
            return redirect(url_for('main.index'))

        except Exception:
            conn.rollback()
            logging.exception("Error creating user account")
            flash('Something went wrong - that email may already be registered.')
            return redirect(url_for('main.index'))
        finally:
            cur.close()
            conn.close()

    return redirect(url_for('main.index'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT u_id, name, password, role FROM users WHERE email = %s",
                        (email,)
                )
                user = cur.fetchone()

                if user is None or not check_password_hash(user['password'], password):
                    flash('Invalid email or password')
                    return redirect(url_for('main.index'))

                session.clear()
                session['user_id'] = user['u_id']
                session['user_name'] = user['name']
                session['role'] = user['role']
                print("DEBUG — about to set session, user dict:", dict(user))
                print("DEBUG — session right after setting:", dict(session))

                if user['role'] == 'admin':
                    return redirect(url_for('dashboard.admin'))
                elif user['role'] == 'customer':
                    return redirect(url_for('customer.home'))
                elif user['role'] == 'owner':
                    return redirect(url_for('dashboard.owner'))
                elif user['role'] == 'mechanic':
                    cur.execute("SELECT w_id FROM mechanic WHERE u_id = %s", (user['u_id'],))
                    mechanic = cur.fetchone()

                    if mechanic and mechanic['w_id']:
                        return redirect(url_for('dashboard.mechanic'))
                    else:
                        return redirect(url_for('mechanic.browse_workshops'))

                else:
                    return redirect(url_for('main.index'))
        finally:
            conn.close()



@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.index'))