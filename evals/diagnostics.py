"""Check a fresh runtime without invoking a harness, model or scoring function."""

from collections import Counter
import json
import os
from pathlib import Path
import platform
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4
import urllib.request
import urllib.error

from .runtime.network import trace_endpoint
from .runtime.profiles import DEFAULT_IMAGE
from .runtime.docker import make_preparer, preflight
from .contracts import HarnessInvocation
from .datasets.loader import load_examples
from .json_io import strict_json_loads


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Never forward a Phoenix bearer credential to a redirect destination.
        return None


def _image_details(image, profile):
    response = subprocess.run(
        ['docker', 'image', 'inspect', image], capture_output=True, text=True, timeout=20)
    if response.returncode:
        raise ValueError('Could not inspect the runtime image')
    info = json.loads(response.stdout)[0]
    actual_version = (info.get('Config', {}).get('Labels') or {}).get(
        f"org.doc-intell.{profile['name']}.version")
    if actual_version is not None and actual_version != profile['version']:
        raise ValueError('Image version label differs from the requested harness version')
    return {'os': info.get('Os'), 'architecture': info.get('Architecture'),
            'version_verified_by_label': actual_version == profile['version']}


def _worker_probe(profile, dataset, documents, image, phoenix_url, network, timeout):
    # A diagnostic process never receives provider credentials or runs the CLI.
    diagnostic = {**profile, 'name': 'diagnostic', 'auth': 'none', 'forward_env': [],
                  'telemetry': 'none', 'command': ['python3', '-c',
                      Path(__file__).with_name('diagnostic_worker.py').read_text()]}
    with TemporaryDirectory(prefix='doc-intell-doctor-') as temporary:
        invocation = HarnessInvocation(
            input_text='', task_id='diagnostic', repetition=1, dataset=dataset,
            documents=tuple(documents), artifact_dir=Path(temporary),
            trace_id=uuid4().hex, parent_span_id=uuid4().hex[:16], run_id='diagnostic')
        with make_preparer(diagnostic, image=image, phoenix_url=phoenix_url)(invocation) as spec:
            # Corporate images may have their own harness ENTRYPOINT. Bypass it
            # even though this profile's command is already the Python probe.
            position = len(spec.argv) - len(diagnostic['command']) - 1
            argv = [*spec.argv[:position], '--entrypoint', 'python3',
                    spec.argv[position], *spec.argv[position + 2:]]
            result = subprocess.run(
                argv, input=json.dumps({'documents': documents, 'network': network,
                    'hosts': profile.get('allowed_hosts') or ['chatgpt.com', 'api.openai.com', 'auth.openai.com']}),
                cwd=spec.cwd, env=spec.env, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=timeout)
    if result.returncode:
        raise ValueError('Worker diagnostic failed; check image tools and Docker networking')
    return strict_json_loads(result.stdout)


def _phoenix_ready(url):
    headers = {}
    if os.environ.get('PHOENIX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['PHOENIX_API_KEY']
    request = urllib.request.Request(url.rstrip('/') + '/readyz', headers=headers)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as error:
        error.close()
        return False


def diagnose(args):
    from .cli import selected_profiles

    result = {'diagnostics_version': 'runtime-check-v1', 'ready': False,
              'model_calls': 0, 'model_access': 'not_tested',
              'readiness_scope': 'Runtime and selected transport checks; effective model settings/access require a real run',
              'network_requested': args.check_network,
              'host': {'os': platform.system(), 'architecture': platform.machine(),
                       'python': platform.python_version()},
              'checks': {}, 'harnesses': [], 'issues': []}
    if os.name != 'posix':
        result['issues'].append('Use a POSIX host; on Windows run from WSL2 with Docker integration')
        return result
    try:
        examples, version = load_examples(args.dataset)
        result['checks']['dataset'] = True
        result['dataset'] = {'version': version, 'tasks': len(examples),
                             'fields': sum(len(example.input.fields) for example in examples)}
        documents = list({doc['path']: doc for example in examples for doc in example.input.documents}.values())
        result['dataset']['document_formats'] = dict(Counter(Path(doc['path']).suffix.lower() for doc in documents))
        result['dataset']['cases'] = len({example.input.case_id for example in examples})
        result['dataset']['tax_years'] = sorted({example.input.tax_year for example in examples})
        profiles = selected_profiles(args)
        phoenix_url = getattr(args, 'phoenix_url', 'http://127.0.0.1:6006')
        trace_endpoint(phoenix_url)
    except (ValueError, OSError) as error:
        result['issues'].append(str(error) if isinstance(error, ValueError) else 'Dataset files are unavailable')
        return result
    if args.check_network:
        try:
            result['checks']['phoenix_runner'] = _phoenix_ready(phoenix_url)
        except Exception:
            result['checks']['phoenix_runner'] = False
            result['issues'].append('Phoenix is not reachable from the runner; check endpoint, TLS and credentials')
    for profile in profiles:
        row = {'harness': profile['name'], 'model': profile['model'], 'thinking': profile['thinking'],
               'ready': False, 'checks': {}, 'warnings': []}
        result['harnesses'].append(row)
        try:
            if any(profile[key].startswith('replace-with-') for key in ('model', 'provider', 'version')):
                raise ValueError('Complete the corporate profile placeholders before checking the runtime')
            image = args.image or DEFAULT_IMAGE
            row['runtime'] = preflight(profile, image=image)
            row['checks']['runtime_and_credential_presence'] = True
            row['image'] = _image_details(row['runtime']['image_id'], profile)
            if not row['image']['version_verified_by_label']:
                row['warnings'].append('Harness version is declared only; add its version label to the image')
            if not all(any(profile[key] in arg for arg in profile['command']) for key in ('model', 'thinking')):
                row['warnings'].append('Model/reasoning are declared; document how the CLI or its environment applies them')
            worker = _worker_probe(profile, args.dataset, documents, row['runtime']['image_id'],
                                   phoenix_url, args.check_network, args.timeout)
            row['checks'].update(worker['checks'])
            row['network'] = worker['network']
            row['worker_python'] = worker['python']
            row['document_content_validation'] = worker.get('document_content_validation', 'not_performed')
            row['model_document_reading'] = worker.get('model_document_reading', 'not_tested')
            row['warnings'].append('Document hashes/readability and installed PDF tools do not validate labels, page counts or model reading')
            row['ready'] = all(row['checks'].values())
        except Exception as error:
            row['issue'] = str(error) if isinstance(error, ValueError) else type(error).__name__
    result['ready'] = bool(result['harnesses']) and all(result['checks'].values()) and all(
        row['ready'] for row in result['harnesses'])
    return result
