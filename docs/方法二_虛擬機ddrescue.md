# 方法二：虛擬機 + ddrescue（`method2_vm_ddrescue/`）

故障硬碟透過 USB 直通接進 VMware 虛擬機，由虛擬機裡的 Linux 和 GNU ddrescue 以唯讀方式讀磁區。Windows 端的控制程式負責：自己解析 NTFS 的 MFT、決定要讀哪些位置、把讀到的檔案從映像檔輸出到目的地。

**適用**：硬碟會整顆卡死、USB 反覆重置、MFT 損毀、已經讓 Windows 當機過。
**這次的成果**：223,472 檔、1.2 TB。

## 為什麼要繞一圈用虛擬機

- 兩次當機都發生在 **Windows 自己的 USB 儲存驅動（UASPStor）讀壞軌**的時候：驅動在壞磁區上反覆重試、重置裝置，最後拖垮整台電腦。
- WSL2、Hyper-V 的硬碟直通底層還是走 Windows 的儲存驅動，躲不掉。
- VMware 的 **USB 裝置直通**只轉送 USB 封包，SCSI 讀取、逾時、錯誤處理都由虛擬機裡的 Linux 負責。Linux 卡住，最多是虛擬機卡住。
- GNU ddrescue 是壞軌救援的標準工具：讀失敗就跳過、記在 mapfile，可以中斷接續，也可以只讀指定範圍。

## 架構

```
 Windows 主機                                        VMware 虛擬機（SystemRescue 光碟開機，不安裝）
 ┌───────────────────────────────────────┐          ┌─────────────────────────────────────────┐
 │ rescue_dd.py（控制程式）                 │── SSH ──▶│ ddrescue（輸入裝置設成唯讀 blockdev --setro）│
 │  - 從映像檔解析 MFT，比對目的地          │          │                                         │
 │  - 產生 domain 檔（這一輪要讀的範圍）    │          │ /mnt/dd  ◀── SMB 掛載（cache=none）       │
 │  - 看門狗、危險區、5 分鐘回報            │          └───────────────▲─────────────────────────┘
 │  - 從映像檔輸出檔案到 G 槽、寫壞檔清單   │                          │ USB 直通
 │ rescue2.py（NTFS/MFT 解析函式庫）        │                   故障硬碟（Windows 看不到）
 │                                        │
 │ C:\PhotoRescueDD\（SMB 共用）           │
 │   seagate.img   稀疏映像檔，位移 = 硬碟位移 │
 │   seagate.map   ddrescue mapfile         │
 │   domain_*.map  每一輪要讀的範圍          │
 └───────────────────────────────────────┘
```

- 映像檔的位移和實體硬碟位移完全相同，所以從 MFT 算出的每個檔案位置可以直接拿來讀映像檔。
- 映像檔是 NTFS **稀疏檔**，只佔實際讀到的資料量（3 TB 的邏輯大小，實際只用掉一批的量）。
- 資料只讀「G 槽還沒有的檔案」所在的磁區，不做整碟映像。

## 需要的東西

| 項目 | 說明 |
|---|---|
| VMware Workstation Pro | 個人使用免費，從 Broadcom Support Portal 下載（這次用 26.0.1） |
| SystemRescue ISO | 這次用 13.02（`systemrescue-13.02-amd64.iso`），下載後驗證 SHA256 |
| Python + openpyxl | `pip install -r requirements.txt` |
| Git Bash | 接續腳本用 |
| C 槽空間 | 至少一批的資料量 × 1.5（見「分批計畫怎麼訂」） |
| **USB 2.0 埠**（黑色） | 見下方「每次開機」第 3 點，這點非常重要 |

## 一次性環境建置

