"""Keycloak-Login (Authorization Code Flow + PKCE) und Bearer-Token-Verwaltung."""

import base64
import hashlib
import http.server
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

    def get_admin_client_logo_url(self):
        """Liest die logoUri aus den Client-Attributen (Erweiterte Einstellungen) via Keycloak Admin-API.

        Benoetigt, dass der Service-Account des Clients die Rolle 'view-clients' des
        'realm-management'-Clients besitzt. Gibt None zurueck, wenn kein Wert gesetzt ist.
        """
        token_endpoint = self._get_endpoints()["token_endpoint"]
        token_response = requests.post(
            token_endpoint,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=10,
        )
        if not token_response.ok:
            raise KeycloakAuthError(
                f"Service-Account-Token-Anfrage fehlgeschlagen ({token_response.status_code}): {token_response.text}"
            )
        service_account_token = token_response.json()["access_token"]

        realm_marker = "/realms/"
        realm_index = self.issuer_url.rfind(realm_marker)
        if realm_index == -1:
            raise KeycloakAuthError("Realm konnte nicht aus der Issuer-URL ermittelt werden.")
        server_base = self.issuer_url[:realm_index]
        realm_name = self.issuer_url[realm_index + len(realm_marker):]

        admin_response = requests.get(
            f"{server_base}/admin/realms/{realm_name}/clients",
            params={"clientId": self.client_id},
            headers={"Authorization": f"Bearer {service_account_token}"},
            timeout=10,
        )
        if not admin_response.ok:
            raise KeycloakAuthError(
                f"Admin-API-Anfrage fehlgeschlagen ({admin_response.status_code}): {admin_response.text}"
            )
        clients = admin_response.json()
        if not clients:
            return None
        return clients[0].get("attributes", {}).get("logoUri") or None

    def get_login_page_logo_url(self):
        """Versucht, die Theme-Logo-URL aus der gerenderten Keycloak-Login-Seite zu extrahieren."""
        endpoints = self._get_endpoints()
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
        }
        response = requests.get(endpoints["authorization_endpoint"], params=params, timeout=10)
        response.raise_for_status()
        html = response.text

        patterns = (
            r'id=["\']kc-logo-text["\'][^>]*background-image:\s*url\((?:["\']?)([^)"\']+)',
            r'<img[^>]+id=["\']kc-logo-img["\'][^>]+src=["\']([^"\']+)["\']',
            r'<img[^>]+src=["\']([^"\']*logo[^"\']*)["\']',
        )
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return urllib.parse.urljoin(response.url, match.group(1))
        return None

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
