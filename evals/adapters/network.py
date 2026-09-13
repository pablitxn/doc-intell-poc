"""An internal worker network with allowlisted TLS egress and write-only OTLP."""

from contextlib import contextmanager
import os
import subprocess
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit


def trace_endpoint(phoenix_url: str) -> str:
    """Translate the runner's Phoenix origin into the sidecar's network view."""
    target = urlsplit(phoenix_url)
    if (target.scheme not in {'http', 'https'} or not target.hostname or
            target.username or target.password or target.query or target.fragment or
            target.path not in {'', '/'}):
        raise ValueError('Phoenix URL must be an HTTP(S) origin without credentials or a path prefix')
    host = target.hostname
    if host in {'localhost', '127.0.0.1', '::1'}:
        host = 'host.docker.internal'
    elif ':' in host:
        host = f'[{host}]'
    port = target.port
    return urlunsplit((target.scheme, host + (f':{port}' if port else ''), '/v1/traces', '', ''))


def _docker(args):
    result = subprocess.run(['docker', *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45)
    if result.returncode:
        raise ValueError('Could not prepare the restricted Docker network')
    return result.stdout.decode().strip()


@contextmanager
def restricted_network(image: str, allowed_hosts=None, *, phoenix_url='http://127.0.0.1:6006'):
    suffix = uuid4().hex[:12]
    network, proxy = f'doc-intell-net-{suffix}', f'doc-intell-egress-{suffix}'
    hosts = allowed_hosts or ['chatgpt.com', 'api.openai.com', 'auth.openai.com']
    endpoint = trace_endpoint(phoenix_url)
    if any(not isinstance(host, str) or not host or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in host) for host in hosts):
        raise ValueError('Egress hosts must be explicit lowercase DNS hostnames')
    created = False
    try:
        _docker(['network', 'create', '--internal', network])
        created = True
        arguments = ['run', '-d', '--rm', '--name', proxy, '--network', 'bridge',
                     '--add-host', 'host.docker.internal:host-gateway',
                     '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                     '--user', '65534:65534', '--env', 'EVAL_ALLOWED_HOSTS=' + ','.join(hosts),
                     '--env', 'EVAL_PHOENIX_ENDPOINT=' + endpoint]
        if os.environ.get('PHOENIX_API_KEY'):
            arguments.extend(['--env', 'PHOENIX_API_KEY'])
        arguments.extend(['--entrypoint', 'python', image, '/opt/doc-intell/egress_proxy.py'])
        _docker(arguments)
        _docker(['network', 'connect', '--alias', 'egress', network, proxy])
        yield {'network': network, 'proxy_url': 'http://egress:8080'}
    finally:
        # Every context owns its own resources; no broad cleanup commands.
        try:
            subprocess.run(['docker', 'rm', '-f', proxy], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        finally:
            if created:
                subprocess.run(['docker', 'network', 'rm', network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