| 步驟 | 做什麼 | 怎麼確認 |
|---|---|---|
| E1 | 下載 SystemRescue ISO，放到 `C:\PhotoRescueVM\` | `Get-FileHash` 的 SHA256 與官網一致 |
| E2 | 下載並安裝 VMware Workstation Pro | 安裝完成（本機有 Hyper-V 也可以，VMware 會自動相容） |
| E3 | 把 `vm/PhotoRescue.vmx` 複製到 `C:\PhotoRescueVM\`，用 VMware 開啟 | 能從光碟開機，DHCP 拿到 IP |
| E4 | 把 `scripts/setup-host.ps1` 複製到 `C:\PhotoRescueVM\setup-host.ps1`，**以系統管理員執行** `scripts/建立救援虛擬機環境.bat` | 最後一行是 `Done. Connection details saved to ...share-password.txt` |
| E5 | 建立 `C:\PhotoRescueVM\askpass.cmd`，內容只有一行 `@echo rescue` | Windows 內建 OpenSSH 不接受從管線餵密碼，要透過 `SSH_ASKPASS` 取得 |
| E6 | `python method2_vm_ddrescue\rescue_dd.py --selftest` | 最後一行 `SELFTEST OK`（不需要虛擬機和硬碟） |

E4 會建立：`C:\PhotoRescueDD` 資料夾與 SMB 共用、專用本機帳號 `photorescue`（**隨機密碼**，不出現在登入畫面）、防火牆規則（445 埠只開放給 VMware NAT 網段）。帳密寫在 `C:\PhotoRescueVM\share-password.txt`，不進版控。

虛擬機範本的關鍵設定：

```
memsize = "1536"                   # SystemRescue 跑 ddrescue 實測只用 379 MB，給多了只是跟 Windows 搶檔案快取
usb_xhci.present = "TRUE"
usb.generic.autoconnect = "FALSE"  # 一定要關，否則硬碟可能先被 Windows 抓走、自動掛載 NTFS（會寫入）
ethernet0.address = "00:50:56:2A:0D:E1"   # 固定 MAC，程式靠它從 VMware DHCP 租約檔找到虛擬機 IP
```

**不要**在 vmx 裡加 `usb.autoConnect.device0`（同一顆硬碟會連線兩次，第二次失敗把第一次撤銷，硬碟掉回 Windows）。如果虛擬機開機 3～5 分鐘後整個凍結，檢查 vmx 裡有沒有 VMware 自己加的 `usb_xhci:6`、`usb_xhci:7` 這類集線器項目，有就刪掉。

## 換一顆硬碟要改的參數

核心引擎（ddrescue 編排、MFT 解析、檔案還原、輸出驗證）跟硬碟無關，但下面這些值寫在程式最上方的「可調參數」區，**換硬碟前逐項確認**：

`rescue_dd.py`

| 參數 | 說明 |
|---|---|
| `DEV_GLOB` | **最重要**。硬碟在 Linux 下的 by-id 路徑樣式。接上虛擬機後執行 `ls /dev/disk/by-id/` 查 |
| `SECTOR` | **最容易錯**。這顆是 4K 原生磁區（4096），多數硬碟是 512。查法：`blockdev --getss /dev/sdX`。`DD_BASE` 裡的 `-b 4096` 也要一起改 |
| `IMG`, `MAP` | 映像檔與 mapfile 檔名。**換硬碟一定要改名**，否則會蓋掉前一顆的資料 |
| `VM_MAC` | 虛擬機網卡 MAC，要和 vmx 一致 |
| `ASKPASS`, `SHARE_CFG`, `DD_DIR` | SSH 密碼檔、SMB 帳密檔、映像檔目錄 |
| `CSV_PATH` | 方法一留下的壞軌紀錄。有的話，「照片」只救方法一沒救到的；**沒有這個檔**的話，「照片」也整個比對 |
| `OTHER_TOPS` | 來源碟上要整個比對的第一層資料夾 |
| `BATCHES` | 分批計畫，見下一節 |

`rescue2.py`：`DST_ROOT`（救回的檔案放哪裡）、`WORK`（資料庫、暫存、日誌）、`REPORT_TXT`、`XLSX`。

### 分批計畫怎麼訂

`BATCHES` 每一項是 `(批次代號, 說明, [路徑前綴], 輪到時要不要先問人)`，每個檔案歸到「前綴最長、最吻合」的那一批。

- **一批控制在 100 GB 上下**。太大，映像檔需要的暫存空間會爆；太小，重複開銷高。
- **不可取代的先救**（照片、影片、文件），硬碟隨時可能永久死亡。
- **可以重新取得的排最後**（遊戲、軟體、音樂），第四個值設 `True`，輪到時程式會停下來先問人。
- 硬碟開始頻繁掛掉後，**改成「離危險區越遠的先讀」**，不要照磁碟位置順序硬磨。

## 每次開機要做的事

1. 開 VMware，啟動 `C:\PhotoRescueVM\PhotoRescue.vmx`。
2. **開機選單按 `e`**，在 `linux` 那一行**行尾**加上（注意是 amd64 不是 amd）：
   ```
   modprobe.blacklist=amd64_edac
   ```
   然後按 F10 開機。原因：`amd64_edac` 在 VMware 裡會存取不存在的晶片組暫存器而崩潰，之後處理硬碟的 udev 可能跟著死掉，`/dev/disk/by-id/` 就永遠不會出現。
3. 開機後在虛擬機畫面打這四行，每行按 Enter（虛擬機的文字畫面不能貼上）：
   ```sh
   dmesg -n 1
   echo root:rescue | chpasswd
   iptables -P INPUT ACCEPT
   iptables -F
   ```
   密碼可以很簡單：虛擬機只存在於 VMware NAT 網段，外面連不進來，而且是用完就丟的環境。
4. **硬碟接 USB 2.0 埠**（黑色，不是藍色）。這顆碟在 USB 3.0 的 UAS 驅動下完全讀不到：第一個讀取指令就 30 秒逾時，連容量都讀不出來。找不到 USB 2.0 埠的話，中間接一個 USB 2.0 集線器也行。
5. 開硬碟電源，約 20 秒後在 VMware 選單點 `VM → Removable Devices → <硬碟名稱> → Connect`。**每次拔插電源後都要再點一次 Connect**，否則硬碟會留在 Windows。
6. 等硬碟就緒。**這顆碟通電後要 7～8 分鐘才就緒**（回報「Logical unit is in process of becoming ready」），這是正常的，不是當掉。程式會自動把 Linux 的 SCSI 逾時拉長到 180 秒。
7. 確認環境：
   ```sh
   cd method2_vm_ddrescue
   PYTHONIOENCODING=utf-8 python rescue_dd.py vm-check
   ```
   要看到「共用資料夾已掛載，硬碟 …（3001 GB，唯讀），Windows 沒有抓到硬碟」。**沒看到就不要往下做。**

## 救援流程

```
vm-check → mft → plan → batches → copy（一批一批，或一個資料夾一個資料夾）→ retry → extract --final → 收尾
```

以下指令都在 `method2_vm_ddrescue/` 執行，前面加 `PYTHONIOENCODING=utf-8`。

| 步驟 | 指令 | 做什麼 | 碰硬碟？ |
|---|---|---|---|
| R1 | `python rescue_dd.py mft` | 只讀 MBR、boot sector、整個 `$MFT`（這次 2 GB、50 萬筆記錄）。MFT 讀不到的部分自動用 `-A -r1` 補讀一次 | 是 |
| R2 | `python rescue_dd.py plan` | 從映像檔裡的 MFT 建出整顆碟的檔案清單，比對 G 槽，只留還沒有的檔案，寫進 `dd.sqlite` 並分批 | 否 |
| — | `python rescue_dd.py batches` | 看每一批的檔案數、GB、狀態。**給使用者確認範圍後才往下** | 否 |
| R3 | `python rescue_dd.py copy` | 讀下一批（或 `--batch b05` 指定），讀完這批就結束 | 是 |
| R3' | `python rescue_dd.py copy --folder "E:\家人B\20250124"` | 資料夾模式：只讀這個資料夾底下還沒救到的檔案 | 是 |
| R4 | `python rescue_dd.py retry --zones safe` | 所有批次讀完後，回頭在壞軌邊緣逐磁區補讀（`-A -r1`）。先只讀危險區以外；危險區（`--zones danger`）最後、由使用者決定。見下方「收尾」 | 是 |
| R5 | `python rescue_dd.py extract --final` | 最終輸出：決定哪些存成部分損壞、哪些救不回來 | 否 |

**先做 `mft` 再做 `plan`**：先把檔案目錄搶下來，就算硬碟之後死了，至少知道原本有什麼、少了什麼。

`copy` 每一輪做的事：
1. 由這批檔案的所有磁區產生 domain 檔，扣掉已登記的危險區，用 `ddrescue -d -b 4096 -c 16 -n -e +50 -T 10m --mapfile-interval=60` 讀（`-n` 不刮取：讀失敗就標記跳過，不在第一輪花時間）。
2. 每 5 分鐘：把已經完整讀到的檔案輸出到 G 槽 → C 槽空間不夠時，把已輸出的資料在映像檔裡打洞歸還 → 寫回報。
3. G 槽剩不到 30 GB 就暫停，等 Google Drive 上傳釋出到 60 GB 自動繼續；C 槽輸出後仍剩不到 50 GB 就停止。
4. 讀 2 小時休息 1 小時，自動循環。
5. 一批讀完：輸出、更新壞檔清單、記錄這批讀完、寫 `WORK\ddrescue批次報告_bNN.txt`。
6. 每批開始前，先把「mapfile 標記讀到了，但檔案還沒輸出到 G 槽」的區段改回未讀（mapfile 先備份成 `.bak-mark`）。**只有已經輸出到 G 槽的資料才算數**，因為當機或延遲寫入失敗可能讓「讀到了」的資料其實沒寫進映像檔。

其他指令（都不碰硬碟）：

| 指令 | 用途 |
|---|---|
| `report` | 印出目前的回報 |
| `bad [--batch bNN]` | 列出這一批碰到壞區的檔案 |
| `close --batch bNN` | 讀到一半的批次收尾（例如最後幾百 MB 是密集壞軌，一直卡），沒讀到的留給 `retry` |
| `extract` | 不等一批讀完，先輸出目前已經完整讀到的檔案 |

注意：
- **一旦開始輸出檔案，`plan` 就不能重跑**。已輸出的資料在映像檔裡可能已經打洞歸還了，但 mapfile 裡仍是「讀到了」，重新規劃會輸出一堆全是 0 的檔案，程式會直接拒絕。
- **資料夾模式不會把批次標成「讀完」**。所以用 `--folder` 救完的批次，進入 `retry` 之前要先對那些批次執行 `close --batch bNN`，否則 `retry` 不會補讀它們的壞區。

### 自動接續

長時間救援不可能每批都有人守著，所以有兩支接續腳本（在 `scripts/`）：

| 腳本 | 模式 | 用法 |
|---|---|---|
| `ddrescue_自動接續.sh` | 批次模式，一批接一批 | `start_background.ps1 ddrescue_自動接續.sh b04 b05 b06` |
| `接續_資料夾清單.sh` | 資料夾模式，照 `FOLDERS` 清單一個接一個；異常結束自動重試，連續 3 次失敗就停 | 先編輯腳本裡的 `FOLDERS`，再 `start_background.ps1 接續_資料夾清單.sh` |

用 `start_background.ps1` 啟動（`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_background.ps1 <腳本> [參數]`），關掉終端機或 AI 對話也不會被一起收掉。兩支腳本都是任何一輪沒有正常結束、或出現 `需要處理.txt` 就整個停下來等人。

## 監控

| 看哪裡 | 內容 |
|---|---|
| `REPORT_TXT`（進度回報.txt） | 每 5 分鐘更新：這一輪讀到幾 %、壞區多少、目前讀到硬碟哪個位置、檔案統計、C/G 槽剩餘空間 |
| `WORK\需要處理.txt` | **程式判定需要人介入時才會有內容**，裡面寫著原因與具體步驟。空的或不存在就代表正常 |
| `tools/狀態.py` | 一次性報告；`--until 75` 會一直監控到完成度 75% 才結束（給 AI 用：監控程式結束才會喚醒 AI） |
| `C:\PhotoRescueDD\ddrescue_run.log` | ddrescue 自己的畫面輸出 |

**判斷「卡住」要看讀到的資料量有沒有增加**（回報裡的「已讀到」、`tools/狀態.py` 的 ddrescue 已讀量與「距上次成功讀取」），不要看：
- 速度 0.0 MB/s：讀到資料稀疏的區段時速度本來就是 0。
- mapfile 的修改時間：SMB 快取會讓它失真。
- 讀取位置：ddrescue 重啟時會先跳回範圍開頭、再回到卡點，看起來像有前進（9/24 補讀時因此空轉約 6 小時）。位置只用來看「卡在哪裡」。

### 記憶體與寫入失敗（每天看一次）

9/20 曾經發生：記憶體裡「還沒寫進磁碟的資料」漲到 13.5 GB，把 32 GB 的記憶體吃光、整台電腦被拖慢，同時映像檔一天出現 11,885 次「延遲寫入失敗」。原因是稀疏映像檔被切成 193 萬個片段，撞上 NTFS 的上限（[踩過的坑](踩過的坑.md)第 32 條）。這種問題等到電腦變慢才發現就晚了，要定期看：

```powershell
# 等著寫進磁碟的資料量（Modified Page List）
"{0:N0} MB" -f ((Get-Counter '\Memory\Modified Page List Bytes').CounterSamples[0].CookedValue / 1MB)
# 中文版 Windows 若找不到計數器，改用：
"{0:N0} MB" -f ((Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).ModifiedPageListBytes / 1MB)
```

| 數值 | 判斷 |
|---|---|
| 500 MB 以下 | 正常（救援期間實測約 86 MB） |
| 持續超過 3 GB | 寫入卡住了，要查 |

也可以在事件檢視器看有沒有大量「延遲寫入失敗」（Windows 記錄 → 系統，訊息含 `seagate.img`）。

真的撞上片段上限時：先 `extract` 把已經讀到但還沒輸出的資料輸出，再停掉救援、刪除映像檔讓程式重建（片段數歸零）。程式現在只在空間不夠時才打洞，正常情況下不會再發生。

### 故障處理（程式大多會自己處理）

| 狀況 | 程式怎麼判斷 | 程式會做什麼 | 人要做什麼 |
|---|---|---|---|
| 壞區 | ddrescue 讀失敗 | 標記跳過，`retry` 才回頭 | 不用 |
| 硬碟還在，只是卡住 | 5 分鐘沒讀到新資料，但 `/dev/...` 還在 | 繼續等，最多 45 分鐘（實測常常 3～8 分鐘後自己恢復） | 不用 |
| 累計 45 分鐘讀到的新資料不滿 1 MB | 同上；**跨 ddrescue 重啟累計**，休息時間不算 | 目前位置前後各 5 GB 記成**危險區**，跳過這段繼續讀別的位置，最後 `retry --zones danger` 再補 | 不用 |
| 讀取中硬碟從匯流排掉了 | 位置停滯 5 分鐘後發現裝置節點消失（dmesg 有 `error -110`） | 立刻停止、寫 `需要處理.txt`。這種情況只有斷電能救，繼續探測沒有意義 | **關硬碟電源 → 等 10 秒 → 開電源 → VMware 選單 Connect → 重新啟動接續腳本** |
| 連確定讀得到的位置都讀不到 | 每一輪開始前讀一個以前讀成功過的位置 | 每分鐘檢查一次，最多等 30 分鐘，恢復了就自己繼續；等不到才寫 `需要處理.txt` 並停止 | 關硬碟電源 → 等 10 秒 → 開電源 → VMware 選單 Connect（之後程式自己繼續） |
| 硬碟掉回 Windows | Windows 出現 E 槽或抓到硬碟 | 立刻停止 | **立刻拔掉硬碟 USB**，這是唯一會再讓 Windows 卡死的路徑 |
| ddrescue 結束但毫無進度 | 範圍內的統計跟上一次完全一樣 | 停止，**絕不自動重跑** | 看紀錄判斷 |
| 虛擬機沒回應 | SSH 連不上 | 停止 | 重開虛擬機。映像檔與 mapfile 都在 Windows 上，進度不會遺失 |
| 壞檔清單寫不進去 | Excel 開著那個檔 | 下次再寫 | 關掉 Excel |

ddrescue 自己的 `-T 10m`（10 分鐘讀不到就放棄）**在硬碟卡死時不會生效**：整支程式被凍在不可中斷的 I/O 等待裡，連計時器都跑不了（實測卡了 2.5 小時沒反應）。所以看門狗必須放在虛擬機外面的 `rescue_dd.py`。

**不要**用 `Stop-Process -Force` 結束正在寫入映像檔的程式，會留下未完成的 SMB 寫入，造成延遲寫入失敗。要停的話，先在虛擬機裡停 ddrescue，等它寫完 mapfile 再停 Windows 端的程式。

## 輔助工具（`tools/`）

| 工具 | 什麼時候用 |
|---|---|
| `重複比對.py` | 讀故障碟之前：比對「還沒救到的檔案」和「已經救到的檔案」，找出其他資料夾已經有副本的（A 級：檔名＋大小＋修改時間相同；B 級：檔名＋大小相同）。只出報告 |
| `標記重複.py` | 看過報告、使用者同意後：把重複的標成不用再讀（這次省下 4,943 檔、8.5 GB） |
| `健康檢測.py` | 懷疑硬碟整體退化時：只讀「以前讀成功過」的位置取樣，加上 SMART，判斷是局部壞軌還是整顆在衰退 |
| `狀態.py` | 監控，見上一節 |

另外，**先找舊備份**。這次比對兩顆舊備份碟，8,093 個待救檔案（35 GB）直接從備份複製，完全不用讀故障碟。

## 產出

| 位置 | 內容 |
|---|---|
| 目的地原本的路徑 | 完整救回的檔案，還原修改時間 |
| `原檔名_部分損壞.jpg` | 只有 JPG、而且壞區 ≤ 5% 才存，壞區補 0（使用者的決定：照片缺一小塊還看得出來，其他格式缺了通常就打不開） |
| `照片救援_無法判斷資料夾\parent#<編號>\` | 檔案本身讀得到，但所屬資料夾的 MFT 記錄壞了，不知道原本放在哪裡 |
| `XLSX` 的「壞軌檔案清單」 | 批次、來源路徑、目的地路徑、大小、壞區 KB 與比例、結果（待補讀／部分損壞已存／救不回來／原檔空白未存／寫入 G 失敗） |
| `WORK\ddrescue批次報告_*.txt` | 每一批（或每個資料夾）的結束報告 |

