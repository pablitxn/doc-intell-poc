# Test-only derivative. The test creates a three-file build context so no
# documents, expected answers, host settings, or credentials enter its layers.
ARG HARNESS_IMAGE=doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0
FROM ${HARNESS_IMAGE}
RUN pip install --no-cache-dir "opentelemetry-sdk==1.44.0" "opentelemetry-exporter-otlp-proto-http==1.44.0"
COPY corporate_otel.py /opt/doc-intell/corporate_otel.py
COPY egress_proxy.py /opt/doc-intell/egress_proxy.py
