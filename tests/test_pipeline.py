"""Layer 1 전체 배선 통합 테스트.

가짜 YouTube/노션 클라이언트로 수집 → 지표 → 큐 → 노션 행 생성 → 렌더까지
한 번에 돌려 본다. 실제 API 키 없이 모듈 간 연결이 맞는지 확인하는 것이 목적이다.
"""

from datetime import datetime, timedelta, timezone

from src import hitqueue, metrics
from src.collect import collect_all
from src.main import (archive_dropped_rows, refresh_metric_properties,
                      sync_notion_rows)
from src.render import render_html

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 4, 7, 10, tzinfo=KST)

CONFIG = {
    "notion": {"channel_database_id": "chan-db", "analysis_database_id": "an-db"},
    "collect": {"years": 3, "max_videos": 1000, "freeze_days": 30},
    "metrics": {"hot_ratio": 3.0, "min_videos": 5,
                "contribution_quantiles": {"best": 0.90, "good": 0.70, "normal": 0.40}},
    "analysis": {"long": {"min_ratio": 5.0, "min_views": 50_000},
                 "shorts": {"min_ratio": 10.0, "min_views": 100_000}},
    "dashboard": {"title": "레퍼런스 유튜브 채널 분석"},
}


class FakeYouTube:
    """채널 2개 — 하나는 정상, 하나는 채널을 못 찾는 상황."""

    def __init__(self):
        self.shorts_lookups = 0

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
            # i=10,11 은 크게 터진 영상(분석 대상), i=8,9 는 배수는 높지만
            # 절대 조회수가 낮은 영상(대시보드 🔥 는 되지만 분석 대상은 아님)
            if i in (10, 11):
                views = 100_000
            elif i == 8:
                views = 20_000
            elif i == 9:
                views = 8_000
            else:
                views = 2_000 if is_short else 1_000
            out.append({
                "video_id": vid, "title": f"{vid} 제목",
                "published_at": (NOW - timedelta(days=40 + i * 10)).isoformat(),
                "duration": 30 if is_short else 900,
                "thumbnail": f"https://img/{vid}.jpg",
                "views": views, "likes": views // 30, "comments": views // 300,
            })
        return out

    def get_shorts_video_ids(self, channel_id):
        """채널당 한 번만 호출되어야 한다."""
        self.shorts_lookups += 1
        handle = channel_id.replace("UC_", "")
        return {f"{handle}{i}" for i in range(12) if i % 2 == 0}


class FakeNotion:
    def __init__(self, existing_urls=()):
        self.updates = []
        self.created = []
        self.archived = []
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

    def archive_page(self, page_id):
        self.archived.append(page_id)
        return {"id": page_id}


def run_pipeline(tmp_path, notion=None, config=CONFIG):
    yt, nt = FakeYouTube(), (notion or FakeNotion())
    accounts = collect_all(yt, nt, config, tmp_path, NOW)
    metrics.annotate_all(accounts, config)
    hits = metrics.collect_hits(accounts)
    targets = metrics.collect_analysis_targets(accounts, config)
    entries, added, removed = hitqueue.sync(
        hitqueue.load(tmp_path / "hit_queue.json"), targets, NOW.isoformat())
    archived = archive_dropped_rows(nt, removed)
    created = sync_notion_rows(nt, config["notion"]["analysis_database_id"],
                               added, entries, accounts)
    refreshed = refresh_metric_properties(nt, entries, accounts,
                                          {e["video_id"] for e in added})
    hitqueue.save(tmp_path / "hit_queue.json", entries)
    return {"yt": yt, "notion": nt, "accounts": accounts, "hits": hits,
            "targets": targets, "entries": entries, "added": added,
            "removed": removed, "created": created, "archived": archived,
            "refreshed": refreshed}


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


def test_analysis_targets_flow_into_queue_and_notion(tmp_path):
    r = run_pipeline(tmp_path)
    assert r["targets"], "대상이 하나도 안 잡히면 파이프라인 검증이 무의미하다"
    assert len(r["added"]) == len(r["targets"])
    assert r["created"] == len(r["targets"])

    # 큐 항목이 노션 페이지와 연결됐는지
    for entry in r["entries"]:
        assert entry["status"] == hitqueue.PENDING
        assert entry["notion_page_id"] is not None

    # 노션 행에 제목·URL·성과도가 들어갔는지
    _, props = r["notion"].created[0]
    assert props["분석 상태"]["select"]["name"] == "대기"
    assert props["성과도"]["select"]["name"] == "Best"
    assert props["채널"]["relation"][0]["id"] in ("p1", "p2")


