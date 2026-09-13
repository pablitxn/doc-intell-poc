"""Version task/scoring semantics independently from harness implementation.

The dataset loader supplies dataset_version (tasks, types, references and verified
PDF hashes). These source fingerprints are deliberately conservative: changing a
comment in contract/scoring code also requires a new comparison cohort. Runtime
code, including adapters and publication, is provenance rather than a scoring gate.
"""

import ast
import hashlib
from pathlib import Path

FINGERPRINT_VERSION = 'eval-fingerprints-v1'
REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FILES = (
    'evals/contracts.py#TaskInput',
    'evals/datasets/loader.py',
    'evals/experiments/prompt.py',
    'evals/json_io.py',
)
SCORING_FILES = (
    'evals/evaluators/__init__.py',
    'evals/evaluators/definitions.py',
    'evals/evaluators/grading.py',
    'evals/evaluators/schema.py',
    'evals/evaluators/scoring.py',
)
FINGERPRINT_FIELDS = ('fingerprint_version', 'contract_sha256', 'scoring_sha256', 'runtime_code_sha256')
HISTORICAL_SCORING_PATH = REPO_ROOT / 'artifacts/2026-09-13/architecture/baseline-scoring.json'


def _source_bytes(root: Path, name: str) -> bytes:
    if '#' not in name:
        return (root / name).read_bytes()
    filename, symbol = name.split('#')
    source = (root / filename).read_text()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.ClassDef) and node.name == symbol)
    start = min([node.lineno, *(item.lineno for item in node.decorator_list)]) - 1
    return '\n'.join(source.splitlines()[start:node.end_lineno]).encode()


def source_manifest(root: Path = REPO_ROOT) -> dict[str, str]:
    """Exact reviewed files needed to establish legacy baseline equivalence."""
    return {name: hashlib.sha256(_source_bytes(root, name)).hexdigest()
            for name in sorted((*CONTRACT_FILES, *SCORING_FILES))}


def _source_hash(root: Path, names) -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        digest.update(name.encode() + b'\0' + _source_bytes(root, name) + b'\0')
    return digest.hexdigest()


def code_fingerprints(root: Path = REPO_ROOT) -> dict[str, str]:
    all_code = {path.relative_to(root).as_posix() for path in (root / 'evals').rglob('*.py')}
    # New evaluator modules are scoring code, even before referenced by this list.
    scoring = set(SCORING_FILES) | {name for name in all_code if name.startswith('evals/evaluators/')}
    contract = set(CONTRACT_FILES)
    runtime = all_code - contract - scoring
    return {
        'fingerprint_version': FINGERPRINT_VERSION,
        'contract_sha256': _source_hash(root, contract),
        'scoring_sha256': _source_hash(root, scoring),
        'runtime_code_sha256': _source_hash(root, runtime),
    }


def legacy_code_sha256(root: Path = REPO_ROOT) -> str:
    """Preserve the original whole-evals provenance algorithm exactly."""
    code_root = root / 'evals'
    return hashlib.sha256(b''.join(
        path.relative_to(code_root).as_posix().encode() + b'\0' + path.read_bytes()
        for path in sorted(code_root.rglob('*.py'))
    )).hexdigest()


def _historical_scoring_sources(manifest: dict) -> dict[str, str]:
    """Verify every frozen source against the original immutable baseline."""
    from ..json_io import strict_json_loads

    snapshot = strict_json_loads(HISTORICAL_SCORING_PATH.read_text())
    sources = snapshot.get('sources', {})
    names = {name for name in manifest['reviewed_sources']
             if name.startswith('evals/evaluators/') or name == 'datasets/tax-mini-poc/grade.py'}
    if (snapshot.get('reviewed_source_commit') != manifest['reviewed_source_commit']
            or not isinstance(sources, dict) or set(sources) != names):
        raise ValueError('Historical scoring source membership differs from the reviewed baseline')
    digest = hashlib.sha256()
    for name in sorted(names):
        source = sources[name]
        if (not isinstance(source, str)
                or hashlib.sha256(source.encode()).hexdigest() != manifest['reviewed_sources'][name]):
            raise ValueError('Historical scoring source bytes differ from the reviewed baseline')
        digest.update(name.encode() + b'\0' + source.encode() + b'\0')
    if (digest.hexdigest() != manifest['scoring_sha256']
            or manifest['reviewed_sources']['datasets/tax-mini-poc/grade.py'] != manifest['grader_sha256']):
        raise ValueError('Historical scoring fingerprint differs from the reviewed baseline')
    return sources


