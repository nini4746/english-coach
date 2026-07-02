# 두호링고 (Duholingo) — 모바일 앱 전환 계획

현재 웹 기반 English Coach 서비스를 **두호링고**라는 이름의 모바일 앱으로 전환하기 위한 검토 문서.

## 브랜딩

- **프로젝트명**: 두호링고 (Duholingo)
- **네이밍 유래**: 호두(walnut)를 뒤집으면 두호 → `두호 + lingo`
- **앱 아이콘**: 호두
- **컨셉**: 이름의 유래(호두→두호)를 아이콘이 시각적으로 설명. 42 경산 카뎃들이 기억하기 쉬운 라이트한 톤.

### 디자인 방향 (제안)
- 심플한 2D 벡터 호두 일러스트 (플랫 또는 살짝 입체)
- iOS/Android 아이콘 가이드라인: 여백 포함 1024×1024 원본, 배경색은 호두 껍질톤(연갈) 또는 크림톤 대비
- 다크모드 대응 시 배경 반전 버전 준비

### 주의 사항
- "두호링고"는 Duolingo(듀오링고)와 발음이 유사 → 42 경산 내부 커뮤니티 서비스 단계에서는 무방하지만, 향후 공개 스토어 배포·상표 등록 시 상표권 검토 필요

## 목표 흐름

**사용자 목소리 녹음 → 영어 텍스트 변환(STT) → 기존 분석 파이프라인 투입**

이 흐름은 앱에서 자연스럽게 구현 가능하며, 웹보다 UX 측면(마이크 접근성, 백그라운드 녹음 등)에서 유리하다.

## 백엔드 재사용

기존 `web/app.py`(FastAPI)와 `tools.py`의 분석 툴(PREP 분석, 어휘 테스트 등)은 **그대로 API 서버로 유지**한다. 앱에서 이미 텍스트로 STT를 마친 뒤 전송하므로 `/transcribe` 같은 서버 측 STT 엔드포인트도 필요 없다.

앱 클라이언트만 새로 만들면 되는 구조.

## 크로스플랫폼 + 온디바이스 STT 조합

### 접근 A: OS 내장 STT 래핑 (권장)

- **React Native**: `@react-native-voice/voice`
- **Flutter**: `speech_to_text`

둘 다 iOS `Speech` 프레임워크 + Android `SpeechRecognizer`를 호출.

| 플랫폼 | 온디바이스 여부 | 영어 정확도 |
|---|---|---|
| iOS 13+ | 대부분 온디바이스 (`requiresOnDeviceRecognition = true`) | 높음 |
| Android (Pixel/최신) | Google 온디바이스 모델 | 높음 |
| Android (구형/일부 OEM) | 네트워크로 fallback 되는 경우 있음 | 기기 편차 |

**장점**: 무료, 실시간 스트리밍, 배터리 부담 적음
**단점**: Android 파편화 — 일부 기기에선 강제 온디바이스 불가

### 접근 B: whisper.cpp 임베드

- **React Native**: `whisper.rn`
- **Flutter**: `whisper_flutter_new` 계열

Whisper 모델을 앱 번들에 넣고 로컬 추론.

| 모델 | 용량 | 모바일 성능 |
|---|---|---|
| tiny.en | 39MB | 빠르지만 정확도 낮음 |
| base.en | 74MB | 균형 |
| small.en | 244MB | 정확도 좋음, 문장당 2~5초 |

**장점**: 완전 오프라인, 기기 무관하게 동일 품질, 영어 학습자 발음에 강함
**단점**: 앱 용량 증가, 첫 로드 지연, 실시간 스트리밍 어려움 (녹음 종료 후 배치)

### 추천 조합

**1차: OS 내장 STT (접근 A)** — 실시간 인식 피드백이 UX상 중요하고, 대부분 사용자(iPhone, 최신 Android)에게 충분함.

**2차 옵션: whisper.cpp** — 정확도 이슈가 있는 사용자에게 선택지로 제공.

## React Native vs Flutter

### 이 프로젝트 맥락에서 결론: **Flutter 추천**

이유:

1. **STT 라이브러리 성숙도** — `speech_to_text`가 유지보수 활발, iOS `onDevice: true` 명시적 지원. RN의 `@react-native-voice/voice`는 원저자가 손 뗀 뒤 커뮤니티 포크 상태.
2. **오디오 처리** — Flutter의 `record` + `just_audio` 조합이 iOS/Android 일관성 좋음. RN은 라이브러리 선택 피로 + 네이티브 브릿지 이슈 잦음.
3. **빌드/네이티브 의존** — 음성 기능처럼 네이티브 의존이 큰 기능에서 Flutter가 편함. RN은 New Architecture 전환기라 호환성 확인 필요.
4. **UI 성격** — 텍스트/카드/리스트 중심이라 Flutter 위젯 시스템으로 빠르게 만들기 좋음.
5. **whisper.cpp 확장성** — FFI로 붙이기 Flutter가 더 깔끔.

