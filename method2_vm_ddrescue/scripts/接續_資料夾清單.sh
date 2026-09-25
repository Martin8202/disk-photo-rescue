#!/usr/bin/env bash
# 資料夾模式：一個資料夾一個資料夾讀（rescue_dd.py copy --folder）。
# 硬碟已經很衰弱、整批讀常常中斷時用這個（9/21 起的做法）：範圍小，每讀完一個資料夾就是一個確定的成果。
#
# 用法：把要救的資料夾照優先順序寫進下面的 FOLDERS，然後
#   powershell -NoProfile -ExecutionPolicy Bypass -File start_background.ps1 接續_資料夾清單.sh
#
# - 前一輪 rescue_dd 還在跑就先等它結束。
# - 程式異常結束（結束碼不是 0，例如 9/22 遊戲批次碰到的偶發 OSError）休息 2 分鐘後重試，
#   同一個資料夾連續失敗 3 次就停下來等人，不要一直磨硬碟。
# - 出現需要處理.txt（硬碟掉線、要人拔插）就立刻停下來。
set -u
cd "$(dirname "$0")/.." || exit 1          # 切到 method2_vm_ddrescue/
export PYTHONIOENCODING=utf-8
WORK="/c/照片救援"                           # 要跟 rescue2.py 的 WORK 一致
LOG="$WORK/接續_資料夾清單紀錄.txt"
FLAG="$WORK/需要處理.txt"

FOLDERS=(                                   # 範例：不可取代的照片影片排前面，可以接受遺失的排最後
  'E:\家人B\20250124'
  'E:\照片'
  'E:\家人B\個人\music'
)

say() { echo "[$(date '+%m/%d %H:%M:%S')] $*" >> "$LOG"; }
left() {      # 這個資料夾還有幾個檔案沒救到
  python -c "
import sqlite3, sys
c = sqlite3.connect(r'C:\照片救援\dd.sqlite', timeout=60)
print(c.execute('SELECT COUNT(*) FROM files WHERE path LIKE ? AND status=\"new\"', (sys.argv[1].rstrip(chr(92)) + chr(92) + '%',)).fetchone()[0])
" "$1" 2>/dev/null
}
running() {   # 還有 rescue_dd 的 python 在跑？
  powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'rescue_dd' }) { exit 0 } else { exit 1 }" 2>/dev/null
}

say "=== 接續啟動，等目前的救援結束 ==="
while running; do sleep 30; done

for f in "${FOLDERS[@]}"; do
  ok=""
  for try in 1 2 3; do
    n=$(left "$f")
    if [ -z "$n" ] || [ "$n" = "0" ]; then say "略過 $f（沒有待救檔案）"; ok=1; break; fi
    say ">>> 開始 $f（$n 個檔案，第 $try 次）"
    python rescue_dd.py copy --folder "$f" >> "$WORK/ddrescue_copy_輸出.txt" 2>&1
    rc=$?
    say "<<< 結束 $f（結束碼 $rc）"
    if [ -s "$FLAG" ]; then say "!!! 需要人工處理，停止接續："; cat "$FLAG" >> "$LOG"; exit 2; fi
    if [ "$rc" = "0" ]; then ok=1; break; fi
    say "異常結束，休息 2 分鐘後重試"
    sleep 120
  done
  [ -n "$ok" ] || { say "!!! $f 連續 3 次異常結束，停止接續，看 ddrescue_copy_輸出.txt 最後 40 行"; exit 3; }
  sleep 60                                  # 讓硬碟休息一分鐘再跑下一個
done
say "=== 清單上的資料夾都處理完了 ==="