def _historical_score_answer(manifest: dict):
    """Load only verified pure functions, without importing any current scorer."""
    from datetime import date
    from decimal import Decimal, InvalidOperation
    import re

    sources = _historical_scoring_sources(manifest)
    namespace = {'date': date, 'Decimal': Decimal, 'InvalidOperation': InvalidOperation, 're': re}
    for name, functions in (
        ('datasets/tax-mini-poc/grade.py', {'equal_value', 'reference_key', 'grade'}),
        ('evals/evaluators/schema.py', {'valid_value', 'schema_errors'}),
        ('evals/evaluators/tax_mini.py', {'score_answer'}),
    ):
        nodes = [node for node in ast.parse(sources[name]).body
                 if isinstance(node, ast.FunctionDef) and node.name in functions]
        if len(nodes) != len(functions) or {node.name for node in nodes} != functions:
            raise ValueError('Historical scoring source is missing required functions')
        exec(compile(ast.Module(body=nodes, type_ignores=[]), name, 'exec'), namespace)
    return namespace['score_answer']


def migrate_baseline(run_dir: Path, output_dir: Path, *, dataset: Path | None = None,
                     historical_only: bool = False) -> Path:
    """Add verified semantic fingerprints to a copy of one audited legacy run.

    This is deliberately not a generic 'trust my old report' switch. Report and
    sidecar bytes must match the committed nine-run baseline. Current-compatible
    migration additionally requires identical current contract/scoring sources.
    Historical-only migration verifies scores using the original frozen sources
    after checking their hashes against that baseline; its old contract/scoring
    identities and recorded prompts remain historical. Both modes verify the
    reference dataset. Publication checkpoints are copied unchanged; importing
    into another Phoenix uses the separate importer.
    """
    import json
    from ..datasets.loader import load_examples, read_json
    from ..json_io import strict_json_loads
    from .prompt import build_prompt
    from .runner import _summary, build_dataset_snapshot

    manifest_path = REPO_ROOT / 'artifacts/2026-09-13/baseline-compatibility.json'
    manifest = read_json(manifest_path)
    original_bytes = (run_dir / 'report.json').read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    allowed = next((entry for entry in manifest['runs'] if entry['report_sha256'] == original_sha), None)
    if allowed is None:
        raise ValueError('Legacy report is not an exact audited baseline; refusing migration')
    if historical_only:
        score_answer = _historical_score_answer(manifest)
    else:
        from ..evaluators.scoring import score_answer
        fingerprints = code_fingerprints()
        if source_manifest() != manifest['reviewed_sources'] or any(
                fingerprints[key] != manifest[key]
                for key in ('fingerprint_version', 'contract_sha256', 'scoring_sha256')):
            raise ValueError('Current contract/scoring sources differ from the reviewed baseline')
    report = strict_json_loads(original_bytes.decode())
    if report.get('complete') is not True or report.get('run_id') != allowed['run_id']:
        raise ValueError('Baseline requires a complete matching run identity')
    for key in ('dataset_version', 'prompt_version', 'evaluator_version', 'grader_sha256'):
        if report.get(key) != manifest[key]:
            raise ValueError('Baseline metadata differs from reviewed provenance')
    if report.get('eval_code_sha256') != manifest['legacy_eval_code_sha256']:
        raise ValueError('Baseline source provenance differs from reviewed provenance')
    if any(key in report for key in FINGERPRINT_FIELDS):
        raise ValueError('Baseline already carries fingerprint metadata')
    dataset = (dataset or REPO_ROOT / 'datasets/tax-mini-poc').resolve()
    examples, version = load_examples(dataset)
    if version != report['dataset_version'] or dataset.name != report['dataset']:
        raise ValueError('Baseline dataset differs from current dataset')
    prompt_root = Path(report['prompt_root']) if report.get('prompt_root') else None
    by_id = {example.input.task_id: example for example in examples}
    identities = [(row['task_id'], row.get('repetition')) for row in report['rows']]
    if report.get('repetitions') != 1 or len(identities) != len(by_id) or set(identities) != {
        (task_id, 1) for task_id in by_id
    }:
        raise ValueError('Baseline task membership is incomplete or duplicated')
    for row in report['rows']:
        example = by_id[row['task_id']]
        if (row.get('case_id') != example.input.case_id or row.get('group') != example.group
                or row.get('document_ids') != [doc['document_id'] for doc in example.input.documents]):
            raise ValueError('Baseline task metadata differs from the verified dataset')
        if not isinstance(row.get('input'), str) or not row['input'].strip():
            raise ValueError('Baseline requires recorded task inputs')
        if not historical_only and row['input'] != build_prompt(example.input, dataset, document_root=prompt_root):
            raise ValueError('Baseline prompt differs from the current contract')
        if row['scores'] != score_answer(row['output'], example.expected, example.input.fields,
                                        row['execution_status']):
            raise ValueError('Baseline scores differ from the verified evaluator')
    summary = _summary(report['rows'])
    summary['groups'] = {
        group: _summary([row for row in report['rows'] if row['group'] == group])
        for group in sorted({row['group'] for row in report['rows']})
    }
    if summary != report['summary']:
        raise ValueError('Baseline summary differs from its task rows')
    copies = {}
    for entry in allowed['files']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid baseline artifact path')
        content = (run_dir / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Baseline artifact differs from the archived bytes')
        copies[relative] = content
    destination = output_dir.resolve() / report['run_id']
    if destination.is_relative_to(run_dir.resolve()):
        raise ValueError('Baseline migration destination must be separate from the original')
    if destination.exists():
        raise ValueError('Baseline migration destination already exists; refusing overwrite')
    if historical_only:
        # Report bytes were verified against the immutable manifest. Use those
        # exact prompts; rendering them with today's contract would falsify history.
        snapshot_examples = [
            {'task_id': row['task_id'], 'case_id': row['case_id'], 'group': row['group'],
             'field_types': by_id[row['task_id']].input.fields, 'document_ids': row['document_ids'],
             'input': row['input'], 'expected': by_id[row['task_id']].expected}
            for row in report['rows']
        ]
    else:
        snapshot_examples = build_dataset_snapshot(examples, dataset, prompt_root)['examples']
    snapshot = {'examples': snapshot_examples, 'dataset_version': version,
                'prompt_version': report['prompt_version']}
    snapshot_bytes = (json.dumps(snapshot, indent=2, allow_nan=False) + '\n').encode()
    semantic_fingerprints = manifest if historical_only else fingerprints
    report.update({key: semantic_fingerprints[key]
                   for key in ('fingerprint_version', 'contract_sha256', 'scoring_sha256')})
    # The old whole-evals hash is the only observed runtime-source provenance.
    # Never substitute a reconstructed post-run runtime hash and label it native.
    report['runtime_code_sha256'] = report['eval_code_sha256']
    report['runtime_fingerprint_basis'] = 'legacy-whole-evals'
    report['dataset_snapshot_sha256'] = hashlib.sha256(snapshot_bytes).hexdigest()
    report['fingerprint_migration'] = {
        'manifest': manifest_path.relative_to(REPO_ROOT).as_posix(),
        'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'original_report_sha256': original_sha,
        'reviewed_source_commit': manifest['reviewed_source_commit'],
        'mode': 'historical-only' if historical_only else 'current-compatible',
        'validation': ('exact archived report and sidecar bytes, verified frozen scoring sources, dataset, '
                       'task membership, recorded prompts and scores; original contract and scoring preserved'
                       if historical_only else
                       'exact archived bytes, source units, dataset, task membership, prompts and scores'),
    }
    if historical_only:
        report['fingerprint_migration']['scoring_snapshot'] = {
            'path': HISTORICAL_SCORING_PATH.relative_to(REPO_ROOT).as_posix(),
            'sha256': hashlib.sha256(HISTORICAL_SCORING_PATH.read_bytes()).hexdigest(),
        }
    copies[Path('report.json')] = (json.dumps(report, indent=2, allow_nan=False) + '\n').encode()
    copies[Path('dataset-snapshot.json')] = snapshot_bytes
    destination.mkdir(parents=True, exist_ok=False)
    for relative, content in copies.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return destination


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Add fingerprints to copies of the nine audited GPT-5.6 baseline runs')
    commands = parser.add_subparsers(dest='command', required=True)
    migrate = commands.add_parser('migrate-baseline')
    migrate.add_argument('run_dirs', nargs='+', type=Path)
    migrate.add_argument('--output-dir', required=True, type=Path)
    migrate.add_argument('--dataset', type=Path, default=REPO_ROOT / 'datasets/tax-mini-poc')
    migrate.add_argument('--historical-only', action='store_true',
                         help='Preserve the audited historical contract; never claim compatibility with the current prompt')
    args = parser.parse_args(argv)
    try:
        for run_dir in args.run_dirs:
            print(migrate_baseline(run_dir, args.output_dir, dataset=args.dataset,
                                   historical_only=args.historical_only))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Baseline migration failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
