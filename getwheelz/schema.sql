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
    photo_path VARCHAR(255),
    capacity   INTEGER NOT NULL DEFAULT 5 CHECK (capacity BETWEEN 1 AND 100),
    is_open    BOOLEAN NOT NULL DEFAULT TRUE  -- owner's Open / Closed switch, shown to customers
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
CREATE TABLE service_catalog (
    sc_id  SERIAL PRIMARY KEY,
    s_name VARCHAR(100) UNIQUE NOT NULL
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
    status         VARCHAR(20) DEFAULT 'pending'
                   CHECK (status IN ('pending', 'confirmed', 'completed', 'cancelled')),
    assigned_m_id  INTEGER REFERENCES mechanic(m_id) ON DELETE SET NULL  -- mechanic the owner assigned the job to
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

-- ---------------------------------------------------------------
-- Indexes for common lookups
-- ---------------------------------------------------------------
CREATE INDEX idx_mechanic_workshop ON mechanic (w_id);
CREATE INDEX idx_service_workshop  ON service (w_id);
CREATE INDEX idx_booking_customer  ON booking (c_id);
CREATE INDEX idx_booking_workshop  ON booking (w_id);
CREATE INDEX idx_booking_mechanic  ON booking (assigned_m_id);
CREATE INDEX idx_join_request_workshop ON join_request (w_id);

-- ---------------------------------------------------------------
-- Seed data
-- ---------------------------------------------------------------
INSERT INTO service_catalog (s_name) VALUES
    ('Engine Repair'), ('Electrical'), ('Tires'), ('AC Service'), ('General Servicing')
ON CONFLICT (s_name) DO NOTHING;

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