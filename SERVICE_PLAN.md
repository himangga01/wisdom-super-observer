# Wisdom Super Observer 서비스 구현 계획

> **통합 인수인계 문서:** 이 파일은 현재까지 합의된 서비스 범위, 연동 조사 결과, 미확정 사항, 다음 작업 지점을 한곳에 정리한 기준 문서다. 새 대화나 다른 작업 환경에서 이어갈 때 이 파일을 먼저 읽는다.

```yaml
last_updated: 2026-08-21
workspace: D:\project\wisdom-super-observer
repository: https://github.com/himangga01/wisdom-super-observer.git
current_stage: 아이디어 구체화 및 외부 연동 기술 조사
implementation_status: 본 서비스 구현 시작 전
next_focus: Android 장치 연결 후 SuperLive Plus APK 정적 분석 및 Tapo 실제 모델 확인
```

> **중요:** 계정 아이디, 비밀번호, 장비 QR/시리얼과 같은 비밀정보는 이 문서에 기록하지 않는다. 필요한 자격증명은 사용자가 보유하고 있으며 실제 연동 시 별도 비밀 저장소 또는 실행 환경을 사용한다.

> **작업 원칙:** 사용자가 승인한 작업만 수행한다. Autonat, 오더퀸 및 CCTV 장비는 조회 전용으로 다루며 설정 변경, 상품 수정, 거래 취소, 업로드 등 외부 상태를 바꾸는 작업은 하지 않는다.

**목표:** 여러 무인매장 점주가 웹과 앱에서 CCTV 이상행동 감지, 알림·경고방송, 키오스크 결제 확인, 상품 판매 분석을 통합 관리할 수 있는 멀티테넌트 서비스를 구축한다.

**아키텍처:** 카메라별 어댑터가 영상 또는 감지 이벤트를 수집하고, YOLO 기반 영상 분석기가 사람·행동·구역 이벤트를 1차 판별한다. 의미 판단이 필요한 사건만 GPT에 대표 이미지를 전달해 재확인·요약하며, 오더퀸 로그인 세션 기반 조회 커넥터가 매장·거래·상품 판매 데이터를 읽기 전용으로 동기화한다.

**권장 기술 스택:** Next.js/React, React Native 또는 Flutter, FastAPI, PostgreSQL, Redis, S3/MinIO, FFmpeg/OpenCV, YOLO, ByteTrack/BoT-SORT, Docker, GPU 추론 서버, Web Push/FCM/APNs.

## 전역 제약사항

- 특정 점주나 특정 매장 전용이 아닌 다중 점주·다중 매장 구조로 구현한다.
- 한 점주는 매장을 1개 또는 여러 개 소유할 수 있다.
- 관리자는 웹과 모바일 앱에서 동일한 매장·사건·판매 데이터를 확인할 수 있어야 한다.
- CCTV와 오더퀸 연동은 점주가 권한을 가진 계정과 매장만 대상으로 한다.
- 오더퀸은 조회 전용 화이트리스트만 사용하며 저장·수정·삭제·취소·업로드 API는 호출하지 않는다.
- 오더퀸 동기화는 대시보드 진입 시 1회 실행하고, 이후에는 사용자가 새로고침 버튼을 눌렀을 때만 실행한다.
- CCTV 이상행동 판정은 YOLO와 규칙 엔진을 기본으로 하고, GPT는 사건 재확인과 자연어 요약에 제한적으로 사용한다.
- LLM 공급자는 우선 GPT만 사용한다. 사용자가 요구한 웹 로그인 계정 기반 연결 방식과 Hermes의 세션 연동 방식은 구현 전 지원 범위와 안정성을 확인한다.
- 얼굴인식이나 자동 범죄 확정이 아니라 사건 후보 탐지와 관리자 확인을 중심으로 설계한다.
- 개인정보, 결제정보, CCTV 증거자료는 최소 수집·암호화·보존기간·접근기록 정책을 적용한다.

## 0. 대화 기반 핵심 의사결정 기록

### 서비스 범위

- 최초 검토 대상은 사용자가 운영하는 2개 매장이지만, 제품은 특정 점주나 2개 매장 전용으로 만들지 않는다.
- 점주별 보유 매장 수를 오더퀸과 카메라 연결 정보에서 동적으로 파악해 1개 매장과 여러 매장을 모두 지원한다.
- 점주와 관리자는 웹과 모바일 앱에서 같은 사건·카메라·판매 정보를 확인할 수 있어야 한다.
- 기능 범위는 현재 문서에 확정된 이상행동, 도움 요청, 사건 요약, 규칙 생성기, 직원 방문 모드, 반복 사건, 결제 매칭, 판매 분석으로 제한한다.

### AI 판정

- 영상 전체를 GPT에 계속 보내는 구조가 아니라 YOLO·추적·포즈·구역 규칙이 1차 실시간 분석을 담당한다.
- GPT는 사건 후보 이미지나 짧은 클립을 재확인하고 한국어 사건 요약을 생성한다.
- 매장 영상이 축적되면 정탐·오탐 피드백을 라벨링해 YOLO/포즈 모델을 추가 학습할 수 있게 한다.
- 초기 LLM 공급자는 GPT만 계획한다.
- 사용자가 요구한 GPT 웹 로그인 계정 기반 인증과 Hermes 세션 방식의 필요한 부분 재사용은 별도 기술 검증 항목이다. 지원 여부가 확인되기 전까지 구현 완료로 간주하지 않는다.

### 카메라

- 카메라 또는 DVR에서 감지 이벤트를 받을 수 있으므로 이를 1차 트리거로 활용한다.
- 구형 Autonat IE/ActiveX 접근 방식은 조사·비상 접근 후보로 유지한다.
- Autonat 운영 연동의 우선순위는 매장 LAN의 RTSP/ONVIF, TVT SDK/AutoNAT, NVMS 2.0 브리지, ActiveX 브리지 순이다.
- TVT SuperLive Plus Android 앱은 P2P Live/Alarm/Talk 구현을 파악하기 위한 정적·동적 분석 대상으로 선정했다.
- Tapo 상시 전원형 카메라는 RTSP/ONVIF와 go2rtc를 우선 사용하며 Flask MJPEG 방식은 PoC로만 사용한다.

### 알림과 대응

- 냉동고 위에 올라가거나 앉기, 매장 내 달리기, 카메라를 향한 손 흔들기, 반복 결제 시도, 결제 오류를 사건 후보로 감지한다.
- 사용자에게 대표 이미지, 짧은 영상, 매장·카메라·발생시각, AI 요약을 제공한다.
- 경고방송은 기본적으로 관리자가 사건을 확인하고 실행을 승인한 뒤에만 전송한다.

### 오더퀸과 판매 대시보드

- 오더퀸의 점주별 매장, 거래, 거래상품, 결제, 취소, 상품, 가격·품절, POS 자료를 조회 전용으로 연결한다.
- 모든 조사와 운영 연동에서 상품·가격·품절·행사·거래를 수정하거나 취소하지 않는다.
- 대시보드 진입 시 한 번 조회·업데이트하고, 화면을 연 상태에서는 자동 폴링하지 않으며 이후 사용자가 새로고침할 때 갱신한다.
- 과거 데이터는 매장별 실제 최초 매출 월을 찾아 백필하고, 상품별 수량·매출·판매속도·추세·간헐성·품절 영향을 분석한다.
- CCTV 방문 세션과 결제 시각을 연결하되 미결제를 범죄나 절도로 자동 확정하지 않는다.

### 현재 상태

- 현재는 구현 전 아이디어·연동 조사 단계다.
- 서비스 애플리케이션, APK 추출, 실제 DVR/Tapo 접속 시험, 동적 후킹은 아직 시작하지 않았다.
- 다음 실제 장치 작업은 매 단계 사용자 승인 후 읽기 전용으로 진행한다.

---

## 1. 서비스 대상과 사용자 구조

### 주요 사용자

- 무인 아이스크림 매장 등 무인매장 점주
- 여러 매장을 관리하는 브랜드 또는 운영 관리자
- 사건 확인, 재고 보충, 청소 등을 담당하는 직원

### 멀티테넌트 계층

```text
Tenant(점주/사업자)
└─ Users(점주·관리자·직원)
   └─ Stores(1개 이상)
      ├─ Cameras
      ├─ Kiosks / OrderQueen connection
      ├─ Zones and Rules
      ├─ Events and Alerts
      └─ Products and Sales Analytics
```

### 권한 기본안

