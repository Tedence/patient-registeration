"""Shared-secret admin auth for mutation endpoints.

Config: ADMIN_TOKEN env var (required). If unset, all admin routes return 503
so the service fails closed rather than silently allowing unauthenticated
writes.

Clients send:
  - X-Admin-Token: must match ADMIN_TOKEN (401 on mismatch)
  - X-Admin-User:  self-declared operator name (required; recorded in audit log)
"""

import os

from fastapi import Header, HTTPException


class AdminContext:
    """Identity carried through admin requests — used by audit log."""
    def __init__(self, user: str) -> None:
        self.user = user


def require_admin(
    x_admin_token: str | None = Header(default=None),
    x_admin_user: str | None = Header(default=None),
) -> AdminContext:
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin mode is not configured on this server.",
        )
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    if not x_admin_user or not x_admin_user.strip():
        raise HTTPException(status_code=401, detail="Operator name is required.")
    return AdminContext(user=x_admin_user.strip())
