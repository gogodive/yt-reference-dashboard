from src import metrics
from src.metrics import BEST, GOOD, NORMAL, WORST


def vid(vid_id, fmt, views, likes=0, comments=0):
    return {
        "video_id": vid_id,
        "format": fmt,
        "metrics": {"views": views, "likes": likes, "comments": comments},
    }


CONFIG = {"metrics": {"hot_ratio": 3.0, "min_videos": 5,
                      "contribution_quantiles": {"best": 0.90, "good": 0.70, "normal": 0.40}}}


def test_performance_ratio():
    assert metrics.performance_ratio(300, 100) == 3.0
    assert metrics.performance_ratio(None, 100) is None
    assert metrics.performance_ratio(0, 100) is None
    assert metrics.performance_ratio(300, 0) is None


def test_grade_performance_boundaries():
    # 3배가 히트 경계 — 정확히 3배면 Best
    assert metrics.grade_performance(3.0) == BEST
    assert metrics.grade_performance(2.999) == GOOD
    assert metrics.grade_performance(1.5) == GOOD
    assert metrics.grade_performance(1.499) == NORMAL
    assert metrics.grade_performance(0.5) == NORMAL
    assert metrics.grade_performance(0.499) == WORST
    assert metrics.grade_performance(None) is None


def test_hot_ratio_is_configurable():
    assert metrics.grade_performance(2.5, hot_ratio=2.0) == BEST
    assert metrics.grade_performance(2.5, hot_ratio=3.0) == GOOD


def test_format_medians_separates_formats():
    videos = ([vid(f"l{i}", "long", 100) for i in range(5)]
              + [vid(f"s{i}", "shorts", 1000) for i in range(5)])
    medians = metrics.format_medians(videos, min_videos=5)
    assert medians == {"long": 100, "shorts": 1000}


def test_format_medians_skips_small_samples():
    videos = [vid(f"l{i}", "long", 100) for i in range(4)]
    assert metrics.format_medians(videos, min_videos=5) == {}


def test_annotate_channel_marks_hits_per_format():
    videos = [vid(f"l{i}", "long", 100) for i in range(5)]
    videos.append(vid("long_hit", "long", 400))          # 롱폼 중앙값 100 → 4배
    videos += [vid(f"s{i}", "shorts", 10_000) for i in range(5)]
    videos.append(vid("shorts_normal", "shorts", 20_000))  # 쇼츠 중앙값 10000 → 2배
    account = {"handle": "x", "subscribers": 1000, "videos": videos}

    metrics.annotate_channel(account, CONFIG)

    by_id = {v["video_id"]: v for v in videos}
    assert by_id["long_hit"]["_perf_grade"] == BEST
    assert by_id["long_hit"]["_is_hit"] is True
    # 쇼츠는 조회수 절대값이 훨씬 크지만 자기 포맷 중앙값 대비 2배라 히트가 아니다
    assert by_id["shorts_normal"]["_perf_grade"] == GOOD
    assert by_id["shorts_normal"]["_is_hit"] is False


def test_annotate_channel_skips_grading_when_sample_too_small():
    videos = [vid(f"l{i}", "long", 100) for i in range(4)]
    account = {"handle": "x", "subscribers": 1000, "videos": videos}
    metrics.annotate_channel(account, CONFIG)
    assert all(v["_perf_grade"] is None for v in videos)
    assert all(v["_is_hit"] is False for v in videos)


def test_contribution_uses_subscriber_ratio_across_channels():
    # 조회수가 같아도 구독자가 적은 채널일수록 기여도(구독자 대비 확산)가 높다
    small = {"handle": "small", "subscribers": 1_000,
             "videos": [vid("viral", "long", 100_000)]}
    big = {"handle": "big", "subscribers": 1_000_000,
           "videos": [vid("ordinary", "long", 100_000)]}
    # 등급 경계가 의미를 갖도록 분포를 채워 준다
    filler = {"handle": "filler", "subscribers": 10_000,
              "videos": [vid(f"f{i}", "long", 1_000 * (i + 1)) for i in range(10)]}

    metrics.annotate_contribution([small, big, filler], CONFIG)

    assert small["videos"][0]["_contribution"] == 100.0
    assert big["videos"][0]["_contribution"] == 0.1
    assert small["videos"][0]["_contribution_grade"] == BEST
    assert big["videos"][0]["_contribution_grade"] == WORST


