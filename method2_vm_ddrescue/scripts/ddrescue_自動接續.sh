#!/usr/bin/env bash
# 批次模式：一批接一批自動讀（rescue_dd.py copy --batch），任何一批沒有正常結束就整個停下來等人。
#
# 用法（照你要的讀取順序列出批次）：
#   bash ddrescue_自動接續.sh b04 b05 b06
#   powershell -NoProfile -ExecutionPolicy Bypass -File start_background.ps1 ddrescue_自動接續.sh b04 b05 b06
# 用 start_background.ps1 啟動的話，關掉終端機或 AI 對話也不會被一起收掉。
#
# - ask=True 的批次（例如 game）不要放進來，輪到時要先問使用者。
# - 已經讀完的批次會自動略過，所以中斷後用同一行指令重跑就好。
# - 順序：硬碟開始頻繁掛掉之後，改成「離危險區越遠的先讀」（9/20 把 b12 排到 b11 前面）。
#   硬碟隨時可能永久死亡，剩下的壽命要先花在最安全的資料上。
set -u
cd "$(dirname "$0")/.." || exit 1          # 切到 method2_vm_ddrescue/
export PYTHONIOENCODING=utf-8
WORK="/c/照片救援"                           # 要跟 rescue2.py 的 WORK 一致
OUT="$WORK/ddrescue_copy_輸出.txt"
LOG="$WORK/ddrescue_自動接續紀錄.txt"
FLAG="$WORK/需要處理.txt"

say() { echo "[$(date '+%m/%d %H:%M:%S')] $*" | tee -a "$LOG"; }
done_flag() { python -c "import sys, rescue_dd as D; sys.exit(0 if D.R.meta_get(D.R.db_open(), 'batch_done_$1') else 1)"; }
running() {   # 還有 rescue_dd 的 python 在跑？
  powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'rescue_dd.py (copy|retry|mft)' }) { exit 0 } else { exit 1 }"
}

[ $# -gt 0 ] || { echo "用法：bash $0 b01 b02 ...（照讀取順序列出批次）"; exit 1; }

say "自動接續啟動，順序：$*"
while running; do sleep 60; done

for b in "$@"; do
  if done_flag "$b"; then say "$b 之前已讀完，略過"; continue; fi
  say "開始 $b"
  python rescue_dd.py copy --batch "$b" >> "$OUT" 2>&1
  rc=$?
  if [ $rc -ne 0 ] || ! done_flag "$b"; then
    say "$b 沒有正常結束（結束碼 $rc），自動接續停止，等使用者處理"
    if [ -s "$FLAG" ]; then
      say "原因與處理方式："
      head -n 3 "$FLAG" | tee -a "$LOG"
    else
      say "看 $OUT 最後 40 行"
    fi
    exit 3
  fi
  say "$b 讀完"
done

say "列出的批次都讀完了。下一步：ask=True 的批次先問使用者；全部讀完後 retry → extract --final"
