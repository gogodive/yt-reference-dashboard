"""히트 영상 분석 큐.

Layer 1(GitHub Actions)이 신규 히트를 넣고, Layer 2(맥의 Claude Code 스킬)가
하나씩 꺼내 분석한 뒤 상태를 갱신한다. 중단·재개가 안전하도록 상태를 파일로 남긴다.
"""

from __future__ import annotations

import json
from pathlib import Path

PENDING = "pending"
DONE = "done"
FAILED = "failed"


def entry_from_hit(hit: dict, queued_at: str) -> dict:
    return {
        "video_id": hit["video_id"],
        "url": hit.get("url"),
        "title": hit.get("title", ""),
        "channel": hit.get("_channel", ""),
        "handle": hit.get("_handle", ""),
        "format": hit.get("format"),
        "ratio": round(hit["_perf_ratio"], 2) if hit.get("_perf_ratio") else None,
        "views": (hit.get("metrics") or {}).get("views"),
        # 배수의 분모. 채널에 새 영상이 쌓이면 중앙값이 움직여서 배수도 따라 움직인다.
        # 이 값을 남겨야 리포트에 적힌 배수를 나중에 그대로 재현할 수 있다.
        "median": round(hit["_median"], 1) if hit.get("_median") else None,
        "metrics_at": queued_at,
        "published_at": hit.get("published_at"),
        "duration": hit.get("duration"),
        "status": PENDING,
        "notion_page_id": None,
        "queued_at": queued_at,
        "analyzed_at": None,
    }


def sync(entries: list[dict], targets: list[dict],
         queued_at: str) -> tuple[list[dict], list[dict], list[dict]]:
    """분석 대상 목록을 큐에 반영한다.

    이미 있는 항목은 상태를 보존하고 성과 지표만 갱신한다.
    기준이 바뀌어 대상에서 빠진 **대기** 항목은 큐에서 뺀다.
    이미 분석한 항목(done/failed)은 기준과 무관하게 보존한다.

    반환값: (전체 큐, 새로 추가된 항목, 큐에서 빠진 항목)
    """
    target_ids = {t["video_id"] for t in targets}
    by_id = {e["video_id"]: e for e in entries}

    removed = [e for e in entries
               if e.get("status") == PENDING and e["video_id"] not in target_ids]
    for e in removed:
        by_id.pop(e["video_id"], None)

    added: list[dict] = []
    for target in targets:
        existing = by_id.get(target["video_id"])
        if existing:
            # 분석이 끝난 항목은 지표를 얼린다. 리포트가 인용한 숫자가 계속 움직이면
            # 본문과 노션 속성이 어긋나고, 어느 쪽이 맞는지 알 수 없게 된다.
            # (실제로 done 71편 중 20편의 배수가 중앙값 이동으로 어긋났다)
            if existing.get("status") != PENDING:
                continue
            existing["ratio"] = (round(target["_perf_ratio"], 2)
                                 if target.get("_perf_ratio") else None)
            existing["views"] = (target.get("metrics") or {}).get("views")
            existing["median"] = (round(target["_median"], 1)
                                  if target.get("_median") else None)
            existing["metrics_at"] = queued_at
            continue
        entry = entry_from_hit(target, queued_at)
        by_id[entry["video_id"]] = entry
        added.append(entry)

    merged = list(by_id.values())
    # 성과 배수 높은 순 — 백필 시 크게 터진 영상부터 분석한다
    merged.sort(key=lambda e: e.get("ratio") or 0, reverse=True)
    return merged, added, removed


def pending(entries: list[dict], limit: int | None = None) -> list[dict]:
    out = [e for e in entries if e.get("status") == PENDING]
    return out[:limit] if limit else out


def counts(entries: list[dict]) -> dict:
    out = {PENDING: 0, DONE: 0, FAILED: 0}
    for e in entries:
        status = e.get("status", PENDING)
        out[status] = out.get(status, 0) + 1
    return out


def mark(entries: list[dict], video_id: str, status: str,
         notion_page_id: str | None = None, analyzed_at: str | None = None) -> bool:
    for e in entries:
        if e["video_id"] == video_id:
            e["status"] = status
            if notion_page_id:
                e["notion_page_id"] = notion_page_id
            if analyzed_at:
                e["analyzed_at"] = analyzed_at
            return True
    return False


def load(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: str | Path, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                          encoding="utf-8")
