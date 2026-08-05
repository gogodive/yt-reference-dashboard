"""노션 페이로드 생성 테스트 — API 호출 없이 순수 함수만 검증한다."""

from src import notion


def page(props):
    return {"id": "page-1", "properties": props}


def test_plain_text_reads_title_and_rich_text():
    assert notion.plain_text({"title": [{"plain_text": "워터양"}]}) == "워터양"
    assert notion.plain_text({"rich_text": [{"plain_text": "a"}, {"plain_text": "b"}]}) == "ab"
    assert notion.plain_text(None) == ""
    assert notion.plain_text({"rich_text": []}) == ""


def test_parse_channel_row():
    row = notion.parse_channel_row(page({
        "채널명": {"title": [{"plain_text": "워터양"}]},
        "채널 주소": {"rich_text": [{"plain_text": "(20) 워터양 - YouTube"}]},
        "모니터링": {"checkbox": True},
    }))
    assert row == {"page_id": "page-1", "name": "워터양",
                   "address": "(20) 워터양 - YouTube", "monitoring": True}


def test_parse_channel_row_handles_empty_cells():
    row = notion.parse_channel_row(page({"채널 주소": {"rich_text": []}}))
    assert row["name"] == ""
    assert row["monitoring"] is False


META = {"url": "https://www.youtube.com/@wateryang", "title": "워터양 Wateryang",
        "subscribers": 120_000, "video_count": 340}


def test_channel_update_fills_blank_name_and_normalizes_url():
    props = notion.channel_update_payload(META, avg_views=51_234.7,
                                          fetched_at="2026-08-04", current_name="")
    assert props["채널명"]["title"][0]["text"]["content"] == "워터양 Wateryang"
    assert props["채널 주소"]["rich_text"][0]["text"]["content"] == META["url"]
    assert props["구독자수"]["number"] == 120_000
    assert props["총 영상수"]["number"] == 340
    assert props["평균 조회수"]["number"] == 51_234        # 정수로 내림
    assert props["해석 상태"]["select"]["name"] == "정상"


def test_channel_update_respects_user_typed_name():
    props = notion.channel_update_payload(META, avg_views=None,
                                          fetched_at="2026-08-04", current_name="내가 적은 이름")
    assert "채널명" not in props
    assert "평균 조회수" not in props


def test_channel_update_omits_hidden_subscriber_count():
    meta = {**META, "subscribers": None}
    props = notion.channel_update_payload(meta, avg_views=1, fetched_at="2026-08-04")
    assert "구독자수" not in props


def test_channel_failure_payload():
    props = notion.channel_failure_payload("채널을 찾을 수 없음: 워터클랜즈", "2026-08-04")
    assert props["해석 상태"]["select"]["name"] == "해석 실패"
    assert "워터클랜즈" in props["메모"]["rich_text"][0]["text"]["content"]


HIT = {
    "video_id": "abc123",
    "title": "울릉도 프리다이빙",
    "url": "https://www.youtube.com/watch?v=abc123",
    "published_at": "2024-08-24T09:00:00Z",
    "duration": 1528,
    "format": "long",
    "metrics": {"views": 46_800, "likes": 900, "comments": 94},
    "_perf_ratio": 4.234,
    "_perf_grade": "Best",
    "_contribution_grade": "Good",
    "_engagement": 0.021239,
}


def test_analysis_row_payload():
    props = notion.analysis_row_payload(HIT, channel_page_id="ch-1")
    assert props["제목"]["title"][0]["text"]["content"] == "울릉도 프리다이빙"
    assert props["영상 URL"]["url"] == HIT["url"]
    assert props["포맷"]["select"]["name"] == "롱폼"
    assert props["게시일"]["date"]["start"] == "2024-08-24"   # 날짜만
    assert props["영상 길이(초)"]["number"] == 1528
    assert props["조회수"]["number"] == 46_800
    assert props["성과 배수"]["number"] == 4.23              # 소수 2자리
    assert props["성과도"]["select"]["name"] == "Best"
    assert props["기여도"]["select"]["name"] == "Good"
    assert props["참여율"]["number"] == 0.0212
    assert props["분석 상태"]["select"]["name"] == "대기"
    assert props["채널"]["relation"] == [{"id": "ch-1"}]


def test_analysis_row_payload_shorts_label():
    props = notion.analysis_row_payload({**HIT, "format": "shorts"})
    assert props["포맷"]["select"]["name"] == "쇼츠"


def test_analysis_row_payload_skips_missing_fields():
    minimal = {"video_id": "x", "url": "https://y", "metrics": {}}
    props = notion.analysis_row_payload(minimal)
    assert props["제목"]["title"][0]["text"]["content"] == "x"
    for absent in ("포맷", "게시일", "영상 길이(초)", "조회수", "성과 배수",
                   "성과도", "기여도", "참여율", "채널"):
        assert absent not in props


def test_long_titles_are_truncated():
    props = notion.analysis_row_payload({**HIT, "title": "가" * 3000})
    assert len(props["제목"]["title"][0]["text"]["content"]) == 2000


# ---------- 허브 콜아웃 ----------

class FakeCallout(notion.NotionClient):
    """API 대신 호출 기록만 남기는 클라이언트."""

    def __init__(self, children):
        self._children = children
        self.updated: list[tuple] = []
        self.appended: list[list] = []

    def block_children(self, block_id):
        return self._children

    def update_block(self, block_id, payload):
        self.updated.append((block_id, payload))
        return {}

    def append_blocks(self, block_id, children, after=None):
        self.appended.append(children)
        return {}


def callout_block(block_id, text):
    return {"id": block_id, "type": "callout",
            "callout": {"rich_text": [{"plain_text": text}]}}


def test_run_callout_updates_existing_block():
    """매일 도는 작업이라 블록이 쌓이면 안 된다 — 같은 블록을 갱신해야 한다."""
    client = FakeCallout([
        {"id": "b0", "type": "paragraph", "paragraph": {"rich_text": []}},
        callout_block("b1", f"{notion.RUN_CALLOUT_PREFIX}: 2026-08-05 07:10 KST"),
    ])
    assert client.sync_run_callout("hub", f"{notion.RUN_CALLOUT_PREFIX}: 새 값") == "updated"
    assert client.appended == []
    block_id, payload = client.updated[0]
    assert block_id == "b1"
    assert payload["callout"]["rich_text"][0]["text"]["content"].endswith("새 값")


def test_run_callout_creates_when_absent():
    client = FakeCallout([{"id": "b0", "type": "paragraph", "paragraph": {"rich_text": []}}])
    assert client.sync_run_callout("hub", "마지막 수집: 값") == "created"
    assert client.updated == []
    assert client.appended[0][0]["callout"]["icon"]["emoji"] == "🕘"


def test_run_callout_ignores_other_callouts():
    """페이지에 있는 다른 콜아웃(안내문 등)을 덮어쓰면 안 된다."""
    client = FakeCallout([callout_block("b1", "이 대시보드는 매일 갱신됩니다")])
    assert client.sync_run_callout("hub", "마지막 수집: 값") == "created"
    assert client.updated == []
