"""Verify a local source snapshot and optionally write a new candidate file."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE_SOURCE_SHA256 = 'd80135063701321128fd11d662d87a1c8798750c92e85a7b796a7b7c448d902d'
ARCHIVE_SNIPPET_SHA256 = {
    'make_packets': 'e1b9fb6c07dd4f31f2044e784f76915db9488e2602cc0ab52301fef244792a15',
    'prepare': '29ca1920427347219355a6c1ce4cdc7f4e90e47b1b974b4061e949a9926b7701',
}
OLD_CALL = "                packets, _ = make_packets(source, context, self.cfg['device_id'], key, now)"
NEW_CALL = """                packed = None
                if self.cfg.get('website_compact_reports') is True:
                    packed = make_compact_v1_packets(source, context, self.cfg['device_id'], key, now)
                if packed is None:
                    packed = make_packets(source, context, self.cfg['device_id'], key, now)
                packets, _ = packed"""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def archived_snippets(evidence_path):
    evidence = json.loads(evidence_path.read_text(encoding='utf-8-sig'))
    metadata = evidence['file_metadata']['website_publish.py']
    if metadata['sha256'] != ARCHIVE_SOURCE_SHA256:
        raise ValueError('ARCHIVED_SOURCE_DIGEST_MISMATCH')
    snippets = {item['function']: item['source']
                for item in evidence['source_excerpts']['website_publish.py']
                if item['function'] in ARCHIVE_SNIPPET_SHA256}
    for name, expected in ARCHIVE_SNIPPET_SHA256.items():
        if name not in snippets or digest(snippets[name].encode('utf-8')) != expected:
            raise ValueError('ARCHIVED_SNIPPET_DIGEST_MISMATCH')
    return snippets


def patch_verified_text(text, snippets, helper):
    """Change only the verified make_packets insertion and prepare call site."""
    tree = ast.parse(text)
    packers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'make_packets']
    publishers = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Publisher']
    if len(packers) != 1 or len(publishers) != 1:
        raise ValueError('EXPECTED_SOURCE_STRUCTURE_MISSING')
    prepares = [node for node in publishers[0].body
                if isinstance(node, ast.FunctionDef) and node.name == 'prepare']
    if len(prepares) != 1 or ast.get_source_segment(text, prepares[0]) != snippets['prepare']:
        raise ValueError('PREPARE_SOURCE_MISMATCH')
    if ast.get_source_segment(text, packers[0]) != snippets['make_packets']:
        raise ValueError('PACKER_SOURCE_MISMATCH')
    if text.count(snippets['make_packets']) != 1 or text.count(OLD_CALL) != 1:
        raise ValueError('SOURCE_INSERTION_AMBIGUOUS')
    candidate = text.replace(snippets['make_packets'], helper.rstrip() + '\n\n\n' + snippets['make_packets'], 1)
    candidate = candidate.replace(OLD_CALL, NEW_CALL, 1)
    compile(candidate, 'website_publish.compact-v1.py', 'exec')
    return candidate


def verified_candidate(source_path, evidence_path):
    raw = source_path.read_bytes()
    if digest(raw) != ARCHIVE_SOURCE_SHA256:
        raise ValueError('BOARD_SNAPSHOT_SHA256_MISMATCH')
    snippets = archived_snippets(evidence_path)
    helper = (HERE / 'compact_payload.py').read_text(encoding='utf-8')
    return patch_verified_text(raw.decode('utf-8'), snippets, helper).encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Local board source snapshot')
    parser.add_argument('--evidence', type=Path, required=True, help='Local archived board-evidence.json')
    parser.add_argument('--write-candidate', action='store_true', help='Create a new file in the ignored hardware-checks directory')
    args = parser.parse_args()
    try:
        candidate = verified_candidate(args.source, args.evidence)
        if args.write_candidate:
            target = HERE.parents[2] / 'outputs/hardware-checks/compact-v1-candidate/website_publish.compact-v1.py'
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as file:
                file.write(candidate)
        print(json.dumps(dict(code='CANDIDATE_CREATED' if args.write_candidate else 'SOURCE_MATCH_VERIFIED',
                              source_sha256=ARCHIVE_SOURCE_SHA256, candidate_sha256=digest(candidate),
                              candidate_written=args.write_candidate)))
        return 0
    except (OSError, ValueError, TypeError, KeyError, SyntaxError) as error:
        code = str(error) if type(error) is ValueError and str(error).replace('_', '').isalnum() else 'CANDIDATE_REFUSED'
        print(json.dumps(dict(code=code, candidate_written=False)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
