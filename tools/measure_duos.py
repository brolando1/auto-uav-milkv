# Runs on the PC against the live node: repeated inference windows (fps, per-stage ms, RTT, memory)
# and repeated retrain trials (dump -> new model live, broken down from the child log).
# usage: cd pc && ../venv/bin/python3 ../tools/measure_duos.py [windows=3] [trials=3]
import sys, time, json, statistics, subprocess, re
sys.path.insert(0, '/home/broland/Desktop/milkv-drone/pc')
from pc_node.link_client import DuoLink

IP = '10.2.250.1'
WINDOWS, WINDOW_S = int(sys.argv[1]) if len(sys.argv) > 1 else 3, 30
TRIALS = int(sys.argv[2]) if len(sys.argv) > 2 else 3

def ms(v): return statistics.mean(v) if v else float('nan')
def sd(v): return statistics.pstdev(v) if len(v) > 1 else 0.0
def p95(v): v = sorted(v); return v[int(0.95 * (len(v) - 1))] if v else float('nan')

l = DuoLink(IP); l.start()
t0 = time.time()
while l.snapshot().get('seq') is None:
    time.sleep(0.2)
    if time.time() - t0 > 30: sys.exit("no state frames from the node")
s = l.snapshot()
print(f"node: model {s['model_name']} gen {s['model_gen']} backend {s.get('classifier_backend')} flight {s.get('flight')}\n")

# ---------------- A: inference windows ----------------
win_rows = []; stage_acc = {}; rtts_all = []
for w in range(WINDOWS):
    seen = set(); rtts = []; last_echo = None; t_ping = 0.0
    stage_samples = {}; mem_samples = []
    tw = time.monotonic()
    while time.monotonic() - tw < WINDOW_S:
        now = time.monotonic()
        if now - t_ping > 0.5:
            l.send_command({'cmd': 'ping'}, quiet=True); t_ping = now
        s = l.snapshot()
        if s.get('seq') is not None: seen.add(s['seq'])
        e = s.get('echo_t_pc')
        if e and e != last_echo:
            last_echo = e; rtts.append((time.monotonic() - float(e)) * 1000.0)
        if int((now - tw) * 10) % 10 == 0:   # ~1 Hz
            for k, v in (s.get('timing_ms') or {}).items():
                stage_samples.setdefault(k, []).append(v['mean'])
            m = s.get('mem_mb') or {}
            if m.get('node'): mem_samples.append((m['node']['rss'], m['node']['peak'], m['system']['available'], m['system']['swap_used']))
        time.sleep(0.02)
    dt = time.monotonic() - tw
    fps = len(seen) / dt; cam = (max(seen) - min(seen) + 1) / dt
    win_rows.append((fps, cam, ms(rtts), p95(rtts)))
    rtts_all += rtts
    for k, v in stage_samples.items(): stage_acc.setdefault(k, []).append(ms(v))
    print(f"window {w+1}: processed {fps:5.1f} fps | camera delivered {cam:5.1f} fps | RTT mean {ms(rtts):5.1f} ms p95 {p95(rtts):5.1f} ms (n={len(rtts)}) | node RSS {mem_samples[-1][0]:.0f} MB")

print(f"\n== inference, {WINDOWS} windows x {WINDOW_S} s ==")
print(f"processed fps      {ms([r[0] for r in win_rows]):6.1f} ± {sd([r[0] for r in win_rows]):.1f}")
print(f"camera fps         {ms([r[1] for r in win_rows]):6.1f} ± {sd([r[1] for r in win_rows]):.1f}")
print(f"link RTT ms        {ms(rtts_all):6.1f} mean, p95 {p95(rtts_all):.1f}  (n={len(rtts_all)})")
order = ["jpeg_decode", "preprocess", "classifier", "buffer_filters", "navigator_run", "navigator_per_frame",
         "poll_training", "state_build", "publish", "loop_total", "latency_arrival_to_state"]
print("stage (ms, mean of per-window means ± std across windows):")
for k in order:
    if k in stage_acc: print(f"  {k:26s} {ms(stage_acc[k]):7.2f} ± {sd(stage_acc[k]):.2f}")
m = mem_samples[-1]
print(f"memory: node RSS {m[0]:.0f} MB (peak {m[1]:.0f}) | system available {m[2]:.0f} MB | swap used {m[3]:.0f} MB")

