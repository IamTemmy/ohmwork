"""D20 reproducible isolated-process performance gate (run with PYTHONPATH=src).

Each fixture builds SOP/POS maps with independent validation plus both rail-mode
syntheses and their exact circuit maps. Child processes enforce a 10-second
wall-clock gate; production searches have separate deterministic work/storage
limits. Peak RSS includes the Python interpreter. No browser work is measured.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import random
import resource
import subprocess
import sys
import time


def fixtures():
    from ohmwork.api import resolve_truth_table
    for name, expr in [('aoi32', "(abc+de)'"), ('nand5', "(abcde)'"),
                       ('nor5', "(a+b+c+d+e)'"), ('oai', "((a+b)(c+d)e)'"),
                       ('shared', "a'b+c'd+e"), ('parity', 'a^b^c^d^e')]:
        _, ones, dc = resolve_truth_table(expr=expr)
        yield {'name': name, 'ones': sorted(ones), 'dc': sorted(dc)}
    rng = random.Random(20260922)
    for i in range(64):
        values = [rng.choice(('0011X','011111X','000001X','01XXXX')[i%4]) for _ in range(32)]
        ones = [j for j,v in enumerate(values) if v=='1']
        dc = [j for j,v in enumerate(values) if v=='X']
        if not ones or len(ones)+len(dc)==32 or not any(v=='0' for v in values):
            continue
        yield {'name': f'seeded-{i}', 'ones': ones, 'dc': dc}


def worker(fixture):
    from ohmwork import kmap, search_budget
    from ohmwork.synth import _synthesize
    budgets = []
    class MeasuredBudget(search_budget.SearchBudget):
        def __init__(self):
            super().__init__()
            budgets.append(self)
    # Observe counters only; use the unchanged production limits/check routine.
    search_budget.SearchBudget = kmap.SearchBudget = MeasuredBudget
    ones, dc = set(fixture['ones']), set(fixture['dc'])
    start = time.perf_counter()
    maps = [kmap._build_kmap(list('abcde'), ones, dc, form=f) for f in ('SOP','POS')]
    results = [_synthesize(list('abcde'),ones,dc,dual_rail=dual) for dual in (False,True)]
    for result in results:
        kmap._build_synthesis_kmap(result)
    elapsed = time.perf_counter()-start
    return {**fixture, 'seconds': round(elapsed,6), 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // (1024 if sys.platform == 'darwin' else 1),
            'candidates': [len(r.other_candidates) for r in results],
            'tied_covers': [len(m.alternatives) for m in maps],
            'max_search_work': max((b.work for b in budgets), default=0),
            'max_search_items': max((b.peak_items for b in budgets), default=0)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker')
    parser.add_argument('--output', default='test-artifacts/five-variable-performance.json')
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.loads(args.worker))))
        return
    rows=[]
    for fixture in fixtures():
        completed = subprocess.run([sys.executable,__file__,'--worker',json.dumps(fixture)],
                                   check=True, capture_output=True,text=True,timeout=10)
        row=json.loads(completed.stdout)
        # The per-fixture process includes startup; measured work must also fit
        # 128 MiB RSS. Any failure blocks this gate, never silently skips a case.
        if row['peak_rss_kib'] > 128*1024:
            raise RuntimeError(f"RSS gate exceeded: {row['name']}")
        rows.append(row)
    result={'python':sys.version, 'platform':platform.platform(), 'cpu_count':os.cpu_count(),
            'gate':{'subprocess_timeout_seconds':10,'peak_rss_mib':128}, 'fixtures':rows}
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'fixtures':len(rows), 'slowest':max(rows,key=lambda r:r['seconds']),
                      'peak_rss_kib':max(r['peak_rss_kib'] for r in rows),
                      'max_search_work':max(r['max_search_work'] for r in rows),
                      'max_search_items':max(r['max_search_items'] for r in rows)},indent=2))


if __name__=='__main__': main()
