"""Who may call the API: token verification for Supabase Auth and for the built-in sign-in."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.security.auth import BuiltinTokenVerifier, SupabaseTokenVerifier

ISSUER = "https://abcdefgh.supabase.co/auth/v1"
USER_ID = str(uuid.uuid4())


@pytest.fixture(scope="module")
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def auth_server_calls():
    return []


@pytest.fixture
def verifier(signing_key, monkeypatch, auth_server_calls):
    """A verifier whose JWKS endpoint serves our test key, as a Supabase project would serve its own."""
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    monkeypatch.setattr(
        jwt.PyJWKClient, "fetch_data", lambda self: {"keys": [{**jwk, "kid": "key-1", "alg": "ES256", "use": "sig"}]}
    )

    def auth_server(request: httpx.Request) -> httpx.Response:
        auth_server_calls.append(request)
        if request.headers["authorization"] == "Bearer legacy-good-token":
            return httpx.Response(200, json={"id": USER_ID, "email": "legacy@example.com", "role": "authenticated"})
        return httpx.Response(401, json={"msg": "invalid JWT"})

    return SupabaseTokenVerifier(supabase_url="https://abcdefgh.supabase.co", issuer=ISSUER, audience="authenticated",
                                 publishable_key="sb_publishable_test", http=httpx.Client(transport=httpx.MockTransport(auth_server)))  # fmt: skip


def token(key, *, algorithm="ES256", **overrides) -> str:
    claims = {"sub": USER_ID, "email": "tendai@example.com", "role": "authenticated", "aud": "authenticated",
              "iss": ISSUER, "exp": int(time.time()) + 300, **overrides}  # fmt: skip
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None}, key, algorithm=algorithm, headers={"kid": "key-1"}
    )


def test_a_supabase_token_signed_with_the_projects_key_is_accepted(verifier, signing_key):
    user = verifier.verify(token(signing_key))
    assert str(user.id) == USER_ID and user.email == "tendai@example.com"


@pytest.mark.parametrize("overrides", [
    {"exp": int(time.time()) - 10}, {"aud": "another-app"}, {"iss": "https://attacker.supabase.co/auth/v1"},
    {"role": "anon"}, {"role": "service_role"}, {"is_anonymous": True}, {"sub": "not-a-uuid"}, {"sub": None}, {"exp": None},
])  # fmt: skip
def test_tokens_that_are_expired_misdirected_or_not_a_signed_in_user_are_refused(verifier, signing_key, overrides):
    with pytest.raises(AuthenticationError):
        verifier.verify(token(signing_key, **overrides))


def test_forged_tokens_are_refused(verifier, signing_key):
    impostor = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(AuthenticationError):
        verifier.verify(token(impostor))  # right shape, wrong key
    unsigned = jwt.encode({"sub": USER_ID, "role": "authenticated", "aud": "authenticated", "iss": ISSUER,
                           "exp": int(time.time()) + 300}, key=None, algorithm="none")  # fmt: skip
    with pytest.raises(AuthenticationError, match="unsupported signing algorithm"):
        verifier.verify(unsigned)
    # "algorithm confusion": sign with HS256 using the (public) verification key as if it were a shared secret
    public_pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    encode = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")
    unsigned_part = (
        encode({"alg": "HS256", "typ": "JWT", "kid": "key-1"})
        + b"."
        + encode(
            {
                "sub": USER_ID,
                "role": "authenticated",
                "aud": "authenticated",
                "iss": ISSUER,
                "exp": int(time.time()) + 300,
            }
        )
    )
    signature = base64.urlsafe_b64encode(hmac.new(public_pem, unsigned_part, hashlib.sha256).digest()).rstrip(b"=")
    with pytest.raises(AuthenticationError):
        verifier.verify((unsigned_part + b"." + signature).decode())
    for junk in ("", "not.a.token", "a.b"):
        with pytest.raises(AuthenticationError):
            verifier.verify(junk)


def test_legacy_shared_secret_projects_are_checked_with_the_auth_server(verifier, auth_server_calls, monkeypatch):
    monkeypatch.setattr(jwt, "get_unverified_header", lambda t: {"alg": "HS256"})
    user = verifier.verify("legacy-good-token")
    assert str(user.id) == USER_ID and user.email == "legacy@example.com"
    request = auth_server_calls[0]
    assert (
        request.url == "https://abcdefgh.supabase.co/auth/v1/user"
        and request.headers["apikey"] == "sb_publishable_test"
    )
    verifier.verify("legacy-good-token")
    assert len(auth_server_calls) == 1  # the answer is cached briefly rather than asked for on every request
    with pytest.raises(AuthenticationError):
        verifier.verify("legacy-bad-token")


def test_built_in_session_tokens(settings):
    from app.security import builtin_auth
    from app.security.auth import AuthUser

    verifier = BuiltinTokenVerifier(settings.session_token_secret, settings.jwt_audience)
    good, _ = builtin_auth.issue_token(AuthUser(id=uuid.UUID(USER_ID), email="dev@example.com"), settings)
    assert str(verifier.verify(good).id) == USER_ID
    with pytest.raises(AuthenticationError):
        BuiltinTokenVerifier("a-different-secret-of-sufficient-length-0001", settings.jwt_audience).verify(good)
    expired = jwt.encode({"sub": USER_ID, "role": "authenticated", "aud": "authenticated", "iss": "tatmaq",
                          "iat": 1, "exp": 2}, settings.session_token_secret, algorithm="HS256")  # fmt: skip
    with pytest.raises(AuthenticationError) as caught:
        verifier.verify(expired)
    assert caught.value.code == "token_expired"


def test_the_api_requires_a_valid_token_and_reports_errors_in_one_shape(client, account):
    for headers in (
        {},
        {"Authorization": "Bearer nonsense"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ):
        response = client.get("/v1/organisations", headers=headers)
        assert response.status_code == 401 and response.json()["error"]["code"] == "not_authenticated"
        assert response.headers["www-authenticate"] == "Bearer"
    missing_org = client.get("/v1/datasets", headers={"Authorization": f"Bearer {account.token}"})
    assert missing_org.status_code == 422 and missing_org.json()["error"]["code"] == "invalid_request"
    assert client.get("/v1/no-such-route").json()["error"]["code"] == "not_found"
    assert client.get("/healthz").headers["x-content-type-options"] == "nosniff"


def test_signing_up_and_signing_in(client):
    email = f"signin-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/v1/auth/register", json={"email": email, "password": "short"}).status_code == 401
    assert (
        client.post("/v1/auth/register", json={"email": "not-an-email", "password": "long enough pw"}).status_code
        == 401
    )
    assert client.post("/v1/auth/register", json={"email": email, "password": "long enough pw"}).status_code == 201
    again = client.post("/v1/auth/register", json={"email": email.upper(), "password": "long enough pw"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "email_taken"
    assert client.post("/v1/auth/login", json={"email": email, "password": "long enough pw"}).status_code == 200
    wrong = client.post("/v1/auth/login", json={"email": email, "password": "wrong password"})
    unknown = client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong password"})
    assert (
        wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
    )  # no hint which emails exist


def test_passwords_are_stored_hashed(client, database_url):
    import psycopg

    email = f"hash-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/v1/auth/register", json={"email": email, "password": "a memorable passphrase"})
    with psycopg.connect(database_url) as connection:
        stored = connection.execute("SELECT encrypted_password FROM auth.users WHERE email = %s", (email,)).fetchone()[
            0
        ]
    assert stored.startswith("scrypt$") and "memorable" not in stored


def base_settings(**overrides) -> Settings:
    values = {"database_url": "postgresql://u@h/d", "auth_mode": "dev", "app_env": "development", **overrides}
    return Settings(_env_file=None, **values)


def test_unsafe_configuration_is_refused_at_start_up(monkeypatch):
    for name in ("APP_ENV", "AUTH_MODE", "STORAGE_BACKEND", "AI_PROVIDER", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    production = {"app_env": "production", "app_secret_key": "x" * 40, "cors_allowed_origins": "https://app.example.com",
                  "auth_mode": "supabase", "supabase_url": "https://abc.supabase.co"}  # fmt: skip
    assert base_settings(**production).app_env == "production"
    for change, message in [
        ({"auth_mode": "dev"}, "refused in production"),
        ({"app_secret_key": "short"}, "at least 32"),
        ({"cors_allowed_origins": ""}, "CORS_ALLOWED_ORIGINS"),
        ({"cors_allowed_origins": "*"}, "explicit origins"),
        ({"supabase_url": ""}, "needs SUPABASE_URL"),
        ({"storage_backend": "supabase"}, "SUPABASE_SECRET_KEY"),
        ({"ai_provider": "anthropic"}, "AI_API_KEY and AI_MODEL"),
    ]:  # fmt: skip
        with pytest.raises(ValueError, match=message):
            base_settings(**{**production, **change})


def test_settings_accept_current_and_legacy_supabase_key_names_and_plain_database_urls(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "legacy-anon")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_new")
    settings = Settings(
        _env_file=None, auth_mode="dev", app_env="development", database_url="postgres://u:p@db.example.com:5432/app"
    )
    assert (settings.supabase_publishable_key, settings.supabase_secret_key) == ("legacy-anon", "sb_secret_new")
    assert settings.sqlalchemy_url == "postgresql+psycopg://u:p@db.example.com:5432/app"


def test_sign_in_and_file_routes_exist_only_when_this_api_provides_them():
    from fastapi import FastAPI

    from app.api.router import build_router

    def paths(settings: Settings) -> set[str]:
        application = FastAPI()
        application.include_router(build_router(settings))
        return set(application.openapi()["paths"])

    supabase = paths(
        base_settings(
            auth_mode="supabase",
            supabase_url="https://abc.supabase.co",
            storage_backend="supabase",
            supabase_secret_key="sb_secret_x",
        )
    )
    assert not {"/auth/login", "/auth/register", "/auth/password"} & supabase and "/auth/profile" in supabase
    assert (
        "/uploads/{token}" not in supabase and "/files/{token}" not in supabase
    )  # the browser talks to storage directly
    ours = {"/auth/login", "/auth/register", "/auth/password", "/uploads/{token}", "/files/{token}"}
    assert ours <= paths(base_settings())  # development: built-in accounts, files on disk
    production = {
        "app_env": "production",
        "app_secret_key": "x" * 40,
        "cors_allowed_origins": "https://app.example.com",
    }
    assert ours <= paths(base_settings(auth_mode="builtin", storage_backend="database", **production))
