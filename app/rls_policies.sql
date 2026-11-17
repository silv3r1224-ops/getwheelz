-- ==========================================================================
-- Row-level security (RLS) for Getwheelz / MechConnect.
--
-- Defense-in-depth: the application already scopes every query by the signed-in
-- user inside its SQL. RLS makes that a *database-level guarantee*, so even a
-- future route that forgets a WHERE clause cannot read or mutate rows it must
-- not touch.
--
-- How it works:
--   * The app connects as one database role (the table owner). RLS normally
--     does not apply to the owner, so every protected table is FORCEd, which
--     makes the policies apply to that role too.
--   * At the start of each request app/db.py sets three session variables:
--       app.luid   -> the signed-in user's u_id (0 when signed out)
--       app.lrole  -> the signed-in role ('customer' | 'owner' | 'mechanic'
--                      | 'admin' | '')
--       app.ladmin -> the admin sub-type when signed in as an admin, else ''
--     The helper functions below read them. When nobody is signed in the
--     values are empty/0, which policies treat as "no access" except for the
--     explicitly public operations (signup, login, public browsing, contact
--     form) and the two token-authorized writes (password reset, Google
--     account linking) that set the context themselves before acting.
--   * Policies are named <table>_<op> so they can be dropped individually.
--
-- Idempotent: safe to re-run. Apply with:
--   venv/Scripts/python.exe scripts/apply_rls.py
-- ==========================================================================

-- --------------------------------------------------------------------------
-- Helper functions (session context)
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_luid() RETURNS int LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.luid', true), '')::int
$$;

CREATE OR REPLACE FUNCTION app_lrole() RETURNS text LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.lrole', true), '')
$$;

CREATE OR REPLACE FUNCTION app_ladmin() RETURNS text LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.ladmin', true), '')
$$;

-- --------------------------------------------------------------------------
-- users
-- Rows are visible to everyone pre-auth (login / forgot-password / public
-- profiles) and to signed-in users, but writes are strictly scoped: a user
-- can change only their own row (or admins anyone). The two token-authorized
-- pre-auth writes call app.set_current_user() first, so they act as that user.
-- --------------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS users_select ON users;
CREATE POLICY users_select ON users FOR SELECT USING (true);

DROP POLICY IF EXISTS users_insert ON users;
CREATE POLICY users_insert ON users FOR INSERT
    WITH CHECK (app_luid() = 0 OR app_ladmin() <> '');

