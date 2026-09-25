# -*- coding: utf-8 -*-
"""救援狀態查詢。固定腳本，測試過就重複使用，不要每次用 heredoc 現寫
（9/21 教訓：heredoc 會吃掉反斜線，監控腳本每輪都 SyntaxError 卻沒人發現）。

    python 狀態.py            一次性報告
    python 狀態.py --until 75 完成度達 75% 就結束（結束才會喚醒 Claude）
    python 狀態.py --until 100
"""
import os
import sqlite3
import sys
import time

DB = r"C:\照片救援\dd.sqlite"
DD_DIR = r"C:\PhotoRescueDD"
RUN_LOG = os.path.join(DD_DIR, "ddrescue_run.log")
NEED_HELP = r"C:\照片救援\需要處理.txt"

# 這一輪不算進進度的資料夾（範例：使用者說可以晚點再救的遊戲、錄音）
SKIP_PREFIX = (
    os.path.join("E:", os.sep, "game") + os.sep,
    os.path.join("E:", os.sep, "家人B", "個人", "music") + os.sep,
)
TOTAL = 1745          # 這一輪開始時的待救檔案數：開始前先跑一次本程式，把「剩 N」的 N 填進來


def in_scope_left(conn):
    """本次範圍還剩幾個檔案沒救到。"""
    n = 0
    for (p,) in conn.execute("SELECT path FROM files WHERE status='new'"):
        if not any(p.startswith(k) for k in SKIP_PREFIX):
            n += 1
    return n


def ddrescue_state():
    """從 ddrescue 自己的輸出取得真實進度。

    9/21 教訓：不要用 mapfile 的 mtime 判斷卡住 —— SMB 快取會讓它失真，
    而且資料稀疏時位置本來就變化很慢。要看 ddrescue 自己回報的
    rescued 位元組數與 time since last successful read。
    """
    out = {}
    try:
        txt = open(RUN_LOG, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    # 檔案用 \r 覆寫畫面，取最後一個畫面
    frame = txt.replace("\r", "\n").rstrip().split("\n")
    def grab(line, key):
        return line.split(key, 1)[1].split(",")[0].strip()

    for line in frame[-12:]:
        # ddrescue 每行有多個欄位，所以不能抓到一個就跳出。
        # 而 "rescued:" 是 "pct rescued:" 的子字串，必須先判斷是不是百分比那行。
        if "pct rescued:" in line:
            out["pct"] = grab(line, "pct rescued:")
        elif "rescued:" in line:
            out["rescued"] = grab(line, "rescued:")
        for key, label in (("bad areas:", "bad_areas"), ("read errors:", "read_errors"),
                           ("last successful read:", "since_read"),
                           ("remaining time:", "eta")):
            if key in line:
                out[label] = grab(line, key)
    return out


def report(conn):
    left = in_scope_left(conn)
    done = TOTAL - left
    pct = done * 100.0 / TOTAL
    rows = dict(conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status").fetchall())
    d = ddrescue_state()

    print(f"[{time.strftime('%H:%M:%S')}] 本次範圍 {pct:.1f}%  ({done:,}/{TOTAL:,}，剩 {left:,})")
    print(f"    全庫已救回 {rows.get('done', 0):,} 檔；G 槽已有 {rows.get('done_before', 0):,}")
    if d:
        print(f"    ddrescue: 已讀 {d.get('rescued', '?')}  {d.get('pct', '?')}  "
              f"壞區 {d.get('bad_areas', '?')}  讀取錯誤 {d.get('read_errors', '?')}")
        print(f"              距上次成功讀取 {d.get('since_read', '?')}  預估剩餘 {d.get('eta', '?')}")
    if os.path.exists(NEED_HELP) and os.path.getsize(NEED_HELP) > 0:
        print("    ★ 需要處理.txt 有內容，請查看")
    return pct, left


def main():
    until = None
    if "--until" in sys.argv:
        until = float(sys.argv[sys.argv.index("--until") + 1])

    conn = sqlite3.connect(DB, timeout=60)
    if until is None:
        report(conn)
        return 0

    for _ in range(300):                       # 最多約 5 小時
        try:
            pct, left = report(conn)
        except Exception as e:                 # 查詢失敗不該讓監控整個死掉
            print(f"[{time.strftime('%H:%M:%S')}] 查詢失敗：{e}", flush=True)
            time.sleep(60)
            continue
        if left == 0 or pct >= until:
            print(f">>> 達成門檻 {until}%（目前 {pct:.1f}%），結束以便通知", flush=True)
            return 0
        if os.path.exists(NEED_HELP) and os.path.getsize(NEED_HELP) > 0:
            print(">>> 需要人工處理，結束以便通知", flush=True)
            return 0
        sys.stdout.flush()
        time.sleep(60)
    print(">>> 監控逾時結束", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
