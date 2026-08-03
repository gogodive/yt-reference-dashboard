"""수집 결과 → 단일 HTML 대시보드.

ViewTrap 채널분석의 구성(채널 요약 카드 + 정렬 가능한 영상 테이블 +
Best/Good/Normal/Worst 등급)을 참고했다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Undefined, select_autoescape

from src.metrics import GRADE_ORDER

KST = timezone(timedelta(hours=9))
_TEMPLATE_DIR = Path(__file__).parent

CHART_DAYS = 365 * 3


def _fmt_num(v) -> str:
    if v is None or isinstance(v, Undefined):
        return "–"
    return f"{v:,}"


def _fmt_compact(v) -> str:
    """46800 → 4.7만"""
    if v is None or isinstance(v, Undefined):
        return "–"
    if v >= 100_000_000:
        return f"{v / 100_000_000:.1f}억"
    if v >= 10_000:
        return f"{v / 10_000:.1f}만"
    return f"{v:,}"


def _fmt_dur(seconds) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _fmt_pct(v) -> str:
    if v is None or isinstance(v, Undefined):
        return "–"
    return f"{v * 100:.2f}%"


def _fmt_ratio(v) -> str:
    if v is None or isinstance(v, Undefined):
        return "–"
    return f"{v:.1f}x"


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt_date(ts: str) -> str:
    if not ts:
        return ""
    return _parse_ts(ts).astimezone(KST).strftime("%Y-%m-%d")


def _days_since(published_at: str, generated_at: datetime) -> int:
    return (generated_at - _parse_ts(published_at)).days


def notion_page_url(page_id: str | None) -> str | None:
    if not page_id:
        return None
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def chart_points(videos: list[dict], generated_at: datetime,
                 days: int = CHART_DAYS) -> list[dict]:
    """조회수 추이 산점도용 데이터 (최근 days일, 조회수 있는 영상만)."""
    cutoff = generated_at - timedelta(days=days)
    pts = []
    for v in videos:
        views = (v.get("metrics") or {}).get("views")
        if not isinstance(views, int) or views <= 0:
            continue
        if _parse_ts(v["published_at"]) < cutoff:
            continue
        pts.append({"t": v.get("title", ""), "d": v["published_at"][:10],
                    "v": views, "f": v.get("format"), "h": bool(v.get("_is_hit"))})
    pts.sort(key=lambda p: p["d"])
    return pts


def grade_rank(grade: str | None) -> int:
    """정렬용 순위. 미판정은 맨 아래로."""
    return GRADE_ORDER.get(grade, -1)


def prepare(accounts: list[dict], queue_entries: list[dict],
            generated_at: datetime) -> None:
    """템플릿이 바로 쓸 수 있도록 파생 필드를 붙인다 (제자리 수정)."""
    queue_by_id = {e["video_id"]: e for e in queue_entries}
    gen_date = generated_at.astimezone(KST).date()

    for acc in accounts:
        fetched = acc.get("fetched_at")
        acc["_stale_date"] = None
        if fetched:
            fdt = _parse_ts(fetched).astimezone(KST)
            if fdt.date() != gen_date:
                acc["_stale_date"] = fdt.strftime("%Y-%m-%d")

        videos = acc.get("videos", [])
        for v in videos:
            v["_days"] = _days_since(v["published_at"], generated_at)
            entry = queue_by_id.get(v["video_id"])
            v["_notion_url"] = notion_page_url((entry or {}).get("notion_page_id"))
            v["_analysis_status"] = (entry or {}).get("status")
            v["_perf_rank"] = grade_rank(v.get("_perf_grade"))
            v["_contrib_rank"] = grade_rank(v.get("_contribution_grade"))

        acc["_long"] = [v for v in videos if v.get("format") != "shorts"]
        acc["_shorts"] = [v for v in videos if v.get("format") == "shorts"]
        acc["_hits"] = [v for v in videos if v.get("_is_hit")]
        acc["_chart"] = chart_points(videos, generated_at)

        if acc.get("channel_published_at"):
            opened = _parse_ts(acc["channel_published_at"])
            acc["_channel_age_days"] = (generated_at - opened).days
        else:
            acc["_channel_age_days"] = None

        collected_views = [(v.get("metrics") or {}).get("views") for v in videos]
        collected_views = [x for x in collected_views if isinstance(x, int)]
        acc["_avg_views"] = int(sum(collected_views) / len(collected_views)) \
            if collected_views else None

        recent_cutoff = generated_at - timedelta(days=30)
        acc["_recent_uploads"] = sum(
            1 for v in videos if _parse_ts(v["published_at"]) >= recent_cutoff)


def render_html(accounts: list[dict], queue_entries: list[dict],
                generated_at: datetime, config: dict | None = None) -> str:
    prepare(accounts, queue_entries, generated_at)

    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["num"] = _fmt_num
    env.filters["compact"] = _fmt_compact
    env.filters["date"] = _fmt_date
    env.filters["dur"] = _fmt_dur
    env.filters["pct"] = _fmt_pct
    env.filters["ratio"] = _fmt_ratio

    dash = (config or {}).get("dashboard", {})
    hot_ratio = (config or {}).get("metrics", {}).get("hot_ratio", 3.0)

    tpl = env.get_template("template.html")
    return tpl.render(
        accounts=accounts,
        title=dash.get("title", "레퍼런스 유튜브 채널 분석"),
        hot_ratio=hot_ratio,
        generated_label=generated_at.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
    )
