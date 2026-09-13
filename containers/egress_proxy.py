"""Small CONNECT allowlist for benchmark workers; no request bodies are logged."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import selectors
import socket
from urllib.parse import urlsplit

ALLOWED = frozenset(os.environ.get('EVAL_ALLOWED_HOSTS', 'chatgpt.com,api.openai.com,auth.openai.com').split(','))
MAX_BODY = 16 * 1024 * 1024
PHOENIX = urlsplit(os.environ.get('EVAL_PHOENIX_ENDPOINT', 'http://host.docker.internal:6006/v1/traces'))


class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        try:
            host, port = self.path.rsplit(':', 1)
            if host.lower() not in ALLOWED or port != '443':
                self.send_error(403, 'Destination not allowed')
                return
            upstream = socket.create_connection((host, 443), timeout=20)
        except (ValueError, OSError):
            self.send_error(502, 'Connection failed')
            return
        with upstream, selectors.DefaultSelector() as selector:
            self.send_response(200, 'Connection established')
            self.end_headers()
            self.wfile.flush()
            selector.register(self.connection, selectors.EVENT_READ, upstream)
            selector.register(upstream, selectors.EVENT_READ, self.connection)
            try:
                while True:
                    ready = selector.select(timeout=180)
                    if not ready:
                        return
                    for key, _ in ready:
                        data = key.fileobj.recv(65536)
                        if not data:
                            return
                        key.data.sendall(data)
            except OSError:
                return

    def do_POST(self):
        # Native corporate exporters can write spans, but cannot query Phoenix.
        target = urlsplit(self.path)
        if target.path != '/v1/traces' or target.query or target.fragment:
            self.send_error(403, 'Only trace ingestion is allowed')
            return
        if self.headers.get('Transfer-Encoding'):
            self.send_error(411, 'Content-Length required')
            return
        encodings = self.headers.get_all('Content-Encoding', [])
        encoding = encodings[0].strip().lower() if len(encodings) == 1 else ''
        if encodings and (len(encodings) != 1 or encoding not in {'identity', 'gzip'}):
            # Never reflect an untrusted header or request body in the error.
            self.send_error(415, 'Unsupported trace content encoding')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                raise ValueError
        except ValueError:
            self.send_error(413, 'Invalid body length')
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self.send_error(400, 'Incomplete trace body')
            return
        headers = {'Content-Type': self.headers.get('Content-Type', 'application/x-protobuf')}
        if encoding:
            # Forward bytes unchanged: Phoenix must see the encoding that its
            # OTLP receiver needs to decode the compressed protobuf correctly.
            headers['Content-Encoding'] = encoding
        token = os.environ.get('PHOENIX_API_KEY')
        if token:
            headers['Authorization'] = f'Bearer {token}'
        constructor = http.client.HTTPSConnection if PHOENIX.scheme == 'https' else http.client.HTTPConnection
        connection = constructor(PHOENIX.hostname, PHOENIX.port, timeout=30)
        try:
            connection.request('POST', '/v1/traces', body=body, headers=headers)
            response = connection.getresponse()
            content = response.read(MAX_BODY)
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'application/x-protobuf'))
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (OSError, http.client.HTTPException):
            self.send_error(502, 'Trace ingestion unavailable')
        finally:
            connection.close()

    def do_GET(self):
        self.send_error(403, 'Read access is disabled')


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Proxy).serve_forever()
