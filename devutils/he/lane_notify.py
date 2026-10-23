"""Outside-client OAuth and T3 MCP transport for the build lane watcher.

No agent-session credentials are read. Login requires explicit T3 approval.
Credentials belong outside source control and are written with mode 0600.
"""

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid
import webbrowser


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("unexpected transport redirect")


def validate_endpoint(url):
    parts = urlsplit(url)
    if (parts.username or parts.password or parts.fragment or parts.query
            or not parts.hostname or (parts.scheme != "https" and not
            (parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}))):
        raise ValueError("use an HTTPS MCP URL or HTTP loopback URL")
    return f"{parts.scheme}://{parts.netloc}"


def request(url, value=None, *, headers=None, form=False):
    headers = dict(headers or {})
    data = None
    if value is not None:
        data = (urlencode(value) if form else json.dumps(value)).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    with build_opener(NoRedirect).open(Request(url, data=data, headers=headers), timeout=15) as response:
        body = response.read(4 * 1024 * 1024).decode()
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            messages = []
            for block in body.replace("\r\n", "\n").split("\n\n"):
                payload = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
                if payload:
                    messages.append(json.loads(payload))
            candidates = [m for m in messages if "result" in m or "error" in m]
            value = candidates[-1] if candidates else None
        else:
            value = json.loads(body) if body else None
        return value, dict(response.headers)


def save_credentials(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".lane-login-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def login(endpoint, path):
    if path.exists():
        raise ValueError("credential file exists; pause watcher and reconcile pending sends before reauthorization")
    origin = validate_endpoint(endpoint)
    metadata, _ = request(origin + "/.well-known/oauth-authorization-server")
    for key in ("authorization_endpoint", "registration_endpoint", "token_endpoint"):
        if validate_endpoint(metadata[key]) != origin:
            raise ValueError("OAuth endpoints must belong to the chosen T3 environment")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    returned = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Authorization codes must not appear in logs.

        def do_GET(self):
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            if (url.path != "/callback" or params.get("state") != [state]
                    or params.get("iss") != [origin] or not params.get("code")):
                self.send_error(400, "Invalid authorization callback")
                return
            returned["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Build lane watcher sign-in received. You can close this page.")

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        client, _ = request(metadata["registration_endpoint"], {
            "client_name": "Arcium build lane watcher", "redirect_uris": [redirect],
            "grant_types": ["authorization_code"], "response_types": ["code"], "token_endpoint_auth_method": "none"})
        authorization = metadata["authorization_endpoint"] + "?" + urlencode({
            "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect,
            "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": endpoint})
        print("Approve Arcium build lane watcher in T3 with a permission ceiling matching the target threads.", flush=True)
        print(authorization, flush=True)
        webbrowser.open(authorization)
        deadline = time.monotonic() + 600
        while not returned and time.monotonic() < deadline:
            server.handle_request()
        if not returned:
            raise TimeoutError("T3 sign-in was not completed")
        token, _ = request(metadata["token_endpoint"], {
            "grant_type": "authorization_code", "client_id": client["client_id"],
            "redirect_uri": redirect, "code": returned["code"], "code_verifier": verifier,
            "resource": endpoint}, form=True)
    credential = {"endpoint": endpoint, "access_token": token["access_token"],
                  "expires": time.time() + token["expires_in"], "identity": uuid.uuid4().hex}
    save_credentials(path, credential)
    print(json.dumps({"credentials": str(path), "identity": credential["identity"], "expires": credential["expires"]}))


def credentials(path):
    if path.stat().st_mode & 0o077:
        raise ValueError("credential file must be private, chmod 600")
    value = json.loads(path.read_text())
    validate_endpoint(value["endpoint"])
    if value["expires"] <= time.time():
        raise ValueError("watcher sign-in expired; pause and reconcile pending sends before reauthorization")
    return value


def call(credential, method, arguments):
    headers = {"Authorization": "Bearer " + credential["access_token"],
               "Accept": "application/json, text/event-stream"}
    endpoint = credential["endpoint"]
    def rpc(payload):
        value, received = request(endpoint, payload, headers=headers)
        for key, val in received.items():
            if key.lower() == "mcp-session-id":
                headers["Mcp-Session-Id"] = val
        if value and "error" in value:
            raise RuntimeError("T3 MCP request failed")
        return value
    initialized = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "arcium-build-lane", "version": "1"}}})
    headers["MCP-Protocol-Version"] = initialized["result"]["protocolVersion"]
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
    reply = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": method, "arguments": arguments}})
    result = reply["result"]
    if result.get("isError"):
        raise RuntimeError("T3 tool rejected the request")
    structured = result.get("structuredContent")
    if structured is None:
        structured = json.loads(next(c["text"] for c in result["content"] if c["type"] == "text"))
    return structured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--login", metavar="MCP_URL")
    parser.add_argument("--identity", action="store_true")
    args = parser.parse_args()
    try:
        if args.login:
            login(args.login, args.credentials)
        else:
            credential = credentials(args.credentials)
            if args.identity:
                print(json.dumps({"identity": credential["identity"]}))
            else:
                payload = json.load(sys.stdin)
                expected = payload.pop("expectedIdentity", None)
                if expected is not None and expected != credential["identity"]:
                    raise ValueError("notifier identity changed; reconcile uncertain sends before retrying")
                if not payload.get("clientRequestId"):
                    raise ValueError("a stable clientRequestId is required")
                result = call(credential, "t3_thread_send", payload)
                print(json.dumps({"messageId": result["messageId"]}))
        return 0
    except Exception as exc:
        print(f"lane notifier failed: {type(exc).__name__}; check sign-in, permissions, and connectivity", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
