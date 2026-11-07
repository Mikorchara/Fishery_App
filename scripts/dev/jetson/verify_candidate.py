"""Offline compact-packet checks against saved samples and a read-only report inbox."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT)]

from make_candidate import archived_snippets, patch_verified_text, verified_candidate
from apps.device_reports.contracts import MAX_BYTES, validate
from apps.device_reports.presentation import project_reports

EVIDENCE = ROOT / 'outputs/hardware-evidence/evidence-20261106T113300Z-c813c773'
MULTIPART = re.compile(r'^(web-[0-9a-f]{40})-[1-9][0-9]{0,2}$')
ORIGINAL = '【完整原始 JSON】'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def instant(value):
    if type(value) is int:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def harness():
    snippets = archived_snippets(EVIDENCE / 'board-evidence.json')
    helper = (HERE / 'compact_payload.py').read_text(encoding='utf-8')
    # Exercise the real archived prepare/packer bodies, with a local fake publisher.
    text = snippets['make_packets'] + '\n\nclass Publisher:\n    ' + snippets['prepare'] + '\n'
    patched = patch_verified_text(text, snippets, helper)
    namespace = dict(encode=encode, load=json.loads, instant=instant, datetime=datetime, timezone=timezone,
                     compact_measurement=lambda value: value, context_of=lambda *_: None,
                     digest=lambda data: hashlib.sha256(data).hexdigest(), LIMIT=MAX_BYTES,
                     IDENTIFIER=re.compile(r'[A-Za-z0-9_-]{1,100}'))
    exec(compile(patched, '<local archived publisher harness>', 'exec'), namespace)
    return namespace


def item(report, received_at=None):
    return dict(report=report, received_at=received_at or report['sent_at'], freshness='stale', warnings=[])


def context_of(report):
    return {key: report[key] for key in ('window', 'detection', 'abnormalities')}


def compare_group(items, compact):
    projected, = project_reports(items)
    report = projected['report']
    before = sum(len(encode(v['report'])) for v in items)
    if projected['assembly']['status'] != 'complete' or ORIGINAL not in report['report_text']:
        return dict(result='NOT_COMPARABLE', kind='unknown', packets_before=len(items), packets_after=len(items),
                    bytes_before=before, bytes_after=before)
    source = json.loads(report['report_text'].split(ORIGINAL, 1)[1])
    kind = 'combined' if isinstance(source.get('inputs'), dict) else (
        'detector_only' if isinstance(source.get('models'), dict) and isinstance(source.get('window'), dict)
        else 'unknown')
    now = instant(report['sent_at'])
    device = report['device_id']
    # Stored base ID retains 40 characters of the source key. This test derives
    # a stable synthetic key; the real sender supplies the complete original key.
    source_key = hashlib.sha256(encode(source)).hexdigest()
    result = compact(source, context_of(report), device, source_key, now)
    if result is None:
        return dict(result='FULL_FALLBACK', kind=kind, packets_before=len(items), packets_after=len(items),
                    bytes_before=before, bytes_after=before)
    packets, _ = result
    raw, = packets
    compact_report, _, _, _ = validate(raw, device_id=device, now=now)
    compact_view, = project_reports([item(compact_report)])
    assert compact_view['assembly']['status'] == 'single'
    assert compact_view['presentation'] == projected['presentation']
    assert compact_report['window'] == report['window']
    assert compact_report['has_abnormality'] == report['has_abnormality']
    assert compact_report['report_id'].startswith('webc1-') and compact_report['report_id'] != report['report_id']
    assert compact_report['sent_at'] == report['sent_at']
    assert compact(source, context_of(report), device, source_key, now) == result
    return dict(result='COMPACT_VERIFIED', kind=kind, packets_before=len(items), packets_after=1,
                bytes_before=before, bytes_after=len(raw), source=source, report=report)


def archive_samples(compact):
    checked = []
    for group in sorted((EVIDENCE / 'samples').iterdir()):
        if group.is_dir():
            reports = [item(json.loads(p.read_text(encoding='utf-8'))) for p in sorted(group.glob('part-*.json'))]
            checked.append(compare_group(reports, compact))
    return checked


def compare_inbox(path, device, compact):
    groups = {}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        rows = conn.execute('SELECT payload,received_at,observed_at FROM reports WHERE device_id=? '
            'ORDER BY received_at DESC,report_id DESC LIMIT 500', (device,)).fetchall()
    latest_windows = set(sorted({row[2] for row in rows}, reverse=True)[:32])
    for payload, received_at, observed_at in rows:
        report = json.loads(payload)
        match = MULTIPART.fullmatch(report['report_id'])
        key = match[1] if match else report['report_id']
        groups.setdefault((observed_at, key), []).append(item(report, received_at))
    cases = [(observed_at, compare_group(group, compact)) for (observed_at, _), group in groups.items()]
    return ([case for _, case in cases], [case for observed_at, case in cases if observed_at in latest_windows],
            len(latest_windows))


def verify_preparation(namespace, case):
    publisher_type = namespace['Publisher']
    compact = namespace['make_compact_v1_packets']
    original, report = case['source'], case['report']
    context = context_of(report)
    device = report['device_id']
    now = instant(report['sent_at'])
    source_key = hashlib.sha256(encode(original)).hexdigest()
    unsupported = dict(original, inputs={'unknown_task': {}})
    oversized = dict(original, inputs={'measurement': {'fishes': [{'status_text':'x'*500} for _ in range(60)]}})
    assert compact(unsupported, context, device, source_key, now) is None
    assert compact(oversized, context, device, source_key, now) is None
    assert compact(original, context, 'different-device', source_key, now) is None
    assert compact(original, context, device, source_key, instant(context['window']['start'])) is None
    temporary = ROOT / 'outputs/test-tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary) as tmp, closing(sqlite3.connect(':memory:')) as db:
        folder = Path(tmp)
        source_dir = folder / 'agent_pending'
        source_dir.mkdir()
        fixture_path = folder / 'archive-fragments-only.py'
        fixture_path.write_text('pass\n', encoding='utf-8')
        try:
            verified_candidate(fixture_path, EVIDENCE / 'board-evidence.json')
        except ValueError as error:
            assert str(error) == 'BOARD_SNAPSHOT_SHA256_MISMATCH'
        else:
            raise AssertionError('unexpected snapshot accepted')
        db.executescript('''CREATE TABLE sources(id TEXT PRIMARY KEY,path TEXT,raw BLOB,kind TEXT);
          CREATE TABLE packets(id TEXT PRIMARY KEY,source_id TEXT,body BLOB,state TEXT DEFAULT 'pending');''')
        publisher = publisher_type()
        publisher.root, publisher.db = folder, db
        publisher.cfg = {'device_id':device}
        publisher.contexts = lambda: [(now, source_dir/'unused', context)]
        # Paths from reporter contexts normally exist. This fixture's context is
        # a previously queued source, so prepare skips it using the same digest key.
        archive = source_dir/'unused'
        archive.write_bytes(b'{}')
        archive_key = hashlib.sha256(b'reporter\0{}').hexdigest()
        db.execute('INSERT INTO sources VALUES(?,?,?,?)', (archive_key, str(archive), b'{}', 'reporter'))
        db.commit()
        first = source_dir / '01.json'
        first.write_bytes(encode(original))
        assert publisher.prepare()['prepared'] == 1
        old_rows = db.execute('SELECT id,body,state FROM packets ORDER BY rowid').fetchall()
        assert old_rows and all(row[0].startswith('web-') for row in old_rows)
        publisher.cfg['website_compact_reports'] = True
        second = source_dir / '02.json'
        second.write_bytes(encode(dict(original, fixture_revision=2)))
        assert publisher.prepare()['prepared'] == 1
        rows = db.execute('SELECT id,body,state FROM packets ORDER BY rowid').fetchall()
        assert rows[:-1] == old_rows
        assert rows[-1][0].startswith('webc1-') and rows[-1][2] == 'pending'
        stored = db.execute('SELECT raw FROM sources WHERE path=?',(str(second.resolve()),)).fetchone()
        assert stored[0] == second.read_bytes()
        assert publisher.prepare()['prepared'] == 0
        publisher.cfg.pop('website_compact_reports')
        assert publisher.prepare()['prepared'] == 0
        assert db.execute('SELECT id,body,state FROM packets ORDER BY rowid').fetchall() == rows


def summary(cases):
    verified = [case for case in cases if case['result'] == 'COMPACT_VERIFIED']
    return dict(groups=len(cases), compact_verified=len(verified),
                full_fallback=sum(v['result']=='FULL_FALLBACK' for v in cases),
                not_comparable=sum(v['result']=='NOT_COMPARABLE' for v in cases),
                packets_before=sum(v['packets_before'] for v in cases),
                packets_after=sum(v['packets_after'] for v in cases),
                bytes_before=sum(v['bytes_before'] for v in cases),
                bytes_after=sum(v['bytes_after'] for v in cases),
                largest_compact_bytes=max((v['bytes_after'] for v in verified), default=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, help='Optional device inbox, read-only latest 500 packets')
    parser.add_argument('--device', default='fish-monitor-orin-01')
    args = parser.parse_args()
    namespace = harness()
    compact = namespace['make_compact_v1_packets']
    archived = archive_samples(compact)
    assert len(archived) == 3 and all(v['result']=='COMPACT_VERIFIED' for v in archived)
    verify_preparation(namespace, archived[0])
    result = dict(archived=summary(archived),
                  sample_sizes=[{k:v for k,v in case.items() if k not in ('source','report')} for case in archived],
                  preparation_fixture='PASSED', real_network_requests=0)
    if args.database:
        all_cases, latest, windows = compare_inbox(args.database, args.device, compact)
        result['latest_500_packets_read_only'] = summary(all_cases)
        result['latest_windows_within_slice'] = dict(windows=windows, total=summary(latest), by_kind={
            kind: summary([case for case in latest if case['kind'] == kind])
            for kind in sorted({case['kind'] for case in latest})})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
