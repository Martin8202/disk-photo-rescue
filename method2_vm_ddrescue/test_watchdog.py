# -*- coding: utf-8 -*-
"""針對 9/20 新增的看門狗與危險區機制的測試。不需要虛擬機、不需要硬碟。

    python test_watchdog.py

測的是「硬碟一直掛掉」這件事的處理邏輯：危險區能不能正確累積與合併、
會不會真的從讀取範圍裡被扣掉、以及扣掉之後那些資料是不是仍留在最後補讀的範圍內。
"""
import os, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rescue2 as R

WORK = tempfile.mkdtemp(prefix="test_wd_")
R.WORK, R.DB = WORK, os.path.join(WORK, "t.sqlite")
import rescue_dd as D

D.DD_DIR = WORK
D.NEED_HELP = os.path.join(WORK, "需要處理.txt")
GB = 10**9


def test_map_pos():
    """map_pos 要能從 ddrescue 的 mapfile 讀出目前位置與多久沒更新。"""
    p = os.path.join(WORK, "m.map")
    with open(p, "w", encoding="ascii", newline="\n") as f:
        f.write("# Mapfile. Created by GNU ddrescue version 1.30\n"
                "# Command line: ddrescue ...\n"
                "# Start time:   2026-09-20 13:57:51\n"
                "# current_pos  current_status  current_pass\n"
                "0x23CE399B000     ?               1\n"
                "#      pos        size  status\n"
                "0x00000000  0x10000000  +\n")
    pos, stale = D.map_pos(p)
    assert pos == 0x23CE399B000, pos
    assert abs(pos / GB - 2460.5) < 0.1, pos / GB          # 就是 9/20 掉線的那個位置
    assert stale is not None and stale < 60, stale
    # 檔案不存在要安全回傳 None，不能炸掉看門狗
    assert D.map_pos(os.path.join(WORK, "沒這個檔.map")) == (None, None)
    print("  map_pos 正確讀出位置與更新時間")


def test_hostile_merge():
    """重疊的危險區要合併，不能越記越碎。"""
    c = R.db_open()
    D.ensure_columns(c)
    D.add_hostile(c, 2255 * GB, 2265 * GB, "第一次掛掉")
    assert D.hostile_zones(c) == [(2255 * GB, 2265 * GB)]
    D.add_hostile(c, 2260 * GB, 2270 * GB, "第二次掛在隔壁")      # 重疊 → 併成 2255~2270
    assert D.hostile_zones(c) == [(2255 * GB, 2270 * GB)], D.hostile_zones(c)
    D.add_hostile(c, 500 * GB, 510 * GB, "另一個不相鄰的位置")     # 不重疊 → 各自獨立
    assert D.hostile_zones(c) == [(500 * GB, 510 * GB), (2255 * GB, 2270 * GB)]
    print("  危險區重疊會合併、不相鄰會分開")
    return c


def test_domain_masking(c):
    """危險區要真的從讀取範圍被扣掉，而且扣掉的部分必須維持『沒讀過』，
    這樣最後的 retry（條件 state IN ('bad','new')）才會回頭補讀，資料不會就此消失。"""
    dom = os.path.join(WORK, "domain_t.map")
    # 一段涵蓋危險區的讀取範圍
    D.write_map(dom, [(2250 * GB, 30 * GB, "+")])
    before = D.tally(dom, dom)["+"]
    n = D.mark_unread(dom, [(a, b - a) for a, b in D.hostile_zones(c)])
    after = D.tally(dom, dom)["+"]
    assert n > 0, "應該要有東西被標記為未讀"
    assert after < before, (before, after)
    assert abs((before - after) - 15 * GB) < D.SECTOR * 2, (before - after) / GB   # 2255~2270 = 15 GB
    # 被扣掉的區段狀態必須是 '?'（沒讀過），不能是 'bad' 或被刪掉
    idx = D.MapIndex(D.read_map(dom))
    assert all(st == "?" for _, _, st in idx.segments(2256 * GB, 1 * GB)), "危險區應維持『沒讀過』"
    print(f"  危險區 15 GB 已從讀取範圍扣除，且維持『沒讀過』（retry 時會回頭補）")


def test_incidents(c):
    """故障事件要記得下來，才能判斷是不是同一個位置重複掛掉。"""
    D.add_incident(c, "硬碟掉線", 2460 * GB, "測試")
    D.add_incident(c, "硬碟掉線", 2461 * GB, "測試")
    D.add_incident(c, "位置卡死", 100 * GB, "測試")
    n, _ = D.recent_incidents(c, "硬碟掉線", 60)
    assert n == 2, n
    n, _ = D.recent_incidents(c, "位置卡死", 60)
    assert n == 1, n
    n, _ = D.recent_incidents(c, "硬碟掉線", 0)          # 時間窗為 0 → 不該算到剛剛那幾筆
    print("  故障事件記錄與時間窗查詢正確")


