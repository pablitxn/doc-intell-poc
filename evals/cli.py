"""Shared options for local evaluations and Phoenix publication."""

from pathlib import Path
import math
import os


def add_execution_options(parser, source):
    source.add_argument('--harness', choices=('pi', 'tau', 'codex', 'all'), help='Native harness profile; all runs the three profiles sequentially')
    source.add_argument('--profile', type=Path, help='Custom harness profile JSON (for example the corporate harness)')
    source.add_argument('--harness-command', help='Legacy host executable: text stdin, one JSON stdout; no filesystem isolation')
    models = parser.add_mutually_exclusive_group()
    models.add_argument('--model', help='Explicit model override for native profiles')
    models.add_argument('--models', nargs='+', help='Run each requested model across the selected harnesses')
    parser.add_argument('--thinking', help='Explicit reasoning effort override for native profiles')
    parser.add_argument('--repetitions', type=int, default=1)
    parser.add_argument('--image', help='Prepared Docker image containing the native harnesses')
    parser.add_argument('--check', action='store_true', help='Validate runtime, image, profile and authentication without model calls')
    parser.add_argument('--check-network', action='store_true', help='With --check, probe provider TLS and Phoenix transport without model calls')


def add_run_options(parser):
    """Keep dataset, selection and output defaults identical in both CLIs."""
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1] / 'datasets/tax-mini-poc')
    parser.add_argument('--task', help='One task_id; defaults to all tasks in the selected dataset')
    parser.add_argument('--timeout', type=float, default=120.0, help='Seconds per harness invocation (default: 120)')
    parser.add_argument('--output-dir', type=Path, default=Path('runs'))
    parser.add_argument('--phoenix-url', default=os.environ.get('PHOENIX_ENDPOINT', 'http://127.0.0.1:6006'),
                        help='Phoenix origin for diagnostics, native OTel and publication when enabled')


def selected_profiles(args):
    from .runtime.profiles import load_profile
    names = ['pi', 'tau', 'codex'] if args.harness == 'all' else [args.profile or args.harness]
    return [load_profile(name, model=model, thinking=args.thinking)
            for model in getattr(args, 'models', None) or [args.model] for name in names]


def native_adapters(args):
    """Preflight every requested profile before any paid invocation."""
    from .adapters.native import NativeHarness
    from .runtime.profiles import DEFAULT_IMAGE
    from .runtime.docker import make_preparer, preflight
    from .runtime.network import trace_endpoint
    phoenix_url = getattr(args, 'phoenix_url', 'http://127.0.0.1:6006')
    trace_endpoint(phoenix_url)
    prepared = []
    for profile in selected_profiles(args):
        image = args.image or DEFAULT_IMAGE
        metadata = preflight(profile, image=image)
        adapter = NativeHarness(profile, make_preparer(profile, image=image, phoenix_url=phoenix_url), args.timeout)
        prepared.append((profile['name'], adapter, metadata))
    return prepared


def validate_execution_options(parser, args):
    if args.repetitions < 1:
        parser.error('--repetitions must be positive')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a positive finite number')
    if args.check_network and not args.check:
        parser.error('--check-network requires --check')
    if args.check and not (args.harness or args.profile):
        parser.error('--check requires --harness or --profile')
    models = getattr(args, 'models', None)
    if models and len(set(models)) != len(models):
        parser.error('--models cannot contain duplicate model names')
    if not args.harness and not args.profile and (args.model or models or args.thinking or args.image):
        parser.error('--model, --models, --thinking and --image require --harness or --profile')
