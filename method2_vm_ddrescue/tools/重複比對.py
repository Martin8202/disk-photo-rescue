# -*- coding: utf-8 -*-
"""比對「還沒救到的檔案」與「已經救到的檔案」，找出不必再讀故障碟的重複檔。

比對方式（無法對未讀檔案算雜湊，只能用中繼資料）：
  A 級：檔名 + 大小 + 修改時間 都相同，且 G 槽上確實存在 → 幾乎確定是同一個檔
  B 級：檔名 + 大小 相同（修改時間不同），且 G 槽上確實存在 → 很可能是同一個檔
輸出：C:\照片救援\重複比對報告.txt
"""
import sqlite3, os, collections

DB = r"C:\照片救援\dd.sqlite"
OUT = r"C:\照片救援\重複比對報告.txt"

c = sqlite3.connect(DB)

# 已交付的檔案：以 (檔名, 大小) 當索引，記下 dst 與 mtime
have = collections.defaultdict(list)
for p, s, m, d in c.execute(
        "SELECT path, size, mtime, dst FROM files WHERE status IN ('done','done_before')"):
    have[(os.path.basename(p).lower(), s)].append((m, d))

pending = c.execute(
    "SELECT id, batch, path, size, mtime FROM files WHERE status='new'").fetchall()

exists_cache = {}
def on_g(d):
    if d not in exists_cache:
        exists_cache[d] = os.path.exists(d)
    return exists_cache[d]

A, B, uniq = [], [], []
for fid, batch, p, s, m in pending:
    cands = have.get((os.path.basename(p).lower(), s))
    if not cands:
        uniq.append((fid, batch, p, s)); continue
    same_m = [d for mm, d in cands if mm == m and on_g(d)]
    if same_m:
        A.append((fid, batch, p, s, same_m[0])); continue
    any_d = [d for mm, d in cands if on_g(d)]
    if any_d:
        B.append((fid, batch, p, s, any_d[0]))
    else:
        uniq.append((fid, batch, p, s))

L = []
def w(t=""):
    L.append(t); print(t)

tot_n = len(pending); tot_sz = sum(r[3] or 0 for r in pending)
w(f"待救檔案總計：{tot_n:,} 個，{tot_sz/1e9:.2f} GB")
w()
for name, arr in (("A 級（檔名+大小+時間相同，G 槽已存在）", A),
                  ("B 級（檔名+大小相同，G 槽已存在）", B),
                  ("獨有（沒有其他副本）", uniq)):
    n = len(arr); sz = sum(r[3] or 0 for r in arr)
    w(f"{name}：{n:,} 個，{sz/1e9:.2f} GB（占 {sz/tot_sz*100 if tot_sz else 0:.1f}%）")
w()

w("=== 依批次拆解 ===")
w(f"{'批次':<6}{'獨有檔數':>10}{'獨有GB':>10}{'重複檔數':>10}{'重複GB':>10}")
bat = collections.defaultdict(lambda: [0, 0, 0, 0])
for _, b, _, s in uniq:
    bat[b][0] += 1; bat[b][1] += (s or 0)
for arr in (A, B):
    for _, b, _, s, _ in arr:
        bat[b][2] += 1; bat[b][3] += (s or 0)
for b in sorted(bat):
    u_n, u_s, d_n, d_s = bat[b]
    w(f"{b:<6}{u_n:>10,}{u_s/1e9:>10.2f}{d_n:>10,}{d_s/1e9:>10.2f}")
w()

w("=== 重複檔案最多的來源資料夾（前 20）===")
fold = collections.defaultdict(lambda: [0, 0])
for arr in (A, B):
    for _, b, p, s, _ in arr:
        f = os.path.dirname(p)
        fold[f][0] += 1; fold[f][1] += (s or 0)
for f, (n, s) in sorted(fold.items(), key=lambda kv: -kv[1][1])[:20]:
    w(f"  {n:>6} 檔 {s/1e9:>8.2f} GB  {f}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(L) + "\n")
print(f"\n報告已寫出：{OUT}")
