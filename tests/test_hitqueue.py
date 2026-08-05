"""히트 큐 — 배수 재현과 분석 완료 항목 동결."""

from src import hitqueue

NOW = "2026-08-06T07:10:00+09:00"
LATER = "2026-09-01T07:10:00+09:00"


def target(vid_id="abc", views=100_000, median=10_000.0, ratio=10.0):
    return {
        "video_id": vid_id,
        "url": f"https://www.youtube.com/watch?v={vid_id}",
        "title": "제목",
        "format": "shorts",
        "metrics": {"views": views},
        "_perf_ratio": ratio,
        "_median": median,
        "_channel": "채널",
        "_handle": "handle",
        "published_at": "2026-07-01T00:00:00Z",
        "duration": 30,
    }


def test_entry_records_median_and_timestamp():
    """배수만 남기면 나중에 재현이 안 된다 — 분모와 시점이 같이 있어야 한다."""
    entry = hitqueue.entry_from_hit(target(), NOW)
    assert entry["views"] == 100_000
    assert entry["median"] == 10_000.0
    assert entry["ratio"] == 10.0
    assert entry["metrics_at"] == NOW
    # 저장된 값만으로 배수가 재계산된다
    assert round(entry["views"] / entry["median"], 2) == entry["ratio"]


def test_pending_entry_keeps_tracking_current_metrics():
    entries, _, _ = hitqueue.sync([], [target()], NOW)
    moved = target(views=120_000, median=12_000.0, ratio=10.0)
    entries, added, removed = hitqueue.sync(entries, [moved], LATER)

    assert (added, removed) == ([], [])
    assert entries[0]["views"] == 120_000
    assert entries[0]["median"] == 12_000.0
    assert entries[0]["metrics_at"] == LATER


def test_done_entry_is_frozen():
    """분석이 끝난 뒤 지표가 계속 움직이면 리포트 본문과 노션이 어긋난다.

    실제로 done 71편 중 20편의 배수가 중앙값 이동만으로 어긋났다.
    """
    entries, _, _ = hitqueue.sync([], [target()], NOW)
    hitqueue.mark(entries, "abc", hitqueue.DONE)

    # 채널에 새 영상이 쌓여 중앙값이 내려가면 배수는 올라간다
    drifted = target(views=105_000, median=9_000.0, ratio=11.67)
    entries, added, removed = hitqueue.sync(entries, [drifted], LATER)

    assert (added, removed) == ([], [])
    frozen = entries[0]
    assert frozen["ratio"] == 10.0, "분석 시점 배수가 보존돼야 한다"
    assert frozen["views"] == 100_000
    assert frozen["median"] == 10_000.0
    assert frozen["metrics_at"] == NOW


def test_done_entry_survives_falling_below_threshold():
    """동결된 항목은 기준에서 빠져도 큐에 남는다 (기존 동작 유지)."""
    entries, _, _ = hitqueue.sync([], [target()], NOW)
    hitqueue.mark(entries, "abc", hitqueue.DONE)

    entries, added, removed = hitqueue.sync(entries, [], LATER)
    assert removed == []
    assert entries[0]["status"] == hitqueue.DONE
    assert entries[0]["ratio"] == 10.0


def test_missing_median_does_not_crash():
    hit = target()
    hit["_median"] = None
    entry = hitqueue.entry_from_hit(hit, NOW)
    assert entry["median"] is None