- 점주: 소유한 전체 매장, 사건, 판매 데이터 관리
- 관리자: 지정된 매장 관리와 사건 확인
- 직원: 지정된 매장 조회 및 직원 방문 모드 사용
- 시스템 운영자: 테넌트 상태와 장애 진단만 수행하며 원본 영상·결제정보 접근은 별도 통제

## 2. 확정 기능 범위

### CCTV 이상행동 감지

- 고객이 냉동고 또는 지정 설비 위에 올라가거나 앉는 행동 감지
- 매장 안에서 뛰어다니는 행동 감지
- 사용자가 화면에서 직접 구역을 그리고 행동 지속시간 조건을 설정
- 같은 행동 패턴이 여러 날 반복되는지 확인
- 사람이 없는 시간, 카메라 가림, 장시간 체류 등은 규칙 확장 대상으로 유지

### 도움 요청 및 키오스크 곤란 감지

- 고객이 카메라를 향해 손을 흔들면 도움 요청으로 인식
- 키오스크 앞에서 반복적으로 결제를 시도하면 사용 곤란 후보로 감지
- 결제 오류가 발생하면 점주에게 원격 지원 요청 알림

### 사건 알림과 대응

- 웹 실시간 알림, 모바일 푸시 알림
- 대표 이미지, 짧은 클립, 감지 시각, 매장, 카메라, 신뢰도 제공
- AI 사건 요약 제공

예시:

> 청소년 3명이 입장해 매장 안을 뛰었으며 한 명이 냉동고 위에 앉았습니다.

- 사용자가 사건을 확인한 뒤 원할 경우 매장 경고 방송 실행
- 자동 방송이 아니라 관리자 확인 후 실행을 기본 정책으로 사용
- 방송 문구 템플릿 및 TTS 지원

### 운영 편의 기능

- 직원 방문 모드: 청소·재고 보충 중 일부 행동 알림 자동 중지
- 매장 규칙 생성기: 구역, 행동 종류, 지속시간, 알림 단계 설정
- 반복 사건 감지: 매장·구역·요일·시간대별 반복 패턴 제공
- 사건 상태: 신규, 확인, 오탐, 조치 완료

### 결제 여부 확인

- CCTV 방문·활동 기록과 오더퀸 거래 시각을 시간대와 매장 기준으로 연결
- 고객의 입장, 상품 구역 체류, 키오스크 체류, 결제 발생 여부를 하나의 방문 세션으로 구성
- 결과는 `결제 확인`, `결제 가능성 높음`, `확인 필요`, `거래 불일치 후보`처럼 신뢰도 단계로 표현
- 시스템이 절도 여부를 자동 확정하지 않고 관리자 검토 자료로 제공

### 상품 판매 분석 대시보드

- 점주가 가진 매장 수에 맞춰 매장 선택기와 대시보드를 동적으로 생성
- 상품별 판매수량, 매출액, 판매속도, 매출 기여도, 기간별 추이 제공
- 잘 팔리는 상품, 안 팔리는 상품, 상승 상품, 하락 상품 자동 분류
- 매장별 비교와 전체 매장 합산 보기
- 상품·바코드·분류별 상세 분석
- 신규 상품과 데이터 부족 상품은 신뢰도 낮음으로 표시
- 판매 0과 품절로 인한 판매 0을 구분

## 3. CCTV 분석 설계

### 처리 흐름

```text
Camera / Detection Event
→ Frame or short clip extraction
→ YOLO object detection
→ Multi-object tracking
→ Zone and duration rule engine
→ Event candidate scoring
→ GPT visual confirmation when needed
→ Incident summary
→ Web/mobile alert
→ Human confirmation
→ Optional warning broadcast
```

### YOLO를 사용하는 이유

- 실시간 영상 전체를 GPT에 계속 전송하지 않고 사람과 객체 위치를 저비용으로 추적
- 사람 수, 바운딩박스, 이동속도, 구역 진입, 체류시간을 수치화
- 냉동고 위 구역, 키오스크 구역, 출입구 구역 등 매장별 규칙과 결합 가능
- 향후 축적된 매장 이미지로 커스텀 행동·객체 모델 학습 가능

### 행동 판정 방식

- 냉동고 위 올라감/앉음: 사람 바운딩박스, 포즈, 냉동고 상단 구역, 지속시간을 조합
- 뛰기: 사람 트랙 이동속도, 프레임 간 변위, 포즈 변화, 최소 지속시간을 조합
- 손 흔들기: 포즈 추정으로 손목의 반복 좌우 움직임과 카메라 방향을 판정
- 반복 결제 시도: 키오스크 구역 체류, 접근 횟수, 손 동작, 오더퀸 결제 오류·거래 부재를 결합
- 규칙별 임계값은 매장과 카메라별로 조절 가능하게 구성

### 학습 데이터 운영

- 오탐/정탐 관리자 피드백을 학습 후보로 저장
- 개인정보 정책에 따라 비식별화 또는 필요한 영역만 잘라 라벨링
- CVAT 또는 Label Studio로 라벨링
- 학습 데이터 버전, 모델 버전, 매장별 성능을 기록
- 공통 모델을 기본으로 사용하고 매장별 임계값을 먼저 조정한 후 필요할 때만 재학습

## 4. 카메라 연동 계획

### Autonat CCTV

- `https://www.autonat.com/`은 TVT 계열 DVR/NVR이 사용하는 P2P/NAT 중계 포털로 파악됨
- 현재 장비의 라이브 페이지는 구형 H.265 `1_3_8_0/u1a` 웹뷰어와 ActiveX 플러그인을 사용
- 웹 로그인 자동화는 조사·비상 접근 수단으로만 유지하고 운영 영상 수집의 중심으로 사용하지 않음
- 운영 영상은 매장 내부 RTSP/ONVIF 직접 연결을 1순위로 사용
- 외부 P2P 연결은 TVT SDK의 AutoNAT/NAT20 기능과 `pytvt` 활용을 우선 검토
- DVR의 `queryAlarmStatus` 읽기 이벤트를 AI 분석의 1차 트리거로 활용
- 세부 조사 결과와 대안 우선순위는 이 문서의 `14. Autonat 및 TVT 연동 조사 결과`를 기준으로 함

### Tapo 홈 카메라

- 지원 모델은 RTSP 또는 ONVIF 스트림 우선 사용
- 직접 연결이 어려우면 매장 내부 엣지 게이트웨이가 영상을 받아 중앙 서버에 사건 프레임만 전송
- 카메라별 연결 상태, 마지막 프레임 시각, 해상도, FPS를 모니터링
- `go2rtc`의 Tapo 입력 지원과 RTSP/WebRTC 재송출 기능을 우선 검토

### 카메라 어댑터 공통 인터페이스

```text
listCameras(store)
getStream(camera)
getDetectionEvents(camera, since)
captureSnapshot(camera, timestamp)
getHealth(camera)
startTalk(camera)
sendAudio(camera, audio)
stopTalk(camera)
```

## 5. GPT 연동 역할

### 사용하는 기능

- YOLO와 규칙 엔진이 만든 사건 후보 이미지 재확인
- 여러 대표 프레임을 보고 행동과 상황 설명
- 사람 수, 주요 행동, 구역, 지속시간을 포함한 사건 요약
- 경고방송 문구 초안 생성

### 사용하지 않는 방식

- CCTV 전체 영상을 GPT에 지속 스트리밍
- GPT 단독으로 모든 프레임을 실시간 판정
- GPT 응답만으로 결제 누락이나 범죄를 자동 확정

### 비용과 개인정보 절감

- 사건 후보가 발생했을 때만 대표 프레임 전송
- 얼굴이나 불필요한 화면 영역 마스킹 옵션
- 동일 사건 프레임 중복 제거
- GPT 응답과 사용량을 사건 ID 기준으로 기록

## 6. 오더퀸 연동 계획

### 연결 특성

- 사이트: `https://www.orderqueen.kr/backoffice_admin/`
- 공식 공개 API가 아니라 로그인 세션 쿠키를 사용하는 내부 API
- 대부분 `POST` 요청
- 목록 응답은 HTML 조각, 차트·선택목록은 JSON
- 점주별 세션과 매장 권한을 분리 보관

### 핵심 조회 API 화이트리스트

