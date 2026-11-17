"""Terms, Privacy Policy, Owner Agreement and the accept page (Phase 8; spec section 11).

The documents are public. Everyone who signs up accepts the Terms and Privacy Policy with a required
checkbox (routes/auth.py records it); owners also accept the Owner Agreement before listing a workshop
(routes/dashboard/owner.py). When a document's version changes (app/legal.py), the gate in
app/__init__.py sends each signed-in person here to accept the new version before they carry on; every
acceptance is a new row in user_consent, so the history of who accepted what, and when, is kept.
"""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import booking_rules as rules
from app import legal
from app.db import get_db_connection

legal_bp = Blueprint('legal', __name__)


# ---------------------------------------------------------------- database helpers (take a cursor)
def accepted_pairs(cur, u_id):
    """Every ``(doc, version)`` this person has ever accepted."""
    cur.execute("SELECT doc, version FROM user_consent WHERE u_id = %s", (u_id,))
    return [(r['doc'], r['version']) for r in cur.fetchall()]


def owner_has_workshop(cur, u_id):
    cur.execute("""
        SELECT 1 FROM workshop w JOIN owner o ON o.o_id = w.o_id WHERE o.u_id = %s LIMIT 1
    """, (u_id,))
    return cur.fetchone() is not None


def record_consent(cur, u_id, docs, at=None):
    """Record that this person accepted the CURRENT version of each of ``docs`` now. Accepting the
    same version twice changes nothing (the first acceptance and its time are kept)."""
    for doc, version in legal.rows_to_record(docs):
        cur.execute("""
            INSERT INTO user_consent (u_id, doc, version, accepted_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (u_id, doc, version) DO NOTHING
        """, (u_id, doc, version, at or rules.now()))


def remember_consent(role, has_workshop):
    """Tell the session this person is up to date, so the database is not asked on every page."""
    session['consent_ws'] = bool(has_workshop)
    session['consent_sig'] = legal.signature(role, has_workshop)


# ---------------------------------------------------------------- the documents
def _page(template, doc):
    return render_template(template, version=legal.VERSIONS[doc], title=legal.TITLES[doc],
                           draft_notice=legal.DRAFT_NOTICE)


@legal_bp.route('/terms')
def terms():
    return _page('legal/terms.html', legal.DOC_TERMS)


@legal_bp.route('/privacy')
def privacy():
    return _page('legal/privacy.html', legal.DOC_PRIVACY)


@legal_bp.route('/owner-agreement')
def owner_agreement():
    return _page('legal/owner_agreement.html', legal.DOC_OWNER)


# ---------------------------------------------------------------- accepting (new sign-in or new version)
@legal_bp.route('/legal/accept', methods=['GET', 'POST'])
def accept():
    if not session.get('user_id'):
        return redirect(url_for('main.index'))
    role = session.get('role')
    nxt = legal.safe_next(request.values.get('next'), fallback=url_for('main.index'))
    if not legal.requires_consent(role):
        return redirect(nxt)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            has_ws = owner_has_workshop(cur, session['user_id']) if role == 'owner' else False
            missing = legal.missing_docs(accepted_pairs(cur, session['user_id']), role, has_ws)
            if not missing:
                remember_consent(role, has_ws)
                return redirect(nxt)
            if request.method == 'POST':
                if request.form.get('agree') not in ('on', '1', 'true', 'yes'):
                    flash('Please tick the box to accept and continue.', 'error')
                else:
                    record_consent(cur, session['user_id'], missing)
                    conn.commit()
                    remember_consent(role, has_ws)
                    flash('Thanks, your acceptance was recorded.', 'success')
                    return redirect(nxt)
    finally:
        conn.close()
    return render_template('legal/accept.html', missing=missing, titles=legal.TITLES, versions=legal.VERSIONS,
                           next_url=nxt)
