# 給 AI 的說明

這個 repo 是故障硬碟照片救援的工具與操作手冊，有兩種方法：
- `method1_windows_copy/`：透過 Windows 逐檔複製
- `method2_vm_ddrescue/`：硬碟直通進 Linux 虛擬機，用 ddrescue 讀磁區，Windows 端自己解析 NTFS

使用者用繁體中文溝通。給使用者看的內容一律用繁體中文，回報要給數字，不要只給印象。

## 先讀什麼

| 情境 | 讀這些 |
|---|---|
| 使用者要救一顆新的硬碟 | `docs/選擇方法.md` → 選定方法的操作手冊 → `docs/踩過的坑.md` |
| 接手一個正在進行的救援 | 下方「接手正在跑的救援」→ `docs/方法二_虛擬機ddrescue.md` |
| 救援結束，要收尾 | `docs/收尾_恢復電腦原狀.md`（硬碟先拔掉，再跑恢復腳本） |
| 要改程式 | 要改的那支程式最上方的「可調參數」區與 docstring → `docs/踩過的坑.md` 裡相關的類別 |
| 想知道某個設計為什麼長這樣 | `docs/演進過程.md`；程式註解裡的日期（例如「9/20 實測」）對應那裡的時間線 |

## 分工

- **使用者**：所有判斷與拍板。要救哪些、不救哪些、批次順序、能不能自動一批接一批跑、硬碟拔插。
- **開發用的 AI**：規劃、寫程式、分析紀錄與當機原因、提出選項。需要使用者決定的事，要提出選項等他確認，不要自己決定。
- **執行用的 AI**：只負責啟動與轉述，照 `docs/監控AI指令範本.md` 做，不改程式、不做判斷。

## 鐵則

1. **對故障碟只讀不寫**。不執行 chkdsk、fsck、ntfsfix 或任何修復，不用檔案總管打開它。
2. **絕對不做 USB 裝置重置**（`pnputil /restart-device`、`usbreset`、`echo 0 > authorized`）。這曾經造成藍屏。硬碟卡死一律停下來，請使用者拔電源。
3. 方法二進行中，Windows 不能看到這顆硬碟。看到它出現在 Windows，立刻請使用者拔 USB。
4. **不手動修改** mapfile、domain 檔、`dd.sqlite`、`壞軌紀錄.csv`。真的要改，先備份並告訴使用者。
5. 程式正在跑的時候，不要改它正在使用的那份程式檔，也不要在同一份資料上跑會寫入的指令。
6. **不要用 `Stop-Process -Force` 結束正在寫入映像檔的程式**。要停的話，先在虛擬機裡停 ddrescue。
7. 寫給 Windows 的 `.bat` 內容一律純 ASCII + CRLF；`.ps1` 內容保持純 ASCII（Windows PowerShell 5.1 會用系統碼頁讀，中文會變亂碼）。
8. 要在 shell 裡跑多行 Python 或腳本，寫成檔案再執行，不要用 heredoc（反斜線會被吃掉）。

## 改完程式一定要跑的測試

都不需要硬碟和虛擬機，最後一行要是 `SELFTEST OK` 或「全部通過」：

```powershell
# 方法一：改 rescue.py 之後
python method1_windows_copy\rescue.py --selftest

# 方法二：改 rescue_dd.py、rescue2.py 任何一支之後，三個都要跑
python method2_vm_ddrescue\rescue2.py --selftest
python method2_vm_ddrescue\rescue_dd.py --selftest
python method2_vm_ddrescue\test_watchdog.py
```

曾經有一次只跑了 `test_watchdog.py` 就在 commit 訊息裡寫「全部通過」，結果 `rescue_dd.py --selftest` 壞了兩天沒人發現。

自我測試會把工作目錄改到暫存資料夾。新增任何「在 import 時就用 `WORK` 算好的路徑」，都要確認自我測試也有把它改掉（`NEED_HELP` 就曾經漏掉，會清空正在跑的救援的旗標檔）。

## 接手正在跑的救援（方法二）

依序看，都不會碰到硬碟：

1. `REPORT_TXT`（預設 `G:\我的雲端硬碟\!家裡硬碟\進度回報.txt`）：最新狀態，最上面一行是時間。
2. `WORK\需要處理.txt`（預設 `C:\照片救援\`）：有內容就代表程式在等人，裡面寫著原因與步驟。
3. `cd method2_vm_ddrescue` 之後執行 `python rescue_dd.py batches` 與 `python rescue_dd.py report`：各批次狀態與目前這一輪的統計。
4. 有沒有程式在跑：
   ```powershell
   Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='bash.exe'" | Select ProcessId, CommandLine
   ```
5. `WORK` 底下的 `*紀錄.txt`（接續腳本的紀錄）與 `ddrescue_copy_輸出.txt` 的最後 40 行。

判斷卡住要看讀到的資料量有沒有增加（回報的「已讀到」、`python method2_vm_ddrescue\tools\狀態.py` 的 ddrescue 已讀量與「距上次成功讀取」），不要看速度 0.0 MB/s、mapfile 的修改時間或讀取位置（`docs/踩過的坑.md` 第 43、51 條）。補讀（retry）如果幾小時只多讀出幾 MB，提出停損選項給使用者，不要讓它一直刮。

## 監控的做法

AI 只有在使用者傳訊息或背景任務結束時才會被喚醒。所以監控要嘛用 `/loop`，要嘛讓監控程式**達到門檻就結束**（`python method2_vm_ddrescue\tools\狀態.py --until 75`）。只寫日誌、永遠不結束的監控程式，使用者會以為有人在看，其實沒有。
