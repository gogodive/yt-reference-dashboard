#!/usr/bin/env bash
# 암호화된 수집 상태(data/state.enc)를 풀거나 다시 잠근다.
#
#   scripts/state.sh pull   원격 최신 받아서 → 복호화 (분석 시작 전)
#   scripts/state.sh push   재암호화 → 커밋 → 푸시 (분석 끝난 뒤)
#
# 암호는 macOS 키체인에서 읽는다. 최초 1회만 아래를 실행해 두면 된다:
#   security add-generic-password -a "$USER" -s yt-reference-dashboard -w
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

case "${1:-}" in
  pull|push) ;;
  *) echo "사용법: scripts/state.sh pull|push" >&2; exit 1 ;;
esac

# 암호를 먼저 확보한다. 명령 치환 안에서 exit 해도 부모 스크립트는 멈추지 않으므로
# 반드시 별도 문장으로 받아서 검사해야 한다.
if ! DASHBOARD_PASSWORD="$(security find-generic-password -a "$USER" \
      -s yt-reference-dashboard -w 2>/dev/null)" || [ -z "$DASHBOARD_PASSWORD" ]; then
  cat >&2 <<'MSG'
키체인에 접속 암호가 없습니다. 아래를 한 번만 실행해 주세요
(GitHub Secret 의 DASHBOARD_PASSWORD 와 같은 값을 입력):

  security add-generic-password -a "$USER" -s yt-reference-dashboard -w

MSG
  exit 1
fi
export DASHBOARD_PASSWORD

case "$1" in
  pull)
    git pull --rebase -q origin main
    "$PY" - <<'PY'
import os, sys
from src import secure
try:
    n = secure.load_state("data", os.environ["DASHBOARD_PASSWORD"])
except Exception:
    sys.exit("복호화 실패 — 키체인에 저장된 암호가 GitHub Secret 과 다릅니다.\n"
             "  security delete-generic-password -s yt-reference-dashboard\n"
             "  security add-generic-password -a \"$USER\" -s yt-reference-dashboard -w")
print(f"수집 상태 복원: 파일 {n}개")
PY
    ;;

  push)
    "$PY" - <<'PY'
import os
from src import secure
secure.save_state("data", os.environ["DASHBOARD_PASSWORD"])
print("state.enc 재암호화 완료")
PY
    git add data/state.enc
    if git diff --cached --quiet; then
      echo "변경 없음 — 푸시 생략"
    else
      git commit -q -m "chore: 영상 분석 진행 상태 갱신"
      git pull --rebase -q origin main
      git push -q origin main
      echo "푸시 완료"
    fi
    ;;
esac
