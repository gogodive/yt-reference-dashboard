# 레퍼런스 유튜브 분석

내 채널에 뭘 올릴지 정할 때 참고할 **레퍼런스 채널 분석 시스템**.

노션에 채널 주소를 적고 모니터링만 체크하면, 매일 아침 자동으로 수집해서
성과 지표로 줄 세우고, **크게 터진 영상은 Claude가 처음부터 끝까지 직접 보고**
구조·후킹·컷 구성을 분해해서 노션에 정리한다.

---

## 매일 내가 할 일

없다. 자동으로 돈다.

**새 레퍼런스 채널을 추가하고 싶을 때만** 노션 [⭐ 레퍼런스 유튜브 채널](https://app.notion.com/p/3b139eba97ed8000bcfcf1ff844365c3)에서
새 행을 만들고 → `채널 주소`에 유튜브 주소를 붙여넣고 → `모니터링`을 체크한다.
채널명·구독자수 등 나머지는 다음 날 아침에 자동으로 채워진다.

> 채널 주소는 `https://www.youtube.com/@핸들` 형태가 가장 정확하지만,
> `(20) 워터양 Wateryang - YouTube` 처럼 브라우저에서 복사한 제목이나 채널 이름만 적어도 알아서 찾는다.
> 못 찾으면 `해석 상태`가 **해석 실패**로 표시되니 그때 주소를 고쳐 주면 된다.

---

## 두 개의 층

| | Layer 1 — 지표 수집 | Layer 2 — 영상 심층 분석 |
|---|---|---|
| 언제 | 매일 07:10 KST 자동 | 내가 Claude Code에서 실행할 때 |
| 어디서 | GitHub Actions (클라우드) | 이 맥 |
| 하는 일 | 수집 · 지표 계산 · 대시보드 배포 · 노션 '분석 대기' 행 생성 | 영상 다운로드 · 시청 · 분석 · 노션 본문 작성 |
| 비용 | 무료 | 추가 요금 없음 (Claude 구독 사용량) |

**왜 나눴나** — 유튜브는 GitHub 서버 IP에서의 영상 다운로드를 거의 항상 차단한다.
지표 수집은 API만 쓰므로 클라우드에서 무인으로 돌지만, 영상을 실제로 받아 보는 일은 맥에서 해야 한다.

---

## 지표 읽는 법

| 지표 | 뜻 | 계산 |
|---|---|---|
| **성과도** | 이 채널 평소 수준을 얼마나 넘어섰나 | 조회수 ÷ 같은 채널·같은 포맷(롱폼/쇼츠) 조회수 중앙값 |
| **기여도** | 채널 밖으로 얼마나 퍼졌나 (성장 잠재력) | 조회수 ÷ 구독자 수 → 전체 채널 통합 순위로 등급화 |
| **참여율** | 좋아요·댓글이 얼마나 붙었나 | (좋아요 + 댓글) ÷ 조회수 |

등급은 **Best / Good / Normal / Worst** 4단계.
**성과도가 Best(중앙값 3배 이상)면 🔥 히트**로 판정되어 심층 분석 대상이 된다.

포맷별 중앙값을 따로 쓰기 때문에 조회수 절대값이 큰 쇼츠와 롱폼이 공평하게 판정된다.

---

## 영상 분석 돌리기

Claude Code에서:

```
/analyze-reference-video
```

대기 중인 히트 영상을 성과 배수 높은 순으로 5편씩 분석한다.
특정 영상만 보고 싶으면:

```
/analyze-reference-video https://www.youtube.com/watch?v=XXXXXXXXXXX
```

결과는 노션 [🎯 성과 좋은 영상 분석](https://app.notion.com/p/e30243b071c74022931a49e4c9d6b4df)에 쌓인다.
영상 만들 때 **포맷 · 후킹 유형 · 콘텐츠 유형**으로 필터링해서 꺼내 쓰면 된다.

> 처음 3년치 백필은 편수가 많다. 한 번에 다 못 돌려도 괜찮다 —
> 큐에 진행 상태가 저장되므로 여러 번 나눠 실행하면 이어서 진행된다.

---

## 일회성 셋업

### 1. YouTube Data API 키
5-1 자사 대시보드에서 쓰는 키를 그대로 써도 된다.
(하루 무료 할당량 10,000유닛 — 채널 5개 일일 수집은 수백 유닛 수준)

### 2. 노션 통합 토큰 (5분)
1. https://www.notion.so/my-integrations → **새 API 통합** → 이름 아무거나 → 생성
2. **내부 통합 시크릿**을 복사 (`ntn_` 로 시작)
3. 노션 [레퍼런스 유튜브 채널 분석](https://app.notion.com/p/3b139eba97ed8091ab92c95318343eed) 페이지 → 우측 상단 `⋯` → **연결** → 방금 만든 통합 추가

### 3. GitHub
1. `yt-reference-dashboard` 라는 이름으로 **public** 저장소를 만들고 이 폴더를 push
2. Settings → Secrets and variables → Actions → 두 개 등록
   - `YOUTUBE_API_KEY`
   - `NOTION_TOKEN`
3. Settings → Pages → Source: **GitHub Actions**
4. Actions 탭 → daily-feed → **Run workflow** 로 첫 실행
5. 배포된 주소를 노션 허브 페이지 맨 위에 링크로 걸어 둔다

### 4. 맥 (영상 분석용)
```bash
brew install yt-dlp ffmpeg
```

---

## 로컬에서 직접 돌려보기

```bash
cd "yt-reference-dashboard"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export YOUTUBE_API_KEY="..."
export NOTION_TOKEN="ntn_..."
python -m src.main

open site/index.html
```

테스트:
```bash
pytest -v
```

---

## 폴더 구조

```
yt-reference-dashboard/
├── config.yaml          # 히트 기준(3배), 수집 범위(3년), 노션 DB ID
├── src/
│   ├── main.py          # Layer 1 엔트리
│   ├── notion.py        # 노션 채널 읽기 / 빈칸 채움 / 분석 대기 행 생성
│   ├── youtube.py       # 수집 + 채널 주소 해석(URL·붙여넣기 제목·이름)
│   ├── collect.py       # 채널별 수집 오케스트레이션
│   ├── merge.py         # 30일 동결 규칙
│   ├── metrics.py       # 조회수 / 기여도 / 성과도 / 히트 판정
│   ├── hitqueue.py      # 분석 큐 (중단·재개 안전)
│   ├── render.py        # 대시보드 렌더
│   └── template.html
├── data/                # 채널별 수집 결과 + hit_queue.json (git에 커밋됨)
└── tests/
```

영상 분석 스킬은 상위 폴더의 `.claude/skills/analyze-reference-video/` 에 있다
(Claude Code가 인식하려면 프로젝트 최상단에 있어야 한다).

---

## 문제가 생기면

| 증상 | 확인할 것 |
|---|---|
| 채널이 `해석 실패`로 표시됨 | 노션의 `채널 주소`를 `https://www.youtube.com/@핸들` 형태로 고친다 |
| 대시보드가 어제 데이터 | 해당 채널 카드에 노란 경고가 뜬다. Actions 탭에서 실패 로그 확인 |
| 히트가 하나도 안 잡힘 | 포맷별 영상이 5편 미만이면 판정하지 않는다. 수집 범위(3년)를 늘리거나 `config.yaml` 의 `hot_ratio` 를 낮춘다 |
| 히트가 너무 많음 | `config.yaml` 의 `metrics.hot_ratio` 를 4~5로 올린다 |
| 영상 다운로드 실패 | 연령제한·지역제한·비공개 영상일 수 있다. 큐에서 `failed` 로 표시되고 넘어간다 |
| `work/` 폴더가 커짐 | 분석이 끝난 영상 폴더는 지워도 된다. `rm -rf work/*` |