def test_need_help(c):
    """要人處理時必須留下旗標檔，內容看得懂該做什麼。"""
    D.S["stage"], D.S["state"] = "測試", "測試中"
    D.need_help(c, None, "硬碟掉線了，請關電源等 10 秒再開")
    assert os.path.exists(D.NEED_HELP)
    txt = open(D.NEED_HELP, encoding="utf-8-sig").read()
    assert "關電源" in txt, txt
    D.clear_need_help()
    assert open(D.NEED_HELP, encoding="utf-8-sig").read().strip() == ""
    print("  需要處理旗標檔會正確寫入與清除")


def test_folder_domain(c):
    """--folder：讀取範圍必須只涵蓋指定資料夾底下還沒救到的檔案，
    別的資料夾、以及同資料夾裡已經救到的檔案，都不可以被排進去讀。"""
    c.executescript("""
    CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, mft INT, path TEXT, size INT,
        mtime REAL, atime REAL, dst TEXT, status TEXT, note TEXT, bad_bytes INT,
        orphan INT, batch TEXT, freed INT);
    CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, file_id INT, foff INT,
        dev_off INT, nbytes INT, state TEXT);
    DELETE FROM files; DELETE FROM chunks;
    """)
    R.meta_set(c, "disk_size", str(3000 * GB))   # domain_blocks 會用它當上限，沒設會算出空範圍
    rows = [
        # (id, 路徑, 狀態, dev_off, nbytes)
        (1, r"E:\A\想讀的\a1.jpg", "new",         700 * GB, 4 * GB),
        (2, r"E:\A\想讀的\a2.jpg", "new",         710 * GB, 4 * GB),
        (3, r"E:\A\想讀的\已救.jpg", "done",       720 * GB, 4 * GB),   # 已救到，不必再讀
        (4, r"E:\A\想讀的\別處有.jpg", "done_before", 730 * GB, 4 * GB), # G 槽已有，不必再讀
        (5, r"E:\A\別的資料夾\b1.jpg", "new",      740 * GB, 4 * GB),   # 不同資料夾
        (6, r"E:\A\想讀的更深\c1.jpg", "new",      750 * GB, 4 * GB),   # 前綴相近但不同層
    ]
    for fid, path, status, off, nb in rows:
        c.execute("INSERT INTO files(id, path, size, status, batch) VALUES(?,?,?,?,?)",
                  (fid, path, nb, status, "bXX"))
        c.execute("INSERT INTO chunks(file_id, foff, dev_off, nbytes, state) VALUES(?,?,?,?,?)",
                  (fid, 0, off, nb, "new"))
    c.commit()

    like = r"E:\A\想讀的" + "\\%"
    dom = "domain_folder_test.map"
    D.write_domain(c, dom, "f.path LIKE ? AND f.status NOT IN ('done_before','unsupported')", (like,))
    idx = D.MapIndex(D.read_map(os.path.join(WORK, dom)))

    def inside(off):
        return any(st == "+" for _, _, st in idx.segments(off + 1 * GB, 1 * GB))

    assert inside(700 * GB), "想讀的/a1.jpg 應該在讀取範圍內"
    assert inside(710 * GB), "想讀的/a2.jpg 應該在讀取範圍內"
    assert inside(720 * GB), "已救到的檔案仍在範圍內（status='done' 不在排除清單，之後由 extract 判定）"
    assert not inside(730 * GB), "done_before 的檔案不可以再讀一次"
    assert not inside(740 * GB), "別的資料夾不可以被排進來"
    assert not inside(750 * GB), "『想讀的更深』不是『想讀的』的子資料夾，不可以被排進來"

    n = c.execute("SELECT COUNT(*) FROM files WHERE path LIKE ? AND status='new'", (like,)).fetchone()[0]
    assert n == 2, n
    print("  --folder 只涵蓋指定資料夾底下該讀的檔案，不會誤抓鄰近同名資料夾")
    return like, dom


def test_folder_report(c, folder_ctx):
    """9/21 踩到的坑：batch_report 在 --folder 模式下曾經拿 bid='資料夾' 這個假批次代號
    去篩 WHERE batch=?，資料表裡從來沒有這個值，篩出來全是 0，整份批次結束報告是假的
    （檔案明明已經交付，報告卻寫『已完整救回 0』）。folder 模式必須改用路徑篩選。"""
    like, dom = folder_ctx
    text = D.batch_report(c, "資料夾", dom, folder=r"E:\A\想讀的")
    assert "已完整救回 1" in text, text        # 只有 a1.jpg 這一個是 done 狀態（見 test_folder_domain 的建表）
    assert "已完整救回 0" not in text, "folder 模式篩到 0 筆，代表又退回舊的錯誤篩選方式了"
    print("  batch_report 在 --folder 模式下用路徑篩選，統計數字正確而不是全部歸零")


