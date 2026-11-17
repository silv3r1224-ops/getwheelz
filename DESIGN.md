# Mechconnect — System Architecture & Design Specification

Mechconnect is a secure, high-performance web platform connecting vehicle owners (customers), independent workshop owners, and professional mechanics with automated booking management, real-time status tracking, role-based access control (RBAC), and rigorous administrative oversight.

---

## 1. System Architecture

```
                       [ Clients (Browser / Mobile) ]
                                     │
                             (HTTPS / AJAX / SSE)
                                     ▼
                        [ Flask Web Application ]
                        ├── Blueprints (Auth, Dashboard, Workshops, Bookings, Customers, Mechanics)
                        ├── Security Interceptors (@admin_access_required, CSRF, RLS)
                        └── Rendering Engine (Jinja2 Templates & Static Assets)
                                     │
                     (Parameterized SQL & Transactions)
                                     ▼
                     [ PostgreSQL Database & RLS ]
                     ├── Tables with FORCE ROW LEVEL SECURITY
                     └── SECURITY DEFINER Functions for Owner Mapping
```

---

## 2. Tech Stack

- **Backend Framework:** Python / Flask (Blueprints architecture)
- **Database:** PostgreSQL with Row-Level Security (RLS) enabled on all core tables
- **Frontend:** HTML5, CSS3 (Modern custom design system with CSS custom properties), JavaScript (Modular DOM controllers, AJAX fetch handling, live filtering, and bulk management)
- **Security:** Werkzeug password hashing, CSRF token validation (`X-CSRFToken`), role-based access control decorators, and secure session management

---

## 3. Core Modules & Subsystems

### A. Authentication & Session Management (`app/routes/auth.py`)
- Supports sign-up and login for Customers, Workshop Owners, and Mechanics.
- Enforces account suspension checks (`is_suspended`) during authentication to block suspended users.
- Secures administrative sessions with explicit role verification and active session tracking.

### B. Admin Control Surface & Bulk Management (`app/routes/dashboard/admin.py`)
- **Bookings Oversight Ledger:** Real-time monitoring of all platform bookings across workshops.
- **Advanced Multi-Field Search:** Server-side search supporting query matching across names, emails, and phone numbers with role and status filtering.
- **Bulk & Single Account Termination:** Controlled transactional cascading deletes across dependent entities (payments, bookings, services, workshops, and user profiles) with pre-flight impact checks and verification.
- **User Suspension & Restoration:** Instant toggle of account suspension state preventing unauthorized login.

### C. Row-Level Security (RLS) & Data Access (`app/rls_policies.sql`, `app/db.py`)
- Enforces strict database-level security policies (`FORCE ROW LEVEL SECURITY`).
- Uses PostgreSQL-owned `SECURITY DEFINER` functions to safely read hidden owner mappings without weakening security policies.

---

## 4. Security & Compliance
- **CSRF Protection:** All state-changing requests require valid anti-forgery tokens.
- **SQL Injection Prevention:** Parameterized queries and prepared statements used exclusively across all database operations.
- **Access Control:** Decorators (`@admin_access_required`, main-admin restrictions) strictly isolate administrative functions.
