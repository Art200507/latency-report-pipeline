import os
import secrets
from fastapi import Header, HTTPException

def require_operator(authorization: str | None = Header(default=None)):
    expected = os.getenv("OPERATOR_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Publishing is not configured for this deployment")
    if not authorization or not authorization.startswith("Bearer ") or not secrets.compare_digest(authorization[7:], expected):
        raise HTTPException(401, "Operator authorization required", headers={"WWW-Authenticate": "Bearer"})
