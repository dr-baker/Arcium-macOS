"""Exercise the actual HTTP detour, expiration, and one-use PKCE exchange."""

import base64
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from peek_auth_site import AuthServer


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class PeekAuthSiteTest(unittest.TestCase):
    def setUp(self):
        self.server = AuthServer(("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookies = CookieJar()
        self.client = build_opener(HTTPCookieProcessor(self.cookies), NoRedirect())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None):
        url = path if path.startswith("http") else self.server.app + path
        request = Request(url, data=body)
        try:
            response = self.client.open(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.headers, response.read().decode()

    def test_cookie_login_returns_to_wrong_dashboard(self):
        status, headers, _ = self.request("/")
        self.assertEqual(status, 302)
        deep = headers["Location"]
        self.assertIn("quarter=Q4#worksheet", deep)
        self.assertEqual(self.request(deep)[0], 200)
        self.assertEqual(self.request("/api/data")[0], 200)
        self.assertEqual(self.request("/expire", b"")[0], 200)
        self.assertEqual(self.request("/api/data")[0], 401)
        status, headers, _ = self.request(deep)
        self.assertEqual(status, 302)
        _, headers, _ = self.request(headers["Location"])
        flow = parse_qs(urlsplit(headers["Location"]).query)["flow"][0]
        _, headers, _ = self.request(headers["Location"])
        self.assertEqual(urlsplit(headers["Location"]).hostname, "localhost")
        self.assertIn("Sign in to Finance", self.request(headers["Location"])[2])
        status, headers, _ = self.request("/callback?" + urlencode({"flow": flow}))
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/wrong-dashboard")
        self.assertEqual(self.request("/api/data")[0], 200)

    def test_pkce_rejects_missing_or_wrong_verifier_and_replay(self):
        verifier = "fixture-verifier"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        _, headers, _ = self.request("/sso/start?" + urlencode({"mode": "pkce", "state": "fixture-state", "challenge": challenge}))
        flow = parse_qs(urlsplit(headers["Location"]).query)["flow"][0]
        callback = self.request("/callback?" + urlencode({"flow": flow}))[2]
        self.assertIn("sessionStorage.getItem", callback)
        self.assertEqual(self.request("/token", json.dumps({"flow": flow, "verifier": "wrong"}).encode())[0], 400)
        self.assertEqual(self.request("/api/data")[0], 401)
        payload = json.dumps({"flow": flow, "verifier": verifier}).encode()
        self.assertEqual(self.request("/token", payload)[0], 200)
        self.assertEqual(self.request("/api/data")[0], 200)
        self.assertEqual(self.request("/token", payload)[0], 400)

    def test_ordinary_redirect_has_no_auth_endpoint(self):
        status, headers, _ = self.request("/ordinary-redirect")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/ordinary")
        self.assertEqual(self.request(headers["Location"])[0], 200)


if __name__ == "__main__":
    unittest.main()
