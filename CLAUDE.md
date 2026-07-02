# 두호링고 (Duholingo)

42 경산 카뎃 대상 영어 학습 코치. 음성 녹음 → STT → 진단·예문 훈련·코알리숑 랭킹.
클라이언트는 **PWA 방식**으로 배포 (네이티브 앱은 실측 병목 발생 시에만 이전).

## 실행 커맨드

```bash
# 웹 서버 (개발)
cd web && python app.py                 # http://127.0.0.1:5050
COACH_DEBUG=1 python app.py             # Flask 디버그·리로드 on

# CLI 에이전트
python agent.py                         # 대화형
python agent.py "질문 한 방"

# 문법 RAG 인덱스 재빌드 (docs/ 변경 시)
python rag.py

# 예문 파이프라인 임베딩 빌드 (예정)
python scripts/build_embeddings.py
```

## 아키텍처 한 눈에

**에이전트 루프** — `agent.py`
- Claude에게 요청 → 툴 호출 → 결과 피드백 → 반복 (max 12 step)
- Anthropic ephemeral 프롬프트 캐싱 적용: `_cached_system`, `_cached_tools`, `_cache_messages_tail`
- 새 LLM 콜 추가 시 이 유틸을 재사용해 5분 TTL 캐시 히트 유지

**툴 + SQLite** — `tools.py`
- 진단·랭킹·연습에 필요한 모든 툴을 `TOOLS` 리스트에 등록
- SQLite 마이그레이션은 `_db()` 안에서 `if COL not in cols: ALTER TABLE` 패턴

**벡터 스토어 두 개 (병존)**
- `rag.py` — 문법 레퍼런스 (`docs/`, `all-MiniLM-L6-v2` 384-dim, pickle 인덱스)
- `vector_store.py` (예정) — 단어·상황 (`multilingual-e5-small` 384-dim, SQLite BLOB)
  - 한국어 상황 큐레이션 지원 위해 multilingual 모델 사용

**웹/PWA** — `web/`
- `app.py`: Flask JSON API + 정적 SPA 서빙
- `static/`: HTML/CSS/JS SPA (햄버거 6뷰)
- PWA 파일 (예정): `manifest.json`, `sw.js`, 호두 아이콘 세트

## PWA 방식 클라이언트 (핵심)

지금은 일반 웹앱. MVP 목표는 이걸 PWA로 만들어서 42 경산 카뎃에게 링크로 배포.

**필수 요소**:
- `web/static/manifest.json` — 앱 이름·아이콘·시작 URL·standalone display
- `web/static/sw.js` — service worker (오프라인 캐싱, 최소만)
- `index.html`에 manifest 링크 + service worker 등록
- 호두 아이콘 세트 (192px, 512px, maskable 별도 권장)

**녹음 + STT**:
- 녹음: `navigator.mediaDevices.getUserMedia` + `MediaRecorder`
- 온디바이스 STT: `window.SpeechRecognition` (Web Speech API)
- iOS Safari 정확도 편차는 감수 (실측 병목 되면 네이티브 이전 검토)

**네이티브 앱은 아직 안 만듦**. Phase 5의 조건부 옵션.

## 도메인 어휘

- **두호링고**: 프로젝트명. 호두(walnut) 뒤집기 + `-lingo`. 앱 아이콘 = 호두
- **42 경산 / 카뎃**: 타겟 유저. 42 Network 경산 캠퍼스 학생
- **코알리숑 (coalition)**: 캠퍼스 내 파벌. 랭킹·사천왕·챔피언 시스템의 그룹 단위
- **사천왕 (四天王)**: 각 코알리숑 상위 4명. 분기 토론 참가자
- **CEFR**: A1~C2 영어 레벨. 티어·단어 필터에 사용
- **티어**: LoL식 (챌린저·그마·마스터·다이아·플래·골드·실버·브론즈)

## 인증

- 42 OAuth (`profile.intra.42.fr` 앱 등록)
- Client Secret은 백엔드에만. 앱 번들·프론트 절대 금지
- OAuth 후 `/v2/me` 로 `campus.name == "Gyeongsan"` 확인, 아닐 시 진입 차단
- 42 API rate limit(초당 2회, 시간당 1200회) 감안해 `/v2/me` 결과는 DB 캐싱

## 코딩 관례