### React Native가 나은 경우

- JS/React 경험을 즉시 활용하고 싶음 (Dart 학습 부담 회피)
- Expo로 프로토타입을 매우 빠르게 뽑고 싶음
- 팀에 JS 개발자만 있음

### 비교표

| 항목 | Flutter | React Native |
|---|---|---|
| STT 라이브러리 안정성 | 우세 | 포크 파편화 |
| 오디오 라이브러리 | 일관성 좋음 | 선택 피로 |
| 학습 곡선 (JS 경험자) | Dart 새로 배움 | 즉시 시작 |
| Expo 같은 편의 도구 | 없음 (자체 툴체인은 좋음) | Expo |
| 앱 크기 (베이스) | 15~20MB | 20~30MB |
| 빌드 속도 | 빠름 | Metro/Gradle 이슈 잦음 |
| whisper.cpp 임베드 | FFI로 깔끔 | 네이티브 모듈 작성 필요 |

## 예상 코드 흐름 (참고)

React Native 기준 스케치:

```javascript
import Voice from '@react-native-voice/voice';

Voice.onSpeechResults = (e) => {
  const englishText = e.value[0];
  fetch('https://your-backend/analyze', {
    method: 'POST',
    body: JSON.stringify({ text: englishText })
  });
};

await Voice.start('en-US', {
  RECOGNIZER_ENGINE: 'services',
  requiresOnDeviceRecognition: true
});
```

Flutter 기준:

```dart
import 'package:speech_to_text/speech_to_text.dart';

final speech = SpeechToText();
await speech.initialize();
await speech.listen(
  onResult: (result) {
    final englishText = result.recognizedWords;
    // POST to backend
  },
  localeId: 'en_US',
  onDevice: true,
);
```

## 알려진 함정

- **Android 온디바이스 언어팩**: 시스템 설정에 "오프라인 음성 인식" 영어 팩이 깔려있어야 함. 최초 실행 시 사용자에게 안내 필요.
- **iOS 마이크 권한**: `Info.plist`에 `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription` 문구 필수.
- **백그라운드 녹음**: iOS는 백그라운드 오디오 모드 활성화 필요.
- **네트워크 fallback 감지**: 일부 Android에서 `onDevice: true` 요청해도 네트워크로 도는 경우 있음. 감지 로직 필요할 수 있음.

## 타겟 사용자 및 배포

**타겟**: 42 경산(42Gyeongsan) 학생

### 42 API 인증

- **OAuth2 앱 등록**: `profile.intra.42.fr` → OAuth Applications → Client ID/Secret 발급
- **흐름**: 앱 → 42 로그인 → 콜백 authorization code → 백엔드에서 access token 교환
- **보안**: Client Secret은 **백엔드에만** 보관. 앱 번들에 절대 포함 금지 (역공학으로 노출됨)
- **캠퍼스 필터링**: OAuth 후 `/v2/me` 호출 → `campus` 배열에서 `Gyeongsan` 확인 → 아닌 사용자는 앱 진입 차단
- **Rate Limit 대응**: 기본 초당 2회, 시간당 1200회. `/v2/me` 결과는 최초 로그인 시 백엔드 DB에 캐싱 (매 요청마다 호출 금지)

### 백엔드 추가 작업

- 세션/JWT 발급 로직 (42 OAuth 성공 후 자체 세션 토큰 발급 → 이후 API 호출은 자체 토큰으로)
- 사용자 테이블 (42 intra login, 캠퍼스, 가입일 등)
- 기존 `sessions.db`에 users 테이블 추가 또는 별도 DB 분리 검토

### 배포 채널

| 채널 | 특징 | 비용 |
|---|---|---|
| iOS TestFlight | 내부 테스터 100명 무료, 외부 테스터 최대 10,000명, 빌드 90일 유효 | Apple Developer $99/년 |
| Android Play 내부 테스트 | 이메일 화이트리스트 기반, 심사 완화 | Google Play Console 일회성 $25 |
| 웹 PWA | 스토어 심사 없음, 즉시 배포 가능, 마이크 접근 가능 | 무료 |

**권장 순서**: 웹 PWA로 MVP 검증 → 반응 좋으면 TestFlight/Play 내부 테스트로 앱화

### 42 경산 배포 시 유의사항

