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
#
# 1) 이미 환경변수에 있으면 그대로 쓴다 (맥이 아닌 환경 대비)
# 2) 없으면 macOS 키체인에서 읽는다
if [ -z "${DASHBOARD_PASSWORD:-}" ] && command -v security >/dev/null 2>&1; then
  DASHBOARD_PASSWORD="$(security find-generic-password -a "$USER" \
    -s yt-reference-dashboard -w 2>/dev/null)" || DASHBOARD_PASSWORD=""
fi

if [ -z "${DASHBOARD_PASSWORD:-}" ]; then
  cat >&2 <<'MSG'
접속 암호를 찾지 못했습니다. 둘 중 하나를 하시면 됩니다.

  맥 (한 번만 등록해 두면 이후 자동):
    security add-generic-password -a "$USER" -s yt-reference-dashboard -w

  그 외 환경 (실행할 때마다):
    export DASHBOARD_PASSWORD='...'

둘 다 GitHub Secret 의 DASHBOARD_PASSWORD 와 같은 값을 넣으면 됩니다.
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
      # state.enc 는 암호화할 때마다 salt·nonce 가 새로 생겨 내용이 같아도 바이트가
      # 통째로 달라진다. 그래서 그 사이 자동 수집이 한 번이라도 올라오면 rebase 가
      # 반드시 충돌한다. 텍스트 병합이 불가능하므로 복호화해서 직접 합친다.
      if ! git pull --rebase -q origin main; then
        "$PY" scripts/merge_state.py || {
          echo "상태 병합 실패 — rebase 가 멈춰 있습니다. 확인 후" >&2
          echo "  git rebase --abort  또는  git rebase --continue" >&2
          exit 1
        }
        git add data/state.enc
        GIT_EDITOR=true git rebase --continue >/dev/null
      fi
      git push -q origin main
      echo "푸시 완료"
    fi
    ;;
esac
