"""Verify evaluator registration independently of harness execution."""

from copy import deepcopy
import unittest

from evals.reporting.phoenix_evaluators import register_evaluators


def definitions():
    return [{
        "name": name,
        "description": f"Definition of {name}",
        "source_code": "def evaluate(output, reference, metadata):\n    return {'score': 1.0}\n",
        "input_mapping": {
            "literalMapping": {},
            "pathMapping": {"output": "output", "reference": "reference", "metadata": "metadata"},
        },
    } for name in ("schema_valid", "value_accuracy", "evidence_accuracy", "task_pass", "execution_status")]


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class PhoenixRegistry:
    """In-memory server records at the HTTP client's public post boundary."""

    def __init__(self):
        self.records = []
        self.configs = []
        self.calls = []
        self.enabled = True
        self.error = None
        self.paginated = False
        self.persisted_configs_hidden = False

    def post(self, path, *, json, timeout):
        assert path == "graphql"
        assert timeout == 60
        query, variables = json["query"], json["variables"]
        self.calls.append(deepcopy(json))
        if self.error:
            return Response({"errors": [{"message": self.error}]})
        if "FindEvaluationDefinition" in query:
            nodes = [deepcopy(node) for node in self.records if node["name"] == variables["name"]]
            if self.persisted_configs_hidden:
                for node in nodes:
                    node["outputConfigs"] = []
            has_next = self.paginated and variables["after"] is None
            return Response({"data": {"evaluators": {
                "edges": [] if has_next else [{"node": deepcopy(node)} for node in nodes],
                "pageInfo": {"hasNextPage": has_next, "endCursor": "page-2" if has_next else None},
            }}})
        if "EvaluationSandboxes" in query:
            return Response({"data": {
                "sandboxBackends": [{"backendType": "WASM", "status": "AVAILABLE"}],
                "sandboxProviders": [{"backendType": "WASM", "enabled": self.enabled, "configs": self.configs}],
            }})
        if "CreateEvaluationSandbox" in query:
            data = variables["input"]
            assert data["config"] == {"wasm": {"language": "PYTHON"}}
            self.configs.append({"id": "sandbox-1", "name": data["name"], "language": "PYTHON", "enabled": data["enabled"]})
            return Response({"data": {"createSandboxConfig": {"sandboxConfig": {"id": "sandbox-1"}}}})
        if "CreateEvaluationDefinition" in query:
            data = deepcopy(variables["input"])
            assert data.pop("sandboxConfigId") in {config["id"] for config in self.configs}
            node = {**data, "kind": "CODE", "id": f"evaluator-{len(self.records) + 1}"}
            node["outputConfigs"] = [{"__typename": "FreeformAnnotationConfig", **data["outputConfigs"][0]["freeform"]}]
            self.records.append(node)
            return Response({"data": {"createCodeEvaluator": {"evaluator": {"id": node["id"]}}}})
        raise AssertionError("Unexpected API operation: attaching or executing is outside registration")


class PhoenixEvaluatorTests(unittest.TestCase):
    def test_registers_five_code_definitions_with_one_local_sandbox(self):
        client = PhoenixRegistry()
        result = register_evaluators(client, definitions())
        self.assertEqual(len(result), 5)
        self.assertEqual(len(client.configs), 1)
        self.assertEqual(len(client.records), 5)
        for definition, node in zip(definitions(), client.records):
            self.assertEqual(node["sourceCode"], definition["source_code"])
            self.assertEqual(node["inputMapping"], definition["input_mapping"])
            self.assertEqual(node["outputConfigs"][0]["name"], definition["name"])
            self.assertEqual(result[definition["name"]]["id"], node["id"])
            self.assertEqual(len(result[definition["name"]]["source_sha256"]), 64)

    def test_repeated_registration_reuses_records_without_mutations_or_runtime_access(self):
        client = PhoenixRegistry()
        first = register_evaluators(client, definitions())
        client.calls.clear()
        client.enabled = False
        second = register_evaluators(client, definitions())
        self.assertEqual(first, second)
        self.assertTrue(all("FindEvaluationDefinition" in call["query"] for call in client.calls))

    def test_reuses_available_python_wasm_config(self):
        client = PhoenixRegistry()
        client.configs.append({"id": "default-python", "name": "default", "language": "PYTHON", "enabled": True})
        register_evaluators(client, definitions())
        self.assertEqual(len(client.configs), 1)
        creates = [call for call in client.calls if "CreateEvaluationDefinition" in call["query"]]
        self.assertTrue(all(call["variables"]["input"]["sandboxConfigId"] == "default-python" for call in creates))

    def test_source_changes_get_new_names_preserving_original_definitions(self):
        client = PhoenixRegistry()
        original = definitions()[:1]
        first = register_evaluators(client, original)
        changed = deepcopy(original)
        changed[0]["source_code"] = changed[0]["source_code"].replace("1.0", "0.0")
        second = register_evaluators(client, changed)
        self.assertNotEqual(first["schema_valid"]["id"], second["schema_valid"]["id"])
        self.assertEqual(client.records[0]["sourceCode"], original[0]["source_code"])
        self.assertEqual(len(client.records), 2)

    def test_refuses_remote_edits_instead_of_overwriting_them(self):
        for field, replacement in (
            ("sourceCode", "changed code"),
            ("inputMapping", {}),
            ("outputConfigs", [{"__typename": "FreeformAnnotationConfig", "name": "different"}]),
        ):
            with self.subTest(field=field):
                client = PhoenixRegistry()
                register_evaluators(client, definitions()[:1])
                client.records[0][field] = replacement
                with self.assertRaisesRegex(ValueError, "content differs"):
                    register_evaluators(client, definitions()[:1])
                self.assertEqual(len(client.records), 1)

    def test_reuses_persisted_definitions_with_phoenix_20_11_hidden_output_configs(self):
        client = PhoenixRegistry()
        first = register_evaluators(client, definitions())
        client.calls.clear()
        # In 20.11.0 storage reloads AnnotationConfigType objects, while the
        # GraphQL resolver only exposes OutputConfigType subclasses: [] results.
        client.persisted_configs_hidden = True
        self.assertEqual(register_evaluators(client, definitions()), first)
        self.assertEqual(len(client.records), 5)
        self.assertTrue(all("FindEvaluationDefinition" in call["query"] for call in client.calls))

    def test_follows_pagination_when_looking_up_an_existing_definition(self):
        client = PhoenixRegistry()
        first = register_evaluators(client, definitions()[:1])
        client.paginated = True
        self.assertEqual(register_evaluators(client, definitions()[:1]), first)
        self.assertEqual(len(client.records), 1)

    def test_disabled_provider_is_not_reenabled(self):
        client = PhoenixRegistry()
        client.enabled = False
        with self.assertRaisesRegex(RuntimeError, "WASM Python sandbox enabled"):
            register_evaluators(client, definitions())
        self.assertEqual(client.configs, [])
        self.assertEqual(client.records, [])

    def test_graphql_failure_does_not_expose_server_diagnostics(self):
        client = PhoenixRegistry()
        client.error = "secret headers and source echoed by a server"
        with self.assertRaisesRegex(RuntimeError, "GraphQL request") as error:
            register_evaluators(client, definitions())
        self.assertNotIn(client.error, str(error.exception))

    def test_duplicate_definitions_are_rejected_before_network_access(self):
        client = PhoenixRegistry()
        same = definitions()[0]
        with self.assertRaisesRegex(ValueError, "unique"):
            register_evaluators(client, [same, same])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