def test_need_to_free(c):
    """空間夠就不該打洞。打洞會把稀疏映像檔切碎，9/20 實測累積到 193 萬個片段後
    撞上 NTFS 上限，所有寫入與打洞全部失敗。只有空間真的不夠時才值得付這個代價。"""
    c.execute("DELETE FROM files")
    c.execute("INSERT INTO files(id, path, size, status, batch) VALUES(1,'E:\\x.bin',?, 'new','bXX')",
              (100 * GB,))
    c.commit()
    real = D.free_bytes
    try:
        D.free_bytes = lambda p: 900 * GB      # 剩 900 GB，要救 100 GB → 綽綽有餘
        assert D.need_to_free(c) is False, "空間充足時不該打洞"
        D.free_bytes = lambda p: 120 * GB      # 剩 120 GB，要救 100 GB → 150 GB 門檻不夠
        assert D.need_to_free(c) is True, "空間不足時必須打洞"
    finally:
        D.free_bytes = real
    print("  空間充足時不打洞、不足時才打（避免把映像檔切碎撞上 NTFS 片段上限）")


def test_sparse_guard():
    """9/21 踩到的坑：ensure_sparse_image 原本只有 cmd_mft 會呼叫。映像檔被刪掉後
    沒再跑過 mft，ddrescue 就自己在 SMB 上建了普通檔案；非稀疏檔寫到 2744 GB 位置時
    NTFS 從 0 開始配置填零，半小時吃掉 511 GB 把 C 槽塞爆。
    這個防護必須真的會擋下非稀疏檔，而且 cmd_copy 每次都要呼叫它。"""
    import inspect
    src = inspect.getsource(D.cmd_copy)
    assert "ensure_sparse_image" in src, "cmd_copy 必須呼叫 ensure_sparse_image，否則映像檔可能非稀疏"

    # 造一個「存在但不是稀疏」的檔案，防護必須拒絕它
    fake = os.path.join(WORK, "notsparse.img")
    with open(fake, "wb") as f:
        f.write(bytes(4096))
    try:
        D.ensure_sparse_image(fake, 4096)
        raise AssertionError("非稀疏檔應該要被擋下來，卻通過了")
    except RuntimeError as e:
        assert "稀疏" in str(e), e
    print("  非稀疏映像檔會被擋下，且 cmd_copy 每次都會做這個檢查")


def test_mount_opts():
    """SMB 掛載必須關掉客戶端寫入快取，否則硬碟卡住時髒頁會堆在 Windows 記憶體裡
    （9/20 實測 24 小時 11,885 次延遲寫入失敗，Modified Page List 漲到 13.5 GB）。"""
    o = D.VmRunner.MOUNT_OPTS
    assert "cache=none" in o, o
    assert "cache=strict" not in o and "cache=loose" not in o, o
    assert "vers=3.1.1" in o, o                      # 版本別被改掉
    assert "credentials=/root/.smbcred" in o, o      # 密碼不能出現在指令列
    assert "password=" not in o, "密碼不可以寫進掛載選項（會出現在 ps 和日誌裡）"
    print("  SMB 掛載已關閉客戶端寫入快取，且密碼不會出現在指令列")


def test_retry_zones(c):
    """9/24：retry 分兩段。safe 必須把危險區扣掉、其他照讀；danger 必須只剩危險區。
    扣錯了等於一開始就去讀會讓硬碟整顆鎖死的位置，安全區的壞區可能再也來不及補讀。"""
    c.executescript("DELETE FROM files; DELETE FROM chunks; DELETE FROM hostile;")
    for fid, off in ((11, 500 * GB), (12, 1050 * GB), (13, 1500 * GB)):       # 12 在危險區裡
        c.execute("INSERT INTO files(id, path, size, status, batch) VALUES(?,?,?,?,?)",
                  (fid, f"E:\\r{fid}.jpg", 4 * GB, "new", "bXX"))
        c.execute("INSERT INTO chunks(file_id, foff, dev_off, nbytes, state) VALUES(?,?,?,?,?)",
                  (fid, 0, off, 4 * GB, "bad"))
    c.commit()
    D.add_hostile(c, 1000 * GB, 1100 * GB, "測試")
    for zones, want in ((None, {500, 1050, 1500}), ("safe", {500, 1500}), ("danger", {1050})):
        dom = f"domain_retry_{zones}.map"
        D.write_domain(c, dom, "ch.state='bad' AND f.status='new'")
        D.limit_zones(c, os.path.join(WORK, dom), zones)
        idx = D.MapIndex(D.read_map(os.path.join(WORK, dom)))
        got = {g for g in (500, 1050, 1500) if any(st == "+" for _, _, st in idx.segments((g + 1) * GB, GB))}
        assert got == want, (zones, got)
    print("  retry --zones safe 不碰危險區、danger 只讀危險區、不指定時全部都讀")