- **커뮤니티 규모**: 카뎃 규모가 크지 않으므로 TestFlight 100명 무료 티어로 충분
- **홍보 채널**: 42 경산 슬랙/디스코드 등 내부 커뮤니티에 초대 링크 공유
- **피드백 루프**: 앱 내 피드백 폼 또는 GitHub Issues 링크 제공
- **개인정보 처리방침**: 42 로그인·음성 데이터 수집이 있으므로 간단한 정책 페이지 필요 (스토어 심사에도 필수)

## 코알리숑 기반 랭킹 & 분기 챔피언 시스템

42의 코알리숑 문화를 게임식 랭킹과 결합한 참여 시스템.

### 개요
- 캠퍼스의 각 코알리숑 안에서 사용자에게 등급(챌린저/마스터/다이아 등)을 부여
- 각 코알리숑 상위 4명 = **사천왕(四天王)**
- 분기마다 사천왕들이 토론 → AI가 유창도 분석 → **분기 챔피언** 선정

### 데이터 소스
- `/v2/users/:id/coalitions` — 사용자의 코알리숑
- `/v2/campus/:id/coalitions` — 경산 캠퍼스 코알리숑 전체
- 로그인 시 캐싱 후 주기적 동기화

### 등급 체계 (LoL식)

```
챌린저 (상위 1명) → 그랜드마스터 (상위 5명) → 마스터
→ 다이아 → 플래티넘 → 골드 → 실버 → 브론즈
```

**MMR/포인트 소스**:
- 학습 세션 완료
- AI 유창도 점수 (세션마다 채점)
- 어휘 테스트 정답률
- 1:1 토론 매치 승률 (PvP 도입 시)

**감쇠(decay)**: 비활동 시 포인트 감소 → 상위 티어 유지에 지속 활동 필요

### 사천왕 선정
- 각 코알리숑 상위 4명 = 사천왕
- 분기 시작일 스냅샷으로 고정 (분기 중 변동 방지)

### 분기별 토론 방식

**비동기 라운드제 권장** (실시간 화상은 인프라·조율 부담 큼):

1. 라운드 1: AI가 무작위 주제 발표 → 각 사천왕 3분 답변 녹음 (48시간 데드라인)
2. 라운드 2: 다른 참가자 답변 청취 후 반박 녹음 (48시간)
3. 라운드 3: 최종 변론
4. AI가 전체 발화 종합 채점 → 최고 득점자 = 챔피언

주제 무작위성 + 짧은 데드라인 = 스크립트 낭독 방지.

### AI 유창도 분석 지표

| 지표 | 측정 방법 |
|---|---|
| WPM (speech rate) | Whisper 타임스탬프 |
| Filler word ratio | uh/um/like/you know 카운트 |
| 어휘 다양성 | Type-Token Ratio + CEFR 등급 분포 |
| 문법 정확성 | LLM 채점 (기존 `tools.py` 재사용) |
| 논리 구조/설득력 | LLM 채점 (PREP 분석 활용) |
| 발음 명료도 | Whisper confidence score 대체 지표 |

가중치 합산 → 라운드별 점수 → 총합 최고자가 챔피언.

### 챔피언 후처리
- 분기별 챔피언 배지
- 명예의 전당 리더보드 페이지
- 다음 분기 사천왕 시드권 부여

### 어려운 지점과 완화책

**AI 채점 공정성**
- 같은 발화 3회 채점 후 중앙값
- 여러 기준 독립 채점 후 합산
- 점수 + 근거 코멘트 공개 → 이의제기 창구 마련

**소규모 코알리숑 문제** (42 경산 카뎃 수 제한)
- 초기엔 "사천왕" 대신 "삼천왕" / "코알리숑 대표 N명"으로 유연 운영
- 또는 전체 캠퍼스를 하나의 리그로 통합하는 대안

**부정 행위 (대본 낭독, 대리 참여)**
- 랜덤 주제 + 짧은 데드라인
- 선택적 카메라 촬영 요구
- 참가자 이전 발화 대비 스타일 급변 감지

**참여 동기 유지 (분기 사이클 김)**
- 주간 미니 챌린지로 포인트 지속 획득
- 코알리숑 내부 리더보드 상시 표시

### 백엔드 추가 스키마 (초안)

- `users` — 42 login, 캠퍼스, 코알리숑 id
- `sessions` — 학습 세션 기록 (기존 확장)
- `fluency_scores` — 세션당 지표별 점수
- `ranking_points` — 사용자별 포인트, 티어, 최종 갱신 시각
- `debate_tournaments` — 분기별 토너먼트 메타
- `debate_submissions` — 사천왕 라운드별 녹음 + AI 채점 결과
- `champions` — 분기별 코알리숑별 챔피언 이력

