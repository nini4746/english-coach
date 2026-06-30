# 기능 추가 계획

---

## 1. 어휘 단어장 — Free Dictionary API 연동

### 목표
단어를 단어장에 추가할 때 [Free Dictionary API](https://dictionaryapi.dev)를 자동 호출해
사전 정보를 함께 저장하고, 단어장 카드에 노출한다.

### API 정보
- **엔드포인트**: `GET https://api.dictionaryapi.dev/api/v2/entries/en/{word}`
- **비용**: 무료, API 키 불필요

### 트리거
단어 추가 시 자동 호출 (`POST /api/vocab` 처리 시점)

### 저장할 데이터
| 항목 | 내용 |
|---|---|
| 사전적 정의 | 품사 + 영어 정의 (첫 번째 의미) |
| 예문 | 정의에 딸린 예문 (있는 경우) |
| 유의어 | synonyms 목록 |
| 반의어 | antonyms 목록 |

### 캐싱
- API 호출 결과를 DB에 저장 (같은 단어 재추가 시 재호출 없음)
- 저장 위치: `vocab` 테이블에 `dict_json` 컬럼 추가, 또는 별도 `vocab_dict` 테이블

### 표시 위치
- 단어장 카드에 접이식(accordion) 영역으로 사전 정보 표시
- 정의 없음 / API 실패 시 조용히 무시 (단어 추가 자체는 항상 성공)

### 변경 파일
- `tools.py` — `add_vocab()` 함수에서 API 호출 + 저장
- `web/app.py` — 필요 시 `/api/vocab` 라우트 보완
- `web/static/app.js` — 단어장 카드 렌더링에 사전 정보 영역 추가
- `web/static/style.css` — 카드 accordion 스타일

---

## 2. 자체 녹음 모듈 (STT 연동)

> **상태: 아이디어 단계 — 구현 보류**

### 목표
앱 안에서 직접 마이크 녹음 후 텍스트로 전사해 분석 화면에 자동 입력.

### 기술 스택 (검토 중)
- **녹음**: 브라우저 `MediaRecorder API` (마이크 권한 요청)
- **전사(STT)**: 로컬 Whisper (`faster-whisper`) — 무료, API 키 불필요
- **서버**: 녹음 파일을 Flask 서버로 전송 → Whisper 처리 → 텍스트 반환

### 미결 사항
- 녹음 형태: 혼자 말하기(독백) vs 튜터와 대화(양방향)
- 전사 결과 처리: 분석 화면 입력창 자동 삽입 vs 별도 녹음 전용 탭
- Whisper 모델 크기 선택 (tiny / base / small — 속도 vs 정확도)

---

## 3. UI 개선 — 분석하기 탭 메트릭 카드 축소

### 문제
분석하기 탭의 코치 진단 패널 상단에 필러/TTR/평균 문장 길이/분석 단어 수 카드 4개가 너무 많은 수직 공간을 차지해 리포트까지 스크롤해야 하는 UX 문제.

### 개선 방향
- `#metrics` 카드를 작은 인라인 칩 형태의 한 줄로 압축
- 큰 카드 스타일은 대시보드(`#dashStats`) / 기록(`#histMetrics`)에만 유지
- `#metrics`에만 별도 CSS 오버라이드 적용 (기존 `.metrics` 스타일 영향 없음)

### 변경 파일
- `web/static/style.css` — `#metrics` 전용 compact 스타일 추가

---

## 4. 어휘 단어장 — 간격 반복 복습 (SRS)

### 목표
Anki 방식의 간격 반복(Spaced Repetition System)으로 "오늘 복습할 단어" 큐를 만들어
기존 어휘 테스트 기능과 연결한다.

### 핵심 로직
- 테스트 결과(통과/실패)에 따라 다음 복습일 계산
  - 통과 → 복습 간격 2배 증가 (1일 → 2일 → 4일 → 8일 …)
  - 실패 → 간격 리셋, 다음 날 재복습
- 매일 앱 접속 시 "오늘 복습할 단어 N개" 배지 표시

### DB 변경
`vocab` 테이블에 컬럼 추가:
| 컬럼 | 타입 | 설명 |
|---|---|---|
| `next_review` | DATE | 다음 복습 예정일 |
| `interval_days` | INTEGER | 현재 복습 간격 (일) |
| `ease` | REAL | 난이도 계수 (기본 2.5) |

### UI 변경
- 어휘 단어장 탭 상단에 **"오늘 복습 (N)"** 버튼 추가
- 클릭 시 오늘 복습 대상 단어만 모아서 테스트 진행
- 대시보드에 오늘 복습할 단어 수 카드 추가

### 변경 파일
- `tools.py` — `mark_vocab()` 수정, SRS 스케줄 계산 로직 추가
- `web/app.py` — `/api/vocab/review/today` 엔드포인트 추가
- `web/static/app.js` — 복습 큐 UI 및 흐름 추가
- `web/static/style.css` — 복습 배지 스타일

---

<!-- 이후 기능은 여기에 추가 -->
