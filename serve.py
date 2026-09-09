#!/usr/bin/env python3
"""Serve the web app on your local network so your phone can open it.

    python3 serve.py

Binds to every interface so an iPhone on the same wifi can reach it. Nothing
here is exposed to the internet.
"""

import argparse
import http.server
import os
import socket
import socketserver

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(ROOT, "web")
DATA_DIR = os.path.join(ROOT, "data")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def translate_path(self, path):
        # The single dynamic route: the generated report lives outside web/.
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean == "/api/report.json":
            return os.path.join(DATA_DIR, "report.json")
        return super().translate_path(path)

    def end_headers(self):
        # The report changes daily and iOS caches aggressively.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # Quiet: the terminal is for the startup banner only.


def lan_ip():
    """Best guess at this Mac's address on the local network."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # No packets sent; just picks the route.
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", args.port), Handler) as httpd:
        print("Fantasy Game Day is running.\n")
        print("  On this Mac:   http://localhost:%d" % args.port)
        print("  On your phone: http://%s:%d" % (lan_ip(), args.port))
        print("\n(Your phone must be on the same wifi. Press Control-C to stop.)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