- **코멘트 최소**. WHY가 비자명할 때만. WHAT 설명 코멘트 금지
- **이모지 금지** (유저가 명시적으로 요청한 경우 예외)
- **유저 피드백·에러 메시지는 한국어**
- **새 툴 추가 시**: `TOOLS` 리스트 등록 + `input_schema` 정의 + `run_tool` 분기 추가
- **LLM 콜 새로 추가 시**: `SYSTEM_CACHED`, `_cached_tools`, `_cache_messages_tail` 패턴 준수
- **문법 참조 인용**: `docs/파일명` 형식으로 출처 표시
- **DB 마이그레이션**: 기존 `_db()`의 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` 패턴 유지
- **파일 생성 최소화**: 편집 우선, 새 파일은 필요할 때만

## 편집 스코프 규칙

이 규칙들은 **엄격**. 스코프 초과 편집은 지금 프로젝트에서 가장 잘 발생하는 사고 유형.

- **요청 범위 밖 파일 편집 금지**. 유저가 명시한 파일·기능 외에는 손대지 말 것
- **관련 코드 발견 시 정리 유혹 참기**. "이 함수도 지저분해 보이는데" → 그건 지금 태스크가 아님. 이슈로 남기고 넘어감
- **리팩터링·이름 변경·구조 개편 금지** (명시 요청 시에만). 버그 픽스는 최소 diff로
- **부산물 붙이지 말 것**: 요청 안 한 주석·docstring·타입힌트·포맷팅·import 정리 다 금지
- **파일 새로 만들지 말 것** (명시 요청 시에만). 기존 파일 편집이 항상 우선
- **문서·README·CLAUDE.md 자동 갱신 금지**. 코드 변경 시 문서도 손대야 할 것 같으면 유저에게 먼저 확인
- **커밋 전 항상 `git diff --stat` 확인**. 예상 밖 파일이 목록에 있으면 그 파일만 `git restore` 로 되돌리고 사유 보고
- **한 세션 한 기능**. 여러 기능을 한 세션에서 왔다갔다 하지 말 것. 컨텍스트 오염으로 실수 유발
- **모호한 지시는 실행 전 확인**. "적당히", "관련 코드도" 같은 애매한 요청은 편집 시작 전에 범위 재확인
- **plan 모드 활용**. 편집 범위가 3파일 이상이거나 100줄 이상이면 plan을 먼저 유저에게 제시하고 승인 후 실행

## 알려진 함정

- **`sessions.db` 는 커밋됨** (샘플 데이터 포함). 개인 실험은 별도 브랜치·로컬만 사용
- **`grammar_index.pkl` 자동 빌드**. `docs/` 바꾸면 `python rag.py` 로 재빌드 필수
- **Anthropic 캐싱은 5분 TTL**. 세션 새로 열면 첫 콜은 캐시 미스
- **`.env.example` 은 placeholder만**. 실제 `.env` 는 커밋 금지 (.gitignore로 차단됨)
- **`docs/*.md` 는 RAG 문법 코퍼스**. UI 렌더링 대상 아님. 절대 유저에게 노출 금지
- **iOS Safari Web Speech API**: Chrome 대비 정확도 편차 있음. 완벽 정확도 기대 금지
- **42 API rate limit**: `/v2/me` 매 요청마다 호출 금지. 로그인 시 캐싱

## 두 개의 벡터 스토어 구분

혼동 주의:

| 스토어 | 코퍼스 | 모델 | 저장 형식 | 용도 |
|---|---|---|---|---|
| `rag.py` | `docs/` 문법 md | all-MiniLM-L6-v2 | `grammar_index.pkl` | 진단 시 문법 규칙 근거 검색 |
| `vector_store.py` (예정) | `vocab_master`, `situations` | multilingual-e5-small | SQLite BLOB 컬럼 | 예문 만들기 훈련 (단어 → 상황) |

두 모델 병존. 새 모델은 한국어 상황 매칭 위해 도입.

## 개발 순서 (요약)

상세는 `MOBILE_APP_PLAN.md` 참조.

- **Phase 0**: 백엔드 API 분리, 42 OAuth 등록, JWT 인증 계층
- **Phase 1**: PWA MVP — 녹음 → STT → 분석 툴 1~2개 노출. 42 경산 배포
- **Phase 2**: 유창도 채점 파이프라인 (WPM·filler·TTR·문법·논리)
- **Phase 3**: 코알리숑 랭킹 + 리더보드
- **Phase 4**: 분기 토론 & AI 챔피언
- **Phase 5** (조건부): 네이티브 앱 이전 (실측 병목 있을 때만)

병렬로 진행: **예문 만들기 파이프라인** (Phase 2~3 사이 언제든). 단어 8000개 + 상황 1000개 + Claude rubric 단일 콜 채점.

## 계획 중인 소규모 기능

큰 기획(랭킹·챔피언·예문 파이프라인)은 `MOBILE_APP_PLAN.md`. 아래는 그와 별개로 코드 정리·UX 개선 성격의 작은 항목.

- **분석하기 탭 메트릭 카드 압축**: `#metrics` 4개 카드가 수직 공간을 잡아먹어 리포트까지 스크롤 필요. 인라인 칩 한 줄로 바꿀 것. 대시보드·기록 뷰의 큰 카드는 유지. → `web/static/style.css` 만 손봄
- **어휘 단어장 SRS (간격 반복 복습)**: Anki식. 통과→간격 2배, 실패→간격 리셋. `vocab` 테이블에 `next_review`, `interval_days`, `ease` 컬럼 추가. "오늘 복습 N개" 배지 + 큐 UI. → `tools.py`(mark_vocab 확장), `web/app.py`(/api/vocab/review/today), `web/static/`(큐 UI)

## 참조

- 앱화·랭킹·챔피언·예문 파이프라인 상세 설계: `MOBILE_APP_PLAN.md`
- 사용자향 README: `README.md`
- 문법 코퍼스: `docs/`

## 자주 헷갈리는 것

**Q. RAG로 진단 근거 인용하는 게 예문 훈련 파이프라인과 관련 있나요?**
아니오. 완전 별개. `rag.py`(진단용) 와 `vector_store.py`(예문 훈련용) 는 다른 벡터 스토어입니다.

**Q. 유저 개인 단어장(`vocab` 테이블)이 `vocab_master`인가요?**
아니오. `vocab`은 유저가 손으로 추가한 개인 단어장. `vocab_master`는 시스템이 미리 임베딩해둔 8000개 코어 어휘. 개인 단어장에 새 단어가 추가되면 자동으로 임베딩해서 `vocab_master`에도 온디맨드 등록 (롱테일 대응).

**Q. 웹 대신 앱으로 바로 가면 안 되나요?**
가지 않는 게 결정. PWA-first가 코어 UX(음성 녹음) 를 유지하면서도 개발 속도·배포 마찰을 최소화. 네이티브는 Phase 5 조건부.
