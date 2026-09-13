"""Integrity checks for immutable acquisition kits and their source files."""

import hashlib
from pathlib import PurePosixPath
import re


def sha256_file(path):
    """Hash a file's exact bytes, without parsing or normalizing its contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(source):
    """Verify the release and its exact file membership before deriving labels."""
    source = source.resolve()
    names = set()
    for line in (source / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or name in names or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('Invalid or duplicated source checksum entry')
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f'Source checksum mismatch: {name}')
        names.add(name)
    actual = {p.relative_to(source).as_posix() for p in source.rglob('*')
              if p.is_file() and p.name != '.DS_Store' and '__pycache__' not in p.parts}
    if actual != names | {'SHA256SUMS'}:
        raise ValueError('Source release has missing or unmanifested files')
    return {'release_files_verified': len(names), 'sha256sums_sha256': sha256_file(source / 'SHA256SUMS')}
