"""Keycloak-Login (Authorization Code Flow + PKCE) und Bearer-Token-Verwaltung."""

import base64
import hashlib
import http.server
import json
import re
import secrets
import time
import urllib.parse

import requests

DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 30


class KeycloakAuthError(RuntimeError):
    """Wird bei fehlgeschlagenem Login oder Token-Refresh ausgeloest."""


class KeycloakAuthenticator:
    """Fuehrt den Login gegen Keycloak durch und liefert Bearer-Token fuer REST-Aufrufe."""

    def __init__(self, issuer_url, client_id, client_secret, redirect_uri=DEFAULT_REDIRECT_URI, scope="openid"):
        if not client_secret:
            raise KeycloakAuthError(
                "Kein Keycloak-Client-Secret gefunden (Umgebungsvariable KEYCLOAK_CLIENT_SECRET)."
            )
        self.issuer_url = issuer_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self._endpoints = None
        self._tokens = None
        self._expires_at = 0.0

    @property
    def is_authenticated(self):
        return self._tokens is not None

    def _decode_token_claims(self):
        access_token = (self._tokens or {}).get("access_token", "")
        token_parts = access_token.split(".")
        if len(token_parts) != 3:
            return None
        try:
            payload = base64.urlsafe_b64decode(token_parts[1] + "=" * (-len(token_parts[1]) % 4))
            return json.loads(payload)
        except (ValueError, json.JSONDecodeError):
            return None

    @property
    def username(self):
        """Liefert den Benutzer fuer die reine Anzeige aus dem OIDC-Token."""
        claims = self._decode_token_claims()
        if claims is None:
            return None
        return claims.get("preferred_username") or claims.get("name") or claims.get("email")

    @property
    def logo_url(self):
        """Liefert die Logo-URL aus dem Access-Token-Claim, falls vorhanden."""
        claims = self._decode_token_claims()
        if claims is None:
            return None
        logo_url = claims.get("logo_url") or None
        if not logo_url:
            return None
        if logo_url.startswith("data:"):
            return logo_url
        if urllib.parse.urlparse(logo_url).scheme:
            return logo_url
        base_url = self.issuer_url.rstrip("/") + "/"
        return urllib.parse.urljoin(base_url, logo_url)

    @property
    def website_color_scheme(self):
        """Liefert das Farbtheme aus dem Access-Token-Claim, falls vorhanden."""
        claims = self._decode_token_claims()
        if claims is None:
            return None
        return claims.get("website_color_scheme") or None

    @property
    def access_token(self):
        """Liefert den aktuell gespeicherten Access-Token fuer die Anzeige."""
        return (self._tokens or {}).get("access_token")

    def is_access_token_valid(self):
        """True, wenn der aktuelle Access-Token noch nicht abgelaufen ist."""
        if not self.is_authenticated:
            return False

        if time.time() >= self._expires_at:
            return False

        claims = self._decode_token_claims()
        if not claims:
            return False

        exp = claims.get("exp")
        if exp is None:
            return True

        expiration_time = float(exp)
        return expiration_time > time.time() + TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS

    def login(self):
        """Blockierender Authorization-Code-Flow mit PKCE ueber den Systembrowser."""
        endpoints = self._get_endpoints()
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        state = secrets.token_urlsafe(16)

        auth_params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{endpoints['authorization_endpoint']}?{urllib.parse.urlencode(auth_params)}"

        result = {}
        server = self._build_callback_server(state, result)
        try:
            import webbrowser

            webbrowser.open(auth_url)
            server.handle_request()
        finally:
            server.server_close()

        if result.get("error"):
            raise KeycloakAuthError(f"Keycloak-Login fehlgeschlagen: {result['error']}")
        code = result.get("code")
        if not code:
            raise KeycloakAuthError("Keycloak-Login abgebrochen: kein Autorisierungscode erhalten.")

        self._store_tokens(
            self._request_tokens(
                endpoints["token_endpoint"],
                grant_type="authorization_code",
                code=code,
                redirect_uri=self.redirect_uri,
                code_verifier=code_verifier,
            )
        )
        return self._tokens

    def logout(self):
        self._tokens = None
        self._expires_at = 0.0

    def get_auth_header(self):
        """Liefert den Authorization-Header, erneuert das Token bei Bedarf automatisch."""
        if not self.is_authenticated:
            raise KeycloakAuthError("Nicht angemeldet.")
        if time.time() >= self._expires_at:
            self._refresh()
        return {"Authorization": f"{self._tokens.get('token_type', 'Bearer')} {self._tokens['access_token']}"}

    def _refresh(self):
        refresh_token = (self._tokens or {}).get("refresh_token")
        if not refresh_token:
            raise KeycloakAuthError("Token abgelaufen und kein Refresh-Token vorhanden, bitte erneut anmelden.")
        endpoints = self._get_endpoints()
        self._store_tokens(
            self._request_tokens(
                endpoints["token_endpoint"], grant_type="refresh_token", refresh_token=refresh_token
            )
        )

    def _request_tokens(self, token_endpoint, **extra_data):
        data = {"client_id": self.client_id, "client_secret": self.client_secret, **extra_data}
        response = requests.post(token_endpoint, data=data, timeout=10)
        if not response.ok:
            raise KeycloakAuthError(f"Token-Anfrage fehlgeschlagen ({response.status_code}): {response.text}")
        return response.json()

    def _store_tokens(self, tokens):
        self._tokens = tokens
        expires_in = tokens.get("expires_in", 60)
        self._expires_at = time.time() + expires_in - TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS

    def _get_endpoints(self):
        if self._endpoints is None:
            response = requests.get(f"{self.issuer_url}/.well-known/openid-configuration", timeout=10)
            response.raise_for_status()
            self._endpoints = response.json()
        return self._endpoints

    def _build_callback_server(self, expected_state, result):
        parsed = urllib.parse.urlparse(self.redirect_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8765

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self_inner):
                query = urllib.parse.urlparse(self_inner.path).query
                params = urllib.parse.parse_qs(query)
                if "error" in params:
                    result["error"] = params["error"][0]
                elif params.get("state", [None])[0] != expected_state:
                    result["error"] = "Ungueltiger state-Parameter."
                else:
                    result["code"] = params.get("code", [None])[0]

                self_inner.send_response(200)
                self_inner.send_header("Content-Type", "text/html; charset=utf-8")
                self_inner.end_headers()
                self_inner.wfile.write(
                    b"<html><body><p>Anmeldung abgeschlossen. Sie koennen dieses Fenster schliessen.</p></body></html>"
                )

            def log_message(self_inner, format_, *args):
                pass  # Zugriffslog des lokalen Callback-Servers unterdruecken

        return http.server.HTTPServer((host, port), CallbackHandler)
