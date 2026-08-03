"""채널별 수집 오케스트레이션.

채널 하나가 실패해도 나머지는 진행하고, 실패 채널은 기존 JSON 을 유지한다.
채널 목록은 노션 '⭐ 레퍼런스 유튜브 채널' DB 에서 읽는다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from src import notion as notion_props
from src.merge import merge_videos

log = logging.getLogger(__name__)

INDEX_FILE = "_index.json"


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_index(data_dir: Path) -> dict:
    """노션 page_id → 데이터 파일 handle 매핑."""
    return _read_json(data_dir / INDEX_FILE, {})


def _empty_account(channel: dict) -> dict:
    return {"brand": channel.get("name") or "", "handle": None,
            "notion_page_id": channel["page_id"], "title": channel.get("name") or "",
            "subscribers": None, "fetched_at": None, "videos": []}


def _average_views(videos: list[dict]) -> int | None:
    views = [(v.get("metrics") or {}).get("views") for v in videos]
    views = [v for v in views if isinstance(v, int) and v > 0]
    if not views:
        return None
    return int(sum(views) / len(views))


def _collect_channel(client, channel: dict, prev: dict, config: dict,
                     now: datetime) -> dict:
    cfg = config.get("collect", {})
    years = cfg.get("years", 3)
    limit = cfg.get("max_videos", 1000)
    freeze_days = cfg.get("freeze_days", 30)

    meta = client.resolve_channel_flexible(channel["address"])
    cutoff = now - timedelta(days=365 * years)

    ids = client.get_video_ids_since(meta["uploads_playlist_id"], cutoff, limit)
    fresh = client.get_videos_details(ids)

    # 쇼츠/롱폼 판별은 새 영상에 대해서만 1회 수행 (저장분은 merge 에서 유지)
    known_format = {v["video_id"]: v.get("format") for v in prev.get("videos", [])}
    for f in fresh:
        if not known_format.get(f["video_id"]):
            f["format"] = "shorts" if client.is_short(f["video_id"], f["duration"]) else "long"

    videos = merge_videos(prev.get("videos", []), fresh, now,
                          freeze_days=freeze_days, limit=limit)
    return {
        "brand": channel.get("name") or meta["title"],
        "handle": meta["handle"] or meta["channel_id"],
        "notion_page_id": channel["page_id"],
        "channel_id": meta["channel_id"],
        "title": meta["title"],
        "url": meta["url"],
        "channel_published_at": meta.get("published_at"),
        "subscribers": meta.get("subscribers"),
        "video_count": meta.get("video_count"),
        "total_views": meta.get("total_views"),
        "fetched_at": now.isoformat(),
        "videos": videos,
        "_meta": meta,
    }


def collect_all(client, notion_client, config: dict, data_dir: Path,
                now: datetime) -> list[dict]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    index = _load_index(data_dir)

    channel_db = config["notion"]["channel_database_id"]
    channels = notion_client.monitored_channels(channel_db)
    log.info("모니터링 채널 %d개", len(channels))

    results: list[dict] = []
    for channel in channels:
        page_id = channel["page_id"]
        handle = index.get(page_id)
        prev = _read_json(data_dir / f"{handle}.json", None) if handle else None
        prev = prev or _empty_account(channel)

        if not channel.get("address"):
            log.warning("채널 주소가 비어 있음 — 건너뜀 (%s)", channel.get("name"))
            results.append(prev)
            continue

        try:
            result = _collect_channel(client, channel, prev, config, now)
        except Exception as exc:  # noqa: BLE001 — 한 채널 실패가 전체를 막지 않는다
            log.exception("%s 수집 실패 — 이전 데이터 유지", channel.get("address"))
            _safe_notion_update(notion_client, page_id,
                                notion_props.channel_failure_payload(
                                    str(exc), now.date().isoformat()))
            results.append(prev)
            continue

        meta = result.pop("_meta")
        index[page_id] = result["handle"]
        _write_json(data_dir / f"{result['handle']}.json", result)

        _safe_notion_update(notion_client, page_id, notion_props.channel_update_payload(
            meta, _average_views(result["videos"]), now.date().isoformat(),
            current_name=channel.get("name", "")))

        results.append(result)

    _write_json(data_dir / INDEX_FILE, index)
    return results


def _safe_notion_update(notion_client, page_id: str, props: dict) -> None:
    try:
        notion_client.update_page(page_id, props)
    except Exception:  # noqa: BLE001 — 노션 실패가 대시보드를 막지 않는다
        log.exception("노션 채널 행 갱신 실패: %s", page_id)
