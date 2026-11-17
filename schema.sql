-- Getwheelz / MechConnect database schema (PostgreSQL)
-- For a FRESH database only. Do not run this on a database that already has data.

-- ---------------------------------------------------------------
-- Users and roles
-- ---------------------------------------------------------------
CREATE TABLE users (
    u_id            SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    email           VARCHAR(100) UNIQUE NOT NULL,
    password        VARCHAR(255) NOT NULL,
    role            VARCHAR(20)  NOT NULL CHECK (role IN ('customer', 'admin', 'owner', 'mechanic')),
    profile_picture VARCHAR(255),
    google_id       VARCHAR(64) UNIQUE,  -- Google account id, set when the person signs in with Google
    password_set    BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE for accounts created with Google that never chose a password
    tour_seen       BOOLEAN NOT NULL DEFAULT FALSE, -- FALSE until the person finishes (or skips) NEO's first-login tour
    is_suspended    BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE blocks sign-in while the account stays on file (admin suspension)
    suspended_by    INTEGER,   -- the admin who suspended the account (an appeal goes to someone else if that was the main admin)
    suspended_at    TIMESTAMP, -- when; one appeal is allowed per suspension
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE admin (
    a_id       SERIAL PRIMARY KEY,
    u_id       INTEGER NOT NULL UNIQUE REFERENCES users(u_id) ON DELETE CASCADE,
    admin_type VARCHAR(30) NOT NULL DEFAULT 'main'
               CHECK (admin_type IN ('main', 'customer_manager', 'owner_workshop_manager', 'mechanic_manager')),
    is_active  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE customer (
    c_id     SERIAL PRIMARY KEY,
    u_id     INTEGER NOT NULL UNIQUE REFERENCES users(u_id) ON DELETE CASCADE,
    phone_no VARCHAR(20),
    a_id     INTEGER REFERENCES admin(a_id) ON DELETE SET NULL
);

CREATE TABLE owner (
    o_id SERIAL PRIMARY KEY,
    u_id INTEGER NOT NULL UNIQUE REFERENCES users(u_id) ON DELETE CASCADE,
    a_id INTEGER REFERENCES admin(a_id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------
-- Workshops and mechanics
-- ---------------------------------------------------------------
CREATE TABLE workshop (
    w_id       SERIAL PRIMARY KEY,
    o_id       INTEGER NOT NULL UNIQUE REFERENCES owner(o_id) ON DELETE CASCADE,  -- one workshop per owner
    name       VARCHAR(150) NOT NULL,
    address    TEXT,
    latitude   DOUBLE PRECISION,
    longitude  DOUBLE PRECISION,
    contact_no VARCHAR(20),
    whatsapp_no VARCHAR(20),  -- optional; the WhatsApp button uses this, the Call button uses contact_no
    photo_path VARCHAR(255),
    capacity   INTEGER NOT NULL DEFAULT 5 CHECK (capacity BETWEEN 1 AND 100),
    is_open    BOOLEAN NOT NULL DEFAULT TRUE,  -- owner's Open / Closed switch, shown to customers
    status     VARCHAR(20) NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'approved', 'rejected')),  -- admin moderation
    rejection_reason TEXT,  -- set when an admin rejects a new workshop (required when rejecting)
    -- Who made the latest approve/reject decision, and when. Appeals (spec section 4) need this:
    -- if the main admin decided, someone else reviews the appeal. NULL until a decision is made.
    decided_by INTEGER REFERENCES users(u_id) ON DELETE SET NULL,
    decided_at TIMESTAMP,
    -- Vehicle types the workshop serves (spec section 5). Existing workshops default to cars.
    serves_cars         BOOLEAN NOT NULL DEFAULT TRUE,
    serves_two_wheelers BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT workshop_vehicle_types_check CHECK (serves_cars OR serves_two_wheelers)
);

-- Weekly opening hours, one row per weekday (dow: 0=Mon ... 6=Sun). A day with
-- NULL times (or no row at all) means closed that day; an empty table means the
-- workshop follows the Open/Closed switch only. Open/close pairs may cross
-- midnight (e.g. 20:00-02:00). Computed in app/workshop_hours.py.
CREATE TABLE workshop_hours (
    workshop_id INTEGER NOT NULL REFERENCES workshop(w_id) ON DELETE CASCADE,
    dow         INTEGER NOT NULL CHECK (dow BETWEEN 0 AND 6),
    open_time   TIME,
    close_time  TIME,
    PRIMARY KEY (workshop_id, dow),
    CHECK ((open_time IS NULL) = (close_time IS NULL))
);

CREATE TABLE mechanic (
    m_id               SERIAL PRIMARY KEY,
    u_id               INTEGER NOT NULL UNIQUE REFERENCES users(u_id) ON DELETE CASCADE,
    w_id               INTEGER REFERENCES workshop(w_id) ON DELETE SET NULL,
    experience_yrs     INTEGER,
    active_stat        VARCHAR(20) DEFAULT 'active',  -- 'active' (active for work now) or 'inactive' (absent)
    leave_requested_at TIMESTAMP,
    leave_reason       TEXT,
    leave_rejected_at  TIMESTAMP
);

CREATE TABLE join_request (
    jr_id      SERIAL PRIMARY KEY,
    m_id       INTEGER NOT NULL REFERENCES mechanic(m_id) ON DELETE CASCADE,
    w_id       INTEGER NOT NULL REFERENCES workshop(w_id) ON DELETE CASCADE,
    status     VARCHAR(20) NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Needed by: INSERT ... ON CONFLICT (m_id, w_id) WHERE status = 'pending' DO NOTHING
CREATE UNIQUE INDEX join_request_one_pending
    ON join_request (m_id, w_id) WHERE status = 'pending';

-- ---------------------------------------------------------------
-- Services
-- ---------------------------------------------------------------
-- The admin catalog is split into a car catalog and a two-wheeler catalog. A name is unique
-- within one catalog, so "Tyres" can exist in both. Existing entries are car services.
CREATE TABLE service_catalog (
    sc_id        SERIAL PRIMARY KEY,
    s_name       VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(20)  NOT NULL DEFAULT 'car'
                 CHECK (vehicle_type IN ('car', 'two_wheeler')),
    CONSTRAINT service_catalog_name_type_key UNIQUE (s_name, vehicle_type)
);

CREATE TABLE service (
    s_id        SERIAL PRIMARY KEY,
    w_id        INTEGER NOT NULL REFERENCES workshop(w_id) ON DELETE CASCADE,
    sc_id       INTEGER NOT NULL REFERENCES service_catalog(sc_id),
    price_range VARCHAR(50),
    duration    VARCHAR(50),
    UNIQUE (w_id, sc_id)
);

-- ---------------------------------------------------------------
-- Bookings and feedback
-- ---------------------------------------------------------------
CREATE TABLE booking (
    b_id           SERIAL PRIMARY KEY,
    c_id           INTEGER NOT NULL REFERENCES customer(c_id) ON DELETE CASCADE,
    w_id           INTEGER NOT NULL REFERENCES workshop(w_id) ON DELETE CASCADE,
    s_id           INTEGER NOT NULL REFERENCES service(s_id),  -- no CASCADE: a service with bookings cannot be removed
    requested_time TIMESTAMP NOT NULL,
    -- 'confirmed' is what people see as "Accepted". Lifecycle rules live in app/booking_rules.py.
    status         VARCHAR(20) DEFAULT 'pending'
                   CHECK (status IN ('pending', 'confirmed', 'in_progress', 'completed', 'cancelled')),
    assigned_m_id  INTEGER REFERENCES mechanic(m_id) ON DELETE SET NULL,  -- mechanic the owner assigned the job to
    amount         NUMERIC(12, 2),  -- the bill the owner sets; NULL until then
    -- No saved vehicle profiles: each booking says what is being brought in (spec section 5).
    vehicle_type        VARCHAR(20) NOT NULL DEFAULT 'car'
                        CHECK (vehicle_type IN ('car', 'two_wheeler')),
    vehicle_description VARCHAR(150),  -- free text, e.g. 'Honda City 2019, plate optional'; NULL on older bookings
    -- Lifecycle (spec section 6). created_at starts the 48-hour window the owner has to answer.
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reminder_sent_at TIMESTAMP,  -- set once the owner was reminded about an unanswered request
    cancelled_by     VARCHAR(10) CHECK (cancelled_by IS NULL OR cancelled_by IN ('customer', 'owner', 'system')),
    cancelled_at     TIMESTAMP,
    -- The customer's request to cancel an accepted booking; NULL = never asked.
    cancel_request_status VARCHAR(10)
                          CHECK (cancel_request_status IS NULL
                                 OR cancel_request_status IN ('requested', 'approved', 'declined')),
    cancel_requested_at   TIMESTAMP,
    cancel_request_reason VARCHAR(300),
    payment_status   VARCHAR(10) NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'paid'))
);

-- Reviews (spec section 7). One review per completed booking; the owner may add ONE public reply.
-- Who may review is enforced by the route AND the INSERT policy in app/rls_policies.sql.
-- reviewer_name is a snapshot ('Asha K.') so the public page never needs to read the customer table.
CREATE TABLE review (
    r_id             SERIAL PRIMARY KEY,
    b_id             INTEGER NOT NULL UNIQUE REFERENCES booking(b_id) ON DELETE CASCADE,
    w_id             INTEGER NOT NULL REFERENCES workshop(w_id) ON DELETE CASCADE,
    c_id             INTEGER NOT NULL REFERENCES customer(c_id) ON DELETE CASCADE,
    rating           SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment          TEXT NOT NULL CHECK (char_length(btrim(comment)) BETWEEN 1 AND 1000),
    reviewer_name    VARCHAR(60) NOT NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    owner_reply      TEXT CHECK (owner_reply IS NULL OR char_length(btrim(owner_reply)) BETWEEN 1 AND 1000),
    owner_replied_at TIMESTAMP,
    CHECK ((owner_reply IS NULL) = (owner_replied_at IS NULL))
);
CREATE INDEX idx_review_workshop ON review (w_id, created_at DESC);

-- Demo payments (see app/payments.py). One payment per booking.
CREATE TABLE payment (
    p_id      SERIAL PRIMARY KEY,
    b_id      INTEGER NOT NULL UNIQUE REFERENCES booking(b_id) ON DELETE CASCADE,
    amount    NUMERIC(12, 2) NOT NULL,
    method    VARCHAR(20) NOT NULL,
    detail    VARCHAR(100),   -- masked, e.g. 'Visa •••• 4242'
    reference VARCHAR(40),
    paid_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    provider  VARCHAR(30) NOT NULL DEFAULT 'demo'  -- which gateway took the payment (app/payments.py)
);

CREATE TABLE feedback (
    f_id         SERIAL PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    email        VARCHAR(100) NOT NULL,
    subject      VARCHAR(150),
    message      TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read      BOOLEAN DEFAULT FALSE
);

CREATE TABLE messages (
    msg_id         SERIAL PRIMARY KEY,
    sender_u_id    INTEGER REFERENCES users(u_id) ON DELETE SET NULL,
    recipient_u_id INTEGER REFERENCES users(u_id) ON DELETE CASCADE,
    target_role    VARCHAR(20),
    subject        VARCHAR(150) NOT NULL,
    body           TEXT NOT NULL,
    sent_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read        BOOLEAN DEFAULT FALSE,
    -- Notice category (app/inbox_ui.py). Admins choose general / important / maintenance; mail the
    -- system sends itself (booking updates, approvals, replies) is 'update'. Important notices also
    -- show once as a banner after login.
    category       VARCHAR(20) NOT NULL DEFAULT 'general'
                   CHECK (category IN ('general', 'important', 'maintenance', 'update')),
    -- Optional link from a system notice to something the reader can act on (Phase 6):
    --   ref_type 'report_response' + ref_id = the report's msg_id -> a response form for the reported person
    --   ref_type 'listing_appeal'  + ref_id = the workshop's w_id -> an Appeal button on a rejection notice
    ref_type       VARCHAR(20) CHECK (ref_type IS NULL OR ref_type IN ('report_response', 'listing_appeal')),
    ref_id         INTEGER
);

-- Per-viewer dismissals for inbox activity cards (join/leave requests): hiding
-- a card only affects THIS viewer's inbox; the underlying business record is
-- never touched.
CREATE TABLE inbox_dismissal (
    u_id        INTEGER NOT NULL REFERENCES users(u_id) ON DELETE CASCADE,
    item_type   VARCHAR(20) NOT NULL
                CHECK (item_type IN ('join_request', 'leave_request', 'booking')),
    item_id     INTEGER NOT NULL,
    dismissed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (u_id, item_type, item_id)
);

-- Per-viewer read markers for the same activity cards: a viewer marks a card
-- as read without affecting what other viewers see or the business record.
CREATE TABLE inbox_read_state (
    u_id        INTEGER NOT NULL REFERENCES users(u_id) ON DELETE CASCADE,
    item_type   VARCHAR(20) NOT NULL
                CHECK (item_type IN ('join_request', 'leave_request', 'booking')),
    item_id     INTEGER NOT NULL,
    read_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (u_id, item_type, item_id)
);

-- Per-viewer state for notices in the `messages` table. Broadcasts (target_role
-- 'all' / a role name) are ONE shared row for every recipient, so read and
-- delete state cannot live on the message itself: each viewer gets their own
-- row here instead. read_at / deleted_at are NULL until the viewer acts.
CREATE TABLE inbox_message_state (
    u_id       INTEGER NOT NULL REFERENCES users(u_id) ON DELETE CASCADE,
    msg_id     INTEGER NOT NULL REFERENCES messages(msg_id) ON DELETE CASCADE,
    read_at    TIMESTAMP,
    deleted_at TIMESTAMP,
    banner_seen_at TIMESTAMP,  -- the login banner for an important notice is shown once per viewer
    PRIMARY KEY (u_id, msg_id)
);

-- Outcome of an account / workshop report (a row in `messages`). No row = still
-- open. 'verified' means a violation was confirmed (outcome: a warning, or the
-- account was suspended); 'dismissed' means no violation was found.
CREATE TABLE report_resolution (
    msg_id     INTEGER PRIMARY KEY REFERENCES messages(msg_id) ON DELETE CASCADE,
    status     VARCHAR(20) NOT NULL CHECK (status IN ('verified', 'dismissed')),
    outcome    VARCHAR(20) NOT NULL CHECK (outcome IN ('warn', 'suspend', 'dismiss')),
    note       VARCHAR(500),
    handled_by INTEGER REFERENCES users(u_id) ON DELETE SET NULL,
    handled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Verification stage of an account / workshop report (spec section 9). One row per report, created
-- the first time an admin acts on it. The FINAL outcome still lives in report_resolution (a report is
-- resolved once); this table holds what happens BEFORE that: the response request (or the recorded
-- decision to skip it) and the Verified marker that unlocks Warn and Suspend.
CREATE TABLE report_review (
    msg_id                INTEGER PRIMARY KEY REFERENCES messages(msg_id) ON DELETE CASCADE,
    reported_u_id         INTEGER REFERENCES users(u_id) ON DELETE SET NULL,  -- who may respond (never shown to the reporter)
    response_mode         VARCHAR(10) CHECK (response_mode IN ('requested', 'skipped')),
    response_decided_by   INTEGER REFERENCES users(u_id) ON DELETE SET NULL,
    response_requested_at TIMESTAMP,   -- start of the 72-hour window (app/report_rules.py)
    skip_reason           VARCHAR(300),  -- required when the request was skipped
    response_text         TEXT CHECK (response_text IS NULL OR char_length(response_text) <= 2000),
    responded_at          TIMESTAMP,
    verified_at           TIMESTAMP,
    verified_by           INTEGER REFERENCES users(u_id) ON DELETE SET NULL,
    CHECK ((response_mode = 'requested') = (response_requested_at IS NOT NULL)),
    CHECK ((response_mode = 'skipped') = (skip_reason IS NOT NULL)),
    CHECK ((response_text IS NULL) = (responded_at IS NULL))
);

-- Appeals (spec sections 4 and 9): a suspended user or a rejected owner asks for the decision to be
-- reconsidered; an admin must answer by upholding or overturning it, with a note. Who may answer is
-- reviewer_type (app/appeals.py): the main admin, or the sub-admin of the area when the main admin
-- made the original decision.
CREATE TABLE appeal (
    ap_id                 SERIAL PRIMARY KEY,
    kind                  VARCHAR(12) NOT NULL CHECK (kind IN ('suspension', 'listing')),
    u_id                  INTEGER NOT NULL REFERENCES users(u_id) ON DELETE CASCADE,  -- the person appealing
    w_id                  INTEGER REFERENCES workshop(w_id) ON DELETE CASCADE,        -- the listing (kind = 'listing')
    message               VARCHAR(1000) NOT NULL,
    decided_by_admin      INTEGER REFERENCES users(u_id) ON DELETE SET NULL,          -- who made the original decision
    reviewer_type         VARCHAR(30) NOT NULL
                          CHECK (reviewer_type IN ('main', 'customer_manager', 'owner_workshop_manager', 'mechanic_manager')),
    needs_second_reviewer BOOLEAN NOT NULL DEFAULT FALSE,  -- main admin decided and no other admin covers the area
    status                VARCHAR(12) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'upheld', 'overturned')),
    decision_note         VARCHAR(500),
    reviewed_by           INTEGER REFERENCES users(u_id) ON DELETE SET NULL,
    reviewed_at           TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (kind <> 'listing' OR w_id IS NOT NULL),
    CHECK ((status = 'open') = (reviewed_at IS NULL)),
    CHECK (status = 'open' OR decision_note IS NOT NULL)
);
-- at most one open appeal per person and kind
CREATE UNIQUE INDEX idx_appeal_one_open ON appeal (u_id, kind) WHERE status = 'open';
CREATE INDEX idx_appeal_reviewer ON appeal (reviewer_type, status);