def test_contribution_ties_get_the_generous_grade():
    """값이 전부 동점이면 분위수로 나눌 수 없으므로 아무도 Worst 가 되지 않는다."""
    acc = {"handle": "x", "subscribers": 1_000,
           "videos": [vid(f"a{i}", "long", 5_000) for i in range(10)]}
    metrics.annotate_contribution([acc], CONFIG)
    assert {v["_contribution_grade"] for v in acc["videos"]} == {BEST}


def test_contribution_none_when_subscribers_hidden():
    acc = {"handle": "x", "subscribers": None,
           "videos": [vid(f"a{i}", "long", 100) for i in range(5)]}
    metrics.annotate_contribution([acc], CONFIG)
    assert all(v["_contribution"] is None for v in acc["videos"])
    assert all(v["_contribution_grade"] is None for v in acc["videos"])


def test_engagement_rate():
    assert metrics.engagement_rate(vid("a", "long", 1000, likes=80, comments=20)) == 0.1
    assert metrics.engagement_rate(vid("a", "long", None)) is None


def test_collect_hits_sorted_by_ratio():
    videos = [vid(f"l{i}", "long", 100) for i in range(5)]
    videos.append(vid("hit_small", "long", 400))   # 4배
    videos.append(vid("hit_big", "long", 900))     # 9배
    acc = {"handle": "x", "title": "채널", "subscribers": 1000, "videos": videos}

    metrics.annotate_all([acc], CONFIG)
    hits = metrics.collect_hits([acc])

    assert [h["video_id"] for h in hits] == ["hit_big", "hit_small"]
    assert hits[0]["_channel"] == "채널"


RULES = {"long": {"min_ratio": 5.0, "min_views": 50_000},
         "shorts": {"min_ratio": 10.0, "min_views": 100_000}}


def target(fmt, ratio, views):
    return {"format": fmt, "_perf_ratio": ratio, "metrics": {"views": views}}


def test_analysis_target_requires_both_ratio_and_views():
    assert metrics.is_analysis_target(target("long", 5.0, 50_000), RULES) is True
    # 배수는 넘지만 조회수가 모자람 — 그 채널에선 잘됐어도 도달이 작다
    assert metrics.is_analysis_target(target("long", 50.0, 10_000), RULES) is False
    # 조회수는 크지만 배수가 모자람 — 그 채널에선 평범한 영상이다
    assert metrics.is_analysis_target(target("long", 2.0, 500_000), RULES) is False


def test_analysis_target_applies_a_higher_bar_to_shorts():
    """쇼츠는 중앙값이 바닥에 깔려 배수가 쉽게 커진다."""
    mid = target("shorts", 6.0, 60_000)
    assert metrics.is_analysis_target(mid, RULES) is False
    # 같은 수치를 롱폼 기준으로 보면 대상이 된다
    assert metrics.is_analysis_target({**mid, "format": "long"}, RULES) is True


def test_analysis_target_handles_missing_data():
    assert metrics.is_analysis_target(target("long", None, 100_000), RULES) is False
    assert metrics.is_analysis_target(target("long", 10.0, None), RULES) is False
    assert metrics.is_analysis_target(target("live", 10.0, 100_000), RULES) is False


def test_collect_analysis_targets_sorted_and_marked():
    videos = [vid(f"l{i}", "long", 1_000) for i in range(5)]
    videos.append(vid("big", "long", 500_000))    # 500배
    videos.append(vid("mid", "long", 60_000))     # 60배 — 둘 다 통과
    videos.append(vid("small", "long", 10_000))   # 10배지만 조회수 미달
    acc = {"handle": "x", "title": "채널", "subscribers": 1_000, "videos": videos}

    metrics.annotate_all([acc], CONFIG)
    targets = metrics.collect_analysis_targets([acc], {"analysis": RULES})

    assert [t["video_id"] for t in targets] == ["big", "mid"]
    by_id = {v["video_id"]: v for v in videos}
    assert by_id["small"]["_is_hit"] is True      # 대시보드에서는 여전히 🔥
    assert by_id["small"]["_analyze"] is False    # 하지만 분석 대상은 아님


def test_percentile_edges():
    assert metrics.percentile([5.0], 0.9) == 5.0
    values = [float(i) for i in range(10)]
    assert metrics.percentile(values, 0.0) == 0.0
    assert metrics.percentile(values, 1.0) == 9.0
