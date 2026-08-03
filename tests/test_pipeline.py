"""Layer 1 전체 배선 통합 테스트.

가짜 YouTube/노션 클라이언트로 수집 → 지표 → 큐 → 노션 행 생성 → 렌더까지
한 번에 돌려 본다. 실제 API 키 없이 모듈 간 연결이 맞는지 확인하는 것이 목적이다.
"""

from datetime import datetime, timedelta, timezone

from src import hitqueue, metrics
from src.collect import collect_all
from src.main import sync_notion_rows
from src.render import render_html

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 4, 7, 10, tzinfo=KST)

CONFIG = {
    "notion": {"channel_database_id": "chan-db", "analysis_database_id": "an-db"},
    "collect": {"years": 3, "max_videos": 1000, "freeze_days": 30},
    "metrics": {"hot_ratio": 3.0, "min_videos": 5,
                "contribution_quantiles": {"best": 0.90, "good": 0.70, "normal": 0.40}},
    "dashboard": {"title": "레퍼런스 유튜브 채널 분석"},
}


class FakeYouTube:
    """채널 2개 — 하나는 정상, 하나는 채널을 못 찾는 상황."""

    def __init__(self):
        self.short_checks = 0

    def resolve_channel_flexible(self, address):
        if "없는채널" in address:
            raise LookupError(f"채널을 찾을 수 없음: {address}")
        handle = "wateryang" if "wateryang" in address else "swimcrazy"
        return {
            "channel_id": f"UC_{handle}", "title": f"{handle} 채널", "handle": handle,
            "url": f"https://www.youtube.com/@{handle}",
            "published_at": "2019-10-21T00:00:00Z",
            "subscribers": 120_000 if handle == "wateryang" else 8_000,
            "video_count": 340, "total_views": 12_000_000,
            "uploads_playlist_id": f"UU_{handle}",
        }

    def get_video_ids_since(self, playlist, cutoff, limit):
        handle = playlist.replace("UU_", "")
        return [f"{handle}{i}" for i in range(12)]

    def get_videos_details(self, ids):
        out = []
        for i, vid in enumerate(ids):
            is_short = i % 2 == 0
            # 각 포맷의 마지막 하나만 크게 터지게 만든다
            views = 100_000 if i in (10, 11) else (2_000 if is_short else 1_000)
            out.append({
                "video_id": vid, "title": f"{vid} 제목",
                "published_at": (NOW - timedelta(days=40 + i * 10)).isoformat(),
                "duration": 30 if is_short else 900,
                "thumbnail": f"https://img/{vid}.jpg",
                "views": views, "likes": views // 30, "comments": views // 300,
            })
        return out

    def is_short(self, video_id, duration):
        self.short_checks += 1
        return duration <= 60


class FakeNotion:
    def __init__(self, existing_urls=()):
        self.updates = []
        self.created = []
        self._existing = set(existing_urls)

    def monitored_channels(self, database_id):
        return [
            {"page_id": "p1", "name": "", "address": "https://www.youtube.com/@wateryang",
             "monitoring": True},
            {"page_id": "p2", "name": "수영에 미치다",
             "address": "https://www.youtube.com/@swimcrazy", "monitoring": True},
            {"page_id": "p3", "name": "없는채널", "address": "없는채널 - YouTube",
             "monitoring": True},
        ]

    def update_page(self, page_id, properties):
        self.updates.append((page_id, properties))
        return {"id": page_id}

    def create_page(self, database_id, properties):
        page_id = f"created-{len(self.created)}"
        self.created.append((database_id, properties))
        return {"id": page_id}

    def existing_analysis_urls(self, database_id):
        return self._existing


def run_pipeline(tmp_path, notion=None):
    yt, nt = FakeYouTube(), (notion or FakeNotion())
    accounts = collect_all(yt, nt, CONFIG, tmp_path, NOW)
    metrics.annotate_all(accounts, CONFIG)
    hits = metrics.collect_hits(accounts)
    entries, added = hitqueue.sync(hitqueue.load(tmp_path / "hit_queue.json"),
                                   hits, NOW.isoformat())
    created = sync_notion_rows(nt, CONFIG["notion"]["analysis_database_id"],
                               added, entries, accounts)
    hitqueue.save(tmp_path / "hit_queue.json", entries)
    return {"yt": yt, "notion": nt, "accounts": accounts, "hits": hits,
            "entries": entries, "added": added, "created": created}


