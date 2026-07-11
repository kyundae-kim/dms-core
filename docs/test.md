# 테스트 정의서

## 1. 문서 목적

본 문서는 DMS SDK의 테스트 목표, 범위, 분류, 실행 기준, 환경 조건을 정의합니다.

## 2. 테스트 목표

DMS SDK 테스트는 다음 목표를 가집니다.
- 문서 등록, 조회, 삭제의 핵심 생명주기를 지속적으로 검증한다.
- 문서 본문 저장소와 문서 정보 저장소의 정합성 규칙을 검증한다.
- 환경 기반 초기화와 명시적 의존성 주입 두 가지 조립 방식을 검증한다.
- 상태 점검, 로그, 오류 매핑 등 운영 관점 동작을 검증한다.
- 준비되지 않은 외부 환경 때문에 전체 검증이 불필요하게 실패하지 않도록 한다.

## 3. 테스트 범위

### 3.1 포함 범위
- `create_sdk_from_environment(...)`
- `create_sdk_from_components(...)`
- 문서 업로드
- 문서 메타데이터 조회
- 문서 본문 전체 조회
- 문서 본문 스트리밍 조회
- 논리 삭제
- 완전 삭제
- 상태 점검
- 오류 매핑
- 구조화 로그
- PostgreSQL/SQLite metadata 저장소
- MinIO object 저장소
- 실제 외부 서비스와의 통합 경로
- `.env.example` 필수 항목 포함 여부

### 3.2 제외 범위
- 인증 기능
- 외부 공유용 임시 접근 링크
- 문서 검색 및 필터링
- 문서 버전 관리
- 비동기 후처리 연계
- 멀티테넌시
- 권한 모델 자체 구현

## 4. 테스트 수준 정의

### 4.1 단위 테스트

관련 테스트 파일:
- `test_dms/test_sdk_behavior.py`

주요 검증 대상:
- 업로드 성공 경로
- 스트리밍 조회 동작
- 청크 크기 검증
- 중복 문서 식별자 처리
- 파일명 정규화 및 저장 경로 생성
- 메타데이터 저장 실패 시 정리 동작
- 논리 삭제/완전 삭제 상태 처리
- 저장소 실패 시 상태 전이
- 메타데이터/본문 불일치 시 일관성 오류
- 문서 없음 오류
- 메타데이터 저장소 오류 매핑
- 상태 점검 결과 집계
- 종료 콜백 호출
- 구조화 로그 기록
- root export와 실제 타입 identity

### 4.2 어댑터 테스트

관련 테스트 파일:
- `test_dms/test_infrastructure_adapters.py`

주요 검증 대상:
- PostgreSQL metadata 저장소 round-trip
- metadata 테이블 인덱스 생성
- MinIO object 저장소 round-trip
- MinIO object 스트리밍 round-trip
- PostgreSQL + MinIO 조합으로 SDK 생성
- SQLite + MinIO 조합으로 SDK 생성
- 환경 매핑 기반 생성 함수 동작
- 시작 단계 상태 점검 실패 처리
- `.env.example` 필수 설정 포함 여부

### 4.3 통합 테스트

관련 테스트 파일:
- `test_dms/test_integration_adapters.py`

주요 검증 대상:
- 실제 PostgreSQL metadata 저장소 동작
- 실제 MinIO object 저장소 동작
- 실제 환경 변수 기반 SDK 생성
- 실제 업로드/조회/삭제 흐름
- 실제 상태 점검 흐름
- 실제 논리 삭제/완전 삭제 흐름

## 5. 테스트 실행 기준

### 5.1 필수 환경 변수
- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

### 5.2 선택 환경 변수
- `MINIO_SECURE`
- `DOCMESH_ENV`
- `DOCMESH_HEALTHCHECK_ENABLED`
- `MILVUS_URI`
- `OLLAMA_HOST`
- `LANGFUSE_HOST`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `NATS_SERVERS`

주의:
- 선택 항목 중 일부는 DMS SDK 기능 자체가 아니라 공통 설정 로더 검증 때문에 필요할 수 있습니다.

### 5.3 건너뛰기 규칙
- 필수 환경 변수가 하나라도 없는 경우 통합 테스트를 건너뜁니다.
- PostgreSQL 드라이버가 설치되어 있지 않은 경우 통합 테스트를 건너뜁니다.
- 외부 서비스를 자동 생성하지 않고 이미 준비된 서비스를 재사용합니다.

## 6. 테스트 실행 방법

### 6.1 전체 테스트 실행

```bash
uv run pytest test_dms -q
```

### 6.2 파일 단위 실행

```bash
uv run pytest test_dms/test_sdk_behavior.py -q
uv run pytest test_dms/test_infrastructure_adapters.py -q
uv run pytest test_dms/test_integration_adapters.py -q
```

## 7. 승인 기준

다음을 만족하면 테스트 기준을 충족한 것으로 봅니다.
- 핵심 문서 생명주기 테스트가 자동화되어 있다.
- 상태 점검 경로가 자동화되어 있다.
- 저장소 어댑터 round-trip 테스트가 존재한다.
- 환경 기반 조립과 명시적 의존성 주입 경로가 모두 검증된다.
- 실제 외부 서비스 재사용 통합 테스트가 준비되어 있다.
- 외부 환경 미준비 시 skip 정책이 적용된다.
- `.env.example` 필수 항목 검증이 포함된다.

## 8. 현재 확인 기준

문서 갱신 시점에는 다음 명령으로 현재 코드 기준 테스트 상태를 확인합니다.

```bash
uv run pytest test_dms -q
```

통합 테스트는 필수 외부 서비스 환경 변수가 없으면 skip 될 수 있으므로, 결과 해석 시 실행 환경의 서비스 준비 상태를 함께 확인해야 합니다.
