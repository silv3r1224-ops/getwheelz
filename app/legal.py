"""Terms, privacy and consent rules (spec section 11). Pure Python: no Flask, no database.

THE DRAFTS ARE PLACEHOLDERS. The text in templates/legal/ reflects the rules in SPEC.md, but it has not
been reviewed by a qualified person and must be reviewed against Indian data protection rules before a
real launch.

Versioning
----------
Each document has a version string. Whenever its text changes in a way that matters, change its version
here: every signed-in person is then asked to accept again (see ``missing_docs``) and the new
acceptance is recorded next to the old ones in ``user_consent`` (who, which document, which version,
when), so the history is never overwritten.

* ``terms`` and ``privacy`` are accepted together by everyone who signs up (customers, owners and
  mechanics). Admin accounts are created by the main admin rather than by sign-up and are not asked.
* ``owner_agreement`` is an extra agreement owners accept before they can list a workshop.
"""
DOC_TERMS = "terms"
DOC_PRIVACY = "privacy"
DOC_OWNER = "owner_agreement"

# Bump a version when its document changes materially. Format: the date of the change.
VERSIONS = {
    DOC_TERMS: "2026-11-11",
    DOC_PRIVACY: "2026-11-11",
    DOC_OWNER: "2026-11-11",
}

TITLES = {
    DOC_TERMS: "Terms and Conditions",
    DOC_PRIVACY: "Privacy Policy",
    DOC_OWNER: "Workshop Owner Agreement",
}

# what everyone signing up accepts with the one required checkbox
SIGNUP_DOCS = (DOC_TERMS, DOC_PRIVACY)
# roles that must accept the signup documents (admins are created by the main admin)
CONSENT_ROLES = ("customer", "owner", "mechanic")

DRAFT_NOTICE = (
    "DRAFT: placeholder text for a demo. It has not been reviewed by a lawyer and must be reviewed by a "
    "qualified person against Indian data protection rules before any real launch."
)


def requires_consent(role):
    """Customers, owners and mechanics accept the terms; admins are exempt."""
    return role in CONSENT_ROLES


def required_docs(role, has_workshop=False):
    """The documents this person must have accepted (at their CURRENT version) to use the site.

    An owner who already lists a workshop must also be on the current owner agreement; one who has not
    listed yet accepts it at the moment they create their listing."""
    if not requires_consent(role):
        return ()
    docs = list(SIGNUP_DOCS)
    if role == "owner" and has_workshop:
        docs.append(DOC_OWNER)
    return tuple(docs)


def missing_docs(accepted, role, has_workshop=False, versions=None):
    """Which required documents still need accepting.

    ``accepted`` is an iterable of ``(doc, version)`` pairs the person has accepted over time. Only an
    acceptance of the CURRENT version counts: accepting an older version does not.
    """
    versions = versions or VERSIONS
    have = set(accepted)
    return [d for d in required_docs(role, has_workshop) if (d, versions[d]) not in have]


def needs_acceptance(accepted, role, has_workshop=False, versions=None):
    return bool(missing_docs(accepted, role, has_workshop, versions))


def has_accepted(accepted, doc, versions=None):
    return (doc, (versions or VERSIONS)[doc]) in set(accepted)


def signature(role, has_workshop=False, versions=None):
    """A short string that changes whenever the set of required documents or their versions change.
    The session remembers it after a successful check so the database is not asked on every page; a
    version bump (or an owner listing a workshop) changes it and triggers a fresh check."""
    versions = versions or VERSIONS
    docs = required_docs(role, has_workshop)
    return "|".join(f"{d}:{versions[d]}" for d in docs) or "exempt"


def rows_to_record(docs, versions=None):
    """``[(doc, version), ...]`` to insert when someone accepts ``docs`` now."""
    versions = versions or VERSIONS
    return [(d, versions[d]) for d in docs]


# Endpoints a person who has not accepted yet may still reach: the documents themselves, the accept
# page, logging out, the suspension/appeal screens, and static files.
GATE_EXEMPT_ENDPOINTS = frozenset({
    "static", "legal.terms", "legal.privacy", "legal.owner_agreement", "legal.accept",
    "auth.logout", "appeals.suspended", "appeals.suspended_appeal", "live.version",
})


def gate_applies(endpoint, role, user_id):
    """Should the consent check run for this request?"""
    if not user_id or not requires_consent(role):
        return False
    if endpoint is None or endpoint in GATE_EXEMPT_ENDPOINTS:
        return False
    return True


def safe_next(target, fallback="/"):
    """A redirect target that stays on this site: a path starting with a single '/'."""
    target = (target or "").strip()
    if target.startswith("/") and not target.startswith("//") and "\\" not in target and "\n" not in target and "\r" not in target:
        return target
    return fallback
