# Runs ON the Duo S: samples /proc/meminfo + per-process RSS once a second into ~/mem_samples.txt
# while ~/mem_sampler.run exists (touch it to start, rm it to stop). Analyse with tools/duos/mem_report.py.
rm -f ~/mem_samples.txt
while [ -f ~/mem_sampler.run ]; do
  {
    echo "T $(date +%s) $(awk '/MemTotal|MemAvailable|SwapTotal|SwapFree/ {printf "%s ", $2}' /proc/meminfo)"
    ps -eo pid,ppid,rss,args --sort=-rss | awk 'NR>1 && $3>2000 {printf "P %s %s %s %s %s %s\n", $1, $2, $3, $4, $5, $6}' | cut -c1-120
  } >> ~/mem_samples.txt
  sleep 1
done
