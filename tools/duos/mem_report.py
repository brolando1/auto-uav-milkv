# usage: python3 mem_report.py mem_samples.txt  (file produced on the board by tools/duos/mem_sampler.sh)
import sys, statistics, collections
samples = []; cur = None
for line in open(sys.argv[1]):
    f = line.split()
    if not f: continue
    if f[0] == 'T':
        cur = {'t': int(f[1]), 'total': int(f[2]) / 1024, 'avail': int(f[3]) / 1024,
               'swap_used': (int(f[4]) - int(f[5])) / 1024, 'procs': []}
        samples.append(cur)
    elif f[0] == 'P' and cur is not None:
        cur['procs'].append((int(f[1]), int(f[2]), int(f[3]) / 1024, ' '.join(f[4:7])))
t_from = int(sys.argv[2]) if len(sys.argv) > 2 else 0
samples = [s for s in samples if s['t'] >= t_from and s['procs']]
def node_pid(s):
    c = [p for p in s['procs'] if p[3].startswith('python3 -u -m')]
    return c
idle, train = [], []
for s in samples:
    n = node_pid(s)
    if not n: continue
    (train if len(n) >= 2 else idle).append(s)
print(f"samples: {len(samples)} total, {len(idle)} node idle, {len(train)} training child alive  (MemTotal {samples[0]['total']:.0f} MB)")
def show(title, s):
    used = s['total'] - s['avail']
    print(f"\n== {title} ==\n  system: used {used:.0f} MB of {s['total']:.0f} (available {s['avail']:.0f}) | swap used {s['swap_used']:.0f} MB")
    print(f"  {'PID':>6} {'RSS MB':>7}  process")
    tot = 0
    for pid, ppid, rss, name in sorted(s['procs'], key=lambda p: -p[2])[:12]:
        tag = ''
        if name.startswith('python3 -u -m'): tag = '  <- node' if not any(p[0] == ppid and p[3].startswith('python3 -u -m') for p in s['procs']) else '  <- training child (forked)'
        print(f"  {pid:>6} {rss:7.1f}  {name}{tag}"); tot += rss
    print(f"  sum of listed RSS {tot:.0f} MB (RSS of parent and forked child overlap: shared copy-on-write pages count twice)")
if idle:
    # median idle sample by system used
    idle_sorted = sorted(idle, key=lambda s: s['total'] - s['avail']); show("node idle (median sample)", idle_sorted[len(idle_sorted)//2])
    print(f"  idle over {len(idle)} samples: system used {statistics.mean(s['total']-s['avail'] for s in idle):.0f} ± {statistics.pstdev(s['total']-s['avail'] for s in idle):.0f} MB, swap {statistics.mean(s['swap_used'] for s in idle):.0f} MB")
if train:
    peak = max(train, key=lambda s: s['total'] - s['avail']); show("training peak (least available memory)", peak)
    child_peaks = []
    for s in train:
        n = node_pid(s)
        child = [p for p in n if any(q[0] == p[1] for q in n)]
        if child: child_peaks.append(child[0][2])
    print(f"  training child RSS over {len(train)} samples: mean {statistics.mean(child_peaks):.0f} MB, max {max(child_peaks):.0f} MB")
    print(f"  system used during training: mean {statistics.mean(s['total']-s['avail'] for s in train):.0f} MB, max {max(s['total']-s['avail'] for s in train):.0f} MB | swap max {max(s['swap_used'] for s in train):.0f} MB | min available {min(s['avail'] for s in train):.0f} MB")
