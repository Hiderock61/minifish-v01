"""LOCAL-ONLY fake sign-in website. Never collects passwords."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockSite(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/account":
            authorized = "demo_session=ok" in self.headers.get("Cookie", "")
            if not authorized:
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            html = "<title>MiniFish Demo Account</title><h1 id='signed-in-user'>Demo Member</h1><p>Authentication OK</p>"
        elif self.path == "/login":
            html = "<title>MiniFish Demo Login</title><h1>Login demo</h1><form action='/login' method='POST'><button>Sign in (no password)</button></form>"
        else:
            html = "<title>MiniFish Demo</title><a href='/account'>My account</a>"
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/login":
            self.send_error(404)
            return
        self.send_response(303)
        self.send_header("Set-Cookie", "demo_session=ok; HttpOnly; SameSite=Lax; Path=/")
        self.send_header("Location", "/account")
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Local-only mock site running at http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), MockSite).serve_forever()
