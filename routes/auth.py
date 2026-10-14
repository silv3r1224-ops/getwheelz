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
            flash('Invalid role selected', 'error')
            return redirect(url_for('main.index'))

        if password != confirm_password:
            flash('Passwords do not match', 'error')
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
            flash('Account created successfully. Please log in.', 'success')
            return redirect(url_for('main.index'))

        except Exception:
            conn.rollback()
            logging.exception("Error creating user account")
            flash('Something went wrong - that email may already be registered.', 'error')
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
                cur.execute("SELECT u_id, name, password, role FROM users WHERE email = %s", (email,))
                user = cur.fetchone()

                if user is None or not check_password_hash(user['password'], password):
                    flash('Invalid email or password', 'error')
                    return redirect(url_for('main.index'))

                admin_row = None
                if user['role'] == 'admin':
                    cur.execute(
                        "SELECT admin_type, is_active FROM admin WHERE u_id = %s",
                        (user['u_id'],)
                    )
                    admin_row = cur.fetchone()
                    if not admin_row or not admin_row['is_active']:
                        flash('This admin account is inactive or not configured.', 'error') 
                        return redirect(url_for('main.index'))

                session.clear()
                session['user_id'] = user['u_id']
                session['user_name'] = user['name']
                session['role'] = user['role']
                if admin_row:
                    session['admin_type'] = admin_row['admin_type']
                    session['is_main_admin'] = admin_row['admin_type'] == 'main'

                flash(f"Welcome back, {user['name']}!", 'success') 

                if user['role'] == 'admin':
                    return redirect(url_for('dashboard.admin'))
                elif user['role'] == 'customer':
                    return redirect(url_for('customer.home'))
                elif user['role'] == 'owner':
                    return redirect(url_for('dashboard.owner'))
                elif user['role'] == 'mechanic':
                    return redirect(url_for('mechanics.home'))
                else:
                    return redirect(url_for('main.index'))
        finally:
            conn.close()
    return redirect(url_for('main.index'))
    

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.index'))