def run_stall_sim(c, gained):
    """跑真正的 cmd_copy 主迴圈，只換掉時鐘、ddrescue 與硬碟：
    每次重啟 ddrescue 先回到範圍開頭（94 GB）90 秒、再回到卡點（98 GB）；跑 10 分鐘自己結束（-T 10m）；
    結束後硬碟卡死 8 分鐘才恢復。gained(秒) 給出目前讀到的位元組數。
    回傳 (第幾秒被記成危險區, 危險區範圍)；模擬滿 4 小時都沒跳過就回傳 (None, None)。"""
    class Clock:                                     # 假時鐘：sleep 只推進時間，不真的等
        now = 0.0
        def time(self):
            return self.now
        def __getattr__(self, name):
            return getattr(time, name)
    clock = Clock()

    class Done(Exception):
        pass

    def fake_sleep(sec):
        clock.now += sec
        if clock.now > 4 * 3600:
            raise Done

    class Runner:
        size, started_at = 3000 * GB, 0.0
        def start(self, domain, opts):
            self.started_at = clock.now
        def running(self):
            return clock.now - self.started_at < 600
        def stop(self, wait=0):
            self.started_at = -10**9
        def drive_present(self):
            return True
        def status_line(self):
            return ""

    real = {k: getattr(D, k) for k in ("time", "host_sees_drive", "map_pos", "tally", "wait_drive",
                                       "step_extract", "emit", "ensure_sparse_image", "add_hostile")}
    hit = []

    def add_hostile(c_, a, b, reason):
        hit.append((clock.now, (a, b)))
        raise Done

    run = Runner()
    R.meta_set(c, "plan", "測試")
    R.meta_set(c, "batch_done_bXX", "測試")
    try:
        D.time = clock
        D.host_sees_drive = lambda: False
        D.map_pos = lambda p: ((94 if clock.now - run.started_at < 90 else 98) * GB, 0)
        D.tally = lambda dp, mp: {"+": gained(clock.now), "?": 100 * 10**6, "retry": 0, "-": 0, "bad": 0}
        D.wait_drive = lambda runner, c_, domain, sleep: (sleep(8 * 60), True)[1]
        D.step_extract = lambda *a, **k: False
        D.emit = lambda *a, **k: None
        D.ensure_sparse_image = lambda *a, **k: None
        D.add_hostile = add_hostile
        try:
            D.cmd_copy(run, c, retry=True, sleep=fake_sleep, zones="safe")
            raise AssertionError("cmd_copy 不該自己結束")
        except Done:
            pass
    finally:
        for k, v in real.items():
            setattr(D, k, v)
    return hit[0] if hit else (None, None)


def test_stall_across_restarts(c):
    """9/24 補讀實測：同一個卡點（98.0 GB）讓硬碟每半小時卡死一次、空轉約 6 小時都沒被跳過。
    兩個原因：計時每次重啟歸零（每輪都不滿 45 分鐘），以及用「讀取位置」判斷前進——
    -A 重啟時位置會先跳回範圍開頭再回到卡點，被當成有動。看門狗必須跨重啟累計、看讀到的資料量。"""
    at, zone = run_stall_sim(c, lambda now: 0)                      # 完全讀不到新資料
    assert at is not None, "模擬 4 小時仍沒跳過卡點：計時又被重啟或位置跳動歸零了"
    a, b = zone
    assert a < 98 * GB < b, (a / GB, b / GB)
    assert D.HANG_WAIT_MIN * 60 <= at <= (D.HANG_WAIT_MIN + 20) * 60, at / 60
    at2, _ = run_stall_sim(c, lambda now: int(now // 600) * 2 * 10**6)   # 慢但持續：每 10 分鐘多 2 MB
    assert at2 is None, f"持續有讀到資料卻在第 {at2 / 60:.0f} 分鐘被當成卡住"
    print(f"  同一點重複卡住時跨重啟累計、不受位置跳動影響，第 {at / 60:.0f} 分鐘跳過；有持續讀到資料則不會誤判")


if __name__ == "__main__":
    print("測試看門狗與危險區機制：")
    test_map_pos()
    c = test_hostile_merge()
    test_domain_masking(c)
    test_incidents(c)
    test_need_help(c)
    ctx = test_folder_domain(c)
    test_folder_report(c, ctx)
    test_need_to_free(c)
    test_sparse_guard()
    test_mount_opts()
    test_retry_zones(c)
    test_stall_across_restarts(c)
    print("全部通過")