## 收尾

1. 對用資料夾模式救完的批次執行 `close --batch bNN`（見上方注意事項）。
2. `retry --zones safe`：先補讀危險區以外的壞區。**設停損**：這次實測兩次共 7.5 小時只多讀出約 0.5 MB、一個檔案都沒救回，硬碟每半小時卡死一次。幾小時內讀到的資料不到幾 MB，就停下來直接做最終輸出，繼續刮只是在消耗硬碟。
3. 危險區要不要讀（`retry --zones danger`）由使用者決定。那些位置一讀就讓整顆硬碟鎖死；如果打算送專業救援，就不要先硬讀。
4. `extract --final`：最終輸出。`retry` 如果是中途停掉的，直接做這一步，**不要**先把壞區改回待處理：`-A` 已經把沒刮完的區塊在 mapfile 標回「沒讀過」，改回去會讓那些檔案永遠停在待處理，連部分損壞的照片都存不出來。
5. **先關硬碟電源（或拔 USB），再關虛擬機**。不要在 VMware 按 Disconnect，那會把硬碟交回 Windows。
6. 讓電腦恢復原狀（**一定要在硬碟拔掉之後**，這支腳本會把硬碟改回可寫入）：以系統管理員執行 `scripts/恢復Windows自動修復.bat`（恢復 Windows 設定，移除排程工作、SMB 共用、專用帳號、防火牆規則），再照[收尾：讓電腦恢復原狀](收尾_恢復電腦原狀.md)檢查，並決定映像檔、虛擬機、工作資料夾要不要刪。

## 鐵則

1. 對故障碟**只讀不寫**：虛擬機裡 `blockdev --setro`；ddrescue 的輸入一律用 `/dev/disk/by-id/...` 完整名稱，不用 `/dev/sdX`。
2. **不做任何 USB 裝置重置**（`pnputil`、`usbreset`、`echo 0 > authorized` 都不行）。卡死一律停下來請人拔插。
3. 救援期間 Windows **不能**看到這顆硬碟。看到 E 槽出現就是異常。
4. 不執行 fsck、ntfsfix、chkdsk 或任何修復。
5. 不手動修改 mapfile、domain 檔、`dd.sqlite`。要改先備份。
6. 改程式前先 commit，改完一定要跑 `python rescue_dd.py --selftest`、`python rescue2.py --selftest`、`python test_watchdog.py`，**三個都要跑**。
