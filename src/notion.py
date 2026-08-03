"""노션 API 클라이언트.

- ⭐ 레퍼런스 유튜브 채널 DB: 모니터링 체크된 채널을 읽고, 빈칸을 자동으로 채운다
- 🎯 성과 좋은 영상 분석 DB: 신규 히트 영상을 '대기' 상태 행으로 만든다
  (본문 리포트는 Layer 2 의 Claude Code 스킬이 MCP 로 채운다)

페이로드 생성 함수는 순수 함수라 API 없이 테스트할 수 있다.
"""

from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
RATE_LIMIT_SLEEP = 0.34  # 노션 권장 한도는 초당 3회

# ⭐ 레퍼런스 유튜브 채널
P_NAME = "채널명"
P_ADDRESS = "채널 주소"
P_MONITOR = "모니터링"
P_SUBSCRIBERS = "구독자수"
P_VIDEO_COUNT = "총 영상수"
P_AVG_VIEWS = "평균 조회수"
P_FETCHED_AT = "마지막 수집일"
P_RESOLVE_STATUS = "해석 상태"
P_MEMO = "메모"

# 🎯 성과 좋은 영상 분석
A_TITLE = "제목"
A_URL = "영상 URL"
A_CHANNEL = "채널"
A_FORMAT = "포맷"
A_PUBLISHED = "게시일"
A_DURATION = "영상 길이(초)"
A_VIEWS = "조회수"
A_RATIO = "성과 배수"
A_PERFORMANCE = "성과도"
A_CONTRIBUTION = "기여도"
A_ENGAGEMENT = "참여율"
A_STATUS = "분석 상태"

STATUS_PENDING = "대기"
FORMAT_LABEL = {"shorts": "쇼츠", "long": "롱폼"}


class NotionError(RuntimeError):
    pass


# ---------- 순수 함수: 값 읽기 ----------

def plain_text(prop: dict | None) -> str:
    """title / rich_text 속성에서 순수 텍스트를 뽑는다."""
    if not prop:
        return ""
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(item.get("plain_text", "") for item in items).strip()


def checkbox(prop: dict | None) -> bool:
    return bool((prop or {}).get("checkbox"))


def parse_channel_row(page: dict) -> dict:
    """노션 페이지 → 채널 정보 dict."""
    props = page.get("properties", {})
    return {
        "page_id": page["id"],
        "name": plain_text(props.get(P_NAME)),
        "address": plain_text(props.get(P_ADDRESS)),
        "monitoring": checkbox(props.get(P_MONITOR)),
    }


# ---------- 순수 함수: 페이로드 만들기 ----------

def _text(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}


def _title(value: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}


def channel_update_payload(meta: dict, avg_views: int | None, fetched_at: str,
                           current_name: str = "") -> dict:
    """채널 DB 행의 빈칸을 채우는 properties 페이로드.

    채널명은 사용자가 직접 적었으면 존중하고, 비어 있을 때만 채운다.
    채널 주소는 항상 정규 URL 로 덮어써서 다음 실행부터 검색을 생략한다.
    """
    props: dict = {
        P_ADDRESS: _text(meta["url"]),
        P_FETCHED_AT: {"date": {"start": fetched_at}},
        P_RESOLVE_STATUS: {"select": {"name": "정상"}},
    }
    if not current_name:
        props[P_NAME] = _title(meta.get("title") or meta["url"])
    if meta.get("subscribers") is not None:
        props[P_SUBSCRIBERS] = {"number": meta["subscribers"]}
    if meta.get("video_count") is not None:
        props[P_VIDEO_COUNT] = {"number": meta["video_count"]}
    if avg_views is not None:
        props[P_AVG_VIEWS] = {"number": int(avg_views)}
    return props


def channel_failure_payload(error: str, fetched_at: str) -> dict:
    return {
        P_RESOLVE_STATUS: {"select": {"name": "해석 실패"}},
        P_FETCHED_AT: {"date": {"start": fetched_at}},
        P_MEMO: _text(f"채널을 찾지 못했습니다: {error}"),
    }


def analysis_row_payload(video: dict, channel_page_id: str | None = None) -> dict:
    """히트 영상 → '성과 좋은 영상 분석' DB 의 대기 행 properties."""
    props: dict = {
        A_TITLE: _title(video.get("title") or video["video_id"]),
        A_URL: {"url": video.get("url")},
        A_STATUS: {"select": {"name": STATUS_PENDING}},
    }
    fmt = FORMAT_LABEL.get(video.get("format"))
    if fmt:
        props[A_FORMAT] = {"select": {"name": fmt}}
    if video.get("published_at"):
        props[A_PUBLISHED] = {"date": {"start": video["published_at"][:10]}}
    if video.get("duration"):
        props[A_DURATION] = {"number": int(video["duration"])}

    views = (video.get("metrics") or {}).get("views")
    if isinstance(views, int):
        props[A_VIEWS] = {"number": views}
    if video.get("_perf_ratio") is not None:
        props[A_RATIO] = {"number": round(video["_perf_ratio"], 2)}
    if video.get("_perf_grade"):
        props[A_PERFORMANCE] = {"select": {"name": video["_perf_grade"]}}
    if video.get("_contribution_grade"):
        props[A_CONTRIBUTION] = {"select": {"name": video["_contribution_grade"]}}
    if video.get("_engagement") is not None:
        props[A_ENGAGEMENT] = {"number": round(video["_engagement"], 4)}
    if channel_page_id:
        props[A_CHANNEL] = {"relation": [{"id": channel_page_id}]}
    return props


# ---------- API 클라이언트 ----------

class NotionClient:
    def __init__(self, token: str | None = None):
        token = token or os.environ.get("NOTION_TOKEN")
        if not token:
            raise NotionError("NOTION_TOKEN 환경변수가 없습니다")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{API_BASE}/{path}"
        for attempt in range(4):
            r = self.session.request(method, url, json=payload, timeout=30)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 1)) + attempt
                log.warning("노션 rate limit — %.1f초 대기", wait)
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise NotionError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
            time.sleep(RATE_LIMIT_SLEEP)
            return r.json()
        raise NotionError(f"{method} {path} — rate limit 재시도 초과")

    def query_database(self, database_id: str, payload: dict | None = None) -> list[dict]:
        results: list[dict] = []
        body = dict(payload or {})
        while True:
            resp = self._request("POST", f"databases/{database_id}/query", body)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            body["start_cursor"] = resp["next_cursor"]
        return results

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._request("PATCH", f"pages/{page_id}", {"properties": properties})

    def create_page(self, database_id: str, properties: dict) -> dict:
        return self._request("POST", "pages", {
            "parent": {"database_id": database_id},
            "properties": properties,
        })

    def archive_page(self, page_id: str) -> dict:
        """페이지를 휴지통으로 보낸다 (기준에서 빠진 '대기' 행 정리용)."""
        return self._request("PATCH", f"pages/{page_id}", {"in_trash": True})

    # ---------- 상위 동작 ----------

    def monitored_channels(self, database_id: str) -> list[dict]:
        """모니터링이 체크된 채널 행만 가져온다."""
        payload = {"filter": {"property": P_MONITOR, "checkbox": {"equals": True}}}
        pages = self.query_database(database_id, payload)
        return [parse_channel_row(p) for p in pages]

    def existing_analysis_urls(self, database_id: str) -> set[str]:
        """이미 DB에 있는 영상 URL — 중복 생성을 막는다."""
        urls = set()
        for page in self.query_database(database_id):
            url = (page.get("properties", {}).get(A_URL) or {}).get("url")
            if url:
                urls.add(url)
        return urls
