"""Verifying who is calling.

Two verifiers share one interface:

* :class:`SupabaseTokenVerifier` checks Supabase Auth access tokens. Projects on
  Supabase's current asymmetric signing keys (ES256/RS256) are verified locally
  against the project's published JWKS. Projects still on the legacy shared secret
  (HS256) are verified by asking the Auth server, which is what Supabase recommends
  instead of copying that secret into another service.
* :class:`BuiltinTokenVerifier` checks the session tokens this API issues itself when
  it keeps the accounts (``AUTH_MODE=builtin``, and ``dev`` on a laptop).
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID

import httpx
import jwt

from ..core.config import Settings, get_settings
from ..core.errors import AuthenticationError

BUILTIN_ISSUER = "tatmaq"
ASYMMETRIC_ALGORITHMS = ("ES256", "RS256", "EdDSA")
#: Supabase's edge caches the key set for 10 minutes; caching longer would delay key revocation.
JWKS_CACHE_SECONDS = 600


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str | None = None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> AuthUser: ...


def _user_from_claims(claims: dict[str, Any]) -> AuthUser:
    if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
        raise AuthenticationError("This token does not belong to a signed-in user.")
    try:
        return AuthUser(id=UUID(str(claims["sub"])), email=claims.get("email") or None)
    except (KeyError, ValueError) as error:
        raise AuthenticationError("The access token is not valid.") from error


class BuiltinTokenVerifier:
    def __init__(self, secret: str, audience: str) -> None:
        self._secret, self._audience = secret, audience

    def verify(self, token: str) -> AuthUser:
        try:
            claims = jwt.decode(
                token, self._secret, algorithms=["HS256"], audience=self._audience, issuer=BUILTIN_ISSUER,
                options={"require": ["exp", "sub", "iat"]},
            )  # fmt: skip
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError(
                "Your session has expired. Please sign in again.", code="token_expired"
            ) from error
        except jwt.PyJWTError as error:
            raise AuthenticationError("The access token is not valid.") from error
        return _user_from_claims(claims)


class SupabaseTokenVerifier:
    def __init__(
        self, *, supabase_url: str, issuer: str, audience: str, publishable_key: str,
        http: httpx.Client | None = None,
    ) -> None:  # fmt: skip
        self._issuer, self._audience = issuer, audience
        self._user_endpoint = f"{supabase_url.rstrip('/')}/auth/v1/user"
        self._publishable_key = publishable_key
        self._jwks = jwt.PyJWKClient(
            f"{issuer}/.well-known/jwks.json", cache_jwk_set=True, lifespan=JWKS_CACHE_SECONDS, timeout=10
        )
        self._http = http or httpx.Client(timeout=10)
        self._checked: OrderedDict[str, tuple[AuthUser, float]] = OrderedDict()

    def verify(self, token: str) -> AuthUser:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as error:
            raise AuthenticationError("The access token is not valid.") from error
        if algorithm in ASYMMETRIC_ALGORITHMS:
            return self._verify_with_public_key(token, algorithm)
        if algorithm == "HS256":
            return self._verify_with_auth_server(token)
        raise AuthenticationError("The access token uses an unsupported signing algorithm.")

    def _verify_with_public_key(self, token: str, algorithm: str) -> AuthUser:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=[algorithm], audience=self._audience, issuer=self._issuer,
                options={"require": ["exp", "sub"]},
            )  # fmt: skip
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError(
                "Your session has expired. Please sign in again.", code="token_expired"
            ) from error
        except jwt.PyJWTError as error:
            raise AuthenticationError("The access token is not valid.") from error
        return _user_from_claims(claims)

    def _verify_with_auth_server(self, token: str) -> AuthUser:
        """Legacy HS256 projects: the Auth server is the authority on whether a token is good."""
        cache_key = hashlib.sha256(token.encode()).hexdigest()
        cached = self._checked.get(cache_key)
        if cached and cached[1] > time.time():
            return cached[0]
        try:
            response = self._http.get(
                self._user_endpoint, headers={"apikey": self._publishable_key, "Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as error:
            raise AuthenticationError("Could not reach the sign-in service. Please try again.") from error
        if response.status_code != 200:
            raise AuthenticationError("The access token is not valid.")
        body = response.json()
        user = _user_from_claims(
            {"sub": body.get("id"), "email": body.get("email"), "role": body.get("role"),
             "is_anonymous": body.get("is_anonymous")}
        )  # fmt: skip
        self._checked[cache_key] = (user, time.time() + 60)
        while len(self._checked) > 1024:
            self._checked.popitem(last=False)
        return user


def build_verifier(settings: Settings) -> TokenVerifier:
    if settings.builtin_sign_in:
        return BuiltinTokenVerifier(settings.session_token_secret, settings.jwt_audience)
    return SupabaseTokenVerifier(
        supabase_url=settings.supabase_url,
        issuer=settings.supabase_issuer,
        audience=settings.jwt_audience,
        publishable_key=settings.supabase_publishable_key,
    )


@lru_cache
def get_verifier() -> TokenVerifier:
    return build_verifier(get_settings())
