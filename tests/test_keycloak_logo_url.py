import base64
import json
import time

from src.keycloak_auth import KeycloakAuthenticator


def _token_with_claims(claims):
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def test_logo_url_from_access_token_claim():
    auth = KeycloakAuthenticator("https://example.com/realms/test", "client", "secret")
    auth._tokens = {"access_token": _token_with_claims({"logo_url": "https://cdn.example.com/logo.svg"})}

    assert auth.logo_url == "https://cdn.example.com/logo.svg"


def test_logo_url_missing_returns_none():
    auth = KeycloakAuthenticator("https://example.com/realms/test", "client", "secret")
    auth._tokens = {"access_token": _token_with_claims({"preferred_username": "demo-user"})}

    assert auth.logo_url is None


def test_logo_url_relative_path_is_resolved_against_issuer():
    auth = KeycloakAuthenticator("https://example.com/realms/test", "client", "secret")
    auth._tokens = {"access_token": _token_with_claims({"logo_url": "/assets/logo.svg"})}

    assert auth.logo_url == "https://example.com/assets/logo.svg"


def test_website_color_scheme_parses_single_line_keycloak_format():
    auth = KeycloakAuthenticator("https://example.com/realms/test", "client", "secret")
    scheme = 'BG_COLOR = "#EAEAEA" CARD_COLOR = "#D9D9D9" ACCENT_COLOR = "#E06020" ACCENT_HOVER = "#D95610" TEXT_COLOR = "#2F2F2F" MUTED_TEXT = "#606060" ERROR_COLOR = "#C94C2E"'
    auth._tokens = {"access_token": _token_with_claims({"website_color_scheme": scheme})}

    assert auth.website_color_scheme == scheme


def test_expired_access_token_is_detected_as_invalid():
    auth = KeycloakAuthenticator("https://example.com/realms/test", "client", "secret")
    auth._tokens = {
        "access_token": _token_with_claims({"exp": int(time.time()) - 60}),
        "refresh_token": "refresh-token",
    }
    auth._expires_at = time.time() - 1

    assert auth.is_access_token_valid() is False
