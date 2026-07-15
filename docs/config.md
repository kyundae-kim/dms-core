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
- `docs/security.md`

## 2. 설정 방식 개요

DMS SDK는 두 가지 방식으로 생성할 수 있습니다.

1. 환경 기반 조립
- `create_sdk_from_environment(env, logger=...)`
- 환경 변수 매핑을 전달하면 SDK가 필요한 저장소를 조립합니다.

2. 명시적 의존성 주입
- `create_sdk_from_components(...)`
- 애플리케이션이 저장소를 직접 준비해 SDK에 전달합니다.

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

## 4. 저장소 선택 규칙

### 4.1 문서 정보 저장소 선택

`DMS_METADATA_BACKEND`를 지정하면 명시 선택 모드가 됩니다.

1. `postgresql`이면 PostgreSQL만 선택하고 PostgreSQL 설정만 검증합니다.
2. `sqlite`이면 SQLite만 선택하고 `SQLITE_PATH`만 검증합니다.
3. 다른 값은 설정 오류입니다.

지정하지 않으면 기존 자동 선택을 유지합니다. `POSTGRES_` 설정이 있으면 PostgreSQL을,
그렇지 않고 `SQLITE_PATH`가 있으면 SQLite를 사용합니다. 둘 다 있으면 경고 후 PostgreSQL을
선택하며, `DMS_CONFIGURATION_STRICT=true`이면 모호한 자동 선택을 설정 오류로 거부합니다.

### 4.2 문서 본문 저장소 선택

현재 문서 본문 저장소는 MinIO만 지원합니다.
SQLite는 문서 정보 저장소 선택지일 뿐이며, SQLite를 사용하는 경우에도 문서 본문 저장소로 MinIO 설정은 필요합니다.

필수 조건:
- MinIO 설정이 로드 가능해야 함
- `MINIO_BUCKET` 값이 비어 있지 않아야 함

## 5. 상태 점검 규칙

공통 설정의 상태 점검 플래그가 활성화되면 SDK 생성 시점에 상태 점검을 수행합니다.
기본 동작은 활성화입니다.

상태 점검 대상:
- 선택된 문서 정보 저장소
- MinIO

실패 결과:
- 필수 서비스 점검 실패 시 `HealthCheckFailedError`

## 6. 환경 변수 정의

빠른 분류표:

| 구분 | 변수 | 설명 |
|---|---|---|
| SDK 직접 사용 | `MINIO_BUCKET` | object store bucket 이름이며 비어 있으면 생성 실패 |
| 저장소 선택 | `POSTGRES_DSN` / `SQLITE_PATH` | metadata 저장소 선택에 직접 사용 |
| 공통 설정 | `DOCMESH_ENV`, `DOCMESH_HEALTHCHECK_ENABLED` | 환경 구분 및 시작 단계 상태 점검 제어 |
| DMS 선택 정책 | `DMS_METADATA_BACKEND`, `DMS_CONFIGURATION_STRICT` | 명시 backend 선택 및 자동 선택 모호성 거부 |
| MinIO 연결 | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_SECURE` | MinIO client 생성 및 공통 설정 로더 검증에 사용 |


### 6.1 공통 설정

#### `DOCMESH_ENV`
- 설명: 실행 환경 이름
- 필수 여부: 선택
- 예시: `local`, `dev`, `test`, `integration`, `prod`

#### `DOCMESH_HEALTHCHECK_ENABLED`
- 설명: 시작 단계 상태 점검 활성화 여부
- 필수 여부: 선택
- 기본값: `true`
- 예시: `true`, `false`

### 6.2 문서 본문 저장소 설정

#### `MINIO_ENDPOINT`
- 설명: MinIO 서버 주소
- 필수 여부: 공통 설정 로더 기준 필수
- 예시: `localhost:9000`

#### `MINIO_ACCESS_KEY`
- 설명: MinIO 접근 키
- 필수 여부: 공통 설정 로더 기준 필수

#### `MINIO_SECRET_KEY`
- 설명: MinIO 비밀 키
- 필수 여부: 공통 설정 로더 기준 필수

#### `MINIO_BUCKET`
- 설명: 문서 본문을 저장할 bucket 이름
- 필수 여부: 예
- 비고: 값이 없으면 SDK 생성이 실패합니다.

#### `MINIO_SECURE`
- 설명: TLS 사용 여부
- 필수 여부: 선택
- 예시: `true`, `false`
- 보안: 신뢰할 수 없는 네트워크 또는 운영 환경에서는 `true`와 유효한 인증서 구성을 권장합니다. SDK가 TLS를 강제하지 않으므로 `false`는 로컬 개발 또는 별도의 전송 보호가 검증된 환경으로 제한합니다.

### 6.3 PostgreSQL 설정

#### `POSTGRES_DSN`
- 설명: PostgreSQL 연결 문자열
- 필수 여부: PostgreSQL 사용 시 사실상 필수
- 예시: `postgresql://user:***@localhost:5432/dms`

### 6.4 SQLite 설정

#### `SQLITE_PATH`
- 설명: SQLite 데이터베이스 파일 경로
- 필수 여부: SQLite 사용 시 예
- 예시: `/tmp/dms.db`

## 7. `.env.example` 사용 기준

현재 `.env.example`은 DMS SDK가 조립 시 선택하는 PostgreSQL 또는 SQLite와 MinIO 설정만 포함합니다.
Keycloak, NATS, Langfuse, Milvus, Ollama 설정은 DMS SDK 조립 대상이 아니므로 템플릿에 포함하지 않습니다.

