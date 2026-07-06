# 설정 정의서

## 1. 문서 목적

본 문서는 DMS SDK를 환경 기반으로 조립할 때 필요한 설정 항목과 동작 기준을 정의합니다.
이 문서는 다음에 답합니다.
- 어떤 환경 변수가 필요한가
- 어떤 저장소 구성이 지원되는가
- 어떤 경우에 SDK 생성이 실패하는가
- 상태 점검 설정은 어떻게 동작하는가

관련 문서:
- `docs/prd.md`
- `docs/srs.md`
- `docs/api.md`
- `docs/examples.md`

## 2. 설정 방식 개요

DMS SDK는 두 가지 방식으로 생성할 수 있습니다.

1. 환경 기반 조립
- 환경 변수 매핑을 전달하면 SDK가 필요한 저장소를 조립합니다.
- 주요 진입점은 `create_sdk(env, logger=...)` 또는 `create_sdk_from_environment(env, logger=...)` 입니다.

2. 명시적 의존성 주입
- 애플리케이션이 저장소를 직접 준비해 SDK에 전달합니다.
- 이 경우 환경 변수 기반 설정은 필수가 아닙니다.

이 문서는 주로 환경 기반 조립에 필요한 설정을 설명합니다.

## 3. 설정 계층 구조

환경 기반 조립 시 SDK는 다음 범주의 설정을 사용합니다.

- 공통 설정
  - 실행 환경 이름
  - 시작 단계 상태 점검 활성화 여부
- 문서 본문 저장소 설정
  - MinIO 연결 정보
- 문서 정보 저장소 설정
  - PostgreSQL 또는 SQLite 연결 정보

## 4. 필수 설정과 선택 설정

### 4.1 항상 필요한 설정

환경 기반으로 SDK를 생성할 때 다음 범주는 반드시 유효해야 합니다.

- 문서 본문 저장소 설정
- 문서 정보 저장소 설정
  - PostgreSQL 또는 SQLite 중 하나
- 공통 설정 체계를 읽을 수 있는 런타임 의존성

### 4.2 조건부 설정

다음 설정은 특정 상황에서만 필요합니다.

- PostgreSQL 설정
  - 운영 환경용 저장소를 사용할 경우 필요
- SQLite 설정
  - 로컬/테스트용 저장소를 사용할 경우 필요

## 5. 설정 선택 규칙

### 5.1 문서 정보 저장소 선택

SDK는 문서 정보 저장소를 다음 우선순위로 선택합니다.

1. `POSTGRES_` 접두사의 설정이 존재하면 PostgreSQL 사용
2. 그렇지 않고 `SQLITE_PATH`가 존재하면 SQLite 사용
3. 둘 다 없으면 SDK 생성 실패

즉, PostgreSQL과 SQLite가 동시에 존재하면 PostgreSQL이 우선합니다.

### 5.2 시작 단계 상태 점검

공통 설정의 상태 점검 플래그가 활성화되면 SDK 생성 시점에 상태 점검을 수행합니다.
기본 동작은 활성화입니다.

상태 점검 대상:
- 선택된 문서 정보 저장소
- 문서 본문 저장소

## 6. 환경 변수 정의

### 6.1 공통 설정

#### `DOCMESH_ENV`
- 설명: 실행 환경 이름
- 필수 여부: 선택
- 예시: `local`, `dev`, `test`, `integration`, `prod`
- 비고: 공통 설정 체계에서 환경 구분에 사용됩니다.

#### `DOCMESH_HEALTHCHECK_ENABLED`
- 설명: 시작 단계 상태 점검 활성화 여부
- 필수 여부: 선택
- 기본값: `true`
- 예시: `true`, `false`
- 비고: 활성화 시 SDK 생성 과정에서 필수 서비스 상태를 점검합니다.

### 6.2 문서 본문 저장소 설정

다음 설정은 MinIO 기반 문서 본문 저장소 조립에 사용됩니다.

#### `MINIO_ENDPOINT`
- 설명: MinIO 서버 주소
- 필수 여부: 예
- 예시: `localhost:9000`

#### `MINIO_ACCESS_KEY`
- 설명: MinIO 접근 키
- 필수 여부: 예

#### `MINIO_SECRET_KEY`
- 설명: MinIO 비밀 키
- 필수 여부: 예

#### `MINIO_BUCKET`
- 설명: 문서 본문을 저장할 bucket 이름
- 필수 여부: 예
- 비고: 값이 없으면 SDK 생성이 실패합니다.

#### `MINIO_SECURE`
- 설명: TLS 사용 여부
- 필수 여부: 선택
- 기본값 예시: `false`
- 예시: `true`, `false`