| 목적 | API |
|---|---|
| 점주 매장 목록 | `BAS01020_STORE_LST.itp` |
| 월별 매출 | `SAL02020_LIST.itp`, `SAL02020_CHART.itp` |
| 일별 매출 | `SAL02010_LIST.itp`, `SAL02010_CHART.itp` |
| 상품코드별 판매 | `SAL03020_LIST.itp`, `SAL03020_CHART.itp` |
| 바코드별 판매 | `SAL03070_LIST.itp`, `SAL03070_CHART.itp` |
| 분류별 판매 | `SAL03080_LIST.itp`, `SAL03080_CHART.itp` |
| 거래 원장 | `SAL01020_LIST.itp` |
| 거래 상품 상세 | `SAL01020_POPUP.itp` |
| 결제 상세 | `SAL01020_PAYMENT.itp` |
| 취소 거래 | `SAL01060_LIST.itp` |
| 카드 승인 | `SAL01030_LIST.itp` |
| 상품 마스터 | `MNU01020_LST.itp` |
| 가격·품절 조회 | `MNU01050_LST.itp` |
| POS 목록 | `SYS02010_POSLIST.itp` |

### 금지 정책

- 이름에 `SAVE`, `DEL`, `CANCEL`, `UPDATE`, `RESET`, `UPLOAD`, `SOLDOUT_SEND`, `PRICE_SAVE` 등이 포함된 변경 API 차단
- 엑셀 업로드와 상품·가격·품절·행사·거래 취소 기능 호출 금지
- 서비스 계층에서 조회 화이트리스트 외 URL 요청을 거부
- 커넥터 계정은 조회에 필요한 최소 권한만 사용

### 최초 데이터 수집

```text
Tenant connection
→ Store list discovery
→ Query yearly monthly-sales summaries
→ Detect first month with actual sales
→ Backfill each store × month × page
→ Upsert products, transactions, cancellations and aggregates
→ Record sync cursor and coverage
```

- 오더퀸 화면은 2020년 이후 연도 선택을 지원
- 현재 확인한 매장 데이터는 2023년부터 실제 매출이 존재하지만 서비스는 매장별 최초 매출 월을 자동 탐색
- 최초 백필은 한 번 수행하고 이후에는 최근 데이터만 갱신
- 전용 `updated_since` API가 없으므로 최근 기간을 재조회한 뒤 내부 DB에 upsert

### 동기화 실행 규칙

- 대시보드에 진입하면 해당 점주의 매장 데이터를 1회 조회·업데이트
- 화면을 계속 열어둔 동안 자동 반복 폴링하지 않음
- 이후 사용자가 새로고침 버튼을 누르면 다시 조회
- 대시보드에서 나갔다가 다시 진입하면 1회 동기화
- 동기화 중복 실행 방지와 매장별 잠금 적용

## 7. 상품 판매 분석 로직

### 분석 축

- 판매력: 기간당 판매수량과 판매일수
- 매출 기여도: 전체 매출에서 상품이 차지하는 비율
- 판매속도: 일평균, 영업일 평균, 최근 7일·28일 속도
- 모멘텀: 최근 구간과 이전 구간의 평활 증가율
- 수요 간헐성: ADI와 CV²를 이용한 안정형·변동형·간헐형·불규칙형 분류
- 품절 상태: 판매 0이 실제 수요 부재인지 품절 때문인지 분리
- 신뢰도: 관측일수, 판매건수, 데이터 누락, 품절일수를 반영

### 기본 결과 분류

- 베스트셀러
- 안정 판매
- 상승세
- 하락세
- 저판매
- 간헐 수요
- 품절 영향
- 신규/데이터 부족

### 분석 원칙

- 고정 가중치 하나로 상품을 단순 순위화하지 않음
- 매장 크기와 카테고리 차이를 고려해 매장·분류 내 상대 순위를 함께 제공
- 취소·환불·가격 변경과 데이터 누락을 반영
- 결과에 근거 지표와 신뢰도를 함께 표시

## 8. CCTV 방문과 결제 기록 매칭

### 방문 세션 생성

- 출입구 구역에서 사람 트랙 생성
- 매장 내 이동과 키오스크 구역 체류 기록
- 동일 카메라 또는 다중 카메라 트랙을 시간과 위치로 연결
- 퇴장 또는 장시간 미관측 시 방문 세션 종료

### 결제 연결

- 매장번호와 POS 번호 일치
- 키오스크 체류 전후의 결제 시각 검색
- 거래 상세의 상품수량, 금액, 취소 여부 확인
- 여러 고객이 동시에 존재하는 경우 자동 확정 대신 확인 필요 처리

### 매칭 결과 예시

```text
PAID_CONFIRMED
PAID_LIKELY
REVIEW_REQUIRED
NO_MATCH_CANDIDATE
PAYMENT_ERROR
CANCELLED_TRANSACTION
```

## 9. 시스템 구성

### 제안 모노레포 구조

```text
apps/
  web/                    # 점주·관리자 웹 대시보드
  mobile/                 # 모바일 앱과 푸시 알림
services/
  api/                    # 인증, 테넌트, 매장, 사건, 대시보드 API
  video-worker/           # 스트림 처리, YOLO, 추적, 규칙 엔진
  llm-worker/             # GPT 이미지 판정과 사건 요약
  orderqueen-connector/   # 로그인 세션과 읽기 전용 동기화
  notification-worker/    # 웹·모바일 알림과 재시도
  broadcast-gateway/      # 매장 경고방송과 TTS
packages/
  contracts/              # 공통 이벤트·API 스키마
  rules/                  # 행동·구역 규칙 정의
  analytics/              # 판매 분석과 결제 매칭 로직
infra/
  docker/                 # 로컬·서버 실행 구성
  migrations/             # 데이터베이스 마이그레이션
docs/                     # API, 운영, 개인정보 정책
```

### 주요 데이터 엔터티

- Tenant, User, Membership
- Store, Camera, CameraCredential, CameraHealth
- Zone, BehaviorRule, StaffVisitMode
- PersonTrack, VisitSession, DetectionEvent, Incident
- EvidenceFrame, EvidenceClip, IncidentSummary
- Alert, AlertDelivery, BroadcastCommand
- KioskConnection, OrderQueenSession, SyncJob
- Product, ProductPriceState, Transaction, TransactionItem, Cancellation
- DailyProductMetric, ProductTrend, DemandPattern
- PaymentMatch, ReviewDecision, ModelFeedback

## 10. 오픈소스 활용 계획

| 영역 | 후보 |
|---|---|
| 객체 탐지·학습 | Ultralytics YOLO 또는 호환 YOLO 구현 |
| 추적 | ByteTrack, BoT-SORT |
| 영상 처리 | FFmpeg, OpenCV, GStreamer |
| TVT 장비·AutoNAT 조사 | `pytvt` + 사용자가 별도로 확보한 TVT SDK |
| 스트림 중계 | MediaMTX, go2rtc |
| 엣지 NVR 참고 | Frigate |
| 포즈 추정 | YOLO Pose, MediaPipe |
| 라벨링 | CVAT, Label Studio |
| 데이터셋 탐색 | FiftyOne |
| 모델 실험 관리 | MLflow |
| API 서버 | FastAPI |
| 작업 큐 | Celery/RQ 또는 동등한 Redis 기반 큐 |
| 객체 저장소 | MinIO/S3 |
| 관측성 | Prometheus, Grafana, OpenTelemetry |

- 채택 전 라이선스와 상업 서비스 사용 조건을 확인한다.
- 전체 솔루션을 그대로 의존하기보다 영상 처리, 추적, 라벨링 등 검증된 부분을 모듈 단위로 재사용한다.
- `pytvt`는 TVT 장비 조회, CGI/Web API, 알람 프레임, 스냅샷, RTSP URL 및 SDK 기반 AutoNAT 로그인에 활용한다.
- 현재 공개된 `pytvt`만으로 P2P 연속 영상 수신이 완성됐다고 가정하지 않는다. SuperLive Plus 분석 또는 TVT SDK의 RealPlay 바인딩으로 보완한다.

## 11. 구현 단계

### Phase 0: 연동 기술 검증

- [x] Autonat 공개 웹 코드에서 TVT/AutoNAT 구조, 로컬 플러그인, 알람 조회 명령 확인
- [ ] 매장 내부에서 DVR RTSP/ONVIF/HTTP CGI 접근 가능 여부를 읽기 전용으로 확인
- [ ] TVT SDK 또는 `pytvt`로 장비 시리얼 기반 AutoNAT 로그인과 조회 기능 확인
- [ ] SuperLive Plus APK에서 P2P Live/Alarm/Talk 네이티브 함수와 호출 흐름 확인
- [ ] P2P를 통해 H.264/H.265 압축 프레임 1개를 읽기 전용으로 확보
- [ ] 사용하는 Tapo 모델의 RTSP/ONVIF 지원 확인
- [ ] YOLO로 사람 탐지와 구역 체류 이벤트 생성
- [ ] GPT에 대표 이미지 전달 후 행동 확인·요약 결과 구조 확정
- [ ] 오더퀸 읽기 전용 커넥터의 로그인, 매장목록, 월별매출, 상품판매 조회 확정
- [ ] 매장 경고방송 장치와 전달 방식 확정

