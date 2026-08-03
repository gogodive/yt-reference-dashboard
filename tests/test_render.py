from datetime import datetime, timedelta, timezone

from src import metrics, render

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 4, 7, 10, tzinfo=KST)

CONFIG = {"metrics": {"hot_ratio": 3.0, "min_videos": 5,
                      "contribution_quantiles": {"best": 0.90, "good": 0.70, "normal": 0.40}},
          "dashboard": {"title": "레퍼런스 유튜브 채널 분석"}}


def video(vid_id, days_ago, views, fmt="long", likes=100, comments=20):
    published = (NOW - timedelta(days=days_ago)).isoformat()
    return {"video_id": vid_id, "title": f"영상 {vid_id}", "url": f"https://y/{vid_id}",
            "thumbnail": "t.jpg", "published_at": published, "duration": 600,
            "format": fmt, "frozen": True,
            "metrics": {"views": views, "likes": likes, "comments": comments}}


def account():
    videos = [video(f"l{i}", 30 + i * 10, 1000) for i in range(5)]
    videos.append(video("hit", 15, 5000))
    videos += [video(f"s{i}", 20 + i * 5, 3000, fmt="shorts") for i in range(5)]
    return {"brand": "워터양", "handle": "wateryang", "title": "워터양 Wateryang",
            "url": "https://www.youtube.com/@wateryang",
            "channel_published_at": (NOW - timedelta(days=1200)).isoformat(),
            "subscribers": 120_000, "video_count": 340, "total_views": 12_000_000,
            "fetched_at": NOW.isoformat(), "videos": videos}


def test_formatters():
    assert render._fmt_compact(46_800) == "4.7만"
    assert render._fmt_compact(123_000_000) == "1.2억"
    assert render._fmt_compact(999) == "999"
    assert render._fmt_compact(None) == "–"
    assert render._fmt_dur(1528) == "25:28"
    assert render._fmt_dur(3723) == "1:02:03"
    assert render._fmt_pct(0.0212) == "2.12%"
    assert render._fmt_ratio(4.234) == "4.2x"
    assert render._fmt_ratio(None) == "–"


def test_grade_rank_puts_unjudged_last():
    assert render.grade_rank("Best") == 3
    assert render.grade_rank("Worst") == 0
    assert render.grade_rank(None) == -1


def test_notion_page_url():
    assert render.notion_page_url("abc-def") == "https://www.notion.so/abcdef"
    assert render.notion_page_url(None) is None


def test_prepare_splits_formats_and_marks_hits():
    acc = account()
    metrics.annotate_all([acc], CONFIG)
    render.prepare([acc], [], NOW)

    assert len(acc["_long"]) == 6
    assert len(acc["_shorts"]) == 5
    assert [v["video_id"] for v in acc["_hits"]] == ["hit"]
    assert acc["_channel_age_days"] == 1200
    assert acc["_stale_date"] is None
    # 30일 이내: hit(15) + 쇼츠 20·25·30 + 롱폼 30 = 5편 (경계값 30일 포함)
    assert acc["_recent_uploads"] == 5


def test_prepare_flags_stale_data():
    acc = account()
    acc["fetched_at"] = (NOW - timedelta(days=3)).isoformat()
    metrics.annotate_all([acc], CONFIG)
    render.prepare([acc], [], NOW)
    assert acc["_stale_date"] == (NOW - timedelta(days=3)).strftime("%Y-%m-%d")


def test_prepare_links_notion_analysis():
    acc = account()
    metrics.annotate_all([acc], CONFIG)
    queue = [{"video_id": "hit", "notion_page_id": "page-abc", "status": "done"}]
    render.prepare([acc], queue, NOW)
    hit = next(v for v in acc["videos"] if v["video_id"] == "hit")
    assert hit["_notion_url"] == "https://www.notion.so/pageabc"
    assert hit["_analysis_status"] == "done"


def test_chart_points_exclude_zero_views_and_sort_by_date():
    acc = account()
    acc["videos"].append(video("novies", 5, 0))
    pts = render.chart_points(acc["videos"], NOW)
    assert "novies" not in [p["t"] for p in pts]
    assert pts == sorted(pts, key=lambda p: p["d"])


def test_render_html_produces_full_page():
    acc = account()
    metrics.annotate_all([acc], CONFIG)
    html = render.render_html([acc], [], NOW, CONFIG)

    assert "<!doctype html>" in html
    assert "워터양" in html
    assert "🔥" in html                    # 히트 뱃지
    assert 'data-key="ratio"' in html      # 정렬 가능한 성과 배수 열
    assert "chart-data-0" in html
    # 등급 셀이 실제로 렌더링됐는지
    assert "grade g-best" in html


def test_render_html_escapes_titles():
    acc = account()
    acc["videos"][0]["title"] = '<script>alert("x")</script>'
    metrics.annotate_all([acc], CONFIG)
    html = render.render_html([acc], [], NOW, CONFIG)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