### 6.3 PostgreSQL 설정

다음 설정 중 하나라도 존재하면 SDK는 PostgreSQL 사용을 우선 시도합니다.

#### `POSTGRES_DSN`
- 설명: PostgreSQL 연결 문자열
- 필수 여부: PostgreSQL 사용 시 사실상 필수
- 예시: `postgresql+psycopg2://user:password@localhost:5432/dms`

추가로 공통 설정 체계가 요구하는 다른 `POSTGRES_` 접두사 항목이 필요할 수 있습니다.
실제 필요한 상세 항목은 공통 설정 체계와 런타임 구성에 따라 달라질 수 있습니다.

### 6.4 SQLite 설정

#### `SQLITE_PATH`
- 설명: SQLite 데이터베이스 파일 경로
- 필수 여부: SQLite 사용 시 예
- 예시: `/tmp/dms.db`
- 비고: PostgreSQL 설정이 없을 때 로컬/테스트용 대체 저장소로 사용됩니다.

## 7. 권장 설정 조합

### 7.1 로컬 개발 환경

권장 목적:
- 빠른 개발 시작
- 외부 의존성 최소화

권장 조합:
- 문서 본문 저장소: MinIO
- 문서 정보 저장소: SQLite
- 시작 단계 상태 점검: 필요에 따라 선택

예시:

```env
DOCMESH_ENV=local
DOCMESH_HEALTHCHECK_ENABLED=false
SQLITE_PATH=/tmp/dms.db
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=dms-documents
```

### 7.2 통합/검증 환경

권장 목적:
- 실제 저장소와의 연결 검증
- 시작 단계 상태 점검 포함 검증

권장 조합:
- 문서 본문 저장소: MinIO
- 문서 정보 저장소: PostgreSQL
- 시작 단계 상태 점검: 활성

예시:

```env
DOCMESH_ENV=integration
DOCMESH_HEALTHCHECK_ENABLED=true
POSTGRES_DSN=postgresql+psycopg2://user:password@localhost:5432/dms
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=dms-documents
MINIO_SECURE=false
```

## 8. SDK 생성 실패 조건

다음 경우 SDK 생성은 실패할 수 있습니다.

### 8.1 공통 설정 체계 사용 불가
- 공통 설정 라이브러리를 import할 수 없는 경우
- 환경 설정 로드 자체가 실패한 경우

결과:
- `ConfigurationError`

### 8.2 MinIO 설정 부족
- MinIO 설정이 전혀 없는 경우
- `MINIO_BUCKET` 값이 비어 있는 경우

결과:
- `ConfigurationError`

### 8.3 문서 정보 저장소 설정 부족
- `POSTGRES_` 계열 설정도 없고 `SQLITE_PATH`도 없는 경우

결과:
- `ConfigurationError`

### 8.4 시작 단계 상태 점검 실패
- 활성 저장소가 준비되지 않은 경우

결과:
- `HealthCheckFailedError`

## 9. 명시적 의존성 주입 사용 시 설정 기준

명시적 의존성 주입 방식에서는 환경 변수 대신 애플리케이션이 직접 다음 요소를 전달합니다.

- `metadata_store`
- `object_store`
- `logger` (선택)
- `id_generator` (선택)
- `service_checks` (선택)
- `close_callbacks` (선택)

이 방식에서는 환경 변수 의존성이 줄어들지만, 애플리케이션이 직접 조립 책임을 가집니다.

## 10. 운영 주의사항

- 환경 기반 조립과 명시적 의존성 주입을 동시에 사용하면 안 됩니다.
- SDK 사용이 끝나면 반드시 `close()`를 호출해야 합니다.
- 로컬/테스트 환경에서는 SQLite를 사용할 수 있지만, 운영 검증에는 실제 저장소 조합 검증이 권장됩니다.
- 상태 점검을 활성화하면 SDK 생성 시점 실패를 빠르게 감지할 수 있습니다.

## 11. 테스트 관점의 설정 기준

통합 테스트 관점에서 실제로 사용되는 핵심 환경 변수는 다음과 같습니다.

- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

테스트는 별도 전용 접두사보다 실제 런타임 환경 변수 이름을 재사용하는 것을 기준으로 합니다.

## 12. 빠른 점검 체크리스트

SDK 생성 전 다음을 확인하면 좋습니다.

- MinIO 연결 정보가 모두 채워져 있는가
- `MINIO_BUCKET`이 비어 있지 않은가
- PostgreSQL 또는 SQLite 중 하나가 준비되어 있는가
- 시작 단계 상태 점검을 활성화할지 결정했는가
- 애플리케이션 종료 시 `sdk.close()`를 호출하는가