**완료 기준:** 한 매장에서 카메라 이벤트, 대표 이미지 분석, 오더퀸 조회가 각각 독립적으로 성공한다.

### Phase 1: 멀티테넌트 기반과 웹 대시보드

- [ ] 테넌트, 사용자, 역할, 매장 데이터 구조 구축
- [ ] 점주 로그인과 소유 매장 선택 화면 구축
- [ ] 카메라·오더퀸 연결 상태 화면 구축
- [ ] 사건 목록과 사건 상세 기본 화면 구축
- [ ] 감사로그와 자격증명 암호화 적용

**완료 기준:** 서로 다른 점주가 상대방 매장이나 사건에 접근할 수 없고 자신의 매장만 관리할 수 있다.

### Phase 2: CCTV 이상행동 MVP

- [ ] 카메라 스트림·감지 이벤트 수집 어댑터 구축
- [ ] YOLO 사람 탐지와 트래킹 구축
- [ ] 구역 편집기와 지속시간 규칙 구축
- [ ] 냉동고 위 올라감/앉음과 달리기 후보 감지
- [ ] 사건 프레임·클립 저장과 웹 알림 구축
- [ ] 정탐·오탐 피드백 구축

**완료 기준:** 테스트 영상에서 사건 후보가 생성되고 관리자가 웹에서 증거와 규칙 근거를 확인할 수 있다.

### Phase 3: GPT 요약, 모바일 알림, 경고방송

- [ ] 사건 후보 대표 프레임 선택
- [ ] GPT 재확인과 구조화 사건 요약 구축
- [ ] 모바일 앱 사건 목록과 푸시 알림 구축
- [ ] 사용자 확인 후 경고방송 실행 흐름 구축
- [ ] 직원 방문 모드 구축

**완료 기준:** 모바일 알림에서 사건을 확인하고 승인한 경우에만 해당 매장 방송이 실행된다.

### Phase 4: 오더퀸 판매 대시보드

- [ ] 점주별 오더퀸 세션과 매장 자동 발견 구축
- [ ] 최초 과거 데이터 백필과 동기화 상태 구축
- [ ] 대시보드 진입·수동 새로고침 동기화 구축
- [ ] 상품·거래·취소·품절 데이터 정규화
- [ ] 판매력, 속도, 모멘텀, ADI/CV², 신뢰도 분석 구축
- [ ] 매장별·전체 매장별 상품 판매 대시보드 구축

**완료 기준:** 매장이 1개인 점주와 여러 개인 점주 모두 자신의 구조에 맞는 대시보드를 자동으로 확인한다.

### Phase 5: 도움 요청과 결제 매칭

- [ ] 손 흔들기 도움 요청 감지
- [ ] 키오스크 반복 시도와 결제 오류 사건 생성
- [ ] CCTV 방문 세션과 오더퀸 거래 연결
- [ ] 결제 불일치 후보와 관리자 검토 화면 구축
- [ ] 원격 지원 요청과 처리 상태 구축

**완료 기준:** 키오스크 체류와 거래 시각을 기반으로 결제 연결 결과와 근거를 관리자에게 제공한다.

### Phase 6: 반복 사건과 커스텀 학습

- [ ] 매장·구역·시간대별 반복 사건 분석
- [ ] 관리자 피드백 기반 학습 데이터 큐 구축
- [ ] 라벨링·학습·평가·배포 파이프라인 구축
- [ ] 모델 버전별 성능과 롤백 구축
- [ ] 오탐률, 알림 지연, 카메라 연결률 운영 대시보드 구축

**완료 기준:** 반복 행동 패턴을 자동 표시하고 검증된 새 모델을 안전하게 배포·롤백할 수 있다.

## 12. 보안·개인정보·운영 기준

- HTTPS와 저장 데이터 암호화
- 점주별 카메라·오더퀸 세션 분리
- 비밀번호 원문 저장 금지
- 사건 영상과 프레임의 보존기간 설정 및 자동 삭제
- 원본 영상 접근과 다운로드 감사로그
- 결제 상세에서 분석에 필요하지 않은 카드·회원정보 저장 금지
- 카메라 장애, 세션 만료, 동기화 실패 알림
- 사건 생성부터 알림까지 지연시간 측정
- 점주가 카메라·매장 연결을 해제하면 관련 자격증명 즉시 폐기

## 13. MVP 완료 기준

- 점주가 웹과 앱에서 자신의 1개 이상 매장을 확인할 수 있다.
- Autonat 또는 Tapo 카메라에서 이상행동 후보를 수집할 수 있다.
- 냉동고 위 행동과 달리기 사건에 대표 이미지와 AI 요약이 생성된다.
- 관리자가 확인한 사건에 한해 경고방송을 실행할 수 있다.
- 오더퀸에서 매장·상품·거래·취소 데이터를 조회 전용으로 동기화한다.
- 대시보드 진입과 수동 새로고침 정책이 적용된다.
- 상품별 판매속도, 추이, Best/Worst, 품절 영향, 신뢰도를 확인할 수 있다.
- CCTV 방문과 거래 기록의 매칭 결과를 관리자 검토용으로 제공한다.

## 14. Autonat 및 TVT 연동 조사 결과

### 확인된 구조

- Autonat는 독립 CCTV 제조사 서비스가 아니라 여러 OEM DVR/NVR이 공유하는 TVT 계열 P2P/NAT 접속 포털이다.
- 공개 설정 코드에는 NAT 1.0 서버 `c2.autonat.com:40002`와 NAT 2.0 서버 `c2020.autonat.com:7968`이 정의되어 있다.
- 로그인 연결 플러그인은 `127.0.0.1`의 로컬 WebSocket 서비스와 통신한다. 즉 브라우저가 영상을 직접 디코딩하는 구조가 아니다.
- 현재 대상 라이브 페이지는 구형 ActiveX/NPAPI 세대의 웹뷰어다. Edge IE 모드와 전용 ActiveX 플러그인이 필요한 이유가 여기에 있다.
- 웹뷰어 내부 명령은 XML 기반이며 `Initial`, `SetLoginInfo`, `Preview`, `StopPreview`, `TakePhoto`, `TalkSwitch` 등의 기능이 존재한다.
- `queryAlarmStatus` 읽기 명령으로 모션, 침입, 라인 통과, 영상 손실, 장비·채널 오프라인, 발생 시각과 채널을 조회할 수 있다.
- 사이트 UI는 이 알람 상태를 약 30초 간격으로 조회하므로, 영상 전체를 계속 AI에 전달하기 전에 DVR 이벤트를 1차 트리거로 사용할 수 있다.

### 연동 방식 우선순위

1. **매장 내부 엣지 게이트웨이 + RTSP/ONVIF/HTTP CGI**
   - 연속 영상 AI 분석에 가장 안정적이다.
   - 외부 인터넷에 DVR 포트를 열지 않고 매장 LAN 안에서 영상을 가져온다.
2. **`pytvt` + TVT 공식 SDK + AutoNAT/NAT20**
   - 매장 외부에서 시리얼 기반 장비 로그인, 상태, 이벤트, 스냅샷을 조회하는 후보이다.
   - TVT SDK의 `libdvrnetsdk.so`, `libNatClientSDK.so`가 별도로 필요하다.
3. **NVMS 2.0 미디어 브리지**
   - 장비를 시리얼/P2P로 등록하고 NVMS의 영상·알람·양방향 음성 기능을 중계 계층으로 사용한다.
4. **Autonat 플러그인/ActiveX 직접 브리지**
   - 별도 Windows 서비스에서 COM/ActiveX를 호스팅하는 방식이다. Windows·GUI·플러그인 버전에 종속되므로 호환용 후순위다.
5. **Edge IE 모드 + Selenium/IEDriver**
   - 현재 조사 방식으로 유지한다. 운영용 영상 수집이 아니라 로그인·화면·명령 확인 및 비상 접근용이다.

### TVT 직접 연결 후보

```text
RTSP main: rtsp://DVR_IP:554/chID=1&streamType=main&linkType=tcp
RTSP sub:  rtsp://DVR_IP:554/chID=1&streamType=sub&linkType=tcp
HTTP/ONVIF: 80 또는 443
RTSP: 554
TVT SDK/NVMS: 6036/TCP
```