# ---------------- B: retrain trials ----------------
def board_log():
    out = subprocess.run(['ssh', f'debian@{IP}', 'cat ~/milkv/simulation_last.log'], capture_output=True, text=True).stdout
    g = lambda rx: (lambda mm: float(mm.group(1)) if mm else float('nan'))(re.search(rx, out))
    return {
        'setup': g(r"Total setup time\s*=\s*([0-9.]+)s"),
        'latents_reused': bool(re.search(r"using \d+ latents dumped by the node", out)),
        'n_dump': g(r"using (\d+) latents dumped"),
        'items': g(r"total train items = (\d+)"),
        'epochs': [float(x) for x in re.findall(r"epoch \d+/\d+ \| time=([0-9.]+)s", out)],
        'train': g(r"Total training time \(run_training\)\s*=\s*([0-9.]+)s"),
        'export': g(r"ONNX export: .*\(([0-9.]+)s\)"),
    }

trials = []
for t in range(TRIALS):
    time.sleep(12)   # buffer refilled (65 frames at ~20 fps) and the node settled
    s = l.snapshot(); gen0 = s['model_gen']
    t_dump = time.monotonic(); l.send_command({'cmd': 'dump'})
    t_run = t_live = None; peak = 0.0; seen = set(); elapsed_last = 0.0
    while time.monotonic() - t_dump < 120:
        s = l.snapshot(); tr = s.get('training') or {}
        if t_run is None and tr.get('state') == 'running': t_run = time.monotonic()
        if tr.get('state') == 'running':
            elapsed_last = tr.get('elapsed', 0.0)
            mm = ((s.get('mem_mb') or {}).get('training') or {}).get('running')
            if mm: peak = max(peak, mm.get('peak') or 0.0)
            if s.get('seq') is not None: seen.add(s['seq'])
        if s['model_gen'] > gen0: t_live = time.monotonic(); break
        time.sleep(0.03)
    if t_live is None: print(f"trial {t+1}: no new model within 120 s"); continue
    time.sleep(2)
    lg = board_log(); s = l.snapshot()
    train_mem = (s.get('mem_mb') or {}).get('training') or {}
    fps_train = len(seen) / max(1e-6, (t_live - (t_run or t_dump)))
    row = {'start': (t_run - t_dump) if t_run else float('nan'), 'child': (t_live - t_run) if t_run else float('nan'),
           'total': t_live - t_dump, 'peak_mb': train_mem.get('last_peak') or peak, 'fps_during': fps_train, **lg}
    trials.append(row)
    print(f"trial {t+1}: dump->fork {row['start']:.2f} s | child {row['child']:.2f} s | TOTAL dump->live {row['total']:.2f} s | "
          f"setup {lg['setup']:.2f} | epochs {'+'.join(f'{e:.2f}' for e in lg['epochs'])} = {lg['train']:.2f} | export {lg['export']:.2f} | "
          f"latents reused {lg['latents_reused']} ({lg['n_dump']:.0f} dumped, {lg['items']:.0f} items) | child peak RSS {row['peak_mb']} MB | node {fps_train:.1f} fps meanwhile | model {s['model_name']}")

if trials:
    print(f"\n== retrain, {len(trials)} trials (mean ± std) ==")
    def col(k): v = [r[k] for r in trials]; return f"{ms(v):6.2f} ± {sd(v):.2f}"
    ep_n = max(len(r['epochs']) for r in trials)
    print(f"dump -> training forked   {col('start')} s")
    print(f"  child setup             {col('setup')} s")
    for i in range(ep_n):
        v = [r['epochs'][i] for r in trials if len(r['epochs']) > i]; print(f"  epoch {i+1}                 {ms(v):6.2f} ± {sd(v):.2f} s")
    print(f"  training total          {col('train')} s")
    print(f"  ONNX export             {col('export')} s")
    other = [r['child'] - r['setup'] - r['train'] - r['export'] for r in trials]
    print(f"  ckpt load/save/other    {ms(other):6.2f} ± {sd(other):.2f} s  (child wall minus the three above)")
    print(f"  child wall              {col('child')} s")
    print(f"dump -> new model live    {col('total')} s")
    print(f"training child peak RSS   {col('peak_mb')} MB")
    print(f"node fps while training   {col('fps_during')}")
    s = l.snapshot(); m = s.get('mem_mb') or {}
    print(f"node RSS after trials     {m['node']['rss']:.0f} MB (peak {m['node']['peak']:.0f}) | system available {m['system']['available']:.0f} MB | swap used {m['system']['swap_used']:.0f} MB")