## 실행 로드맵

**핵심 원칙**: 작은 것부터 검증. 랭킹/토론 시스템은 사용자 기반이 없으면 죽은 기능이 됨. 각 단계마다 게이트를 두고 다음 단계 진입 여부 판단.

### Phase 0. 준비 (1~2주)
- 백엔드 API와 웹 UI 분리 (`web/app.py`에서 JSON API만 추출)
- 42 OAuth 앱 등록, redirect URI 설계
- 사용자 테이블 + JWT 발급 로직 추가
- **앱 개발은 아직 시작 안 함**

### Phase 1. PWA MVP (2~3주) — 실제 사용자 확보
- 기존 웹에 manifest + service worker → 설치 가능한 PWA
- 42 OAuth 로그인 + 경산 캠퍼스 필터
- Web Speech API로 브라우저 온디바이스 STT
- 녹음 → 텍스트 → 기존 분석 툴 1~2개 결과 표시
- 개인정보 처리방침 페이지
- 42 경산 커뮤니티에 배포 후 **일주일 사용 데이터 수집**

**게이트**: 재사용률이 낮으면 다음 단계 보류. 코어 UX부터 재검토.

### Phase 2. 유창도 채점 파이프라인 (2주)
- Whisper 기반 WPM, filler ratio
- 어휘 다양성 (TTR + CEFR 분포)
- LLM 기반 문법·논리 채점 프롬프트 튜닝 및 편차 측정
- `fluency_scores` 테이블에 세션마다 저장
- 사용자 본인 점수 추이만 노출 (랭킹 아직 없음)

**이 단계 채점 품질이 이후 랭킹의 정당성을 결정**

### Phase 3. 코알리숑 랭킹 & 리더보드 (2~3주)
- 42 API에서 코알리숑 정보 동기화
- MMR 공식 및 포인트 로직
- 티어 구간 확정 (실사용자 수 보고 조정)
- 코알리숑별 리더보드 UI
- 주간 미니 챌린지

**게이트**: 코알리숑별 활성 사용자 4명 미만이면 "코알리숑 대표 N명"으로 유연화

### Phase 4. 분기 토론 & AI 챔피언 (3~4주)
- 비동기 라운드제 인프라 (주제 생성, 데드라인, 녹음 업로드)
- 다중 지표 종합 채점
- 채점 근거 코멘트 자동 생성 (이의제기용)
- 명예의 전당 페이지
- 첫 분기 파일럿 → 회고 → 규칙 조정

### Phase 5. 네이티브 앱 전환 (선택, 4~6주)

PWA 제약이 실제 병목이 된 경우에만 진행:
- 백그라운드 녹음/알림이 필수인데 브라우저 제약이 큼
- iOS Safari STT 정확도 부족 → 네이티브 Speech 프레임워크 필요
- 앱 스토어 존재감이 발견성·신뢰도에 유리

Flutter로 이전, 백엔드는 그대로.

### 병렬화 가능
- Phase 2 (채점)와 Phase 3 (랭킹 UI 스켈레톤) 부분 병렬 가능
- Phase 4 채점 프롬프트 설계는 Phase 2 결과 나오자마자 시작

### 총 예상 기간
- PWA + 랭킹까지: 약 2~3개월
- 분기 토론 파일럿 포함: 약 3~4개월
- 네이티브 앱까지: 약 4~6개월

## 다음 단계 (미정)

- [ ] Flutter vs RN 최종 결정
- [ ] 42 OAuth 앱 등록 및 리다이렉트 URI 설계
- [ ] 백엔드 인증 계층 추가 (42 OAuth → 자체 JWT 발급)
- [ ] 사용자 테이블 스키마 정의
- [ ] 백엔드 API 스펙 정리 (앱에서 호출할 엔드포인트 목록)
- [ ] 최소 프로토타입 범위 정의 (녹음 → STT → 1개 분석 툴 결과 표시)
- [ ] iOS/Android 각각 마이크·STT 권한 UX 설계
- [ ] 배포 채널 결정 (PWA 먼저 vs 바로 네이티브 앱)
- [ ] 개인정보 처리방침 초안 작성
- [ ] 랭킹 시스템 MMR 공식 설계 (포인트 소스별 가중치)
- [ ] 등급 구간 인원 비율 결정 (예: 챌린저 1명, 그마 5명 등)
- [ ] 분기 토론 라운드 규칙 확정 (라운드 수, 데드라인, 주제 풀)
- [ ] AI 유창도 지표별 가중치 결정 및 채점 프롬프트 설계
- [ ] 코알리숑별 인원 실측 후 사천왕 규모 조정 여부 판단
- [ ] 명예의 전당 UI 설계
