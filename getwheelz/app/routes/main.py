from flask import Blueprint, render_template,redirect, url_for, request, flash
from app.db import get_db_connection

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT w_id, name, address, latitude, longitude FROM workshop LIMIT 10")
    workshops = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', workshops=workshops)

@main_bp.route('/about')
def about():
    return render_template('about.html')

@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        subject = request.form.get('subject')
        message = request.form['message']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO feedback (name, email, subject, message) VALUES (%s, %s, %s, %s)",
            (name, email, subject, message)
        )
        conn.commit()
        cur.close()
        conn.close()

        flash('Message sent — thank you for reaching out!')
        return redirect(url_for('main.contact'))

    return render_template('contact.html')

@main_bp.route('/services')
def services():
    return render_template('services.html')
