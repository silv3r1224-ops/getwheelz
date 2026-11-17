# Getwheelz

A platform where customers find and book **car and two-wheeler workshops**. Owners run workshops, mechanics
work at them, and admins oversee the platform. Python/Flask, PostgreSQL with Row-Level Security, a custom
industrial UI, role-based access control.

> The project folder and a few internal names still say `mechconnect`; that name is internal only. Everything
> users see says **Getwheelz**.

## Running it

1. Create a virtualenv and install the requirements.
2. Copy `app/.env.example` (or create `app/.env`) with at least `SECRET_KEY`, `DB_HOST`, `DB_PORT`, `DB_NAME`,
   `DB_USER` (the restricted role, `mechconnect_app`), `DB_PASSWORD`. Never commit `app/.env`.
3. Set up the database (below), then `flask --app app run` (or your WSGI server of choice).
4. Optional settings: `BOOKING_SWEEP_SECONDS` (how often the site runs the 48-hour check while people browse;
   default 300, `0` turns it off), `PAYMENT_GATEWAY` (default `demo`), `RATE_LIMIT_STORAGE_URI` (e.g. Redis, in
   production), the Google sign-in and SMTP settings.

## Database setup

### Database setup (new database)

Run as the PostgreSQL superuser (`postgres`):

1. `schema.sql`
2. Create the restricted `mechconnect_app` role manually (DBA step)
3. Apply `app/rls_policies.sql` (Row-Level Security for every table)
4. Create the owner lookup used by public pages, and the `booking_parties()` lookup used by status notices

Existing databases: the one-time migration scripts were removed from `scripts/` on 2026-11-15. If you have
a live database, recreate the migration scripts before deploying new schema-dependent code.

## Scheduled job

Unanswered bookings are cancelled after 48 hours (owners are reminded at 24). The standalone sweep helper
(`scripts/run_booking_sweep.py`) was removed with the rest of `scripts/`; the website still runs the same
check while people browse (at most once per `BOOKING_SWEEP_SECONDS`), so the rule holds without a cron job.

## Terms, privacy and consent

The Terms, Privacy Policy and Owner Agreement (`app/templates/legal/`) are **placeholder drafts**. They reflect the
rules in the spec but **must be reviewed by a qualified person against Indian data protection rules before a
real launch**.

Versions live in `app/legal.py`. When you change a document in a way that matters, change its version there:
everyone is asked to accept again and the new acceptance is recorded next to the old ones in `user_consent`.

## Not built on purpose

In-site chat, saved vehicle profiles, email or phone verification, email notifications, and seeded sample data.
Payment is a demo behind a gateway interface (`app/payments.py`) that a real provider can replace. Email
verification is the first thing to add before a real launch.
