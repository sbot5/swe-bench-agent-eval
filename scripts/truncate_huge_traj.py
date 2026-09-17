import json, os, sys, shutil
# 入库前截断超大 traj.json。2026-09-17。
#
# 为什么需要：mini 的 observation_template 只截断「送给模型看的那份」（10000 字符），
# 落盘的 messages[].extra.raw_output 存的是完整输出。断网跑里两条实例因此各 204 MB：
#   sphinx-11510  grep -rn "index-url|proxy" /opt/miniconda3/pkgs/cache/*.json | head
#   sphinx-9711   grep -R "mplcursors|..." /opt /root /testbed | head -20
# conda 的包索引缓存是「单行巨 JSON」，所以 `| head` 取 10~20 行也有 204 MB。
# GitHub 单文件上限 100 MB，不截断就 push 不上去。
#
# 原件不删：备份到 ~/traj-originals/<run>/，不入库。截断处留显式标记与原始字节数。
LIMIT = 64 * 1024        # 单个字符串字段超过这个就截
KEEP = 24 * 1024         # 头尾各保留

def cut(s):
    if not isinstance(s, str) or len(s) <= LIMIT:
        return s, False
    return (s[:KEEP]
            + "\n\n===== [truncate_huge_traj.py] 此处截断：原始 %d 字节，头尾各留 %d =====\n\n" % (len(s), KEEP)
            + s[-KEEP:]), True

def walk(o):
    n = 0
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str):
                nv, hit = cut(v)
                if hit: o[k] = nv; n += 1
            else:
                n += walk(v)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                nv, hit = cut(v)
                if hit: o[i] = nv; n += 1
            else:
                n += walk(v)
    return n

run = sys.argv[1]
base = "/home/zixu/swe-bench-eval/results/inference/" + run
bak = "/home/zixu/traj-originals/" + run
THRESH = 5 * 1024 * 1024  # 只动超过 5MB 的文件
for dirpath, _, files in os.walk(base):
    for f in files:
        if not f.endswith(".traj.json"): continue
        p = os.path.join(dirpath, f)
        sz = os.path.getsize(p)
        if sz <= THRESH: continue
        rel = os.path.relpath(p, base)
        os.makedirs(os.path.dirname(os.path.join(bak, rel)), exist_ok=True)
        shutil.copy2(p, os.path.join(bak, rel))
        d = json.load(open(p))
        n = walk(d)
        json.dump(d, open(p, "w"), ensure_ascii=False)
        print("%-34s %7.1f MB -> %6.2f MB  截断 %d 处  原件备份 %s"
              % (rel, sz / 1e6, os.path.getsize(p) / 1e6, n, os.path.join(bak, rel)))
