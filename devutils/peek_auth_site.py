#!/usr/bin/env python3
"""Deterministic two-origin SSO fixture. Run, then open the printed deep URL."""

from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit


STYLE = """
:root { color-scheme: light dark; font: 16px system-ui; }
body { max-width: 880px; margin: 64px auto; padding: 0 28px; }
h1 { font-size: 38px; letter-spacing: -.04em; }
button, a.button { display: inline-block; font: inherit; padding: 10px 16px;
  margin: 4px 6px 4px 0; border-radius: 8px; border: 1px solid #888; cursor: pointer; }
textarea { box-sizing: border-box; width: 100%; min-height: 160px; font: inherit; padding: 12px; }
pre { white-space: pre-wrap; padding: 16px; background: #8882; border-radius: 8px; }
section { margin: 48px 0; } .quiet { opacity: .65; } #rows p { padding: 20px 0; border-bottom: 1px solid #8884; }
"""


def page(title: str, body: str, script: str = "") -> str:
    return f"<!doctype html><meta charset=utf-8><title>{title}</title><style>{STYLE}</style><main>{body}</main><script>{script}</script>"


DEEP_BODY = """
<p class=quiet>Arcium auth test · Finance / Quarterly model</p>
<h1>Revenue worksheet</h1>
<p>Type a draft, scroll down, then expire the session. Login intentionally lands elsewhere.</p>
<button id=cookie>Expire &amp; sign in</button>
<button id=pkce>Test sessionStorage PKCE</button>
<button id=memory>Test memory-only state</button>
<button id=ordinary>Ordinary redirect</button>
<button id=probe>Check authenticated request</button>
<pre id=status>Ready</pre><pre id=identity></pre>
<section id=worksheet><h2>Unsent draft</h2><textarea id=draft placeholder="Write something that must survive sign-in"></textarea></section>
<div id=rows></div>
"""

DEEP_SCRIPT = """
const statusView = document.getElementById('status');
const identityView = document.getElementById('identity');
window.pageIdentity = crypto.randomUUID();
window.tickCount = 0;
window.freezeCount = 0;
window.resumeCount = 0;
document.addEventListener('freeze', () => window.freezeCount++);
document.addEventListener('resume', () => window.resumeCount++);
setInterval(() => {
  window.tickCount++;
  identityView.textContent = JSON.stringify({pageIdentity, tickCount, freezeCount, resumeCount}, null, 2);
}, 100);
sessionStorage.setItem('source-only', 'original');
rows.innerHTML = Array.from({length: 24}, (_, i) => `<p>Revenue row ${i+1} · $${(i+1)*4317}</p>`).join('');
window.beginAuth = async (mode = 'cookie') => {
  await fetch('/expire', {method: 'POST'});
  const verifier = crypto.randomUUID();
  const state = crypto.randomUUID();
  if (mode === 'pkce') sessionStorage.setItem('pkce:' + state, verifier);
  if (mode === 'memory') window.memoryVerifier = verifier;
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
  const challenge = btoa(String.fromCharCode(...digest)).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
  location.href = '/sso/start?' + new URLSearchParams({mode, state, challenge});
};
cookie.onclick = () => beginAuth('cookie');
pkce.onclick = () => beginAuth('pkce');
memory.onclick = () => beginAuth('memory');
ordinary.onclick = () => location.href = '/ordinary-redirect';
probe.onclick = async () => {
  const response = await fetch('/api/data');
  statusView.textContent = response.status + ' ' + await response.text();
};
"""


class AuthServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.flows: dict[str, dict[str, str]] = {}
        self.sessions: set[str] = set()

    @property
    def app(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    @property
    def idp(self) -> str:
        return f"http://localhost:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: AuthServer

    def log_message(self, *_):
        pass

    def send(self, body: str, status=200, headers=None, mime="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, url: str, cookie=None):
        headers = {"Location": url}
        if cookie:
            headers["Set-Cookie"] = cookie
        self.send("", 302, headers)

    def session(self):
        cookies = dict(part.strip().split("=", 1) for part in self.headers.get("Cookie", "").split(";") if "=" in part)
        return cookies.get("fixture_session", "")

    def authenticate(self):
        token = secrets.token_urlsafe(20)
        self.server.sessions.add(token)
        return f"fixture_session={token}; HttpOnly; SameSite=Lax; Path=/"

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        path = parsed.path
        if path == "/":
            self.redirect("/workspace/finance/worksheet?quarter=Q4#worksheet", self.authenticate())
        elif path.startswith("/workspace/"):
            if self.session() not in self.server.sessions:
                self.redirect("/sso/start?" + urlencode({"mode": "cookie", "return": self.path}))
            else:
                self.send(page("Revenue worksheet", DEEP_BODY, DEEP_SCRIPT))
        elif path == "/sso/start":
            flow = secrets.token_urlsafe(16)
            self.server.flows[flow] = query
            self.redirect("/login?" + urlencode({"flow": flow}))
        elif path == "/login":
            self.redirect(self.server.idp + "/idp?" + urlencode(query))
        elif path == "/idp" and query.get("flow") in self.server.flows:
            callback = self.server.app + "/callback?" + urlencode(query)
            self.send(page("Sign in", '<p class=quiet>Local identity provider</p><h1>Sign in to Finance</h1><p>This test uses no account or password.</p><button id=signin>Sign in</button>', f"signin.onclick = () => location.href = {json.dumps(callback)};"))
        elif path == "/callback" and query.get("flow") in self.server.flows:
            flow = query["flow"]
            config = self.server.flows[flow]
            if config.get("mode", "cookie") == "cookie":
                del self.server.flows[flow]
                self.redirect("/wrong-dashboard", self.authenticate())
            else:
                script = """
const statusView = document.getElementById('status');
const verifier = config.mode === 'memory' ? window.memoryVerifier : sessionStorage.getItem('pkce:' + config.state);
if (!verifier) {
  statusView.textContent = 'Tab-local state is unavailable. Continue in tab, then use Fresh sign-in.';
} else {
  fetch('/token', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({flow, verifier})})
    .then(async r => {
      if (!r.ok) throw Error(await r.text());
      sessionStorage.setItem('callback-only', 'complete');
      location.replace('/wrong-dashboard');
    }).catch(e => statusView.textContent = e.message);
}
fresh.onclick = () => location.href = '/fresh-login';
"""
                self.send(page("Finish sign-in", '<h1>Finish sign-in</h1><pre id=status>Checking tab-local state…</pre><button id=fresh>Fresh sign-in</button>', f"const config={json.dumps(config)}, flow={json.dumps(flow)};" + script))
        elif path == "/fresh-login":
            self.redirect("/wrong-dashboard", self.authenticate())
        elif path == "/wrong-dashboard":
            self.send(page("Signed in · Home", '<p class=quiet>Deliberately wrong return destination</p><h1>You are signed in</h1><p>Close Peek to return to your worksheet. The worksheet draft and position should be unchanged.</p><a href="/ordinary">Another redirect destination</a>'))
        elif path == "/ordinary-redirect":
            self.redirect("/ordinary")
        elif path == "/ordinary":
            self.send(page("Ordinary page", "<h1>Ordinary navigation</h1><p>This should open normally, without Peek.</p>"))
        elif path == "/api/data":
            authenticated = self.session() in self.server.sessions
            self.send(json.dumps({"authenticated": authenticated}), 200 if authenticated else 401, mime="application/json")
        else:
            self.send("Not found", 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 4096:
            self.send("Request too large", 413)
            return
        body = self.rfile.read(length)
        if self.path == "/expire":
            self.server.sessions.discard(self.session())
            self.send("Expired", headers={"Set-Cookie": "fixture_session=; Max-Age=0; Path=/"})
        elif self.path == "/token":
            try:
                request = json.loads(body)
                config = self.server.flows.get(request["flow"], {})
                challenge = base64.urlsafe_b64encode(hashlib.sha256(request["verifier"].encode()).digest()).decode().rstrip("=")
                valid = config and secrets.compare_digest(config.get("challenge", ""), challenge)
            except (ValueError, KeyError, TypeError, AttributeError):
                valid = False
            if valid:
                del self.server.flows[request["flow"]]
                self.send("Signed in", headers={"Set-Cookie": self.authenticate()})
            else:
                self.send("Invalid or missing PKCE verifier", 400)
        else:
            self.send("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with AuthServer(("127.0.0.1", args.port)) as server:
        print(f"Open {server.app}/ to start an authenticated deep page.", flush=True)
        print("Enable 'Sign in with Peek on this site' in the page context menu.", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
