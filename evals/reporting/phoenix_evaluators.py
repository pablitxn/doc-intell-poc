"""Store local evaluator source in Phoenix's CODE evaluator registry.

Uses the GraphQL schema shipped with Phoenix 20.11.0. The caller supplies an
authenticated httpx.Client with its base_url set to the Phoenix server root.
Registration does not attach evaluators to datasets or execute their source.
"""

import hashlib
import json
import re


_FIND_EVALUATOR = """
query FindEvaluationDefinition($name: String!, $after: String) {
  evaluators(first: 100, after: $after, filter: {col: name, value: $name}) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id name kind
      ... on CodeEvaluator {
        description sourceCode language
        inputMapping { literalMapping pathMapping }
        outputConfigs {
          __typename
          ... on FreeformAnnotationConfig {
            name optimizationDirection lowerBound upperBound threshold
          }
        }
      }
    } }
  }
}
"""

_SANDBOXES = """
query EvaluationSandboxes {
  sandboxBackends { backendType status }
  sandboxProviders {
    backendType enabled
    configs { id name language enabled }
  }
}
"""

_CREATE_SANDBOX = """
mutation CreateEvaluationSandbox($input: CreateSandboxConfigInput!) {
  createSandboxConfig(input: $input) { sandboxConfig { id } }
}
"""

_CREATE_EVALUATOR = """
mutation CreateEvaluationDefinition($input: CreateCodeEvaluatorInput!) {
  createCodeEvaluator(input: $input) { evaluator { id } }
}
"""


def _graphql(client, query, variables=None):
    response = client.post("graphql", json={"query": query, "variables": variables or {}}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        # Do not echo server diagnostics: they may contain source or headers.
        raise RuntimeError("Phoenix rejected the evaluator registry GraphQL request")
    return payload["data"]


def _sandbox_id(client):
    data = _graphql(client, _SANDBOXES)
    backend = next((item for item in data["sandboxBackends"] if item["backendType"] == "WASM"), None)
    provider = next((item for item in data["sandboxProviders"] if item["backendType"] == "WASM"), None)
    if not backend or backend["status"] != "AVAILABLE" or not provider or not provider["enabled"]:
        raise RuntimeError("Phoenix needs its bundled WASM Python sandbox enabled to register new evaluators")
    configs = provider["configs"]
    available = [config for config in configs if config["language"] == "PYTHON" and config["enabled"]]
    if available:
        return sorted(available, key=lambda config: (config["name"] != "doc-intell-python", config["name"]))[0]["id"]
    if any(config["name"] == "doc-intell-python" for config in configs):
        raise RuntimeError("Phoenix sandbox configuration doc-intell-python exists but is disabled")
    created = _graphql(client, _CREATE_SANDBOX, {"input": {
        "name": "doc-intell-python",
        "description": "Local Python runtime for document evaluator definitions.",
        "config": {"wasm": {"language": "PYTHON"}},
        "timeout": 30,
        "enabled": True,
    }})
    return created["createSandboxConfig"]["sandboxConfig"]["id"]


def _find_evaluator(client, name):
    after = None
    found = []
    while True:
        page = _graphql(client, _FIND_EVALUATOR, {"name": name, "after": after})["evaluators"]
        found.extend(edge["node"] for edge in page["edges"] if edge["node"]["name"] == name)
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
        if not cursor or cursor == after:
            raise RuntimeError("Phoenix evaluator pagination did not advance")
        after = cursor
    if len(found) > 1:
        raise ValueError("Phoenix has multiple evaluator definitions with the same versioned name")
    return found[0] if found else None


def register_evaluators(client, definitions) -> dict:
    """Register/reuse definitions and return their IDs keyed by logical name.

    Each definition contains name, description, source_code and input_mapping.
    Source must expose evaluate(...) returning one score/label/explanation dict;
    input_mapping uses Phoenix's literalMapping/pathMapping object format.
    These metrics are normalized to 0..1, with larger scores indicating success.
    """
    definitions = list(definitions)
    names = [definition["name"] for definition in definitions]
    if len(set(names)) != len(names) or any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in names):
        raise ValueError("Evaluator names must be unique lowercase identifiers")
    registered = {}
    sandbox_id = None
    for definition in definitions:
        name = definition["name"]
        output_config = {
            "name": name,
            "optimizationDirection": "MAXIMIZE",
            "lowerBound": 0,
            "upperBound": 1,
            "threshold": 1,
        }
        content = {
            "description": definition["description"],
            "sourceCode": definition["source_code"],
            "language": "PYTHON",
            "inputMapping": definition["input_mapping"],
            "outputConfigs": [{"freeform": output_config}],
        }
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        versioned_name = f"doc-intell-{name}-{fingerprint[:16]}"
        remote = _find_evaluator(client, versioned_name)
        if remote is None:
            if sandbox_id is None:
                sandbox_id = _sandbox_id(client)
            created = _graphql(client, _CREATE_EVALUATOR, {"input": {
                **content,
                "name": versioned_name,
                "sandboxConfigId": sandbox_id,
            }})
            evaluator_id = created["createCodeEvaluator"]["evaluator"]["id"]
        else:
            expected_config = {"__typename": "FreeformAnnotationConfig", **output_config}
            # Phoenix 20.11.0 persists these as AnnotationConfigType, but its
            # GraphQL resolver filters for OutputConfigType subclasses. That
            # returns [] after a database read, even for configured evaluators.
            # Compare any visible config; the versioned name still fingerprints
            # the submitted config and source/mappings remain fully verifiable.
            # See CodeEvaluator in the release's db/models.py and
            # server/api/types/Evaluator.py.
            output_configs_match = remote.get("outputConfigs") in ([], [expected_config])
            if (remote["kind"] != "CODE"
                    or any(remote.get(key) != content[key] for key in ("description", "sourceCode", "language", "inputMapping"))
                    or not output_configs_match):
                raise ValueError("Phoenix evaluator content differs from its local versioned definition")
            evaluator_id = remote["id"]
        registered[name] = {
            "id": evaluator_id,
            "name": versioned_name,
            "source_sha256": hashlib.sha256(definition["source_code"].encode()).hexdigest(),
        }
    return registered
