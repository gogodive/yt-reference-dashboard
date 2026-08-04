#!/usr/bin/env python3
"""rebase 가 충돌시킨 data/state.enc 를 복호화해서 합친다.

state.enc 는 data/*.json 을 한 덩어리로 묶어 암호화한 블롭이다. 암호화할 때마다
salt·nonce 가 새로 생기므로 **내용이 같아도 바이트는 매번 전부 다르고**, 그래서
그 사이 자동 수집이 한 번이라도 올라오면 rebase 가 반드시 충돌한다.
git 은 이걸 텍스트로 합칠 수 없으니 양쪽을 풀어서 JSON 수준에서 합친다.

  · 바탕      = 원격  (자동 수집이 갱신한 채널 데이터가 최신이다)
  · 얹는 것   = 이쪽의 분석 결과 (큐의 status / analyzed_at / notion_page_id)

이쪽에만 있는 큐 항목은 그대로 살리고, 원격에만 새로 수집된 항목도 그대로 둔다.
rebase 중에는 스테이지 2 가 rebase 대상(원격), 3 이 replay 되는 이쪽 커밋이다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import secure  # noqa: E402

QUEUE = "hit_queue.json"
CARRY = ("status", "analyzed_at", "notion_page_id")


def stage(n: int) -> str:
    """충돌 파일의 n 번 스테이지를 꺼낸다."""
    out = subprocess.run(["git", "show", f":{n}:data/state.enc"],
                         capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit(f"state.enc 스테이지 {n} 을 읽지 못했습니다 — 충돌 상태가 맞는지 확인하세요.")
    return out.stdout


def main() -> int:
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password:
        sys.exit("DASHBOARD_PASSWORD 가 없습니다.")

    try:
        remote = json.loads(secure.decrypt(stage(2), password))
        mine = json.loads(secure.decrypt(stage(3), password))
    except Exception as exc:                       # 암호가 다르거나 블롭이 깨진 경우
        sys.exit(f"복호화 실패: {exc}")

    mine_q = {e["video_id"]: e for e in mine.get(QUEUE, [])}
    merged_q, applied = [], []

    for entry in remote.get(QUEUE, []):
        ours = mine_q.pop(entry["video_id"], None)
        if ours and ours.get("status") != entry.get("status"):
            for key in CARRY:
                if ours.get(key) is not None:
                    entry[key] = ours[key]
            applied.append(f"{entry['video_id']}→{entry['status']}")
        merged_q.append(entry)

    merged_q.extend(mine_q.values())               # 이쪽에만 있던 항목은 잃지 않는다
    remote[QUEUE] = merged_q

    data = Path("data")
    for name, obj in remote.items():
        (data / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    secure.save_state(data, password)

    done = sum(1 for e in merged_q if e.get("status") == "done")
    print(f"상태 병합 — 원격 기준에 분석 결과 {len(applied)}건 반영 "
          f"({', '.join(applied) or '없음'}) · 큐 {len(merged_q)}편 중 완료 {done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