- URL과 포트는 장비 세대·설정에 따라 달라질 수 있으므로 실제 장비에서는 읽기 전용으로 확인한다.
- DVR의 HTTP, RTSP, 6036 포트를 공인 인터넷에 직접 노출하지 않는다. 매장 엣지 게이트웨이 또는 VPN을 사용한다.

### `pytvt` 평가

- 저장소: `https://github.com/dannielperez/pytvt`
- 라이선스: MIT
- 제공 기능: TVT 장비 탐색, 채널 조회, CGI/Web API, 알람 push frame 파싱, 스냅샷, RTSP URL 조회, SDK 기반 AutoNAT 로그인
- AutoNAT는 `NET_SDK_SetNat2Addr`와 `NET_SDK_LoginEx(..., NET_SDK_CONNECT_NAT20, serial)`을 사용한다.
- 프로젝트 기록에는 Linux 컨테이너에서 다수 TVT NVR의 시리얼 기반 NAT20 로그인을 수행한 사례가 있다.
- 공개 구현에는 RTSP URL과 JPEG 캡처가 있지만 P2P 연속 영상의 RealPlay 수신은 완성된 공개 기능으로 확인되지 않았다.
- 따라서 장비 조회·이벤트·스냅샷에는 우선 활용하고, 연속 영상과 양방향 음성은 SuperLive Plus 분석 및 TVT SDK 추가 바인딩으로 보완한다.

### 관련 공개 자료

- Autonat 설정: `https://www.autonat.com/config/index.js`
- Autonat 프로그램 정보: `https://www.autonat.com/config/pgm.js`
- P2P 로컬 WebSocket: `https://www.autonat.com/infst/conn/js/websocket.P2P.js`
- 알람 상태 UI 코드: `https://www.autonat.com/dev/bd/dvr/h265/1_3_8_0/u1a/js/app/AlarmCfg/viewAlarmStatus.js`
- TVT NVMS: `https://en.tvt.net.cn/products/1172.html`
- `pytvt` NAT 조사: `https://github.com/dannielperez/pytvt/blob/main/src/pytvt/sdk/nat_capabilities.md`

## 15. SuperLive Plus APK 분석 계획

### 조사 대상과 이유

```yaml
android_package: com.tvt.superliveplus
play_store: https://play.google.com/store/apps/details?id=com.tvt.superliveplus
developer: TVT (HK) LIMITED
play_store_last_update_observed: 2026-04-02
```

- 이 앱은 TVT 장비의 시리얼/QR 기반 P2P 접속, H.264/H.265 실시간 영상, 녹화 재생, 알람, 스냅샷 및 양방향 음성을 이미 구현한다.
- 목표는 앱 UI를 자동 조작하는 것이 아니라 APK 안의 TVT 네이티브 SDK와 JNI 경계를 찾아 독립 커넥터 구현에 필요한 호출 순서와 데이터 구조를 파악하는 것이다.
- Autonat 웹뷰어에서 부족했던 P2P 연속 영상과 Talk/Broadcast 경로를 찾는 것이 핵심이다.

### 정적 분석 순서

1. 사용자가 정식 설치해 사용 중인 Android 장치를 USB 디버깅으로 연결한다.
2. `adb devices`로 장치 인식만 확인한다.
3. `adb shell pm path com.tvt.superliveplus`로 base 및 split APK 경로를 읽는다.
4. APK 파일을 PC로 복사하고 원본 해시와 버전을 기록한다.
5. JADX와 apktool로 Manifest, Java/Kotlin 코드, 리소스, JNI 호출을 확인한다.
6. `lib/<ABI>/*.so`를 목록화하고 `readelf`, `nm`, `strings`, Ghidra로 네이티브 라이브러리를 분석한다.

우선 검색할 단어:

```text
autonat, autonatglb, NAT20, LoginEx, RealPlay, Preview,
StartLive, StopLive, Talk, Broadcast, Alarm, 6036, 7968,
RTSP, H264, H265, MediaCodec
```

우선 확인할 네이티브 경계:

```text
JNI_OnLoad
RegisterNatives
Java_com_tvt_*
NET_SDK_SetNat2Addr
NET_SDK_LoginEx
NET_SDK_RealPlay 또는 유사 Live/Preview 함수
영상 데이터 콜백
알람 데이터 콜백
Talk/Broadcast 오디오 송신 함수
```

### 동적 분석 순서

- 정적 분석에서 후보 함수를 찾은 뒤 별도 승인 하에 Frida와 Android 실행 로그를 사용한다.
- 로그인 → NAT 서버 선택 → P2P 세션 → 채널 조회 → Live 시작 순서의 함수 인자와 반환값을 추적한다.
- 암호화된 네트워크 패킷부터 해석하기보다 암호화 직전, 복호화 직후, 디코더 입력 직전 데이터를 관찰한다.
- `MediaCodec` 입력 또는 네이티브 영상 콜백에서 H.264/H.265 NAL unit을 확보하면 MediaMTX/FFmpeg로 전달한다.
- 알람 콜백과 Talk 오디오 송신 콜백도 같은 방식으로 분리한다.

### 구현 선택지

1. **Android 네이티브 브리지**: 앱에서 확인한 네이티브 라이브러리를 Android 서비스에서 호출하고 스트림을 재송출한다. 가장 빠른 PoC 후보다.
2. **Android 에뮬레이터 브리지**: 서버의 Android 런타임에서 앱 또는 브리지를 실행한다. 검증은 빠르지만 다중 매장 운영에는 무겁다.
3. **독립 TVT 커넥터**: 앱에서 확인한 호출과 패킷 구조를 `pytvt` 또는 별도 C++/Python 서비스로 구현한다. 운영 서비스의 최종 권장안이다.

### 기술 검증 완료 기준

- 장비 시리얼 기반 P2P 로그인 성공
- 카메라 채널 목록 조회
- 한 채널의 H.264/H.265 압축 프레임 수신
- 알람 이벤트 1건 수신
- Talk/Broadcast 오디오 송신 함수와 지원 채널 확인
- 앱 UI 없이 재연결 및 세션 종료 가능

## 16. 현재 작업 상태와 재개 지점

### 완료된 조사

- 서비스 기능 범위와 멀티테넌트 구조 정리
- YOLO 중심 분석과 GPT 사건 재확인·요약 역할 구분
- 오더퀸 읽기 전용 조회 API와 판매 분석 방향 정리
- Autonat가 TVT P2P 포털임을 공개 코드에서 확인
- Autonat 로컬 플러그인, ActiveX 영상 계층, 알람 조회 명령 확인
- RTSP/ONVIF, `pytvt`, TVT SDK, NVMS 2.0 대안 비교
- SuperLive Plus APK 분석 방향 수립

### 아직 수행하지 않은 작업

- 실제 CCTV 장비의 설정 변경 또는 쓰기 동작
- SuperLive Plus APK 추출·디컴파일
- Frida 동적 후킹
- Android 장치의 ADB 인식 확인
- TVT SDK 확보 및 실행
- P2P 연속 영상 또는 Talk 기능 실장
- 본 서비스 애플리케이션 구현

### 다음 작업

1. 사용자가 Android폰을 USB 데이터 케이블로 연결하고 USB 디버깅을 허용한다.
2. 사용자 승인 후 `adb devices`로 연결 상태만 확인한다.
3. 별도 승인 후 설치된 SuperLive Plus의 base/split APK를 읽기 전용으로 복사한다.
4. 정적 분석 결과로 라이브 영상, 알람, Talk 함수 지도를 작성한다.
5. 정적 분석 결과를 사용자에게 보고한 다음 동적 분석 진행 여부를 결정한다.

### 절대 준수사항

- 문서와 저장소에 로그인 아이디, 비밀번호, 장비 시리얼/QR을 기록하지 않는다.
- 오더퀸은 조회 API만 호출하며 상품·가격·품절·거래를 수정하지 않는다.
- CCTV와 Autonat 장비 설정을 변경하지 않는다.
- 사용자의 명시적 승인 없이 APK 추출, 동적 후킹, 실제 장비 접속 시험을 진행하지 않는다.

## 17. Tapo 카메라 연동 조사 결과

### 지정된 네이버 글의 방식

- 대상 글: `https://blog.naver.com/jiyh78/223634852134`
- 글의 예제 모델: Tapo C211
- 선행 설정: Tapo 앱의 `고급 설정 → 카메라 계정`에서 RTSP/ONVIF용 별도 아이디와 비밀번호 생성
- 입력 영상: `rtsp://CAMERA_USER:CAMERA_PASSWORD@CAMERA_IP:554/stream2`
- Python OpenCV의 `cv2.VideoCapture`로 RTSP 영상을 디코딩
- 각 프레임을 `cv2.imencode('.jpg', frame)`으로 JPEG 변환
- Flask가 `/video_feed`에서 `multipart/x-mixed-replace` 형식의 MJPEG로 응답
- 웹페이지는 `<img>` 태그로 해당 MJPEG 주소를 표시

