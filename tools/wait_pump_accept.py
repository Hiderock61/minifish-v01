"""Synthetic localhost reproduction only. No real-site or credential access."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from playwright.sync_api import sync_playwright

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><body>local test</body></html>")
    def log_message(self, *args):
        pass

server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
        context=browser.new_context(service_workers="block")
        page=context.new_page()
        base="http://127.0.0.1:"+str(server.server_port)
        observed=[]
        def route(request):
            if request.request.url.startswith(base+"/"):
                observed.append(1)
                request.continue_()
            else:
                request.abort()
        context.route("**/*",route)
        page.goto(base+"/start")
        observed.clear()
        page.evaluate("url => setTimeout(() => location.href=url, 50)",base+"/next")
        Event().wait(.4)
        starved=not observed
        page.wait_for_timeout(800)
        pumped=bool(observed) and page.url==base+"/next"
        browser.close()
        print("EVENT_WAIT_STARVES_ROUTE_CALLBACKS" if starved else "HOLD_NO_STARVATION")
        print("PLAYWRIGHT_WAIT_DISPATCHES_ROUTE_PASS" if pumped else "HOLD_NO_DISPATCH")
        assert starved and pumped
finally:
    server.shutdown()
