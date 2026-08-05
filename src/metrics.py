"""조회수 / 기여도 / 성과도 계산 (순수 함수 — API·파일 접근 없음).

ViewTrap 의 3지표를 YouTube Data API 로 얻을 수 있는 공개 데이터만으로 근사한다.

- 성과도  = 조회수 ÷ 같은 채널·같은 포맷 조회수 중앙값
            "구독자 기반 노출을 얼마나 넘어섰나". 채널 내 상대 지표.
- 기여도  = 조회수 ÷ 채널 구독자 수
            "이 주제가 채널 밖으로 얼마나 퍼졌나". 전체 채널 통합 분위수로 등급화.
- 참여율  = (좋아요 + 댓글) ÷ 조회수. 채널 내 분위수로 등급화.

히트(심층 분석 대상) = 성과도 Best (중앙값의 hot_ratio 배 이상).
"""

from __future__ import annotations

import statistics

BEST, GOOD, NORMAL, WORST = "Best", "Good", "Normal", "Worst"
GRADE_ORDER = {BEST: 3, GOOD: 2, NORMAL: 1, WORST: 0}

DEFAULT_HOT_RATIO = 3.0
DEFAULT_MIN_VIDEOS = 5

# 성과도 등급 경계 (중앙값 대비 배수)
PERF_GOOD_RATIO = 1.5
PERF_NORMAL_RATIO = 0.5

FORMATS = ("long", "shorts")


def _views(video: dict) -> int | None:
    v = (video.get("metrics") or {}).get("views")
    return v if isinstance(v, int) and v > 0 else None


def percentile(sorted_values: list[float], q: float) -> float:
    """0~1 사이 분위수. 선형 보간 없이 가장 가까운 하위 값을 쓴다."""
    if not sorted_values:
        raise ValueError("빈 목록의 분위수는 계산할 수 없습니다")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = min(int(q * (len(sorted_values) - 1)), len(sorted_values) - 1)
    return sorted_values[idx]


def performance_ratio(views: int | None, median: float) -> float | None:
    """조회수를 같은 포맷 중앙값으로 나눈 배수."""
    if not isinstance(views, int) or views <= 0 or median <= 0:
        return None
    return views / median


def grade_performance(ratio: float | None, hot_ratio: float = DEFAULT_HOT_RATIO) -> str | None:
    if ratio is None:
        return None
    if ratio >= hot_ratio:
        return BEST
    if ratio >= PERF_GOOD_RATIO:
        return GOOD
    if ratio >= PERF_NORMAL_RATIO:
        return NORMAL
    return WORST


def contribution_score(views: int | None, subscribers: int | None) -> float | None:
    """구독자 대비 조회수 배수. 구독자 정보가 없으면 판정하지 않는다."""
    if not isinstance(views, int) or views <= 0:
        return None
    if not isinstance(subscribers, int) or subscribers <= 0:
        return None
    return views / subscribers


def engagement_rate(video: dict) -> float | None:
    m = video.get("metrics") or {}
    views = _views(video)
    if views is None:
        return None
    likes = m.get("likes") or 0
    comments = m.get("comments") or 0
    if not isinstance(likes, int) or not isinstance(comments, int):
        return None
    return (likes + comments) / views


def make_quantile_grader(values: list[float], quantiles: dict,
                         min_samples: int = DEFAULT_MIN_VIDEOS):
    """값 분포로부터 4등급 판정 함수를 만든다.

    표본이 min_samples 미만이면 항상 None 을 돌려주는 함수를 반환한다.
    """
    clean = sorted(v for v in values if isinstance(v, (int, float)))
    if len(clean) < min_samples:
        return lambda _value: None

    best_at = percentile(clean, quantiles.get("best", 0.90))
    good_at = percentile(clean, quantiles.get("good", 0.70))
    normal_at = percentile(clean, quantiles.get("normal", 0.40))

    def grade(value):
        if value is None:
            return None
        if value >= best_at:
            return BEST
        if value >= good_at:
            return GOOD
        if value >= normal_at:
            return NORMAL
        return WORST

    return grade


def format_medians(videos: list[dict], min_videos: int = DEFAULT_MIN_VIDEOS) -> dict:
    """포맷별 조회수 중앙값. 표본이 적으면 그 포맷은 빠진다."""
    out = {}
    for fmt in FORMATS:
        views = [_views(v) for v in videos if v.get("format") == fmt]
        views = [x for x in views if x is not None]
        if len(views) >= min_videos:
            median = statistics.median(views)
            if median > 0:
                out[fmt] = median
    return out