### 적용 가능성 판단

**가능하다.** 특히 Tapo C211처럼 상시 전원형이고 RTSP를 지원하는 모델이라면 같은 구조로 영상을 가져와 YOLO 입력 프레임을 만들 수 있다.

다만 글의 구현은 실험용으로 적합하며 운영 서비스에서는 그대로 사용하지 않는다.

- 모든 프레임을 JPEG로 다시 압축하므로 CPU와 네트워크 사용량이 커진다.
- MJPEG에는 오디오가 없고 H.264/H.265보다 압축 효율이 낮다.
- 예제 구조는 웹 시청자마다 새 `VideoCapture`를 만들 수 있어 Tapo의 동시 스트림 한도를 빠르게 소비한다.
- 연결 끊김, 재접속, 버퍼 누적, 오래된 프레임 제거, 다중 시청자 fan-out 처리가 없다.
- 코드의 실행 포트는 8000인데 본문 일부 접근 예시는 8080으로 표기가 섞여 있다.
- 카메라 계정이 코드와 RTSP URL에 직접 포함되므로 실제 구현에서는 암호화된 설정과 비밀 주입 방식을 사용한다.

따라서 역할을 다음처럼 제한한다.

```yaml
good_for:
  - 최초_RTSP_연결_PoC
  - YOLO용_프레임_샘플링
  - 로컬_디버그_화면
not_for:
  - 다수_사용자_웹_실시간_영상
  - 웹_및_앱_오디오
  - 양방향_경고방송
  - 다중_매장_운영_중계
```

### 2026년 공식 RTSP/ONVIF 상태

- TP-Link의 2026년 7월 공식 가이드 기준 대부분의 상시 전원형 Tapo 카메라는 RTSP와 ONVIF Profile S를 지원한다.
- Tapo C211 최신 데이터시트도 RTSP와 ONVIF Profile S 지원을 명시한다.
- Tapo 앱 로그인 계정과 별도로 `카메라 계정`을 생성해야 한다.
- RTSP 포트는 554, ONVIF 서비스 포트는 2020이다.

```text
고화질: rtsp://CAMERA_USER:CAMERA_PASSWORD@CAMERA_IP:554/stream1
저화질: rtsp://CAMERA_USER:CAMERA_PASSWORD@CAMERA_IP:554/stream2
```

- 듀얼 렌즈 일부 모델은 두 번째 렌즈에 `/stream6`, `/stream7`을 사용한다.
- ONVIF Profile S로 영상·카메라 오디오, 이벤트, 네트워크 정보와 PTZ를 사용할 수 있지만 양방향 오디오는 지원하지 않는다.
- 배터리형 카메라 대부분은 RTSP를 지원하지 않는다. 일부 유선 상시 전원 도어벨만 예외이므로 모델·하드웨어 버전을 반드시 구분한다.
- Tapo Care, SD 카드 녹화, NVR/NAS/ONVIF 녹화는 세 가지를 모두 동시에 사용할 수 없고 두 가지만 함께 사용할 수 있다.
- 모델에 따라 동시 메인·서브 스트림 수가 제한되므로 엣지 중계기가 카메라 연결을 하나로 유지하고 여러 소비자에게 재배포해야 한다.

### 최신 권장 구성

```text
Tapo Camera
├─ RTSP stream1 ── 고화질 증거 클립·관리자 라이브뷰
├─ RTSP stream2 ── YOLO 실시간 분석
├─ ONVIF :2020 ── 모션 이벤트·PTZ·상태
└─ Tapo proprietary talk channel ── 경고방송
             │
             ▼
      Store Edge go2rtc
      ├─ 단일 카메라 연결 및 fan-out
      ├─ WebRTC → 웹·앱 저지연 라이브
      ├─ local RTSP → video-worker/FFmpeg/YOLO
      ├─ snapshot/MP4/HLS 필요 시 변환
      └─ PCMA 오디오/TTS → 카메라 스피커
```

### `go2rtc` 활용

- 저장소: `https://github.com/AlexxIT/go2rtc`
- 라이선스: MIT
- 일반 RTSP 입력뿐 아니라 Tapo 전용 `tapo://` 소스를 지원한다.
- Tapo 전용 프로토콜은 양방향 오디오를 지원하며 최신 펌웨어에 따라 cloud password의 MD5 또는 SHA-256 해시 방식이 사용될 수 있다.
- 웹·앱에는 WebRTC, 내부 AI worker에는 go2rtc가 다시 제공하는 로컬 RTSP를 사용한다.
- `POST /api/ffmpeg` 또는 stream-to-camera API로 TTS/오디오 파일을 카메라가 지원하는 PCMA 형식으로 변환해 전송할 수 있다.
- 하나의 경고방송 세션이 끝나면 backchannel 소비자를 확실히 종료해야 한다. 일부 모델에서는 세션이 남으면 공식 Tapo 앱에 `Line is busy`가 표시될 수 있다.
- go2rtc API와 WebUI는 외부에 직접 공개하지 않고 엣지 내부 또는 우리 백엔드 뒤에 둔다.

개념 구성 예시이며 실제 자격증명은 파일에 직접 기록하지 않는다.

```yaml
streams:
  store_camera_main:
    - rtsp://CAMERA_SECRET@CAMERA_IP:554/stream1
    - tapo://TAPO_SECRET@CAMERA_IP
  store_camera_sub:
    - rtsp://CAMERA_SECRET@CAMERA_IP:554/stream2
```

### 기타 오픈소스 후보

| 후보 | 활용 범위 | 판단 |
|---|---|---|
| `pytapo` | 로컬 장비 정보, 설정 조회, 녹화 검색·다운로드, 전용 8800 스트림 | Tapo 전용 어댑터 구현의 주요 참고 후보 |
| `HomeAssistant-Tapo-Control` | RTSP/전용 스트림, 모션 센서, 녹화, PTZ 등 폭넓은 구현 | 소스 참고와 모델 호환성 조사에 유용 |
| `mihai-dinculescu/tapo` | Rust/Python API, 일부 카메라의 RTSP URL·스냅샷·PTZ | 타입이 명확한 조회용 보조 후보 |
| `MediaMTX` | RTSP를 WebRTC/HLS/녹화로 중계 | 양방향 Tapo 오디오가 필요 없을 때 대안 |
| Flask + OpenCV MJPEG | 빠른 로컬 화면과 프레임 디버그 | 운영 중계가 아닌 개발 도구로 한정 |

`HomeAssistant-Tapo-Control`과 `pytapo`의 전체 테스트는 카메라 이동, 설정 변경, 재부팅 같은 동작을 포함할 수 있으므로 사용자 카메라에서 실행하지 않는다. 필요한 읽기 함수만 선택한다.

### 서비스 적용 결론

1. Tapo의 영상은 SuperLive Plus처럼 앱을 역분석할 필요 없이 RTSP로 직접 확보할 가능성이 높다.
2. YOLO 분석은 `/stream2`, 증거 클립과 관리자 확인은 `/stream1`을 기본으로 한다.
3. 웹·앱 실시간 영상은 블로그의 MJPEG 대신 go2rtc WebRTC를 사용한다.
4. 모션 이벤트는 ONVIF PullPoint 또는 Tapo 전용 이벤트를 1차 트리거로 사용한다.
5. 카메라 스피커 경고방송은 ONVIF가 아니라 go2rtc의 Tapo 전용 양방향 오디오 경로를 사용한다.
6. 매장마다 엣지 게이트웨이를 두고 카메라에는 로컬로 연결하며 중앙 서버로는 필요한 스트림과 사건 데이터만 전달한다.

### 실제 장비 확인 전에 필요한 정보

- Tapo 정확한 모델명
- 하드웨어 버전
- 현재 펌웨어 버전
- 상시 전원형 또는 배터리형 여부
- Tapo Care 사용 여부
- SD 카드 녹화 사용 여부
- 카메라 스피커와 양방향 음성 지원 여부

### 조사 자료