def test_pipeline_collects_and_writes_data_files(tmp_path):
    r = run_pipeline(tmp_path)
    assert len(r["accounts"]) == 3                       # 실패 채널도 자리를 지킨다
    assert (tmp_path / "wateryang.json").exists()
    assert (tmp_path / "swimcrazy.json").exists()
    assert (tmp_path / "_index.json").exists()


def test_failed_channel_is_marked_in_notion_and_does_not_break_others(tmp_path):
    r = run_pipeline(tmp_path)
    failures = [props for pid, props in r["notion"].updates
                if props.get("해석 상태", {}).get("select", {}).get("name") == "해석 실패"]
    assert len(failures) == 1
    successes = [props for pid, props in r["notion"].updates
                 if props.get("해석 상태", {}).get("select", {}).get("name") == "정상"]
    assert len(successes) == 2


def test_blank_channel_name_gets_filled_but_typed_name_is_kept(tmp_path):
    r = run_pipeline(tmp_path)
    by_page = {pid: props for pid, props in r["notion"].updates}
    assert "채널명" in by_page["p1"]        # 비어 있던 행은 채워지고
    assert "채널명" not in by_page["p2"]    # 사용자가 적은 이름은 건드리지 않는다


def test_hits_flow_into_queue_and_notion(tmp_path):
    r = run_pipeline(tmp_path)
    assert r["hits"], "히트가 하나도 안 잡히면 파이프라인 검증이 무의미하다"
    assert len(r["added"]) == len(r["hits"])
    assert r["created"] == len(r["hits"])

    # 큐 항목이 노션 페이지와 연결됐는지
    for entry in r["entries"]:
        assert entry["status"] == hitqueue.PENDING
        assert entry["notion_page_id"] is not None
        assert entry["ratio"] >= 3.0

    # 노션 행에 제목·URL·성과도가 들어갔는지
    _, props = r["notion"].created[0]
    assert props["분석 상태"]["select"]["name"] == "대기"
    assert props["성과도"]["select"]["name"] == "Best"
    assert props["채널"]["relation"][0]["id"] in ("p1", "p2")


def test_second_run_does_not_duplicate_notion_rows(tmp_path):
    first = run_pipeline(tmp_path)
    urls = {e["url"] for e in first["entries"]}

    second = run_pipeline(tmp_path, notion=FakeNotion(existing_urls=urls))
    assert second["added"] == []          # 이미 큐에 있으므로 신규 없음
    assert second["created"] == 0
    assert len(second["entries"]) == len(first["entries"])


def test_analysis_progress_survives_recollection(tmp_path):
    """분석을 마친 항목이 다음 날 수집에서 '대기'로 되돌아가면 안 된다."""
    first = run_pipeline(tmp_path)
    entries = first["entries"]
    hitqueue.mark(entries, entries[0]["video_id"], hitqueue.DONE,
                  notion_page_id="page-x", analyzed_at="2026-08-04")
    hitqueue.save(tmp_path / "hit_queue.json", entries)

    second = run_pipeline(tmp_path, notion=FakeNotion(existing_urls={e["url"] for e in entries}))
    done = [e for e in second["entries"] if e["status"] == hitqueue.DONE]
    assert len(done) == 1
    assert done[0]["notion_page_id"] == "page-x"


def test_pipeline_renders_dashboard(tmp_path):
    r = run_pipeline(tmp_path)
    html = render_html(r["accounts"], r["entries"], NOW, CONFIG)
    assert "wateryang 채널" in html
    assert "🔥" in html
    assert "분석 대기" in html            # 큐에 연결된 노션 링크


def test_shorts_detection_runs_once_per_video(tmp_path):
    """쇼츠 판별은 비싸므로 새 영상에 대해서만 1회 수행해야 한다."""
    yt, nt = FakeYouTube(), FakeNotion()
    collect_all(yt, nt, CONFIG, tmp_path, NOW)
    first_pass = yt.short_checks
    assert first_pass == 24               # 채널 2개 × 12편

    collect_all(yt, nt, CONFIG, tmp_path, NOW)
    assert yt.short_checks == first_pass   # 두 번째 수집에서는 추가 확인 없음
