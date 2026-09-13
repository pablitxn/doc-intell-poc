"""Harmless worker probe: assigned files, installed tools and optional transport.

This is executed as Python code by diagnostics, never as a model prompt.
Provider probes perform a TLS handshake only, without an API request or login.
"""

import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request


def probe(config):
    checks = {
        'documents_readable': all(
            Path('/workspace/' + doc['path']).is_file()
            and hashlib.sha256(Path('/workspace/' + doc['path']).read_bytes()).hexdigest() == doc['sha256']
            for doc in config['documents']),
        'references_hidden': not Path('/workspace/ground_truth').exists(),
        'pdf_tools': bool(shutil.which('pdftotext') or importlib.util.find_spec('pypdf')),
    }
    network = []
    if config['network']:
        for host in config['hosts']:
            passed, issue = False, 'connection_failed'
            for attempt in range(3):
                connection = http.client.HTTPSConnection(
                    'egress', 8080, timeout=5, context=ssl.create_default_context())
                connection.set_tunnel(host, 443)
                try:
                    connection.connect()
                    passed, issue = True, None
                    break
                except ssl.SSLCertVerificationError:
                    issue = 'certificate_verification_failed'
                    break
                except (OSError, http.client.HTTPException):
                    time.sleep(0.15)
                finally:
                    connection.close()
            network.append({'host': host, 'tls_route': passed, 'issue': issue})
        checks['provider_tls_routes'] = all(row['tls_route'] for row in network)
        checks['phoenix_otlp_transport'] = False
        # Valid protobuf with zero spans: verify routing without adding records.
        request = urllib.request.Request(
            'http://egress:8080/v1/traces', data=b'\x0a\x00', method='POST',
            headers={'Content-Type': 'application/x-protobuf'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(3):
            try:
                with opener.open(request, timeout=10) as response:
                    checks['phoenix_otlp_transport'] = response.status == 200
                    response.read()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.15)
    return {'checks': checks, 'network': network, 'python': sys.version.split()[0]}


if __name__ == '__main__':
    print(json.dumps(probe(json.loads(sys.stdin.read()))))