- 지정 블로그: `https://blog.naver.com/jiyh78/223634852134`
- TP-Link 2026 RTSP/ONVIF 가이드: `https://www.tp-link.com/kr/support/faq/2680/`
- TP-Link 2026 RTSP/ONVIF FAQ: `https://www.vigi.com/kr/support/faq/4465/`
- Tapo C211 데이터시트: `https://static.tp-link.com/upload/product-overview/2026/202605/20260514/Tapo%20C211%203.0%263.6_Datasheet.pdf`
- go2rtc Tapo 문서: `https://github.com/AlexxIT/go2rtc/blob/master/internal/tapo/README.md`
- go2rtc 오디오 전송: `https://github.com/AlexxIT/go2rtc/blob/master/internal/streams/README.md`
- PyTapo: `https://github.com/JurajNyiri/pytapo`
- Home Assistant Tapo Control: `https://github.com/JurajNyiri/HomeAssistant-Tapo-Control`
- Tapo Rust/Python API: `https://github.com/mihai-dinculescu/tapo`

## 18. GitHub 저장소 및 작업 인수인계

### 연결 상태

```yaml
local_repository: D:\project\wisdom-super-observer
local_branch: main
remote_name: origin
remote_url: https://github.com/himangga01/wisdom-super-observer.git
github_account: himangga01
git_protocol: https
remote_state_at_2026_08_21: empty_repository
commit_created: false
push_executed: false
```

- 2026년 8월 21일 현재 로컬 폴더를 Git 저장소로 초기화하고 `main` 브랜치를 생성했다.
- GitHub CLI는 `himangga01` 계정으로 인증되어 있으며 Git의 GitHub 인증 도우미 연결을 설정했다.
- 원격 `origin`은 `https://github.com/himangga01/wisdom-super-observer.git`이다.
- 원격 저장소는 연결 당시 커밋과 파일이 없는 빈 저장소였다.
- 이번 작업에서는 커밋과 푸시를 실행하지 않았다. 사용자가 이후 명시적으로 요청할 때 변경 파일을 확인하고 선택적으로 스테이징한다.

### 최초 커밋·푸시 예정 절차

```powershell
git status --short
git diff -- SERVICE_PLAN.md
git add -- SERVICE_PLAN.md
git commit -m "docs: add integrated service plan"
git push -u origin main
```

- 다른 파일이 추가된 경우 `git add .`를 사용하지 않고 사용자가 승인한 파일 경로만 `git add -- <path>`로 추가한다.
- 최초 푸시 이후에는 작업 단위별 기능 브랜치와 의도적인 커밋을 사용한다.
- 자격증명, 카메라 시리얼, 캡처 원본, APK, 네이티브 SDK 바이너리는 검토 없이 저장소에 추가하지 않는다.

### 새 대화에서 작업을 재개하는 방법

1. 작업 디렉터리를 `D:\project\wisdom-super-observer`로 연다.
2. 이 `SERVICE_PLAN.md`의 한국어 영역을 먼저 읽고, 세부 인터페이스가 필요하면 하단 AI Implementation Context를 읽는다.
3. `git status --short`와 `git remote -v`로 현재 상태를 확인한다.
4. `16. 현재 작업 상태와 재개 지점`에서 완료·미완료 항목을 확인한다.
5. 다음 외부 장치 또는 계정 작업은 사용자 승인을 받은 뒤 진행한다.

---

# AI Implementation Context (English)

## Product Definition

```yaml
product_name: Wisdom Super Observer
product_type: Multi-tenant unmanned-store monitoring and analytics platform
workspace: D:\project\wisdom-super-observer
repository: https://github.com/himangga01/wisdom-super-observer.git
current_stage: pre-implementation_integration_research
current_next_focus: connect_Android_device_then_inspect_SuperLive_Plus_APK_and_identify_Tapo_models
primary_users:
  - Single-store owners
  - Multi-store owners
  - Store managers and staff
clients:
  - Responsive web dashboard
  - Mobile application with push notifications
core_domains:
  - CCTV event monitoring
  - Behavior detection
  - Human-reviewed alerts and warning broadcasts
  - OrderQueen sales synchronization
  - Product sales analytics
  - CCTV visit and payment matching
```

## Confirmed Functional Requirements

```yaml
behavior_events:
  - person_sitting_or_climbing_on_freezer
  - person_running_inside_store
  - customer_waving_at_camera_for_help
  - repeated_kiosk_payment_attempts
  - kiosk_payment_error
incident_features:
  - representative_frames
  - short_evidence_clip
  - GPT_incident_summary
  - web_and_mobile_notifications
  - human_confirmed_warning_broadcast
operations:
  - visual_zone_rule_builder
  - behavior_duration_conditions
  - staff_visit_mode
  - repeated_incident_pattern_detection
sales_dashboard:
  - dynamic_store_discovery
  - single_or_multiple_store_support
  - quantity_revenue_velocity_and_trends
  - best_worst_rising_falling_products
  - stockout_aware_zero_sales_analysis
  - confidence_score
```

## Architecture Boundaries

```yaml
camera_adapters:
  autonat:
    authentication: owner-authorized web login session
    preferred_trigger: existing camera detection events
  tapo:
    preferred_transport: RTSP_or_ONVIF
    fallback: in-store edge gateway
vision_pipeline:
  primary_detector: YOLO
  tracking: ByteTrack_or_BoT_SORT
  rule_inputs:
    - bounding_boxes
    - pose_keypoints
    - zone_membership
    - duration
    - motion_velocity
llm_pipeline:
  provider: GPT_only_for_initial_plan
  invocation: event_candidates_only
  responsibilities:
    - semantic_confirmation
    - structured_incident_summary
    - warning_message_draft
  prohibited_use:
    - continuous_full_video_streaming
    - autonomous_crime_determination
```

## OrderQueen Integration Contract

```yaml
authentication: isolated_owner_web_session
api_type: undocumented_internal_web_API
access_policy: strict_read_only_allowlist
response_formats:
  list: text_html_fragment
  chart_and_lookup: application_json
sync_policy:
  initial_connection: historical_backfill_per_store_month_and_page
  dashboard_entry: one_sync
  dashboard_open: no_recurring_polling
  manual_refresh: one_sync
  reentry: one_sync
incremental_strategy:
  native_updated_since: false
  method: requery_recent_window_and_upsert
forbidden_operations:
  - SAVE
  - DELETE
  - CANCEL
  - UPDATE
  - RESET
  - UPLOAD
  - PRICE_SAVE
  - SOLDOUT_SEND
```

## Core Read-Only Endpoints

```yaml
store_discovery: BAS01020_STORE_LST.itp
monthly_sales:
  - SAL02020_LIST.itp
  - SAL02020_CHART.itp
daily_sales:
  - SAL02010_LIST.itp
  - SAL02010_CHART.itp
product_sales:
  - SAL03020_LIST.itp
  - SAL03020_CHART.itp
barcode_sales:
  - SAL03070_LIST.itp
  - SAL03070_CHART.itp
category_sales:
  - SAL03080_LIST.itp
  - SAL03080_CHART.itp
transactions:
  - SAL01020_LIST.itp
  - SAL01020_POPUP.itp
  - SAL01020_PAYMENT.itp
cancellations: SAL01060_LIST.itp
card_approvals: SAL01030_LIST.itp
product_catalog: MNU01020_LST.itp
price_and_soldout_read: MNU01050_LST.itp
pos_lookup: SYS02010_POSLIST.itp
```

## Sales Analytics Model

```yaml
dimensions:
  sales_power: quantity_and_active_sales_days
  revenue_contribution: product_revenue_share
  velocity: per_calendar_day_and_per_sales_day
  momentum: smoothed_recent_vs_previous_period
  intermittency:
    metrics: [ADI, CV_squared]
    classes: [smooth, erratic, intermittent, lumpy]
  stockout_effect: separate_zero_demand_from_unavailable_inventory
  confidence:
    factors:
      - observation_days
      - transaction_count
      - missing_data
      - stockout_days
output_labels:
  - bestseller
  - stable
  - rising
  - falling
  - low_seller
  - intermittent
  - stockout_affected
  - insufficient_data
```

## Visit-to-Payment Matching

```yaml
inputs:
  - store_id
  - camera_track_timestamps
  - entrance_zone_events
  - kiosk_zone_dwell
  - OrderQueen_transaction_time
  - POS_id
  - cancellation_state
outputs:
  - PAID_CONFIRMED
  - PAID_LIKELY
  - REVIEW_REQUIRED
  - NO_MATCH_CANDIDATE
  - PAYMENT_ERROR
  - CANCELLED_TRANSACTION
policy: Evidence_assistance_only_with_human_review
```

## Delivery Sequence