예시의 호스트와 자격 증명은 실제 연결 정보가 아닙니다. 따라서 예시는 상태 점검을 비활성화한 상태로 제공하며,
실제 서비스 주소와 자격 증명을 주입한 뒤에만 `DOCMESH_HEALTHCHECK_ENABLED=true`로 변경합니다.
접근 키, 비밀 키, 연결 문자열 등의 실제 값은 소스코드·문서 예시·로그에 기록하지 않고 배포 환경의 secret 주입 기능으로 제공합니다.

## 7.1 자격 증명 운영

- `.env.example`은 변수 이름과 비민감 예시를 위한 템플릿이며 실제 자격 증명 파일이 아닙니다.
- `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, PostgreSQL 연결 정보는 버전 관리 대상에 넣지 않습니다.
- MinIO bucket과 PostgreSQL 계정에는 필요한 작업에 한정된 최소 권한을 부여합니다.
- `diagnose_environment(env)`는 secret 값을 결과에 포함하지 않으므로, 값 노출 없이 설정 구조를 점검할 때 사용합니다.
- SDK 보안 경계와 운영 확인 목록은 `docs/security.md`를 참조합니다.

## 8. 권장 설정 조합

### 8.1 로컬 개발 환경

```env
DOCMESH_ENV=local
DOCMESH_HEALTHCHECK_ENABLED=false
SQLITE_PATH=/tmp/dms.db
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=documents
```

### 8.2 통합/검증 환경

```env
DOCMESH_ENV=integration
DOCMESH_HEALTHCHECK_ENABLED=true
POSTGRES_DSN=postgresql://user:***@localhost:5432/dms
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=documents
MINIO_SECURE=false
```

## 9. SDK 생성 실패 조건

다음 경우 SDK 생성은 실패할 수 있습니다.

### 9.1 설정 로드 실패
- 공통 설정 로더가 설정을 해석하지 못한 경우

결과:
- `ConfigurationError`

### 9.2 MinIO bucket 설정 부족
- `MINIO_BUCKET` 값이 비어 있는 경우

결과:
- `ConfigurationError`

### 9.3 문서 정보 저장소 설정 부족
- 자동 선택 모드에서 `POSTGRES_` 계열 설정도 없고 `SQLITE_PATH`도 없는 경우
- 명시 선택 모드에서 선택한 backend의 필수 설정이 없는 경우

결과:
- `ConfigurationError`

### 9.4 시작 단계 상태 점검 실패
- 활성 저장소가 준비되지 않은 경우

결과:
- `HealthCheckFailedError`

## 10. 명시적 의존성 주입 사용 시 설정 기준

명시적 의존성 주입 방식에서는 애플리케이션이 직접 다음 요소를 전달합니다.
- `metadata_store`
- `object_store`
- `logger` (선택)
- `id_generator` (선택)
- `service_checks` (선택)
- `close_callbacks` (선택)
- `max_file_size` (선택, bytes/stream 업로드 공통 최대 크기)
- `operation_store` (선택, 멱등 업로드를 위한 영속 저장소)
- `metadata_validator` (선택, 사용자 metadata 정규화·검증 함수)
- `metadata_max_serialized_bytes`, `metadata_max_depth` (선택, 기본 metadata 정책 한계)

## 11. 테스트 관점의 설정 기준

통합 테스트 관점에서 실제로 사용되는 핵심 환경 변수는 다음과 같습니다.
- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

테스트는 별도 전용 접두사보다 실제 런타임 환경 변수 이름을 재사용합니다.

## 12. 명시적 선택과 진단

- `DMS_METADATA_BACKEND=postgresql|sqlite`를 지정하면 해당 metadata backend만 로드하고 그 설정만 검증합니다.
- 변수가 없으면 기존 자동 선택(PostgreSQL 우선)을 유지합니다. 두 설정이 모두 있으면 경고 후 PostgreSQL을 선택합니다.
- `DMS_CONFIGURATION_STRICT=true`이면 자동 선택의 모호성이 `ConfigurationError`가 됩니다.
- `diagnose_environment(env)`는 연결이나 서비스 조립 없이 선택 결과, MinIO, healthcheck, 누락 키, 경고와 유효성을 반환합니다. 값이나 secret은 보고서에 포함하지 않습니다.
- DMS 필수 MinIO 키는 `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`입니다. PostgreSQL은 `POSTGRES_DSN` 또는 `POSTGRES_HOST/DB/USER/PASSWORD`, SQLite는 `SQLITE_PATH`를 요구합니다.

- `MINIO_BUCKET`이 비어 있지 않은가
- PostgreSQL 또는 SQLite 중 하나가 준비되어 있는가
- 시작 단계 상태 점검을 활성화할지 결정했는가
- 애플리케이션 종료 시 `sdk.close()`를 호출하는가

### 12.1 로컬에서 가장 적게 필요한 값

SQLite 기반 최소 로컬 시작 기준:
- `SQLITE_PATH`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

SQLite 기반 설정은 metadata 저장소만 로컬 파일로 대체합니다.
문서 본문 저장과 조회에는 여전히 MinIO 연결 정보가 필요합니다.

PostgreSQL 기반 최소 시작 기준:
- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

주의:
- 자동 선택 모드에서 SQLite를 의도했는데 PostgreSQL이 선택되면 현재 환경의 `POSTGRES_` 접두사 변수를 확인합니다. 명시 선택 모드에서는 `DMS_METADATA_BACKEND=sqlite`를 지정하면 PostgreSQL 설정은 선택·검증 대상이 아닙니다.
