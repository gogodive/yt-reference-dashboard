"""영상 병합 + 30일 동결 규칙 (순수 함수 — API/파일 접근 없음).

5-1 자사 대시보드의 merge.py 와 동일한 규칙을 쓴다.
레퍼런스 채널은 과거 영상이 대부분이라 대개 첫 수집에서 곧바로 동결된다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

FREEZE_DAYS = 30
DISPLAY_LIMIT = 1000


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_frozen(published_at: str, now: datetime, freeze_days: int = FREEZE_DAYS) -> bool:
    return now - _parse_ts(published_at) > timedelta(days=freeze_days)


def merge_videos(
    stored_videos: list[dict],
    fresh_videos: list[dict],
    now: datetime,
    freeze_days: int = FREEZE_DAYS,
    limit: int = DISPLAY_LIMIT,
) -> list[dict]:
    """오늘 받아온 영상 목록을 기준으로 저장분과 병합한다.

    - 30일 이내: 오늘 조회한 지표로 갱신
    - 30일 경과: 저장된 동결 지표 유지 (저장 지표가 없으면 최초 1회 백필)
    - fresh_videos 에 없는 저장분은 탈락 (삭제되었거나 수집 범위 밖)
    - format(shorts/long)은 저장분 우선 (판별은 1회만)
    """
    stored_by_id = {v["video_id"]: v for v in stored_videos}
    merged: list[dict] = []
    for f in fresh_videos[:limit]:
        vid = f["video_id"]
        old = stored_by_id.get(vid)
        frozen = is_frozen(f["published_at"], now, freeze_days)
        video = {
            "video_id": vid,
            "title": f.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "thumbnail": f.get("thumbnail"),
            "published_at": f["published_at"],
            "duration": f.get("duration", 0),
            "format": (old or {}).get("format") or f.get("format"),
            "frozen": frozen,
            "metrics": {},
            "metrics_updated_at": None,
        }
        has_stored = bool((old or {}).get("metrics"))
        if not frozen or not has_stored:
            video["metrics"] = {"views": f.get("views"), "likes": f.get("likes"),
                                "comments": f.get("comments")}
            video["metrics_updated_at"] = now.isoformat()
        else:
            video["metrics"] = old.get("metrics", {})
            video["metrics_updated_at"] = old.get("metrics_updated_at")
        # 분석 연동 정보는 병합 과정에서 잃지 않는다
        for key in ("notion_page_id", "analyzed_at"):
            if (old or {}).get(key):
                video[key] = old[key]
        merged.append(video)
    return merged