```yaml
phases:
  - id: 0
    name: integration_spikes
    deliverable: validated_camera_OrderQueen_GPT_and_broadcast_interfaces
  - id: 1
    name: multi_tenant_foundation
    deliverable: isolated_owner_store_and_role_management
  - id: 2
    name: CCTV_behavior_MVP
    deliverable: YOLO_tracking_rules_evidence_and_web_alerts
  - id: 3
    name: GPT_mobile_and_broadcast
    deliverable: summaries_push_notifications_and_human_confirmed_audio
  - id: 4
    name: OrderQueen_sales_dashboard
    deliverable: dynamic_multi_store_backfill_sync_and_product_analytics
  - id: 5
    name: help_and_payment_matching
    deliverable: wave_kiosk_difficulty_and_visit_transaction_matching
  - id: 6
    name: repeated_patterns_and_custom_training
    deliverable: feedback_dataset_model_lifecycle_and_operations_metrics
```

## Non-Negotiable Safety Rules

```yaml
rules:
  - Never_call_OrderQueen_mutation_endpoints
  - Never_store_plaintext_credentials
  - Never_expose_one_tenants_data_to_another
  - Never_auto_broadcast_without_owner_confirmation_by_default
  - Never_treat_AI_output_as_final_criminal_judgment
  - Minimize_payment_and_CCTV_personal_data
  - Record_access_and_operator_actions_in_audit_logs
```

## TVT / Autonat Integration Research

```yaml
autonat:
  identity: TVT_OEM_P2P_NAT_portal
  current_web_client: legacy_H265_1_3_8_0_u1a_ActiveX_viewer
  nat_endpoints_observed_in_public_config:
    nat_1: c2.autonat.com:40002
    nat_2: c2020.autonat.com:7968
  browser_connector:
    transport: localhost_WebSocket_then_native_plugin
    localhost_port_observed: 11853
  private_command_format: XML_wrapped_NVMS_NAT_CMD
  useful_read_command: queryAlarmStatus
  alarm_types:
    - motion
    - intrusion
    - line_crossing
    - video_loss
    - channel_offline
    - device_offline
  production_priority:
    - store_edge_RTSP_ONVIF_HTTP_CGI
    - pytvt_plus_vendor_TVT_SDK_AutoNAT
    - NVMS_2_media_bridge
    - native_ActiveX_COM_bridge
    - Selenium_IEDriver_research_fallback
```

## PyTVT Assessment

```yaml
repository: https://github.com/dannielperez/pytvt
license: MIT
usable_features:
  - TVT_device_discovery
  - channel_inventory
  - NVR_CGI_and_Web_API
  - alarm_frame_parsing
  - snapshots
  - RTSP_URL_resolution
  - SDK_backed_AutoNAT_login
vendor_runtime_required_for_P2P:
  - libdvrnetsdk.so
  - libNatClientSDK.so
important_calls:
  - NET_SDK_SetNat2Addr
  - NET_SDK_LoginEx_with_NET_SDK_CONNECT_NAT20
known_gap: no_confirmed_complete_public_P2P_continuous_RealPlay_receiver
recommended_role: device_metadata_alarm_snapshot_and_AutoNAT_accelerator
```

## SuperLive Plus Reverse-Engineering Brief

```yaml
target:
  package: com.tvt.superliveplus
  developer: TVT_HK_LIMITED
  purpose: discover_TVT_P2P_live_alarm_playback_and_talk_integration
  non_goal: production_UI_automation
acquisition:
  source: user_installed_Android_device
  expected_artifacts:
    - base.apk
    - split_config_ABI.apk
    - other_split_APKs
static_tools:
  - adb
  - jadx
  - apktool
  - readelf
  - nm
  - strings
  - Ghidra
dynamic_tools_after_separate_approval:
  - Frida
  - adb_logcat
focus_boundaries:
  - JNI_OnLoad_and_RegisterNatives
  - AutoNAT_server_selection
  - P2P_login
  - channel_inventory
  - RealPlay_or_Preview_start_stop
  - compressed_video_callback
  - MediaCodec_input
  - alarm_callback
  - Talk_or_Broadcast_audio_send
preferred_result:
  - documented_call_graph
  - documented_data_structures
  - one_H264_or_H265_frame_without_UI
  - reusable_connector_contract
implementation_options:
  fastest_POC: Android_native_sidecar
  compatibility_fallback: Android_emulator_bridge
  production_target: independent_TVT_connector_extending_pytvt_or_vendor_SDK
```

## Resume Checklist

```yaml
completed:
  - product_scope_and_multi_tenant_requirements
  - YOLO_plus_GPT_responsibility_split
  - OrderQueen_read_only_dashboard_plan
  - public_Autonat_architecture_research
  - SuperLive_Plus_analysis_strategy
not_started:
  - adb_device_detection
  - APK_extraction
  - static_APK_analysis
  - dynamic_instrumentation
  - TVT_SDK_execution
  - production_application_implementation
next_actions_requiring_user_approval:
  - run_adb_devices
  - pull_installed_base_and_split_APKs
  - perform_dynamic_Frida_tracing
secrets_policy: never_write_credentials_or_device_identifiers_to_repository_docs
external_mutation_policy: read_only_only
```

## Tapo Integration Research

```yaml
linked_blog_method:
  reference: https://blog.naver.com/jiyh78/223634852134
  demonstrated_model: Tapo_C211
  input: rtsp_stream2
  decoder: OpenCV_VideoCapture
  browser_transport: Flask_multipart_MJPEG
  verdict: valid_for_POC_and_AI_frame_sampling_only
  production_gaps:
    - per_frame_JPEG_CPU_and_bandwidth_cost
    - no_audio
    - no_shared_fanout
    - no_reconnect_or_stale_frame_handling
    - consumes_camera_stream_slots_per_viewer
official_2026_interface:
  powered_models: most_support_RTSP_and_ONVIF_Profile_S
  rtsp_port: 554
  onvif_port: 2020
  main_stream: /stream1
  sub_stream: /stream2
  dual_lens_secondary_streams: [/stream6, /stream7]
  credentials: separate_camera_account_created_in_Tapo_app
  onvif_capabilities:
    - media
    - camera_audio
    - events
    - PTZ
  onvif_missing: two_way_audio
  battery_models: generally_no_RTSP_except_specific_hardwired_always_on_devices
  resource_constraint: only_two_of_Tapo_Care_SD_recording_NVR_ONVIF_recording
recommended_edge_stack:
  ingest_and_fanout: go2rtc
  AI_input: restreamed_RTSP_substream
  evidence_and_live: RTSP_mainstream
  web_mobile_live: WebRTC
  event_trigger: ONVIF_PullPoint_or_Tapo_local_event
  warning_broadcast: go2rtc_tapo_proprietary_backchannel_with_PCMA_TTS
  cloud_connectivity: outbound_store_edge_tunnel_or_VPN
open_source_roles:
  go2rtc: RTSP_fanout_WebRTC_Tapo_two_way_audio_and_TTS
  pytapo: local_control_recordings_and_proprietary_port_8800_reference
  HomeAssistant_Tapo_Control: compatibility_and_event_implementation_reference
  mihai_dinculescu_tapo: typed_Rust_Python_snapshot_RTSP_URL_and_PTZ_helper
  MediaMTX: generic_stream_router_when_Tapo_talkback_is_not_required
  Flask_OpenCV_MJPEG: debug_only
device_validation_inputs_required:
  - exact_model
  - hardware_revision
  - firmware_version
  - powered_or_battery
  - Tapo_Care_state
  - SD_recording_state
  - speaker_and_two_way_audio_capability
prohibited_live_test:
  - never_run_full_pytapo_or_HomeAssistant_Tapo_Control_test_suites_on_user_camera
  - never_change_camera_configuration_without_explicit_user_approval
```

## Git Repository Handoff

```yaml
git:
  worktree: D:\project\wisdom-super-observer
  branch: main
  remote:
    name: origin
    url: https://github.com/himangga01/wisdom-super-observer.git
  github_cli_account: himangga01
  authentication: configured_https_via_gh
  remote_was_empty_when_connected: true
  initial_commit_created: false
  initial_push_executed: false
initial_publish_scope:
  include:
    - SERVICE_PLAN.md
  exclude_until_explicit_review:
    - credentials
    - device_serials_or_QR_values
    - raw_CCTV_media
    - extracted_APKs
    - proprietary_TVT_SDK_binaries
suggested_initial_commit: "docs: add integrated service plan"
resume_sequence:
  - read_SERVICE_PLAN_Korean_section
  - inspect_git_status_and_remote
  - check_section_16_current_state
  - obtain_user_approval_before_external_device_or_account_actions
```
