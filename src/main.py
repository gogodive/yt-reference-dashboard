"""Layer 1 엔트리포인트.

노션에서 채널 목록 읽기 → 수집 → 지표 계산 → 히트 큐 갱신
→ 노션에 분석 대기 행 생성 → HTML 대시보드 생성.

영상을 실제로 보는 심층 분석은 Layer 2(맥의 Claude Code 스킬)가 담당한다.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import hitqueue, metrics
from src.collect import collect_all, load_config
from src.notion import NotionClient, analysis_row_payload
from src.render import render_html
from src.youtube import YouTubeClient

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent

log = logging.getLogger(__name__)


def sync_notion_rows(notion_client, analysis_db: str, added: list[dict],
                     entries: list[dict], accounts: list[dict]) -> int:
    """새로 큐에 들어온 히트를 노션에 '대기' 행으로 만든다."""
    if not added:
        return 0
    try:
        existing = notion_client.existing_analysis_urls(analysis_db)
    except Exception:  # noqa: BLE001
        log.exception("노션 분석 DB 조회 실패 — 행 생성 건너뜀")
        return 0

    page_by_handle = {a["handle"]: a.get("notion_page_id") for a in accounts if a.get("handle")}
    videos_by_id = {v["video_id"]: v for a in accounts for v in a.get("videos", [])}

    created = 0
    for entry in added:
        if entry.get("url") in existing:
            hitqueue.mark(entries, entry["video_id"], hitqueue.PENDING)
            continue
        video = videos_by_id.get(entry["video_id"])
        if not video:
            continue
        props = analysis_row_payload(video, page_by_handle.get(entry.get("handle")))
        try:
            page = notion_client.create_page(analysis_db, props)
        except Exception:  # noqa: BLE001
            log.exception("노션 분석 행 생성 실패: %s", entry.get("title"))
            continue
        hitqueue.mark(entries, entry["video_id"], hitqueue.PENDING,
                      notion_page_id=page["id"])
        created += 1
    return created


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY 환경변수가 없습니다", file=sys.stderr)
        return 1
    if not os.environ.get("NOTION_TOKEN"):
        print("NOTION_TOKEN 환경변수가 없습니다", file=sys.stderr)
        return 1

    config = load_config(ROOT / "config.yaml")
    data_dir = ROOT / "data"
    now = datetime.now(KST)

    client = YouTubeClient(api_key)
    notion_client = NotionClient()

    accounts = collect_all(client, notion_client, config, data_dir, now)
    if not accounts:
        print("모니터링 체크된 채널이 없습니다", file=sys.stderr)
        return 1

    metrics.annotate_all(accounts, config)
    hits = metrics.collect_hits(accounts)

    queue_path = data_dir / "hit_queue.json"
    entries = hitqueue.load(queue_path)
    entries, added = hitqueue.sync(entries, hits, now.isoformat())
    created = sync_notion_rows(notion_client, config["notion"]["analysis_database_id"],
                               added, entries, accounts)
    hitqueue.save(queue_path, entries)

    site = ROOT / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(render_html(accounts, entries, now, config),
                                     encoding="utf-8")

    stats = hitqueue.counts(entries)
    print(f"완료: 채널 {len(accounts)}개 · 히트 {len(hits)}편 "
          f"(신규 {len(added)}, 노션 행 생성 {created}) · "
          f"분석 대기 {stats['pending']} / 완료 {stats['done']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
