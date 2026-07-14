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

SDK는 문서 정보 저장소를 다음 우선순위로 선택합니다.

1. `POSTGRES_` 접두사의 설정이 존재하면 PostgreSQL 사용
2. 그렇지 않고 `SQLITE_PATH`가 존재하면 SQLite 사용
3. 둘 다 없으면 SDK 생성 실패

즉, PostgreSQL과 SQLite가 동시에 존재하면 PostgreSQL이 우선합니다.
개발 환경에서 SQLite를 사용하려면 남아 있는 `POSTGRES_` 접두사 환경 변수가 PostgreSQL 선택을 유발하지 않는지 확인해야 합니다.

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
| MinIO 연결 | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_SECURE` | MinIO client 생성 및 공통 설정 로더 검증에 사용 |
| upstream loader 검증 가능성 | `KEYCLOAK_*`, `MILVUS_URI`, `OLLAMA_HOST`, `LANGFUSE_*`, `NATS_SERVERS` | DMS SDK 기능이 아니라 `docmesh-py-core` 설정 검증 때문에 필요할 수 있음 |

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

## 7. `.env.example`와 공통 설정 로더 주의사항

현재 저장소의 `.env.example`에는 DMS SDK가 직접 사용하지 않는 다음 설정도 포함됩니다.
- `KEYCLOAK_*`
- `MILVUS_URI`
- `OLLAMA_HOST`
- `LANGFUSE_*`
- `NATS_SERVERS`

이 값들은 현재 DMS SDK 기능을 위한 공개 API가 아니라, `docmesh-py-core` 설정 검증을 통과시키기 위한 런타임 예시입니다.
즉, DMS SDK가 직접 Keycloak, NATS, Langfuse, Milvus, Ollama 기능을 제공하는 것은 아닙니다.

개발 관점 해석:
- "SDK가 직접 읽는 값"과 "공통 설정 로더가 검증하기 때문에 환경에 있어야 할 수 있는 값"을 구분해서 봐야 합니다.
- 실제 장애 원인 분석 시에는 DMS SDK 코드 오류인지, upstream 설정 로더 검증 실패인지 먼저 나누어 보는 것이 좋습니다.

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
- `POSTGRES_` 계열 설정도 없고 `SQLITE_PATH`도 없는 경우

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

## 11. 테스트 관점의 설정 기준

통합 테스트 관점에서 실제로 사용되는 핵심 환경 변수는 다음과 같습니다.
- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

테스트는 별도 전용 접두사보다 실제 런타임 환경 변수 이름을 재사용합니다.

## 12. 빠른 점검 체크리스트

## Release 5: 명시적 선택과 진단

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
- 위 값만으로 충분한지는 현재 실행 환경의 `docmesh-py-core` 설정 검증 범위에 따라 달라질 수 있습니다.
- `.env.example`에 포함된 추가 서비스 값이 요구되면, 이는 현재 DMS 기능이 아니라 upstream 공통 설정 검증 요구사항입니다.
- SQLite를 의도했는데 PostgreSQL 설정 오류가 발생하면 현재 환경에 남아 있는 `POSTGRES_` 접두사 변수가 있는지 먼저 확인합니다.