def test_analysis_targets_are_stricter_than_dashboard_hits(tmp_path):
    """대시보드 🔥(성과도 Best)보다 심층 분석 대상이 더 좁아야 한다."""
    r = run_pipeline(tmp_path)
    assert len(r["targets"]) < len(r["hits"])
    for t in r["targets"]:
        rule = CONFIG["analysis"][t["format"]]
        assert t["_perf_ratio"] >= rule["min_ratio"]
        assert t["metrics"]["views"] >= rule["min_views"]


def test_tightening_criteria_drops_pending_rows_from_queue_and_notion(tmp_path):
    """기준을 올리면 아직 분석 안 한 행은 큐에서 빠지고 노션에서도 정리된다."""
    first = run_pipeline(tmp_path)
    assert first["targets"]

    strict = {**CONFIG, "analysis": {"long": {"min_ratio": 999, "min_views": 999_999_999},
                                     "shorts": {"min_ratio": 999, "min_views": 999_999_999}}}
    second = run_pipeline(tmp_path, config=strict)

    assert second["targets"] == []
    assert len(second["removed"]) == len(first["targets"])
    assert second["archived"] == len(first["targets"])
    assert second["entries"] == []


def test_existing_rows_get_fresh_metrics_but_not_on_creation(tmp_path):
    """행을 만든 날엔 이미 최신값이라 갱신하지 않고, 이후 실행부터 갱신한다."""
    first = run_pipeline(tmp_path)
    assert first["refreshed"] == 0            # 방금 만든 행은 건너뛴다

    second = run_pipeline(tmp_path, notion=FakeNotion(
        existing_urls={e["url"] for e in first["entries"]}))
    assert second["refreshed"] == len(first["entries"])

    # 지표만 갱신하고 분석으로 채우는 속성은 건드리지 않는다
    metric_updates = [props for _, props in second["notion"].updates
                      if "성과 배수" in props]
    assert metric_updates
    for props in metric_updates:
        assert "제목" not in props
        assert "분석 상태" not in props
        assert "콘텐츠 유형" not in props
        assert "후킹 유형" not in props


def test_completed_analyses_survive_criteria_change(tmp_path):
    """이미 분석을 마친 영상은 기준이 바뀌어도 큐에서 지우면 안 된다."""
    first = run_pipeline(tmp_path)
    entries = first["entries"]
    hitqueue.mark(entries, entries[0]["video_id"], hitqueue.DONE,
                  notion_page_id="page-done", analyzed_at="2026-08-04")
    hitqueue.save(tmp_path / "hit_queue.json", entries)

    strict = {**CONFIG, "analysis": {"long": {"min_ratio": 999, "min_views": 999_999_999},
                                     "shorts": {"min_ratio": 999, "min_views": 999_999_999}}}
    second = run_pipeline(tmp_path, config=strict)

    survived = [e for e in second["entries"] if e["status"] == hitqueue.DONE]
    assert len(survived) == 1
    assert survived[0]["notion_page_id"] == "page-done"
    assert "page-done" not in second["notion"].archived


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


def test_shorts_detection_is_one_lookup_per_channel(tmp_path):
    """영상 편수와 무관하게 채널당 한 번만 조회해야 한다.

    영상마다 요청을 보내면 3년치 수집에서 수천 건이 되어 사실상 멈춘다.
    """
    yt, nt = FakeYouTube(), FakeNotion()
    accounts = collect_all(yt, nt, CONFIG, tmp_path, NOW)
    assert yt.shorts_lookups == 2          # 성공한 채널 2개 (영상은 24편)

    # 판별 결과가 실제로 반영됐는지
    videos = accounts[0]["videos"]
    assert {v["format"] for v in videos} == {"shorts", "long"}

    collect_all(yt, nt, CONFIG, tmp_path, NOW)
    assert yt.shorts_lookups == 2          # 두 번째 수집에서는 추가 조회 없음
