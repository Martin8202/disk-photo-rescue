# -*- coding: utf-8 -*-
"""硬碟健康快篩：只讀「先前已成功讀過」的區域，判斷是整體退化還是局部壞軌。
唯讀、不寫入來源碟。用法：python 健康檢測.py [取樣點數]
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rescue_dd as D

MAPF = os.path.join(D.DD_DIR, D.MAP)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
READ_MB = 4
TIMEOUT = 30            # 單點逾時，秒


def good_segments(path):
    """回傳 mapfile 裡狀態為 '+'（已成功讀完）的區段。"""
    segs = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        f = ln.strip().split()
        if len(f) >= 3 and f[0].startswith("0x") and f[1].startswith("0x") and f[2] == "+":
            segs.append((int(f[0], 16), int(f[1], 16)))
    return segs


def pick(segs, n, need):
    """在已讀區段裡挑 n 個分散的取樣點（跳過裝不下 need 位元組的小區段）。"""
    big = [s for s in segs if s[1] >= need]
    if not big:
        return []
    step = max(1, len(big) // n)
    return [big[i][0] + (big[i][1] - need) // 2 for i in range(0, len(big), step)][:n]


def main():
    ip = D.vm_ip()
    rc, out = D.ssh(ip, "true", 30)
    if rc is None:
        print("虛擬機連不上，請先開機並確認 SSH 可用"); return 1
    rc, dev = D.ssh(ip, f"ls -d {D.DEV_GLOB} | grep -v -- -part | head -1", 30)
    dev = (dev or "").strip().split("\n")[-1].strip()
    if not dev:
        print("硬碟沒有出現在 /dev/disk/by-id/，請確認電源與 VMware 的 Connect"); return 1
    print(f"裝置：{dev}")

    rc, out = D.ssh(ip, f"smartctl -d sat -H -A {dev} 2>&1 | head -25", 60)
    print("--- SMART ---")
    print((out or "(取不到)").strip()[:1200])

    segs = good_segments(MAPF)
    need = READ_MB * 1024 * 1024
    pts = pick(segs, N, need)
    print(f"\n--- 取樣讀取：{len(pts)} 點 × {READ_MB} MB（全部取自已成功讀過的區域）---")
    ok = slow = fail = 0
    for i, off in enumerate(pts, 1):
        cmd = (f"timeout {TIMEOUT} dd if={dev} bs=1M count={READ_MB} "
               f"skip={off // (1024*1024)} iflag=direct,skip_bytes of=/dev/null 2>&1 | tail -1")
        t0 = time.time()
        rc, out = D.ssh(ip, cmd, TIMEOUT + 25)
        el = time.time() - t0
        txt = (out or "").strip().replace("\n", " ")
        if rc is None or "copied" not in txt:
            print(f"  {i:2}. {off/1e9:8.1f} GB  逾時/失敗  ({el:.1f}s)  {txt[:60]}")
            fail += 1
        else:
            mbs = READ_MB / el if el > 0 else 0
            tag = "正常" if mbs >= 10 else "緩慢"
            if mbs >= 10: ok += 1
            else: slow += 1
            print(f"  {i:2}. {off/1e9:8.1f} GB  {tag}  {mbs:6.1f} MB/s  ({el:.1f}s)")

    print(f"\n結果：正常 {ok}、緩慢 {slow}、逾時/失敗 {fail}（共 {len(pts)}）")
    if fail == 0 and slow == 0:
        print("判讀：硬碟整體健康，先前的卡住是局部問題 → 可以繼續救援")
    elif fail >= len(pts) // 2:
        print("判讀：多數已知好區都讀不動 → 硬碟整體退化，建議停止並討論後續")
    else:
        print("判讀：部分退化 → 可以繼續，但要有心理準備會很慢，優先救最重要的批次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
