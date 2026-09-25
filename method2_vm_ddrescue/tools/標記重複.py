# -*- coding: utf-8 -*-
"""把「G 槽別處已經有同一個檔案」的待救檔標記成 done_before，不再讀故障碟。

比對：檔名 + 大小 + 修改時間（A 級），或檔名 + 大小（B 級），
且 G 槽上那個檔案實際存在。note 會記下副本在 G 槽的哪個路徑。
"""
import sqlite3, os, collections

DB = r"C:\照片救援\dd.sqlite"
c = sqlite3.connect(DB, timeout=120)

have = collections.defaultdict(list)
for p, s, m, d in c.execute(
        "SELECT path, size, mtime, dst FROM files WHERE status IN ('done','done_before')"):
    have[(os.path.basename(p).lower(), s)].append((m, d))

cache = {}
def on_g(d):
    if d not in cache:
        cache[d] = os.path.exists(d)
    return cache[d]

todo = []
for fid, p, s, m in c.execute("SELECT id, path, size, mtime FROM files WHERE status='new'"):
    cands = have.get((os.path.basename(p).lower(), s))
    if not cands:
        continue
    same = [d for mm, d in cands if mm == m and on_g(d)]
    if same:
        todo.append((fid, same[0], "A")); continue
    any_d = [d for mm, d in cands if on_g(d)]
    if any_d:
        todo.append((fid, any_d[0], "B"))

print(f"要標記的檔案：{len(todo):,}")
c.executemany(
    "UPDATE files SET status='done_before', note=? WHERE id=? AND status='new'",
    [(f"{lv}級重複，G槽已有：{d}", fid) for fid, d, lv in todo])
c.commit()

print("\n標記後的狀態分布：")
for st, n, sz in c.execute(
        "SELECT status, COUNT(*), SUM(size) FROM files GROUP BY status ORDER BY 2 DESC"):
    print(f"  {st:<14}{n:>8,}{(sz or 0)/1e9:>10.2f} GB")

print("\n各批次還要讀的量：")
for b, n, sz in c.execute(
        "SELECT batch, COUNT(*), SUM(size) FROM files WHERE status='new' "
        "GROUP BY batch ORDER BY batch"):
    print(f"  {b}  {n:>7,} 檔  {(sz or 0)/1e9:>8.2f} GB")
