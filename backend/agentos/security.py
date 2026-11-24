"""Separate local demo tokens from signed OIDC deployment authentication."""

import json
import os
import secrets
import time
from functools import lru_cache

import jwt
from fastapi import HTTPException
from pydantic import BaseModel


class Principal(BaseModel):
    subject: str
    workspace: str
    role: str
    scopes: list[str]


def validate_configuration():
    mode = os.getenv("AUTH_MODE", "demo")
    if mode not in {"demo", "oidc"}:
        raise RuntimeError("Unsupported AUTH_MODE")
    if os.getenv("DEPLOYMENT", "local") != "local" and mode == "demo":
        raise RuntimeError("Demo authentication is forbidden in deployment mode")
    if mode == "oidc" and not all(os.getenv(k) for k in ["OIDC_ISSUER", "OIDC_AUDIENCE"]):
        raise RuntimeError("OIDC issuer and audience required")
    if mode == "oidc" and not (os.getenv("OIDC_PUBLIC_KEY") or os.getenv("OIDC_JWKS_URL")):
        raise RuntimeError("OIDC verification key required")


ROLE_SCOPES = {
    "viewer": ["data:read"],
    "editor": ["data:read", "knowledge:write", "action:write"],
    "admin": ["data:read", "knowledge:write", "action:write", "admin"],
}


@lru_cache(maxsize=4)
def jwks_client(url):
    return jwt.PyJWKClient(url, cache_keys=True)


def authenticate(authorization: str):
    validate_configuration()
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    token = authorization[7:]
    if os.getenv("AUTH_MODE", "demo") == "demo":
        registry = json.loads(
            os.getenv("API_KEYS") or '{"local-demo-token":{"workspace":"demo","role":"admin"}}'
        )
        match = next((v for key, v in registry.items() if secrets.compare_digest(key, token)), None)
        if not match:
            raise HTTPException(401, "Invalid bearer token")
        role = match["role"]
        if role not in ROLE_SCOPES:
            raise HTTPException(403, "Unknown role")
        return Principal(
            subject="local:" + match["workspace"] + ":" + role,
            workspace=match["workspace"],
            role=role,
            scopes=ROLE_SCOPES[role],
        ).model_dump()
    try:
        key = os.getenv("OIDC_PUBLIC_KEY")
        if not key:
            url = os.environ["OIDC_JWKS_URL"]
            if not url.startswith("https://"):
                raise ValueError("HTTPS JWKS required")
            key = jwks_client(url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=os.environ["OIDC_AUDIENCE"],
            issuer=os.environ["OIDC_ISSUER"],
            options={"require": ["exp", "iat", "sub", "iss", "aud", "workspace", "role"]},
        )
        if (
            claims["role"] not in ROLE_SCOPES
            or not isinstance(claims["workspace"], str)
            or not claims["workspace"]
        ):
            raise ValueError("Invalid authorization claims")
        # Scope intersection prevents a signed role token from silently broadening rights.
        requested = claims.get("scope", " ".join(ROLE_SCOPES[claims["role"]])).split()
        return Principal(
            subject=claims["sub"],
            workspace=claims["workspace"],
            role=claims["role"],
            scopes=[s for s in ROLE_SCOPES[claims["role"]] if s in requested],
        ).model_dump()
    except Exception as exc:
        raise HTTPException(401, "Token verification failed") from exc


def rate_limit(store, principal):
    bucket = int(time.time() // 60)
    key = principal["workspace"] + ":" + principal["subject"] + ":" + str(bucket)
    limit = int(os.getenv("REQUESTS_PER_MINUTE", "120"))
    store.execute(
        "INSERT INTO rate_limits(id,bucket,count) VALUES(:id,:b,0) ON CONFLICT(id) DO NOTHING",
        dict(id=key, b=bucket),
    )
    from sqlalchemy import text

    with store.engine.begin() as c:
        r = c.execute(
            text("UPDATE rate_limits SET count=count+1 WHERE id=:id AND count<:limit"),
            dict(id=key, limit=limit),
        )
        if r.rowcount != 1:
            raise HTTPException(429, "Workspace request limit reached")
        c.execute(text("DELETE FROM rate_limits WHERE bucket<:b"), {"b": bucket - 2})
