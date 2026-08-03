"""YouTube Data API v3 클라이언트 + 유연한 채널 해석 + 쇼츠 판별.

5-1 자사 대시보드의 youtube.py 를 기반으로, 노션에 손으로 적어 넣은
제각각인 '채널 주소' 값을 해석하는 기능과 3년 범위 수집을 추가했다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests

log = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
SHORTS_MAX_SECONDS = 183  # 이 길이를 넘으면 쇼츠일 수 없음 (URL 확인 생략)

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)

# "(20) 워터양 Wateryang - YouTube" 처럼 브라우저에서 복사한 링크 제목
_COUNT_PREFIX_RE = re.compile(r"^\(\d+\)\s*")
_YOUTUBE_SUFFIX_RE = re.compile(r"\s*[-–—]\s*YouTube\s*$", re.IGNORECASE)

_HANDLE_URL_RE = re.compile(r"youtube\.com/@([\w.\-가-힣]+)", re.IGNORECASE)
_CHANNEL_URL_RE = re.compile(r"youtube\.com/channel/(UC[\w\-]+)", re.IGNORECASE)
_LEGACY_URL_RE = re.compile(r"youtube\.com/(?:c|user)/([\w.\-]+)", re.IGNORECASE)
_BARE_HANDLE_RE = re.compile(r"^@([\w.\-가-힣]+)$")


def parse_duration(iso: str) -> int:
    """ISO 8601 길이 문자열(PT1M30S 등) → 초. 파싱 실패 시 0."""
    m = _DURATION_RE.match(iso or "")
    if not m:
        return 0
    parts = {k: int(v) for k, v in m.groupdict().items() if v}
    return (parts.get("days", 0) * 86400 + parts.get("hours", 0) * 3600
            + parts.get("minutes", 0) * 60 + parts.get("seconds", 0))


def clean_channel_text(raw: str) -> str:
    """브라우저에서 복사한 링크 제목의 군더더기를 제거한다.

    "(20) 워터양 Wateryang - YouTube" → "워터양 Wateryang"
    """
    text = (raw or "").strip()
    text = _COUNT_PREFIX_RE.sub("", text)
    text = _YOUTUBE_SUFFIX_RE.sub("", text)
    return text.strip()


def parse_channel_ref(raw: str) -> tuple[str, str]:
    """노션의 '채널 주소' 값 → (종류, 값).

    종류는 "handle" | "id" | "query" 중 하나다.
    handle/id 는 API 로 바로 조회할 수 있고, query 는 채널 검색이 필요하다.

    >>> parse_channel_ref("https://www.youtube.com/@mulchingirl")
    ('handle', 'mulchingirl')
    >>> parse_channel_ref("(20) 워터양 Wateryang - YouTube")
    ('query', '워터양 Wateryang')
    """
    text = clean_channel_text(raw)
    if not text:
        raise ValueError("채널 주소가 비어 있습니다")

    m = _HANDLE_URL_RE.search(text)
    if m:
        return "handle", m.group(1)
    m = _CHANNEL_URL_RE.search(text)
    if m:
        return "id", m.group(1)
    m = _LEGACY_URL_RE.search(text)
    if m:
        return "query", m.group(1)
    m = _BARE_HANDLE_RE.match(text)
    if m:
        return "handle", m.group(1)
    return "query", text


def parse_video_item(item: dict) -> dict:
    """videos.list 응답 아이템 → 표준 형태."""
    sn = item["snippet"]
    st = item.get("statistics", {})
    cd = item.get("contentDetails", {})
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    return {
        "video_id": item["id"],
        "title": sn.get("title", ""),
        "published_at": sn.get("publishedAt"),
        "duration": parse_duration(cd.get("duration", "")),
        "thumbnail": thumb,
        "views": int(st["viewCount"]) if "viewCount" in st else None,
        "likes": int(st["likeCount"]) if "likeCount" in st else None,
        "comments": int(st["commentCount"]) if "commentCount" in st else None,
    }


class ChannelNotFound(LookupError):
    """채널을 어떤 방법으로도 찾지 못했을 때."""


class YouTubeClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, path: str, **params) -> dict:
        params["key"] = self.api_key
        r = self.session.get(f"{API_BASE}/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ---------- 채널 해석 ----------

    def _channel_meta(self, **lookup) -> dict | None:
        resp = self._get("channels", part="snippet,statistics,contentDetails", **lookup)
        items = resp.get("items", [])
        if not items:
            return None
        it = items[0]
        stats = it.get("statistics", {})
        sn = it["snippet"]
        handle = (sn.get("customUrl") or "").lstrip("@")
        return {
            "channel_id": it["id"],
            "title": sn.get("title", ""),
            "handle": handle,
            "url": f"https://www.youtube.com/@{handle}" if handle
                   else f"https://www.youtube.com/channel/{it['id']}",
            "published_at": sn.get("publishedAt"),
            "subscribers": None if stats.get("hiddenSubscriberCount")
            else int(stats.get("subscriberCount", 0)),
            "video_count": int(stats.get("videoCount", 0)) if "videoCount" in stats else None,
            "total_views": int(stats.get("viewCount", 0)) if "viewCount" in stats else None,
            "uploads_playlist_id": it["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def search_channel_id(self, query: str) -> str | None:
        """채널명으로 검색한다 (search.list — 호출당 100유닛)."""
        resp = self._get("search", part="snippet", type="channel", q=query, maxResults=1)
        items = resp.get("items", [])
        if not items:
            return None
        return items[0]["snippet"]["channelId"]

    def resolve_channel_flexible(self, raw: str) -> dict:
        """노션에 적힌 값이 URL이든 붙여넣기 제목이든 채널명이든 해석한다.

        search.list 는 비싸므로(100유닛) 호출 결과의 정규 URL을 노션에 되써서
        다음 실행부터는 handle 조회(1유닛)로 처리되게 한다.
        """
        kind, value = parse_channel_ref(raw)

        if kind == "handle":
            meta = self._channel_meta(forHandle=value)
            if meta:
                return meta
            log.warning("핸들 조회 실패, 이름으로 검색합니다: %s", value)
            kind, value = "query", value

        if kind == "id":
            meta = self._channel_meta(id=value)
            if meta:
                return meta
            raise ChannelNotFound(f"채널 ID를 찾을 수 없음: {value}")

        channel_id = self.search_channel_id(value)
        if not channel_id:
            raise ChannelNotFound(f"채널을 찾을 수 없음: {value!r}")
        meta = self._channel_meta(id=channel_id)
        if not meta:
            raise ChannelNotFound(f"검색된 채널의 정보를 가져오지 못함: {value!r}")
        return meta

    # ---------- 영상 수집 ----------

    def get_video_ids_since(self, uploads_playlist_id: str, cutoff: datetime,
                            limit: int = 1000) -> list[str]:
        """업로드 재생목록을 최신순으로 훑어 cutoff 이후 영상 ID를 모은다.

        재생목록은 최신순이므로 cutoff 보다 오래된 영상을 만나면 멈춘다.
        """
        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": uploads_playlist_id,
                      "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("playlistItems", **params)
            items = resp.get("items", [])
            if not items:
                break
            reached_cutoff = False
            for it in items:
                cd = it["contentDetails"]
                published = cd.get("videoPublishedAt")
                if published:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if ts < cutoff:
                        reached_cutoff = True
                        continue
                ids.append(cd["videoId"])
                if len(ids) >= limit:
                    break
            if reached_cutoff:
                break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids[:limit]

    def get_videos_details(self, video_ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            resp = self._get("videos", part="snippet,statistics,contentDetails",
                             id=",".join(batch))
            out.extend(parse_video_item(it) for it in resp.get("items", []))
        return out

    def get_shorts_video_ids(self, channel_id: str, limit: int = 2000) -> set[str] | None:
        """채널의 쇼츠 전용 재생목록(UUSH…)에 담긴 영상 ID 집합.

        업로드 재생목록 UU… 와 짝을 이루는 숨은 재생목록이다.
        영상마다 youtube.com 에 HTTP 요청을 보내는 방식은 편수가 많아지면
        느려지고 차단당하기 쉬워서, 채널당 재생목록 한 번 훑기로 대체했다.

        재생목록이 없는 채널(쇼츠를 한 번도 올리지 않은 경우 등)은 None 을 돌려주고,
        호출부가 길이 휴리스틱으로 폴백한다.
        """
        if not channel_id.startswith("UC"):
            return None
        playlist_id = f"UUSH{channel_id[2:]}"
        ids: set[str] = set()
        page_token = None
        try:
            while len(ids) < limit:
                params = {"part": "contentDetails", "playlistId": playlist_id,
                          "maxResults": 50}
                if page_token:
                    params["pageToken"] = page_token
                resp = self._get("playlistItems", **params)
                items = resp.get("items", [])
                if not items:
                    break
                ids.update(it["contentDetails"]["videoId"] for it in items)
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                log.info("%s: 쇼츠 재생목록 없음 — 길이로 판별", channel_id)
            else:
                log.warning("%s: 쇼츠 재생목록 조회 실패(%s) — 길이로 판별",
                            channel_id, status)
            return None
        return ids


def guess_format(duration: int, shorts_ids: set[str] | None, video_id: str) -> str:
    """쇼츠/롱폼 판별. 재생목록 정보가 있으면 그걸 믿고, 없으면 길이로 추정한다."""
    if duration > SHORTS_MAX_SECONDS:
        return "long"          # 3분 초과는 쇼츠일 수 없다
    if shorts_ids is not None:
        return "shorts" if video_id in shorts_ids else "long"
    return "shorts" if duration <= 60 else "long"
