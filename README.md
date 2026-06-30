# English-habit coach — 대화 전사본 기반 멀티툴 AI 코치

대화 전사본(STT)을 분석해 **영어 말하기 습관을 진단**하고, 세션별 개선을 추적하고,
어휘 단어장을 만들고, 약점 맞춤 연습문제를 내주는 AI 에이전트.

에이전트 루프(Claude에게 묻기 → 요청한 툴 실행 → 결과 피드백 → 반복)에
여러 툴 + 멀티뷰 Flask 웹 UI를 붙인 형태.

## 구조

```
english-coach/
├── agent.py            에이전트 루프 + CLI (대화형 / 일회성)
├── tools.py            툴 모음 + SQLite 영속화
├── rag.py              문법 레퍼런스 RAG (chunk·embed·search)
├── docs/               문법/콩글리시 레퍼런스 코퍼스 (.md)
├── grammar_index.pkl   임베딩 인덱스 (첫 실행시 자동 생성)
├── transcripts/        샘플 STT 전사본 (Tutor / Me 대화)
├── sessions.db         지표·오류·단어·연습·저장된 분석
├── web/
│   ├── app.py          Flask 백엔드 (JSON API + SPA 서빙, 구조화 진단)
│   └── static/         index.html / style.css / app.js (멀티뷰 UI)
├── .env.example
└── requirements.txt    anthropic, python-dotenv, flask, sentence-transformers
```

## 웹 UI — 6개 뷰 (햄버거 메뉴)

- **대시보드** — 스탯 카드(세션 수·최근 필러율·TTR·단어 수) + 필러 추이 차트 + 습관 TOP + 최근 분석
- **분석하기** — 전사본 입력 → 에이전트 진단 → 구조화 카드 + 도구 호출 로그
- **진척 추이** — 지표별 세션 추세 차트 + 반복 실수 프로필
- **어휘 단어장** — 의미 묶음(theme)별 그룹, 수동 추가, 학습중↔외움 토글
- **연습** — 약점 자동추천 → 문제 생성 → 풀이 → 채점 → 점수 기록
- **분석 기록** — 저장된 분석 다시 보기

## 툴

| 툴 | 종류 | 설명 |
|---|---|---|
| `list_transcripts` / `load_transcript` | local | 파일 목록 / 한 화자 발화 미리보기 (기본 `Me`) |
| `read_dialogue` | local | 전체 대화(양쪽 화자) — 이해·응답 적절성 판단용 |
| `search_grammar_ref` | RAG | 문법 코퍼스에서 관련 규칙 검색 → 진단 근거·인용 |
| `filler_stats` | local | 필러 수 + 100단어당 비율 (um, uh, you know…) |
| `vocab_stats` | local | 어휘 다양성(TTR) + 최다 반복 내용어 |
| `pace_stats` | local | 평균 문장 길이 + 짧은 단편 수 |
| `formality_stats` | local | 캐주얼 표현 비율 → 목표 격식 조언 |
| `find_pattern` | local | 의심 습관 정규식 검색 |
| `save_session` / `get_trend` | SQLite | 고정 스키마 지표 저장(날짜당 1개) / 추세 |
| `log_errors` / `my_weaknesses` | SQLite | 분류된 오류 기록 / 반복 실수 프로필 |
| `add_vocab` / `list_vocab` / `mark_vocab` | SQLite | 단어장 (theme별 묶음, 상태 토글) |
| `create_practice` / `grade_practice` | SQLite | 약점 맞춤 드릴 생성 / 채점(점수 저장) |

문법·콩글리시 판단은 에이전트가 추론(원문 인용 + 교정 제시). 카운팅은 전부 결정적이라 재현됨.

## 문법 레퍼런스 RAG

진단할 때 문법 규칙을 LLM 기억에만 의존하지 않고, `docs/`의 레퍼런스 코퍼스에서
**검색해 근거로 인용**한다 (chunk → embed → search → cite).

- 임베딩: `sentence-transformers/all-MiniLM-L6-v2` (로컬, API 키 불필요)
- 코퍼스: 한국인 학습자 빈출 오류 6개 문서 (주어-동사 일치, 시제/현재완료, 관사,
  복수형, 콩글리시, 전치사/격식)
- 흐름: 에이전트가 오류마다 `search_grammar_ref(query)` 호출 → 규칙 chunk 검색 →
  `why` 설명의 근거로 삼고 `references`에 출처 파일 인용
- 인덱스는 첫 실행시 자동 빌드. 코퍼스를 바꾸면 `python rag.py`로 재빌드.

## 설치

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # .env에 본인 ANTHROPIC_API_KEY 입력 (절대 커밋 금지)
```

## 실행 — 웹앱 (권장)

```bash
cd web
python app.py               # http://127.0.0.1:5050
```

`COACH_DEBUG=1` 로 Flask 디버그/리로드 켜기 (기본 꺼짐).

## 실행 — CLI

```bash
python agent.py             # 대화형 ('exit' 입력시 종료)
python agent.py "Analyze session-2026-06-20.txt and list my top 3 habits."
```

## 데모 데이터

`sessions.db`에 두 샘플 세션(2026-06-20 → 2026-06-27) 포함 — 개선 스토리:
필러율 13.2 → 0.0, TTR 0.532 → 0.682, 문법 오류는 후반 세션에서 0으로 감소.
`sessions.db`를 지우면 초기화됨(첫 쓰기에서 테이블 재생성).
