from datetime import datetime, timedelta, timezone

from src.merge import is_frozen, merge_videos

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


def fresh(vid_id, days_ago, views, fmt="long"):
    published = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {"video_id": vid_id, "title": f"영상 {vid_id}", "published_at": published,
            "duration": 600, "thumbnail": "t.jpg", "format": fmt,
            "views": views, "likes": 10, "comments": 5}


def test_is_frozen():
    assert is_frozen((NOW - timedelta(days=31)).isoformat(), NOW) is True
    assert is_frozen((NOW - timedelta(days=29)).isoformat(), NOW) is False


def test_recent_video_metrics_are_refreshed():
    stored = [{"video_id": "a", "metrics": {"views": 100}, "metrics_updated_at": "old"}]
    merged = merge_videos(stored, [fresh("a", days_ago=5, views=250)], NOW)
    assert merged[0]["metrics"]["views"] == 250
    assert merged[0]["frozen"] is False


def test_old_video_metrics_are_frozen():
    stored = [{"video_id": "a", "metrics": {"views": 100, "likes": 1, "comments": 1},
               "metrics_updated_at": "2026-01-01T00:00:00+00:00"}]
    merged = merge_videos(stored, [fresh("a", days_ago=90, views=999)], NOW)
    assert merged[0]["metrics"]["views"] == 100          # 동결된 값 유지
    assert merged[0]["metrics_updated_at"] == "2026-01-01T00:00:00+00:00"
    assert merged[0]["frozen"] is True


def test_old_video_without_stored_metrics_is_backfilled_once():
    """3년치 백필: 처음 보는 과거 영상은 그 시점 지표를 1회 기입한다."""
    merged = merge_videos([], [fresh("a", days_ago=400, views=50_000)], NOW)
    assert merged[0]["metrics"]["views"] == 50_000
    assert merged[0]["metrics_updated_at"] == NOW.isoformat()
    assert merged[0]["frozen"] is True


def test_format_is_kept_from_storage():
    """쇼츠 판별은 1회만 하므로 저장분의 format 이 우선한다."""
    stored = [{"video_id": "a", "format": "shorts", "metrics": {"views": 1}}]
    merged = merge_videos(stored, [fresh("a", days_ago=5, views=2, fmt="long")], NOW)
    assert merged[0]["format"] == "shorts"


def test_videos_missing_from_fresh_are_dropped():
    stored = [{"video_id": "gone", "metrics": {"views": 1}}]
    merged = merge_videos(stored, [fresh("a", days_ago=1, views=2)], NOW)
    assert [v["video_id"] for v in merged] == ["a"]


def test_analysis_links_survive_merge():
    """분석 완료 후 노션 페이지 연결이 다음 수집에서 지워지면 안 된다."""
    stored = [{"video_id": "a", "metrics": {"views": 100},
               "notion_page_id": "page-123", "analyzed_at": "2026-08-01"}]
    merged = merge_videos(stored, [fresh("a", days_ago=90, views=100)], NOW)
    assert merged[0]["notion_page_id"] == "page-123"
    assert merged[0]["analyzed_at"] == "2026-08-01"


def test_limit_truncates():
    videos = [fresh(f"v{i}", days_ago=i + 1, views=100) for i in range(10)]
    merged = merge_videos([], videos, NOW, limit=3)
    assert len(merged) == 3
