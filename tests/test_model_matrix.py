"""Model/harness selection must preserve exact requested IDs and effort."""

import argparse
from contextlib import redirect_stderr
from io import StringIO
import unittest
from unittest.mock import patch

from evals.cli import add_execution_options, native_adapters, validate_execution_options


def parse(arguments):
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    add_execution_options(parser, source)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args(arguments)
    validate_execution_options(parser, args)
    return args


class ModelMatrixTests(unittest.TestCase):
    def test_all_nine_combinations_preserve_model_and_medium(self):
        models = ['gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra']
        args = parse(['--harness', 'all', '--models', *models, '--thinking', 'medium'])
        with patch('evals.adapters.runtime.preflight', side_effect=lambda profile, **kw: dict(profile)) as preflight, \
             patch('evals.adapters.runtime.make_preparer'):
            prepared = native_adapters(args)
        self.assertEqual([(name, meta['model']) for name, _, meta in prepared],
                         [(name, model) for model in models for name in ['pi', 'tau', 'codex']])
        self.assertEqual(preflight.call_count, 9)
        for _, adapter, metadata in prepared:
            self.assertEqual(metadata['thinking'], 'medium')
            self.assertIn(metadata['model'], adapter.profile['command'])

    def test_rejects_duplicate_models_and_legacy_model_matrix(self):
        for argv in (['--harness', 'all', '--models', 'same', 'same'],
                     ['--harness-command', 'example', '--models', 'one', 'two'],
                     ['--harness', 'all', '--model', 'one', '--models', 'two']):
            with self.subTest(argv=argv), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parse(argv)

    def test_profile_error_prevents_any_execution(self):
        args = parse(['--harness', 'all', '--models', 'gpt-5.6-sol', 'gpt-5.6-terra'])
        with patch('evals.adapters.runtime.preflight', side_effect=[{}, ValueError('profile unavailable')]), \
             patch('evals.adapters.native.NativeHarness.invoke') as invoke, \
             patch('evals.adapters.runtime.make_preparer'):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                native_adapters(args)
        invoke.assert_not_called()

    def test_network_checks_are_explicit_and_timeouts_are_finite(self):
        for flags in (['--check-network'], ['--timeout', 'nan'],
                      ['--timeout', 'inf'], ['--timeout', '0'], ['--timeout', '-1']):
            with self.subTest(flags=flags), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parse(['--harness', 'pi', *flags])
        self.assertTrue(parse(['--harness', 'pi', '--check', '--check-network']).check_network)
