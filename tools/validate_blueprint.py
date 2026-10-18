#!/usr/bin/env python3
"""Validate blueprint fixtures and references; does not test a running product."""
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote
import sys

try:
    import jsonschema
    import yaml
except ImportError:
    sys.exit("Install documentation validators: python3 -m pip install -r tools/requirements-validation.txt")

ROOT = Path(__file__).resolve().parents[1]
checks = 0
EXCLUDED = {".venv", ".local", ".git", "node_modules", "dist", "test-results", "playwright-report", "__pycache__"}

def source_files(suffix):
    for directory, subdirectories, filenames in os.walk(ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in EXCLUDED]
        for filename in filenames:
            if filename.endswith(suffix):
                yield Path(directory) / filename

def verify(condition, message):
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1

for p in source_files('.json'):
    json.loads(p.read_text(encoding="utf-8"))
    checks += 1
for p in (ROOT / 'contracts').glob('*.schema.json'):
    jsonschema.Draft202012Validator.check_schema(json.loads(p.read_text()))
    checks += 1

mapping = {
    'event': 'event', 'tool-invocation': 'tool-invocation', 'decision': 'decision',
    'investigation': 'investigation', 'policy': 'policy', 'route-transition': 'route-transition'
}
for fixture, schema in mapping.items():
    data = json.loads((ROOT / f'examples/{fixture}.json').read_text())
    spec = json.loads((ROOT / f'contracts/{schema}.schema.json').read_text())
    jsonschema.Draft202012Validator(spec, format_checker=jsonschema.FormatChecker()).validate(data)
    checks += 1

# Negative contract checks: these are documentation-level constraints.
spec = json.loads((ROOT / 'contracts/tool-invocation.schema.json').read_text())
original = json.loads((ROOT / 'examples/tool-invocation.json').read_text())
for extra in ('tenant_id', 'principal_id', 'upstream_url'):
    bad = dict(original, **{extra: 'attacker-controlled'})
    verify(not jsonschema.Draft202012Validator(spec).is_valid(bad), f'Unexpected accepted field: {extra}')

for md in source_files('.md'):
    content = md.read_text(encoding="utf-8")
    verify(content.count('```') % 2 == 0, f'Unclosed fence: {md}')
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
        if '://' in target or target.startswith(('#', 'mailto:')):
            continue
        path = target.split('#', 1)[0]
        if path:
            verify((md.parent / unquote(path)).exists(), f'Broken link {target} in {md}')

api = yaml.safe_load((ROOT / 'contracts/openapi.yaml').read_text())
verify(api['openapi'] == '3.1.0', 'Wrong OpenAPI version')
verify(bool(api.get('security')), 'Missing API security declaration')
ops = []

def resolve_pointer(obj, pointer):
    for part in pointer.lstrip('/').split('/'):
        obj = obj[part.replace('~1', '/').replace('~0', '~')]
    return obj

def walk_refs(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == '$ref':
                if value.startswith('#/'):
                    resolve_pointer(api, value[1:])
                elif value.startswith('./'):
                    verify((ROOT / 'contracts' / value).is_file(), f'Missing external schema: {value}')
            else:
                walk_refs(value)
    elif isinstance(obj, list):
        for value in obj:
            walk_refs(value)
walk_refs(api)
for path, item in api['paths'].items():
    for method in ('get', 'post', 'put', 'patch', 'delete'):
        if method in item:
            op = item[method]
            verify('responses' in op, f'Missing responses: {path}')
            ops.append(op['operationId'])
verify(len(ops) == len(set(ops)), 'Duplicate operation IDs')

fixture = json.loads((ROOT / 'examples/event.json').read_text())
analysis = json.loads((ROOT / 'examples/investigation.json').read_text())
for claim in analysis['claims']:
    verify(set(claim['evidence_event_ids']) <= {fixture['event_id']}, 'Unknown example evidence ref')
verify('single event' in (ROOT / 'examples/README.md').read_text(), 'Missing eligibility caveat')

# Traceability: all TH matrix test IDs and backlog test refs must exist in the test matrix.
tests = (ROOT / 'docs/testing.md').read_text()
known = set(re.findall(r'\| (T-\d+) \|', tests))
for filename in ('docs/security-model.md', 'docs/backlog.md'):
    refs = set(re.findall(r'\bT-\d+\b', (ROOT / filename).read_text()))
    verify(refs <= known, f'Unresolved test IDs in {filename}: {refs-known}')

print(f'PASS: {checks} documentation/fixture checks; {len(ops)} API operations; {len(known)} specified product tests.')
print('Product security, provider deployment and runtime isolation were NOT executed by this validator.')