DROP POLICY IF EXISTS users_update ON users;
CREATE POLICY users_update ON users FOR UPDATE
    USING (u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS users_delete ON users;
CREATE POLICY users_delete ON users FOR DELETE
    USING (u_id = app_luid() OR app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- admin (only admins may see the table; only the main admin may edit it)
-- --------------------------------------------------------------------------
ALTER TABLE admin ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS admin_select ON admin;
CREATE POLICY admin_select ON admin FOR SELECT
    USING (app_luid() = 0 OR app_ladmin() <> '');

DROP POLICY IF EXISTS admin_update ON admin;
CREATE POLICY admin_update ON admin FOR UPDATE
    USING (app_ladmin() = 'main');

-- --------------------------------------------------------------------------
-- customer / owner (1:1 profile rows)
-- --------------------------------------------------------------------------
ALTER TABLE customer ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_select ON customer;
CREATE POLICY customer_select ON customer FOR SELECT
    USING (u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS customer_insert ON customer;
CREATE POLICY customer_insert ON customer FOR INSERT
    WITH CHECK (app_luid() = 0 OR u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS customer_update ON customer;
CREATE POLICY customer_update ON customer FOR UPDATE
    USING (u_id = app_luid() OR app_ladmin() <> '');

ALTER TABLE owner ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS owner_select ON owner;
CREATE POLICY owner_select ON owner FOR SELECT
    USING (u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS owner_insert ON owner;
CREATE POLICY owner_insert ON owner FOR INSERT
    WITH CHECK (app_luid() = 0 OR u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS owner_update ON owner;
CREATE POLICY owner_update ON owner FOR UPDATE
    USING (u_id = app_luid() OR app_ladmin() <> '');

-- Without a DELETE policy, FORCE ROW LEVEL SECURITY makes "DELETE FROM owner" silently remove 0 rows.
DROP POLICY IF EXISTS owner_delete ON owner;
CREATE POLICY owner_delete ON owner FOR DELETE
    USING (u_id = app_luid() OR app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- workshop (public to browse; only its owner or an admin may change it)
-- Vehicle types (serves_cars / serves_two_wheelers) are ordinary columns on this
-- table, so the policies below already cover them: public read, owner/admin write.
-- The same goes for the approval columns (status, rejection_reason, decided_by,
-- decided_at). Row policies cannot limit columns, so "only an admin may approve" and
-- "pending/rejected listings are hidden from customers" are enforced in the routes
-- and queries (see tests/test_workshop_approval.py), not by these policies.
-- --------------------------------------------------------------------------
ALTER TABLE workshop ENABLE ROW LEVEL SECURITY;
ALTER TABLE workshop FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS workshop_select ON workshop;
CREATE POLICY workshop_select ON workshop FOR SELECT USING (true);

DROP POLICY IF EXISTS workshop_insert ON workshop;
CREATE POLICY workshop_insert ON workshop FOR INSERT
    WITH CHECK (
        o_id IN (SELECT o_id FROM owner WHERE u_id = app_luid())
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS workshop_update ON workshop;
CREATE POLICY workshop_update ON workshop FOR UPDATE
    USING (
        o_id IN (SELECT o_id FROM owner WHERE u_id = app_luid())
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS workshop_delete ON workshop;
CREATE POLICY workshop_delete ON workshop FOR DELETE
    USING (
        o_id IN (SELECT o_id FROM owner WHERE u_id = app_luid())
        OR app_ladmin() <> ''
    );

-- --------------------------------------------------------------------------
-- workshop_hours (opening hours are public; only this workshop's owner or an
-- admin may write them)
-- --------------------------------------------------------------------------
ALTER TABLE workshop_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE workshop_hours FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS workshop_hours_select ON workshop_hours;
CREATE POLICY workshop_hours_select ON workshop_hours FOR SELECT USING (true);

DROP POLICY IF EXISTS workshop_hours_insert ON workshop_hours;
CREATE POLICY workshop_hours_insert ON workshop_hours FOR INSERT
    WITH CHECK (
        workshop_id IN (
            SELECT w.w_id FROM workshop w JOIN owner o ON o.o_id = w.o_id
            WHERE o.u_id = app_luid()
        )
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS workshop_hours_update ON workshop_hours;
CREATE POLICY workshop_hours_update ON workshop_hours FOR UPDATE
    USING (
        workshop_id IN (
            SELECT w.w_id FROM workshop w JOIN owner o ON o.o_id = w.o_id
            WHERE o.u_id = app_luid()
        )
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS workshop_hours_delete ON workshop_hours;
CREATE POLICY workshop_hours_delete ON workshop_hours FOR DELETE
    USING (
        workshop_id IN (
            SELECT w.w_id FROM workshop w JOIN owner o ON o.o_id = w.o_id
            WHERE o.u_id = app_luid()
        )
        OR app_ladmin() <> ''
    );

-- --------------------------------------------------------------------------
-- mechanic (profiles are public; sensitive fields only by the mechanic, their
-- workshop's owner, or an admin)
-- --------------------------------------------------------------------------
ALTER TABLE mechanic ENABLE ROW LEVEL SECURITY;
ALTER TABLE mechanic FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mechanic_select ON mechanic;
CREATE POLICY mechanic_select ON mechanic FOR SELECT USING (true);

DROP POLICY IF EXISTS mechanic_insert ON mechanic;
CREATE POLICY mechanic_insert ON mechanic FOR INSERT
    WITH CHECK (app_luid() = 0 OR u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS mechanic_update ON mechanic;
CREATE POLICY mechanic_update ON mechanic FOR UPDATE
    USING (
        u_id = app_luid()
        OR w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    )
    WITH CHECK (
        -- the same parties may write the row; owners can also release a mechanic
        -- (w_id -> NULL) or move them between the workshops they own
        u_id = app_luid()
        OR w_id IS NULL
        OR w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS mechanic_delete ON mechanic;
CREATE POLICY mechanic_delete ON mechanic FOR DELETE
    USING (app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- service (public to browse; workshop owner or admin manages)
-- A service's vehicle type comes from its service_catalog row. service_catalog is a
-- shared reference list that has never had RLS; the new vehicle_type column does not
-- change that. The rule "an owner may only offer catalog entries of the types the
-- workshop serves" is enforced in the owner routes (app/vehicles.py).
-- --------------------------------------------------------------------------
ALTER TABLE service ENABLE ROW LEVEL SECURITY;
ALTER TABLE service FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_select ON service;
CREATE POLICY service_select ON service FOR SELECT USING (true);

DROP POLICY IF EXISTS service_insert ON service;
CREATE POLICY service_insert ON service FOR INSERT
    WITH CHECK (
        w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                 (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS service_update ON service;
CREATE POLICY service_update ON service FOR UPDATE
    USING (
        w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                 (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS service_delete ON service;
CREATE POLICY service_delete ON service FOR DELETE
    USING (
        w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                 (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

-- --------------------------------------------------------------------------
-- join_request (mechanic sees their own; the workshop's owner sees requests
-- to their workshop; admins see all)
-- --------------------------------------------------------------------------
ALTER TABLE join_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE join_request FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS join_request_select ON join_request;
CREATE POLICY join_request_select ON join_request FOR SELECT
    USING (
        m_id IN (SELECT m_id FROM mechanic WHERE u_id = app_luid())
        OR w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS join_request_insert ON join_request;
CREATE POLICY join_request_insert ON join_request FOR INSERT
    WITH CHECK (
        m_id IN (SELECT m_id FROM mechanic WHERE u_id = app_luid())
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS join_request_update ON join_request;
CREATE POLICY join_request_update ON join_request FOR UPDATE
    USING (
        w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                 (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS join_request_delete ON join_request;
CREATE POLICY join_request_delete ON join_request FOR DELETE
    USING (
        m_id IN (SELECT m_id FROM mechanic WHERE u_id = app_luid())
        OR app_ladmin() <> ''
    );

-- --------------------------------------------------------------------------
-- booking (customer sees their own; workshop owner sees their workshop's;
-- the assigned mechanic sees their jobs; admins see all)
-- vehicle_type / vehicle_description are ordinary columns on this table, covered by the
-- same policies: only the customer, the workshop's owner, the assigned mechanic and
-- admins can read what vehicle was brought in.
-- The lifecycle columns (created_at, reminder_sent_at, cancelled_by, cancelled_at,
-- cancel_request_*, payment_status) and payment.provider are ordinary columns too, so the
-- policies below cover them. Row policies cannot limit columns, so WHO may make each status
-- change (the customer cancels / requests, the owner accepts / assigns / decides, the assigned
-- mechanic starts / completes) is enforced in the routes, each as one conditional UPDATE
-- (see tests/test_booking_lifecycle.py). The scheduled sweep that cancels unanswered bookings
-- runs on its own connection with an admin context (app/booking_events.py:run_sweep).
-- Notices about status changes are rows in `messages`, which has never had RLS; the lookup
-- that finds the other people on a booking is booking_parties() (scripts/booking_party_lookup.sql).
-- --------------------------------------------------------------------------
ALTER TABLE booking ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS booking_select ON booking;
CREATE POLICY booking_select ON booking FOR SELECT
    USING (
        c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid())
        OR assigned_m_id IN (SELECT m_id FROM mechanic WHERE u_id = app_luid())
        OR w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS booking_insert ON booking;
CREATE POLICY booking_insert ON booking FOR INSERT
    WITH CHECK (
        c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid())
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS booking_update ON booking;
CREATE POLICY booking_update ON booking FOR UPDATE
    USING (
        c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid())
        OR assigned_m_id IN (SELECT m_id FROM mechanic WHERE u_id = app_luid())
        OR w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS booking_delete ON booking;
CREATE POLICY booking_delete ON booking FOR DELETE
    USING (app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- payment (the paying customer, the workshop owner, the assigned mechanic, admins)
-- --------------------------------------------------------------------------
ALTER TABLE payment ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS payment_select ON payment;
CREATE POLICY payment_select ON payment FOR SELECT
    USING (
        b_id IN (SELECT b_id FROM booking WHERE
                 c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid())
                 OR assigned_m_id IN (SELECT m_id FROM mechanic WHERE u_id = app_luid())
                 OR w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                             (SELECT o_id FROM owner WHERE u_id = app_luid())))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS payment_insert ON payment;
CREATE POLICY payment_insert ON payment FOR INSERT
    WITH CHECK (
        b_id IN (SELECT b_id FROM booking WHERE
                 c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid()))
        OR app_ladmin() <> ''
    );

DROP POLICY IF EXISTS payment_update ON payment;
CREATE POLICY payment_update ON payment FOR UPDATE
    USING (app_ladmin() <> '');

DROP POLICY IF EXISTS payment_delete ON payment;
CREATE POLICY payment_delete ON payment FOR DELETE
    USING (app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- feedback (public contact form may insert; only admins may read/change)
-- --------------------------------------------------------------------------
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback FORCE ROW LEVEL SECURITY;

-- --------------------------------------------------------------------------
-- bookmark (each customer manages their own saved workshops; admins see all)
-- --------------------------------------------------------------------------
ALTER TABLE bookmark ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookmark FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bookmark_select ON bookmark;
CREATE POLICY bookmark_select ON bookmark FOR SELECT
    USING (c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid()) OR app_ladmin() <> '');

DROP POLICY IF EXISTS bookmark_insert ON bookmark;
CREATE POLICY bookmark_insert ON bookmark FOR INSERT
    WITH CHECK (c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid()) OR app_ladmin() <> '');

DROP POLICY IF EXISTS bookmark_delete ON bookmark;
CREATE POLICY bookmark_delete ON bookmark FOR DELETE
    USING (c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid()) OR app_ladmin() <> '');

DROP POLICY IF EXISTS feedback_insert ON feedback;
CREATE POLICY feedback_insert ON feedback FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS feedback_select ON feedback;
CREATE POLICY feedback_select ON feedback FOR SELECT
    USING (app_ladmin() <> '');

DROP POLICY IF EXISTS feedback_update ON feedback;
CREATE POLICY feedback_update ON feedback FOR UPDATE
    USING (app_ladmin() <> '');

DROP POLICY IF EXISTS feedback_delete ON feedback;
CREATE POLICY feedback_delete ON feedback FOR DELETE
    USING (app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- inbox_dismissal (each user manages their own dismissals; used to hide
-- resolved join/leave cards from a viewer's inbox without touching the record)
-- --------------------------------------------------------------------------
ALTER TABLE inbox_dismissal ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_dismissal FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS inbox_dismissal_select ON inbox_dismissal;
CREATE POLICY inbox_dismissal_select ON inbox_dismissal FOR SELECT
    USING (u_id = app_luid());

DROP POLICY IF EXISTS inbox_dismissal_insert ON inbox_dismissal;
CREATE POLICY inbox_dismissal_insert ON inbox_dismissal FOR INSERT
    WITH CHECK (u_id = app_luid());

DROP POLICY IF EXISTS inbox_dismissal_delete ON inbox_dismissal;
CREATE POLICY inbox_dismissal_delete ON inbox_dismissal FOR DELETE
    USING (u_id = app_luid());

-- --------------------------------------------------------------------------
-- inbox_read_state (each user manages their own read markers for activity cards)
-- --------------------------------------------------------------------------
ALTER TABLE inbox_read_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_read_state FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS inbox_read_state_select ON inbox_read_state;
CREATE POLICY inbox_read_state_select ON inbox_read_state FOR SELECT
    USING (u_id = app_luid());

DROP POLICY IF EXISTS inbox_read_state_insert ON inbox_read_state;
CREATE POLICY inbox_read_state_insert ON inbox_read_state FOR INSERT
    WITH CHECK (u_id = app_luid());

DROP POLICY IF EXISTS inbox_read_state_delete ON inbox_read_state;
CREATE POLICY inbox_read_state_delete ON inbox_read_state FOR DELETE
    USING (u_id = app_luid());

-- --------------------------------------------------------------------------
-- inbox_message_state (each user manages their own read/deleted markers for
-- notices; broadcasts are shared rows so this state must be per viewer)
-- --------------------------------------------------------------------------
ALTER TABLE inbox_message_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_message_state FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS inbox_message_state_select ON inbox_message_state;
CREATE POLICY inbox_message_state_select ON inbox_message_state FOR SELECT
    USING (u_id = app_luid());

DROP POLICY IF EXISTS inbox_message_state_insert ON inbox_message_state;
CREATE POLICY inbox_message_state_insert ON inbox_message_state FOR INSERT
    WITH CHECK (u_id = app_luid());

DROP POLICY IF EXISTS inbox_message_state_update ON inbox_message_state;
CREATE POLICY inbox_message_state_update ON inbox_message_state FOR UPDATE
    USING (u_id = app_luid())
    WITH CHECK (u_id = app_luid());

DROP POLICY IF EXISTS inbox_message_state_delete ON inbox_message_state;
CREATE POLICY inbox_message_state_delete ON inbox_message_state FOR DELETE
    USING (u_id = app_luid());

-- --------------------------------------------------------------------------
-- report_resolution (admins record and read outcomes; a reporter may read the
-- outcome of the reports they filed)
-- --------------------------------------------------------------------------
ALTER TABLE report_resolution ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_resolution FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS report_resolution_select ON report_resolution;
CREATE POLICY report_resolution_select ON report_resolution FOR SELECT
    USING (app_ladmin() <> ''
           OR msg_id IN (SELECT msg_id FROM messages WHERE sender_u_id = app_luid()));

DROP POLICY IF EXISTS report_resolution_insert ON report_resolution;
CREATE POLICY report_resolution_insert ON report_resolution FOR INSERT
    WITH CHECK (app_ladmin() <> '');

DROP POLICY IF EXISTS report_resolution_update ON report_resolution;
CREATE POLICY report_resolution_update ON report_resolution FOR UPDATE
    USING (app_ladmin() <> '')
    WITH CHECK (app_ladmin() <> '');

DROP POLICY IF EXISTS report_resolution_delete ON report_resolution;
CREATE POLICY report_resolution_delete ON report_resolution FOR DELETE
    USING (app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- review (Phase 4: public reviews, one per completed booking, one owner reply)
-- --------------------------------------------------------------------------
ALTER TABLE review ENABLE ROW LEVEL SECURITY;
ALTER TABLE review FORCE ROW LEVEL SECURITY;

-- Reviews are public: anyone may read them (workshop pages, search ratings).
DROP POLICY IF EXISTS review_select ON review;
CREATE POLICY review_select ON review FOR SELECT
    USING (true);

-- Only the customer who made a COMPLETED booking may review it, as themselves, for that booking's
-- workshop. (One per booking is the UNIQUE constraint on b_id.)
DROP POLICY IF EXISTS review_insert ON review;
CREATE POLICY review_insert ON review FOR INSERT
    WITH CHECK (
        c_id IN (SELECT c_id FROM customer WHERE u_id = app_luid())
        AND EXISTS (SELECT 1 FROM booking b
                    WHERE b.b_id = review.b_id AND b.c_id = review.c_id
                      AND b.w_id = review.w_id AND b.status = 'completed')
    );

-- Only the workshop's owner (or an admin) may update a review: that is how the single public reply
-- is added. Row policies cannot limit columns, so the route only ever sets owner_reply /
-- owner_replied_at, and only while owner_reply IS NULL.
DROP POLICY IF EXISTS review_update ON review;
CREATE POLICY review_update ON review FOR UPDATE
    USING (w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
           OR app_ladmin() <> '')
    WITH CHECK (w_id IN (SELECT w_id FROM workshop WHERE o_id IN
                    (SELECT o_id FROM owner WHERE u_id = app_luid()))
           OR app_ladmin() <> '');

DROP POLICY IF EXISTS review_delete ON review;
CREATE POLICY review_delete ON review FOR DELETE
    USING (app_ladmin() <> '');

-- --------------------------------------------------------------------------
-- report_review and appeal (Phase 6: report verification, response window, appeals)
-- --------------------------------------------------------------------------
ALTER TABLE report_review ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_review FORCE ROW LEVEL SECURITY;

-- Admins see and manage every review (the routes apply the sub-admin domain rules); the reported
-- person sees only their own so they can answer inside the window. The reporter never can.
DROP POLICY IF EXISTS report_review_select ON report_review;
CREATE POLICY report_review_select ON report_review FOR SELECT
    USING (app_ladmin() <> '' OR reported_u_id = app_luid());

DROP POLICY IF EXISTS report_review_insert ON report_review;
CREATE POLICY report_review_insert ON report_review FOR INSERT
    WITH CHECK (app_ladmin() <> '');

-- Row policies cannot limit columns, so the respond route only ever sets response_text and
-- responded_at, and only while the window is open and no response exists yet.
DROP POLICY IF EXISTS report_review_update ON report_review;
CREATE POLICY report_review_update ON report_review FOR UPDATE
    USING (app_ladmin() <> '' OR reported_u_id = app_luid())
    WITH CHECK (app_ladmin() <> '' OR reported_u_id = app_luid());

DROP POLICY IF EXISTS report_review_delete ON report_review;
CREATE POLICY report_review_delete ON report_review FOR DELETE
    USING (app_ladmin() <> '');

ALTER TABLE appeal ENABLE ROW LEVEL SECURITY;
ALTER TABLE appeal FORCE ROW LEVEL SECURITY;

-- The appellant reads their own appeals; an admin reads only the appeals assigned to their type
-- (the main admin cannot read or answer one assigned to a sub-admin, and vice versa).
DROP POLICY IF EXISTS appeal_select ON appeal;
CREATE POLICY appeal_select ON appeal FOR SELECT
    USING (u_id = app_luid() OR reviewer_type = app_ladmin());

-- A person files an appeal only for themselves, and only against a real decision: a suspended
-- account, or a rejected workshop they own. (A suspended person is not logged in: the suspension
-- screen sets their identity for this one request, as the Google sign-in link does.)
DROP POLICY IF EXISTS appeal_insert ON appeal;
CREATE POLICY appeal_insert ON appeal FOR INSERT
    WITH CHECK (
        u_id = app_luid()
        AND (
            (kind = 'suspension'
             AND EXISTS (SELECT 1 FROM users x WHERE x.u_id = appeal.u_id AND x.is_suspended))
            OR (kind = 'listing'
                AND EXISTS (SELECT 1 FROM workshop w JOIN owner o ON o.o_id = w.o_id
                            WHERE w.w_id = appeal.w_id AND o.u_id = appeal.u_id AND w.status = 'rejected'))
        )
    );

DROP POLICY IF EXISTS appeal_update ON appeal;
CREATE POLICY appeal_update ON appeal FOR UPDATE
    USING (reviewer_type = app_ladmin())
    WITH CHECK (reviewer_type = app_ladmin());

DROP POLICY IF EXISTS appeal_delete ON appeal;
CREATE POLICY appeal_delete ON appeal FOR DELETE
    USING (app_ladmin() = 'main');

-- --------------------------------------------------------------------------
-- user_consent (Phase 8: which version of the terms / privacy / owner agreement each person accepted)
-- --------------------------------------------------------------------------
ALTER TABLE user_consent ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_consent FORCE ROW LEVEL SECURITY;

-- A person reads their own acceptances; admins read all. Sign-up records consent right after creating
-- the account, acting as that new person (the same way the Google link step does), so inserting is
-- limited to yourself. There is no update or delete policy: the record is append-only (it only goes
-- away when the account itself is deleted).
DROP POLICY IF EXISTS user_consent_select ON user_consent;
CREATE POLICY user_consent_select ON user_consent FOR SELECT
    USING (u_id = app_luid() OR app_ladmin() <> '');

DROP POLICY IF EXISTS user_consent_insert ON user_consent;
CREATE POLICY user_consent_insert ON user_consent FOR INSERT
    WITH CHECK (u_id = app_luid());