-- Consent record (spec section 11): which version of which document each person accepted, and when.
-- Append-only history: a new version is a NEW row, old rows stay. Documents and versions: app/legal.py.
CREATE TABLE user_consent (
    u_id        INTEGER NOT NULL REFERENCES users(u_id) ON DELETE CASCADE,
    doc         VARCHAR(20) NOT NULL CHECK (doc IN ('terms', 'privacy', 'owner_agreement')),
    version     VARCHAR(20) NOT NULL,
    accepted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (u_id, doc, version)
);


-- Customers save workshops they like; one row per (customer, workshop).
CREATE TABLE bookmark (
    c_id       INTEGER NOT NULL REFERENCES customer(c_id) ON DELETE CASCADE,
    w_id       INTEGER NOT NULL REFERENCES workshop(w_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (c_id, w_id)
);

-- ---------------------------------------------------------------
-- Indexes for common lookups
-- ---------------------------------------------------------------
CREATE INDEX idx_mechanic_workshop ON mechanic (w_id);
CREATE INDEX idx_service_workshop  ON service (w_id);
CREATE INDEX idx_service_catalog_type ON service_catalog (vehicle_type);
CREATE INDEX idx_booking_customer  ON booking (c_id);
CREATE INDEX idx_booking_workshop  ON booking (w_id);
CREATE INDEX idx_booking_mechanic  ON booking (assigned_m_id);
CREATE INDEX idx_booking_pending_created ON booking (created_at) WHERE status = 'pending';
CREATE INDEX idx_join_request_workshop ON join_request (w_id);
CREATE INDEX idx_bookmark_workshop ON bookmark (w_id);

-- ---------------------------------------------------------------
-- Seed data
-- ---------------------------------------------------------------
-- Starter entries for the car catalog. The two-wheeler catalog starts empty: the main admin adds
-- its entries from the Service Catalog page.
INSERT INTO service_catalog (s_name, vehicle_type) VALUES
    ('Engine Repair', 'car'), ('Electrical', 'car'), ('Tires', 'car'),
    ('AC Service', 'car'), ('General Servicing', 'car')
ON CONFLICT (s_name, vehicle_type) DO NOTHING;

-- ---------------------------------------------------------------
-- First (main) admin
-- Signup cannot create admins, so create the first one by hand.
-- 1) Generate a hash:  python -c "from werkzeug.security import generate_password_hash as g; print(g('CHANGE-ME'))"
-- 2) Paste it below, uncomment, and run:
--
-- WITH new_user AS (
--     INSERT INTO users (name, email, password, role)
--     VALUES ('Main Admin', 'admin@example.com', 'PASTE_HASH_HERE', 'admin')
--     RETURNING u_id
-- )
-- INSERT INTO admin (u_id, admin_type, is_active)
-- SELECT u_id, 'main', TRUE FROM new_user;
-- ---------------------------------------------------------------

-- ---------------------------------------------------------------
-- After the schema AND app/rls_policies.sql are applied, install the booking lookup that status-change
-- notices use (it relies on the app_luid()/app_ladmin() helpers that rls_policies.sql creates).
-- Run as the postgres superuser:  psql -d getwheelz -f scripts/booking_party_lookup.sql
-- (an existing database gets it from scripts/migrate_booking_lifecycle.py instead)
-- ---------------------------------------------------------------
