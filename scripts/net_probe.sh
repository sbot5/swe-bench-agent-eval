#!/bin/bash
# P1 第一步：证明 `--network none` 在本机 docker 上确实断网，且 loopback 仍可用。
# 成对跑：同一镜像、同一条命令，只差 --network none。2026-09-17。
set -u

IMG=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep sweb.eval | head -1)
echo "image = $IMG"
echo

probe() {
  local label="$1"; shift
  local netargs="$1"; shift
  local cmd="$1"; shift
  local out rc
  out=$(docker run --rm $netargs "$IMG" bash -c "$cmd" 2>&1)
  rc=$?
  printf '%-14s %-18s rc=%-3s %s\n' "$label" "$netargs" "$rc" "$(echo "$out" | tr '\n' ' ' | cut -c1-110)"
}

for NET in "" "--network=none"; do
  tag=$([ -z "$NET" ] && echo WITH-NET || echo NO-NET)
  probe "$tag dns"   "$NET" 'getent hosts github.com >/dev/null && echo RESOLVED || echo DNS-FAIL'
  probe "$tag curl"  "$NET" 'curl -sS --max-time 12 -o /dev/null -w OK-%{http_code} https://github.com || echo CURL-FAIL'
  probe "$tag patch" "$NET" 'curl -sS --max-time 12 -L https://github.com/django/django/pull/11138.patch | wc -c'
  probe "$tag git"   "$NET" 'timeout 15 git ls-remote https://github.com/django/django HEAD 2>&1 | head -1'
  probe "$tag pip"   "$NET" 'timeout 20 pip download --no-deps -d /tmp/pp six 2>&1 | tail -1'
  probe "$tag loop"  "$NET" 'python -c "import socket;s=socket.socket();s.bind((\"127.0.0.1\",0));s.listen(1);p=s.getsockname()[1];c=socket.socket();c.connect((\"127.0.0.1\",p));print(\"LOOPBACK-OK\",p)"'
  echo
done
