"""Shared options for local evaluations and Phoenix publication."""

from pathlib import Path


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


def native_adapters(args):
    """Preflight every requested profile before any paid invocation."""
    from .adapters.native import NativeHarness
    from .adapters.runtime import DEFAULT_IMAGE, load_profile, make_preparer, preflight
    from .adapters.network import trace_endpoint
    phoenix_url = getattr(args, 'phoenix_url', 'http://127.0.0.1:6006')
    trace_endpoint(phoenix_url)
    names = ['pi', 'tau', 'codex'] if args.harness == 'all' else [args.profile or args.harness]
    prepared = []
    for model in getattr(args, 'models', None) or [args.model]:
        for name in names:
            profile = load_profile(name, model=model, thinking=args.thinking)
            image = args.image or DEFAULT_IMAGE
            metadata = preflight(profile, image=image)
            adapter = NativeHarness(profile, make_preparer(profile, image=image, phoenix_url=phoenix_url), args.timeout)
            prepared.append((profile['name'], adapter, metadata))
    return prepared


def validate_execution_options(parser, args):
    if args.repetitions < 1:
        parser.error('--repetitions must be positive')
    models = getattr(args, 'models', None)
    if models and len(set(models)) != len(models):
        parser.error('--models cannot contain duplicate model names')
    if not args.harness and not args.profile and (args.model or models or args.thinking or args.image):
        parser.error('--model, --models, --thinking and --image require --harness or --profile')
