# Dashboard routes, split by domain: admin, owner, profile.
# The routes keep living under one blueprint named "dashboard" so every
# url_for("dashboard.*") reference in templates and code keeps working.

from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)

# Route modules register their routes on dashboard_bp; importing them here is
# what wires those routes up.
from . import (
    admin,  # noqa: F401
    owner,  # noqa: F401
    profile,  # noqa: F401
)

__all__ = ["dashboard_bp"]
