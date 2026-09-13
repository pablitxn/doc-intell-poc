"""No live sockets or Docker engine are used by these egress boundary tests."""

from email.message import Message
import gzip
import importlib.util
import io
import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from evals.runtime.network import restricted_network, trace_endpoint
from tests.support.paths import ROOT


def load_proxy_module():
    path = ROOT / "containers/egress_proxy.py"
    spec = importlib.util.spec_from_file_location("test_egress_proxy_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proxy_module = load_proxy_module()


def handler(path, body=b"protobuf-trace", headers=None):
    instance = object.__new__(proxy_module.Proxy)
    instance.path = path
    instance.headers = Message()
    for key, value in (headers or {}).items():
        instance.headers[key] = value
    instance.rfile = io.BytesIO(body)
    instance.wfile = io.BytesIO()
    instance.connection = MagicMock()
    for method in ("send_error", "send_response", "send_header", "end_headers"):
        setattr(instance, method, MagicMock())
    return instance


class ProxyBoundaryTests(unittest.TestCase):
    def test_connect_rejects_local_private_ip_and_unknown_hosts_before_opening_socket(self):
        destinations = (
            "localhost:443", "127.0.0.1:443", "10.0.0.1:443", "169.254.169.254:443",
            "[::1]:443", "host.docker.internal:443", "unlisted.example:443",
            "chatgpt.com.evil.example:443", "chatgpt.com.:443",
        )
        with patch.object(proxy_module.socket, "create_connection") as connect:
            for destination in destinations:
                with self.subTest(destination=destination):
                    request = handler(destination)
                    request.do_CONNECT()
                    request.send_error.assert_called_once()
                    self.assertEqual(request.send_error.call_args.args[0], 403)
            connect.assert_not_called()

    def test_connect_allows_only_tls_port_443(self):
        with patch.object(proxy_module.socket, "create_connection") as connect:
            for destination in ("chatgpt.com:80", "chatgpt.com:6006", "chatgpt.com:0443", "chatgpt.com"):
                request = handler(destination)
                request.do_CONNECT()
                request.send_error.assert_called_once()
            connect.assert_not_called()

    def test_connect_opens_only_the_explicitly_allowed_tls_destination(self):
        with patch.object(proxy_module.socket, "create_connection") as connect, \
             patch.object(proxy_module.selectors, "DefaultSelector") as selector:
            selector.return_value.__enter__.return_value.select.return_value = []
            request = handler("chatgpt.com:443")
            request.do_CONNECT()
        connect.assert_called_once_with(("chatgpt.com", 443), timeout=20)
        request.send_response.assert_called_once_with(200, "Connection established")
        request.send_error.assert_not_called()

    def test_get_cannot_query_phoenix_or_forward_arbitrary_urls(self):
        with patch.object(proxy_module.http.client, "HTTPConnection") as connection, \
             patch.object(proxy_module.socket, "create_connection") as connect:
            for path in ("/", "/v1/datasets", "/graphql", "http://host.docker.internal:6006/v1/datasets"):
                request = handler(path)
                request.do_GET()
                request.send_error.assert_called_once_with(403, "Read access is disabled")
            connection.assert_not_called()
            connect.assert_not_called()

    def test_post_denies_query_traversal_and_every_non_ingestion_path(self):
        paths = (
            "/graphql", "/v1/datasets", "/v1/traces?query=all", "/v1/traces#fragment",
            "/v1/../graphql", "/v1/traces/../datasets", "/v1/%2e%2e/graphql",
            "/v1/traces/", "/v1/%74races",
        )
        with patch.object(proxy_module.http.client, "HTTPConnection") as connection:
            for path in paths:
                with self.subTest(path=path):
                    request = handler(path, headers={"Content-Length": "14"})
                    request.do_POST()
                    request.send_error.assert_called_once_with(403, "Only trace ingestion is allowed")
            connection.assert_not_called()

    def test_trace_post_has_fixed_destination_and_does_not_forward_worker_authorization(self):
        body = b"protobuf-trace"
        request = handler("/v1/traces", body=body, headers={
            "Content-Length": str(len(body)), "Content-Type": "application/x-protobuf",
            "Authorization": "Bearer worker-supplied-secret", "Host": "attacker.example",
        })
        with patch.dict(os.environ, {"PHOENIX_API_KEY": "proxy-private-secret"}), \
             patch.object(proxy_module.http.client, "HTTPConnection") as constructor:
            connection = constructor.return_value
            response = connection.getresponse.return_value
            response.status = 200
            response.read.return_value = b"accepted"
            response.getheader.return_value = "application/x-protobuf"
            request.do_POST()
        constructor.assert_called_once_with("host.docker.internal", 6006, timeout=30)
        connection.request.assert_called_once_with("POST", "/v1/traces", body=body, headers={
            "Content-Type": "application/x-protobuf", "Authorization": "Bearer proxy-private-secret",
        })
        connection.close.assert_called_once()
        self.assertEqual(request.wfile.getvalue(), b"accepted")
        self.assertNotIn(b"secret", request.wfile.getvalue())

    def test_trace_post_rejects_missing_oversized_and_chunked_bodies_before_upstream(self):
        with patch.object(proxy_module.http.client, "HTTPConnection") as connection:
            for headers in ({}, {"Content-Length": "-1"}, {"Content-Length": "not-a-number"},
                            {"Content-Length": str(proxy_module.MAX_BODY + 1)},
                            {"Content-Length": "1", "Transfer-Encoding": "chunked"}):
                request = handler("/v1/traces", headers=headers)
                request.do_POST()
                request.send_error.assert_called_once()
            connection.assert_not_called()

    def test_trace_post_preserves_gzip_and_identity_without_decoding_body(self):
        for encoding, body in (("gzip", gzip.compress(b"protobuf-trace")),
                               ("identity", b"protobuf-trace")):
            with self.subTest(encoding=encoding):
                request = handler("/v1/traces", body=body, headers={
                    "Content-Length": str(len(body)), "Content-Encoding": encoding,
                })
                with patch.object(proxy_module.http.client, "HTTPConnection") as constructor:
                    response = constructor.return_value.getresponse.return_value
                    response.status = 200
                    response.read.return_value = b"accepted"
                    response.getheader.return_value = "application/x-protobuf"
                    request.do_POST()
                sent = constructor.return_value.request.call_args.kwargs
                self.assertEqual(sent["body"], body)
                self.assertEqual(sent["headers"]["Content-Encoding"], encoding)

    def test_trace_post_rejects_unknown_or_multiple_encodings_without_reflection(self):
        for encoding in ("br", "deflate", "gzip, identity", "sensitive-sentinel", ""):
            with self.subTest(encoding=encoding):
                request = handler("/v1/traces", headers={
                    "Content-Length": "14", "Content-Encoding": encoding,
                })
                with patch.object(proxy_module.http.client, "HTTPConnection") as constructor:
                    request.do_POST()
                constructor.assert_not_called()
                request.send_error.assert_called_once_with(415, "Unsupported trace content encoding")
                self.assertNotIn("sensitive-sentinel", repr(request.send_error.call_args))
        request = handler("/v1/traces", headers={"Content-Length": "14", "Content-Encoding": "gzip"})
        request.headers["Content-Encoding"] = "identity"
        with patch.object(proxy_module.http.client, "HTTPConnection") as constructor:
            request.do_POST()
        constructor.assert_not_called()
        request.send_error.assert_called_once_with(415, "Unsupported trace content encoding")

    def test_trace_post_rejects_incomplete_body_before_upstream(self):
        request = handler("/v1/traces", body=b"short", headers={"Content-Length": "14"})
        with patch.object(proxy_module.http.client, "HTTPConnection") as constructor:
            request.do_POST()
        constructor.assert_not_called()
        request.send_error.assert_called_once_with(400, "Incomplete trace body")

    def test_trace_post_respects_configured_https_origin_and_port(self):
        body = b"protobuf-trace"
        request = handler("/v1/traces", body=body, headers={"Content-Length": str(len(body))})
        with patch.object(proxy_module, "PHOENIX", urlsplit("https://phoenix.corp.example:8443/v1/traces")), \
             patch.object(proxy_module.http.client, "HTTPSConnection") as https, \
             patch.object(proxy_module.http.client, "HTTPConnection") as http:
            response = https.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b"accepted"
            response.getheader.return_value = "application/x-protobuf"
            request.do_POST()
        https.assert_called_once_with("phoenix.corp.example", 8443, timeout=30)
        http.assert_not_called()
        self.assertEqual(https.return_value.request.call_args.args[:2], ("POST", "/v1/traces"))
        self.assertEqual(request.wfile.getvalue(), b"accepted")


class RestrictedNetworkTests(unittest.TestCase):
    def test_trace_endpoint_preserves_remote_origins_and_maps_custom_local_ports(self):
        cases = {
            "http://localhost:7007": "http://host.docker.internal:7007/v1/traces",
            "http://127.0.0.1:8008/": "http://host.docker.internal:8008/v1/traces",
            "http://[::1]:9009": "http://host.docker.internal:9009/v1/traces",
            "https://phoenix.corp.example:8443/": "https://phoenix.corp.example:8443/v1/traces",
            "https://phoenix.corp.example": "https://phoenix.corp.example/v1/traces",
            "https://[2001:db8::1]:8443": "https://[2001:db8::1]:8443/v1/traces",
        }
        for origin, expected in cases.items():
            with self.subTest(origin=origin):
                self.assertEqual(trace_endpoint(origin), expected)

    def test_credentialed_and_unsupported_urls_fail_before_docker_without_echoing_secrets(self):
        urls = (
            "https://user:secret-sentinel@phoenix.corp.example",
            "https://secret-sentinel@phoenix.corp.example",
            "https://phoenix.corp.example?token=secret-sentinel",
            "https://phoenix.corp.example#secret-sentinel",
            "https://phoenix.corp.example/api", "file:///tmp/phoenix", "ftp://phoenix.corp.example",
        )
        with patch("evals.runtime.network.subprocess.run") as run:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError) as raised:
                    with restricted_network("test-image", phoenix_url=url):
                        self.fail("Unsupported Phoenix URL was accepted")
                self.assertNotIn("secret-sentinel", str(raised.exception))
            run.assert_not_called()

    def test_custom_phoenix_origin_is_passed_to_sidecar_with_actual_port(self):
        result = subprocess.CompletedProcess(["docker"], 0, b"created", b"")
        with patch("evals.runtime.network.subprocess.run", return_value=result) as run:
            with restricted_network("test-image", phoenix_url="http://localhost:7007"):
                pass
        launch = next(call.args[0] for call in run.call_args_list if call.args[0][1:3] == ["run", "-d"])
        self.assertIn("EVAL_PHOENIX_ENDPOINT=http://host.docker.internal:7007/v1/traces", launch)
        self.assertNotIn("EVAL_PHOENIX_ENDPOINT=http://host.docker.internal:6006/v1/traces", launch)

    def test_cleanup_removes_only_owned_proxy_and_network_after_startup_failure(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            result = 1 if argv[1:3] == ["network", "connect"] else 0
            return subprocess.CompletedProcess(argv, result, b"created", b"")

        with patch("evals.runtime.network.subprocess.run", side_effect=run):
            with self.assertRaises(ValueError):
                with restricted_network("test-image"):
                    self.fail("Startup failure must not yield a worker network")
        create = next(argv for argv in calls if argv[1:3] == ["network", "create"])
        launch = next(argv for argv in calls if argv[1:3] == ["run", "-d"])
        proxy_name = launch[launch.index("--name") + 1]
        self.assertEqual(calls[-2], ["docker", "rm", "-f", proxy_name])
        self.assertEqual(calls[-1], ["docker", "network", "rm", create[-1]])
        self.assertIn("--internal", create)
        self.assertNotIn("prune", repr(calls))

    def test_proxy_credential_is_inherited_by_name_and_never_serialized_in_argv(self):
        result = subprocess.CompletedProcess(["docker"], 0, b"created", b"")
        with patch.dict(os.environ, {"PHOENIX_API_KEY": "phoenix-sensitive-token"}), \
             patch("evals.runtime.network.subprocess.run", return_value=result) as run:
            with restricted_network("test-image") as metadata:
                self.assertEqual(metadata["proxy_url"], "http://egress:8080")
                self.assertNotIn("phoenix-sensitive-token", repr(metadata))
        calls = [call.args[0] for call in run.call_args_list]
        launch = next(argv for argv in calls if argv[1:3] == ["run", "-d"])
        self.assertIn("PHOENIX_API_KEY", launch)
        self.assertNotIn("phoenix-sensitive-token", repr(calls))
        self.assertEqual(calls[-2][1:3], ["rm", "-f"])
        self.assertEqual(calls[-1][1:3], ["network", "rm"])


if __name__ == "__main__":
    unittest.main()