def annotate_channel(account: dict, config: dict | None = None) -> None:
    """한 채널의 영상들에 성과도·참여율을 붙인다 (제자리 수정).

    참여율 등급도 포맷별로 매긴다. 쇼츠는 조회수 대비 좋아요가 롱폼보다
    구조적으로 높아서, 섞어 놓으면 등급이 성과가 아니라 포맷을 말하게 된다.
    """
    cfg = (config or {}).get("metrics", {})
    hot_ratio = cfg.get("hot_ratio", DEFAULT_HOT_RATIO)
    min_videos = cfg.get("min_videos", DEFAULT_MIN_VIDEOS)
    quantiles = cfg.get("contribution_quantiles", {})

    videos = account.get("videos", [])
    medians = format_medians(videos, min_videos)
    account["_medians"] = medians

    engagement_graders = {}
    for fmt in FORMATS:
        values = [e for e in (engagement_rate(v) for v in videos
                              if v.get("format") == fmt) if e is not None]
        engagement_graders[fmt] = make_quantile_grader(values, quantiles, min_videos)

    for v in videos:
        median = medians.get(v.get("format"))
        ratio = performance_ratio(_views(v), median) if median else None
        # 배수는 중앙값이 움직이면 같이 움직인다. 나중에 재현하려면 분모도 있어야 한다.
        v["_median"] = median
        v["_perf_ratio"] = ratio
        v["_perf_grade"] = grade_performance(ratio, hot_ratio)
        v["_is_hit"] = v["_perf_grade"] == BEST
        eng = engagement_rate(v)
        v["_engagement"] = eng
        grader = engagement_graders.get(v.get("format"))
        v["_engagement_grade"] = grader(eng) if grader else None


def annotate_contribution(accounts: list[dict], config: dict | None = None) -> None:
    """기여도는 채널 간 비교라 전체를 모아 등급화하되, 포맷별로 나눈다.

    쇼츠는 구독자 대비 도달이 롱폼보다 압도적이라 섞어서 순위를 매기면
    쇼츠가 상위 등급을 독식한다(실측: 쇼츠 94%가 Best). 그러면 등급이
    "쇼츠냐 롱폼이냐"를 말할 뿐 성과를 말하지 못한다.
    """
    cfg = (config or {}).get("metrics", {})
    min_videos = cfg.get("min_videos", DEFAULT_MIN_VIDEOS)
    quantiles = cfg.get("contribution_quantiles", {})

    scores: dict[str, list[float]] = {fmt: [] for fmt in FORMATS}
    for acc in accounts:
        subs = acc.get("subscribers")
        for v in acc.get("videos", []):
            score = contribution_score(_views(v), subs)
            v["_contribution"] = score
            if score is not None and v.get("format") in scores:
                scores[v["format"]].append(score)

    graders = {fmt: make_quantile_grader(values, quantiles, min_videos)
               for fmt, values in scores.items()}
    for acc in accounts:
        for v in acc.get("videos", []):
            grader = graders.get(v.get("format"))
            v["_contribution_grade"] = grader(v.get("_contribution")) if grader else None


def annotate_all(accounts: list[dict], config: dict | None = None) -> None:
    for acc in accounts:
        annotate_channel(acc, config)
    annotate_contribution(accounts, config)


def collect_hits(accounts: list[dict]) -> list[dict]:
    """전체 채널의 히트 영상(성과도 Best)을 성과 배수 높은 순으로 모은다."""
    hits = []
    for acc in accounts:
        for v in acc.get("videos", []):
            if v.get("_is_hit"):
                hits.append({**v, "_channel": acc.get("title") or acc.get("handle"),
                             "_handle": acc.get("handle")})
    hits.sort(key=lambda v: v.get("_perf_ratio") or 0, reverse=True)
    return hits


# ---------- 심층 분석 대상 선정 ----------

DEFAULT_ANALYSIS = {
    "long": {"min_ratio": 5.0, "min_views": 50_000},
    "shorts": {"min_ratio": 10.0, "min_views": 100_000},
}


def is_analysis_target(video: dict, rules: dict) -> bool:
    """영상을 끝까지 볼 만한가.

    배수(채널 내 상대 성과)와 조회수(절대 도달)를 **둘 다** 넘어야 한다.
    배수만 보면 조회수가 낮은 채널의 소소한 영상이 걸리고,
    조회수만 보면 그 채널에선 평범한 영상이 걸린다.
    """
    rule = rules.get(video.get("format"))
    if not rule:
        return False
    ratio = video.get("_perf_ratio")
    views = (video.get("metrics") or {}).get("views")
    if ratio is None or not isinstance(views, int):
        return False
    return ratio >= rule["min_ratio"] and views >= rule["min_views"]


def collect_analysis_targets(accounts: list[dict],
                             config: dict | None = None) -> list[dict]:
    """심층 분석 큐에 넣을 영상을 성과 배수 높은 순으로 모은다."""
    rules = (config or {}).get("analysis") or DEFAULT_ANALYSIS
    targets = []
    for acc in accounts:
        for v in acc.get("videos", []):
            hit = is_analysis_target(v, rules)
            v["_analyze"] = hit
            if hit:
                targets.append({**v, "_channel": acc.get("title") or acc.get("handle"),
                                "_handle": acc.get("handle")})
    targets.sort(key=lambda v: v.get("_perf_ratio") or 0, reverse=True)
    return targets
