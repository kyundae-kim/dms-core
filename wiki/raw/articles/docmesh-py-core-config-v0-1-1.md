---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.3.0/docs/config.md
ingested: 2026-07-17
sha256: 1924e994fb59db8658095328434eae3db49547edba18887c91b0cd1b1024d9b5
---

# docmesh-py-core Configuration Guide

이 문서는 현재 구현(`settings.py`, `config_loading.py`, `config_diagnostics.py`, `service_factories.py`, `function_logging.py`)을 기준으로 `docmesh-py-core`의 공개 환경변수 계약을 설명합니다.

목표는 세 가지입니다.

1. 어떤 값을 설정해야 하는지 빠르게 알 수 있게 하기
2. 필수 / 선택 / 조건부 필수 값을 구분하기
3. 코드가 실제로 어떻게 동작하는지 문서와 일치시키기

전체 환경변수 템플릿은 [`.env.example`](../.env.example)을 참고하세요. 실제 secret은 템플릿이나 저장소에 기록하지 않습니다.

## 1. 공통 원칙

- 모든 서비스 설정은 환경변수에서 읽습니다.
- 애플리케이션 lifecycle 조립은 **assembly-first**로 `assemble_services()` 또는 `assemble_service_runtime()`을 우선 사용합니다.
- 서비스별 config class와 `create_*_client()`는 Keycloak 기능 직접 사용, CLI·배치, 테스트, SDK별 확장 hook 제어 같은 **direct-api-when-needed** 상황에 사용합니다.
- 공백 문자열은 미설정(`None`)으로 처리합니다.
- Boolean 값은 `true` / `false`, `1` / `0`, `yes` / `no`, `on` / `off`를 허용합니다.
- 숫자형 값은 타입과 범위를 검증합니다.
- 서비스별 config class(`CommonConfig`, `KeycloakConfig`, `LangfuseConfig`, `PostgresConfig`, `SqliteConfig` 등)를 직접 생성하면 필요한 설정만 검증할 수 있습니다.
- `load_service_configs(services={...})`를 사용하면 필요한 서비스만 선택적으로 검증/로딩할 수 있습니다.
- `load_service_configs(env, services={...})`에 mapping을 전달하면 프로세스 환경을 수정하지 않고 해당 mapping만 설정 소스로 사용합니다.
- `load_available_service_configs(env, services={...})`는 후보 중 관련 환경변수가 있는 서비스만 로딩하며, 부분 설정은 오류로 처리합니다.
- `load_service_configs()` 경로의 검증 오류는 `ConfigError`로 래핑됩니다.
- `ConfigError.issues`에는 서비스명, 환경변수 키, 사유, 오류 유형, remediation을 담은 `ConfigIssue`가 제공됩니다.
- `validate_service_requirements()`로 필수 서비스와 `one_of` 대안 서비스 그룹을 선언적으로 검증할 수 있습니다.
- `require_minio_bucket()`은 bucket이 필요한 제품만 `MINIO_BUCKET` 필수 검증을 선택적으로 적용할 수 있게 합니다.
- `CommonConfig.is_production` 판정 결과가 production이면 `validate_runtime_security()`가 추가 보안 제약을 검사합니다.

### 사전 설정 진단과 서비스 선택

`diagnose_services()`는 CI/CD, Helm preflight, 로컬 개발 환경에서 실제 client를 만들기 전에 설정을 검사하는 API입니다. 결과의 `to_dict()`는 JSON 직렬화에 안전하며 민감값을 포함하지 않습니다.

- `services`: 검사할 후보 서비스 집합
- `required`: 반드시 완전하게 구성되어야 하는 서비스
- `one_of`: 그룹별로 하나 이상 구성되어야 하는 대안 서비스 집합
- `selection_mode="auto"`: 완전한 설정을 가진 서비스만 선택합니다.
- `selection_mode="explicit"`: 호출자가 지정한 후보만 검사·선택합니다.
- `selection_mode="strict"`: `one_of` 그룹에서 둘 이상이 완전하게 구성된 경우 모호성 오류를 추가합니다.

서비스 상태는 `absent`, `complete`, `partial`, `invalid` 중 하나입니다. `partial` 또는 `invalid` 상태의 서비스 오류도 결과에 모두 집계되므로, 첫 오류만 보고 재실행할 필요가 없습니다.

`diagnose_services(env, plan=...)`은 동일한 `RuntimePlan`을 startup 전 검증에 재사용합니다. production으로 판정된 환경에서는 선택된 서비스의 placeholder secret 또는 예제/localhost endpoint를 `production_placeholder` issue로 보고합니다. issue에는 환경변수 키만 포함되고 원래 값은 포함되지 않습니다.

`diagnose_services()`의 `services`/`required`/`one_of` legacy 인자는 deprecated이며 v0.4.0 제거를 목표로 합니다. 신규 코드는 `RuntimePlan`을 `plan=`으로 전달하세요. `assemble_service_runtime()`의 legacy 선택/health 인자도 같은 정책을 따릅니다.

### 설정값 적용 단계

환경변수가 config model에 존재한다고 해서 모두 SDK 생성자에 직접 전달되는 것은 아닙니다.

| 구분 | 현재 적용 방식 |
| --- | --- |
| 공통/서비스 config 필드 | 환경변수 파싱과 validation에 사용 |
| PostgreSQL pool/timeout/SSL | SQLAlchemy engine 생성 옵션에 직접 반영 |
| SQLite readonly/WAL/busy timeout | URL, connect args, connection pragma에 반영 |
| MinIO bucket/timeout/retry | `MinioRuntimeDefaults`에 보존 |
| Milvus collection/connect timeout/retry/secure | `MilvusRuntimeDefaults`에 보존 |
| Ollama model/retry | `OllamaRuntimeDefaults`에 보존 |
| production TLS 제약 | `validate_runtime_security()`에서 검증 |

`DOCMESH_HEALTHCHECK_ENABLED`는 `check_on_startup`에 자동 연결되지 않습니다. 현재 구현에서는 `CommonConfig.healthcheck_enabled`에 로딩될 뿐이며, 소비 애플리케이션이 이 값을 읽어 `assemble_services()` 또는 `assemble_service_runtime()`의 `check_on_startup` 정책을 결정해야 합니다.

### 공개 설정 API 추적

환경변수 계약과 package root 공개 API의 관계는 다음과 같습니다. 각 이름의 반환값·예외·lifecycle 계약은 [API Reference](./api.md#공개-api-추적-인벤토리)를 기준으로 하고, 이 문서는 값의 출처와 validation 규칙만 정의합니다.

| 공개 API | 이 문서에서 다루는 설정 책임 |
| --- | --- |
| `CommonConfig` | `DOCMESH_*` 공통 환경, production 판정, healthcheck 기본값 |
| `KeycloakDiscoveryConfig`, `KeycloakConfig`, `KeycloakAuthService`, `KeycloakProvisioner` | Keycloak discovery/auth/token/provisioning 환경 |
| `PostgresConfig`, `SqliteConfig`, `MinioConfig`, `MilvusConfig`, `OllamaConfig`, `LangfuseConfig`, `NatsConfig` | 각 서비스의 환경변수와 조건부 필수값 |
| `ServiceConfigs`, `load_service_configs`, `load_available_service_configs` | 선택 로딩 및 엄격/available validation 경로 |
| `ConfigIssue`, `ServiceConfigurationDiagnosis`, `EnvironmentDiagnosis`, `diagnose_services` | client 생성 전의 JSON-safe 진단 결과 |
| `RuntimePlan`, `Service`, `ServiceSelection`, `HealthcheckPolicy` | 선택·required·one-of·startup health 정책 선언 |
| `SERVICE_CATALOG`, `ServiceDescriptor`, `EnvironmentRequirement` | 지원 서비스와 secret-safe 환경 metadata 조회 |
| `validate_service_requirements`, `require_minio_bucket`, `validate_runtime_security` | 조합, bucket, production TLS의 opt-in 검증 |
| `MinioRuntimeDefaults`, `MilvusRuntimeDefaults`, `OllamaRuntimeDefaults` | config에는 있으나 SDK 생성자에 직접 전달되지 않는 typed 값 보존 |
| `configure_logging` | `DOCMESH_LOG_LEVEL`을 읽는 별도 logging entrypoint |

환경변수를 읽지 않는 공개 API(예: `ServiceClientWrapper`, `check_all_services`, 오류 타입, `retry_call`)는 이 문서에 중복하지 않고 [API Reference](./api.md#공개-api-추적-인벤토리)와 [Examples](./examples.md#11-공개-api-레시피-인덱스)에서 추적합니다.

## 2. 공통 환경변수

| 환경변수 | 사용처 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `DOCMESH_ENV` | `CommonConfig.env` | 아니요 | `development` | 실행 환경 식별자 |
| `DOCMESH_HEALTHCHECK_ENABLED` | `CommonConfig.healthcheck_enabled` | 아니요 | `true` | 헬스체크 활성화 여부 |
| `DOCMESH_SECURITY_MODE` | `CommonConfig.security_mode` | 아니요 | 없음 | `development` 또는 `production`; 설정되면 환경 이름보다 우선 |
| `DOCMESH_PRODUCTION_ALIASES` | `CommonConfig.production_aliases` | 아니요 | `prod,production` | 운영으로 판정할 환경 이름 목록 |
| `DOCMESH_LOG_LEVEL` | `configure_logging()` | 아니요 | `INFO` | 루트 로거 기본 로그 레벨 |

권장값 예시:

- 로컬 개발: `DOCMESH_ENV=development`
- 통합 테스트: `DOCMESH_ENV=integration`
- 운영: `DOCMESH_ENV=production`

주의:

- `DOCMESH_ENV`는 자유 문자열입니다. 코드가 enum 검증을 하지는 않습니다.
- `DOCMESH_SECURITY_MODE`가 있으면 명시적 판정을 사용하고, 없으면 `DOCMESH_PRODUCTION_ALIASES`와 비교합니다.
- 설정 로딩 시 `runtime_security_mode` 로그에 환경 이름과 최종 보안 모드를 기록합니다.
- `DOCMESH_LOG_LEVEL`은 `CommonConfig` 필드가 아니라 `configure_logging()`가 읽는 별도 환경변수입니다.

### 로깅 규칙

- `configure_logging(level=...)`를 명시하지 않으면 `DOCMESH_LOG_LEVEL`을 읽습니다.
- `DOCMESH_LOG_LEVEL`이 없거나 빈 문자열이면 기본값은 `INFO`입니다.
- 허용 예: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- 잘못된 값이면 `ValueError`가 발생합니다.

## 3. 서비스별 설정

### 3.1 Keycloak discovery / auth

#### 기본 인증/JWT 검증

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KEYCLOAK_URL` | 예 | 없음 | Keycloak 기본 URL |
| `KEYCLOAK_REALM` | 예 | 없음 | 인증 Realm |
| `KEYCLOAK_CLIENT_ID` | 예 | 없음 | OIDC Client ID |
| `KEYCLOAK_CLIENT_SECRET` | 조건부 | 없음 | `KEYCLOAK_CLIENT_PUBLIC=false`일 때 필요 |
| `KEYCLOAK_VERIFY_SSL` | 아니요 | `true` | TLS 인증서 검증 여부 |
| `KEYCLOAK_AUDIENCE` | 아니요 | 없음 | JWT audience 검증 대상 |
| `KEYCLOAK_REQUEST_TIMEOUT_SECONDS` | 아니요 | `10` | 요청 제한 시간 |
| `KEYCLOAK_MAX_RETRIES` | 아니요 | `3` | 일시적 오류 재시도 횟수 |
| `KEYCLOAK_JWKS_CACHE_TTL_SECONDS` | 아니요 | `300` | JWKS 캐시 TTL |
| `KEYCLOAK_CLIENT_PUBLIC` | 아니요 | `false` | public client 여부 |

규칙:

- `KeycloakDiscoveryConfig`는 `KEYCLOAK_URL`, `KEYCLOAK_REALM`만 읽습니다.
- `KeycloakConfig`는 discovery 설정을 확장하고 `KEYCLOAK_CLIENT_ID`를 추가로 요구합니다.
- `KEYCLOAK_CLIENT_PUBLIC=false`면 `KEYCLOAK_CLIENT_SECRET`가 필요합니다.
- 운영 환경에서는 `KEYCLOAK_VERIFY_SSL=false`를 허용하지 않습니다.

#### 토큰 획득

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KEYCLOAK_TOKEN_GRANT_TYPE` | 아니요 | `password` | 토큰 grant type (`client_credentials`, `password`) |
| `KEYCLOAK_TOKEN_SCOPE` | 아니요 | 없음 | 기본 scope |
| `KEYCLOAK_TOKEN_USERNAME` | 아니요 | 없음 | password grant 기본 username; 함수 인자가 우선 |
| `KEYCLOAK_TOKEN_PASSWORD` | 아니요 | 없음 | password grant 기본 password; 함수 인자가 우선 |

중요:

- `fetch_access_token()` 함수 인자가 우선하며, 생략된 username/password는 `KEYCLOAK_TOKEN_USERNAME`, `KEYCLOAK_TOKEN_PASSWORD`에서 가져옵니다.
- 두 입력 경로에도 자격증명이 모두 갖춰지지 않으면 구체적인 configuration error가 발생합니다.
- 기본 grant는 `password`입니다. `KEYCLOAK_TOKEN_GRANT_TYPE=password` 자체는 설정 로딩 시 허용되며, 이 단계에서 username/password를 강제하지 않습니다.

#### 프로비저닝

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KEYCLOAK_PROVISIONING_ENABLED` | 아니요 | `false` | 프로비저닝 활성화 여부 |
| `KEYCLOAK_PROVISIONING_DRY_RUN` | 아니요 | `false` | 변경 없이 계획만 반환 |
| `KEYCLOAK_ADMIN_REALM` | 아니요 | `master` | Admin API 인증 Realm |
| `KEYCLOAK_ADMIN_CLIENT_ID` | 아니요 | `admin-cli` | Admin API 인증 Client ID |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | 조건부 | 없음 | service account 방식 secret |
| `KEYCLOAK_ADMIN_USERNAME` | 조건부 | 없음 | 사용자명 기반 admin 인증 |
| `KEYCLOAK_ADMIN_PASSWORD` | 조건부 | 없음 | 비밀번호 기반 admin 인증 |
| `KEYCLOAK_REALM_ENABLED` | 아니요 | `true` | 대상 Realm 활성화 여부 |
| `KEYCLOAK_REALM_DISPLAY_NAME` | 아니요 | 없음 | Realm 표시 이름 |
| `KEYCLOAK_CLIENT_REDIRECT_URIS` | 아니요 | 빈 리스트 | 쉼표 구분 redirect URI 목록 |
| `KEYCLOAK_CLIENT_WEB_ORIGINS` | 아니요 | 빈 리스트 | 쉼표 구분 web origin 목록 |
| `KEYCLOAK_REALM_ROLES` | 아니요 | 빈 리스트 | 쉼표 구분 realm role 목록 |
| `KEYCLOAK_CLIENT_ROLES` | 아니요 | 빈 리스트 | 쉼표 구분 client role 목록 |

규칙:

- `KEYCLOAK_PROVISIONING_ENABLED=true`이면 admin 인증 방식이 정확히 하나여야 합니다.
- 허용되는 두 방식은 아래 둘 중 하나입니다.
  - `KEYCLOAK_ADMIN_CLIENT_SECRET`
  - `KEYCLOAK_ADMIN_USERNAME` + `KEYCLOAK_ADMIN_PASSWORD`
- 둘 다 주거나 둘 다 비우면 `KEYCLOAK provisioning requires a single admin auth mode` 오류가 발생합니다.
- 선언에서 제거된 리소스를 자동 삭제하지 않습니다.

### 3.2 PostgreSQL

`POSTGRES_DSN`은 deprecated이며 v0.4.0 제거를 목표로 합니다. 새 설정과 catalog metadata는 개별 연결 필드를 우선합니다.

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `POSTGRES_DSN` | deprecated | 없음 | 하위 호환용 PostgreSQL 연결 URI; 사용 시 `DeprecationWarning` 발생 |
| `POSTGRES_HOST` | 조건부 | 없음 | 호스트 |
| `POSTGRES_PORT` | 아니요 | `5432` | 포트 |
| `POSTGRES_DB` | 조건부 | 없음 | 데이터베이스 이름 |
| `POSTGRES_USER` | 조건부 | 없음 | 사용자명 |
| `POSTGRES_PASSWORD` | 조건부 | 없음 | 비밀번호 |
| `POSTGRES_SSLMODE` | 아니요 | `prefer` | SSL 모드 |
| `POSTGRES_CONNECT_TIMEOUT_SECONDS` | 아니요 | `10` | 연결 제한 시간 |
| `POSTGRES_POOL_SIZE` | 아니요 | `5` | 기본 풀 크기 |
| `POSTGRES_MAX_OVERFLOW` | 아니요 | `10` | 추가 허용 연결 수 |

규칙:

- 새 설정은 `host`, `db`, `user`, `password` 조합을 모두 사용합니다. `port`의 기본값은 `5432`입니다.
- 하위 호환용 DSN은 개별 연결 필드와 함께 설정할 수 없습니다. 혼용하면 설정 오류가 발생합니다.
- 기본 헬스체크는 `SELECT 1`입니다.

### 3.3 SQLite

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `SQLITE_PATH` | 예 | 없음 | 파일 경로 또는 `:memory:` |
| `SQLITE_READONLY` | 아니요 | `false` | 읽기 전용 모드 |
| `SQLITE_ENABLE_WAL` | 아니요 | `false` | WAL 활성화 여부 |
| `SQLITE_BUSY_TIMEOUT_MS` | 아니요 | `5000` | 잠금 대기 시간(ms) |

규칙:

- `:memory:`를 지원합니다.
- 상대경로는 현재 작업 디렉터리 기준으로 SQLAlchemy가 해석합니다.
- 라이브러리는 상위 디렉터리를 자동 생성하지 않습니다.
- 파일 존재 여부/경로 유효성은 설정 로딩 단계가 아니라 실제 연결 단계에서 드러납니다.
- `readonly=true`면 `sqlite:///file:...?...` URI 모드로 연결합니다.
- 기본 헬스체크는 `SELECT 1`입니다.

### 3.4 MinIO

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MINIO_ENDPOINT` | 예 | 없음 | `host:port` 형식 endpoint |
| `MINIO_ACCESS_KEY` | 예 | 없음 | access key |
| `MINIO_SECRET_KEY` | 예 | 없음 | secret key |
| `MINIO_SECURE` | 아니요 | `true` | HTTPS 사용 여부 |
| `MINIO_REGION` | 아니요 | 없음 | region |
| `MINIO_BUCKET` | 아니요 | 없음 | 기본 bucket |
| `MINIO_REQUEST_TIMEOUT_SECONDS` | 아니요 | `30` | 설정 모델에 존재하는 timeout 값 |
| `MINIO_MAX_RETRIES` | 아니요 | `3` | 설정 모델에 존재하는 재시도 값 |

주의:

- SDK 생성자에 직접 전달할 수 없는 `request_timeout_seconds`, `max_retries`, `bucket`은 `MinioRuntimeDefaults`로 보존됩니다.
- 기본 헬스체크는 `list_buckets()`입니다.
- 운영 환경에서는 `MINIO_SECURE=false`를 허용하지 않습니다.

### 3.5 Milvus

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MILVUS_URI` | 예 | 없음 | Milvus 서버 URI |
| `MILVUS_TOKEN` | 아니요 | 없음 | 인증 토큰 |
| `MILVUS_DB_NAME` | 아니요 | `default` | 데이터베이스 이름 |
| `MILVUS_COLLECTION` | 아니요 | 없음 | 기본 collection |
| `MILVUS_SECURE` | 아니요 | `false` | TLS 사용 여부 |
| `MILVUS_CONNECT_TIMEOUT_SECONDS` | 아니요 | `10` | 설정 모델에 존재하는 연결 timeout 값 |
| `MILVUS_REQUEST_TIMEOUT_SECONDS` | 아니요 | `30` | 클라이언트 생성에 전달되는 timeout |
| `MILVUS_MAX_RETRIES` | 아니요 | `3` | 설정 모델에 존재하는 재시도 값 |

주의:

- SDK 생성자에 직접 전달할 수 없는 `connect_timeout_seconds`, `collection`, `max_retries`, `secure`는 `MilvusRuntimeDefaults`로 보존됩니다.
- 기본 헬스체크는 `list_collections()`입니다.
- 운영 환경에서는 `MILVUS_SECURE=false`를 허용하지 않습니다.

### 3.6 Ollama

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `OLLAMA_HOST` | 예 | 없음 | Ollama API 기본 URL |
| `OLLAMA_GENERATION_MODEL` | 아니요 | 없음 | 기본 생성 모델 |
| `OLLAMA_EMBEDDING_MODEL` | 아니요 | 없음 | 기본 임베딩 모델 |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | 아니요 | `120` | 요청 제한 시간 |
| `OLLAMA_MAX_RETRIES` | 아니요 | `2` | 설정 모델에 존재하는 재시도 값 |

주의:

- SDK 생성자에 직접 전달할 수 없는 `max_retries`, 모델명 필드는 `OllamaRuntimeDefaults`로 보존됩니다.
- 기본 헬스체크는 `ps()`입니다.

### 3.7 Langfuse

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `LANGFUSE_ENABLED` | 아니요 | `true` | 활성화 여부 |
| `LANGFUSE_HOST` | 조건부 | 없음 | Langfuse API 기본 URL |
| `LANGFUSE_PUBLIC_KEY` | 조건부 | 없음 | public key |
| `LANGFUSE_SECRET_KEY` | 조건부 | 없음 | secret key |
| `LANGFUSE_RELEASE` | 아니요 | 없음 | 릴리스 식별자 |
| `LANGFUSE_ENVIRONMENT` | 아니요 | `DOCMESH_ENV` 값 | 환경 식별자 |
| `LANGFUSE_REQUEST_TIMEOUT_SECONDS` | 아니요 | `10` | 요청 제한 시간 |
| `LANGFUSE_MAX_RETRIES` | 아니요 | `3` | 설정 모델에 존재하는 재시도 값 |

규칙:

- `LANGFUSE_ENABLED=false`이면 host/public_key/secret_key 없이도 설정 로딩이 가능합니다.
- `LANGFUSE_ENABLED=true`일 때만 `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`가 필수입니다.
- `LANGFUSE_ENVIRONMENT`가 비어 있으면 `CommonConfig().env` 값을 사용합니다.
- `LANGFUSE_MAX_RETRIES`는 현재 설정 파싱과 검증에만 사용되며 기본 factory나 runtime defaults에는 자동 연결되지 않습니다. 소비 애플리케이션이 별도 retry 정책에 사용할 수 있습니다.
- 기본 헬스체크는 `auth_check()`입니다.

### 3.8 NATS

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `NATS_SERVERS` | 예 | 빈 리스트 | 쉼표 구분 서버 URL 목록 |
| `NATS_USER` | 조건부 | 없음 | 사용자명 인증 |
| `NATS_PASSWORD` | 조건부 | 없음 | 비밀번호 인증 |
| `NATS_TOKEN` | 조건부 | 없음 | 토큰 인증 |
| `NATS_CREDS_FILE` | 조건부 | 없음 | credentials 파일 경로 |
| `NATS_NAME` | 아니요 | `docmesh-py-core` | 연결 이름 |
| `NATS_CONNECT_TIMEOUT_SECONDS` | 아니요 | `10` | 연결 제한 시간 |
| `NATS_MAX_RECONNECT_ATTEMPTS` | 아니요 | `10` | 최대 재연결 횟수 |

규칙:

- `NATS_SERVERS`는 쉼표 구분 문자열을 list로 파싱합니다.
- 인증 없이 연결하거나, 인증이 필요한 경우 아래 셋 중 최대 하나만 선택할 수 있습니다.
  - `NATS_USER` + `NATS_PASSWORD`
  - `NATS_TOKEN`
  - `NATS_CREDS_FILE`
- `NATS_USER`와 `NATS_PASSWORD`는 함께 제공해야 합니다.
- 헬스체크는 임시 연결 후 `flush()` 확인입니다.

## 4. 최소 구성 가이드

### 4.1 서비스별 최소 활성화 세트

#### Keycloak 기본 인증 / 토큰 획득

필수:

- `KEYCLOAK_URL`
- `KEYCLOAK_REALM`
- `KEYCLOAK_CLIENT_ID`
- `KEYCLOAK_CLIENT_SECRET` (`KEYCLOAK_CLIENT_PUBLIC=false` 기본값 기준)

추가 조건:

- `KEYCLOAK_CLIENT_PUBLIC=true`면 `KEYCLOAK_CLIENT_SECRET` 없이 로딩 가능
- `KEYCLOAK_TOKEN_GRANT_TYPE=password`여도 설정 로딩 시 username/password는 필요 없음
- 실제 호출에서는 함수 인자가 우선하고, 생략된 값은 config credential을 사용
- Keycloak을 assembly startup healthcheck 대상으로 선택하면 factory가 `fetch_access_token()`을 호출합니다. 기본 password grant에서는 `KEYCLOAK_TOKEN_USERNAME`과 `KEYCLOAK_TOKEN_PASSWORD`가 모두 설정되어야 하며, 그렇지 않으면 설정 로딩 후 healthcheck 단계에서 실패합니다.

#### PostgreSQL 저장소

개별 필드 방식을 사용합니다.

1. 권장 개별 필드 방식
   - `POSTGRES_HOST`
   - `POSTGRES_DB`
   - `POSTGRES_USER`
   - `POSTGRES_PASSWORD`
2. deprecated 호환 방식
   - `POSTGRES_DSN` (v0.4.0 제거 목표)

#### SQLite 저장소

필수:

- `SQLITE_PATH`

#### MinIO 객체 저장소

필수:

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`

운영 환경에서는 기본값 `MINIO_SECURE=true`를 유지해야 합니다.

#### Milvus 벡터 저장소

필수:

- `MILVUS_URI`

`MILVUS_SECURE` 기본값은 `false`이므로 production으로 판정되는 환경에서는 반드시 `MILVUS_SECURE=true`를 설정해야 합니다.

#### Ollama 모델 서비스

필수:

- `OLLAMA_HOST`

#### Langfuse 비활성화

최소:

- `LANGFUSE_ENABLED=false`

#### Langfuse 활성화

필수:

- `LANGFUSE_HOST`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`

#### NATS 인증 모드

필수:

- `NATS_SERVERS`

인증이 필요하지 않으면 모두 생략할 수 있습니다. 인증이 필요한 경우 아래 세 모드 중 **최대 하나만** 선택합니다.

1. user/password
   - `NATS_USER`
   - `NATS_PASSWORD`
2. token
   - `NATS_TOKEN`
3. creds file
   - `NATS_CREDS_FILE`

## 5. 보안 운영 가이드

- 실제 secret 값이 들어간 `.env` 파일은 버전 관리에 포함하지 마세요.
- 비밀번호, token, secret, 전체 DSN/URI를 로그에 그대로 남기지 마세요.
- 운영 환경에서는 TLS 검증 비활성화를 사용하지 마세요.
- Keycloak 프로비저닝은 가능하면 최소 권한 자격증명을 사용하세요.
- Access Token, Refresh Token 원문은 애플리케이션 로그나 트레이싱 이벤트에 기록하지 마세요.

현재 production 보안 제약은 아래 세 값에만 적용됩니다.

- `KEYCLOAK_VERIFY_SSL`
- `MINIO_SECURE`
- `MILVUS_SECURE`

## 6. 자주 실패하는 설정 패턴 / 트러블슈팅

### `ConfigError: Missing required environment variable ...`

의미:

- 필수 env가 비어 있거나 누락되었습니다.
- 이 라이브러리는 공백 문자열도 미설정으로 취급합니다.

### `KEYCLOAK_CLIENT_SECRET` 누락 오류

원인:

- 기본값은 confidential client 전제이므로 `KEYCLOAK_CLIENT_SECRET`가 필요합니다.

해결:

- confidential client면 secret 제공
- public client면 `KEYCLOAK_CLIENT_PUBLIC=true` 명시

### `Password grant requires username and password credentials`

원인:

- 함수 인자와 config 양쪽 모두에 완전한 username/password가 없습니다.

해결:

- 함수 인자를 전달하거나 `KEYCLOAK_TOKEN_USERNAME`, `KEYCLOAK_TOKEN_PASSWORD`를 모두 설정하세요.

### `KEYCLOAK provisioning requires a single admin auth mode`

원인:

- service account 방식과 username/password 방식을 동시에 주었거나, 둘 다 주지 않았습니다.

해결:

- 아래 둘 중 하나만 선택하세요.
  - `KEYCLOAK_ADMIN_CLIENT_SECRET`
  - `KEYCLOAK_ADMIN_USERNAME` + `KEYCLOAK_ADMIN_PASSWORD`

### `NATS requires a single authentication mode`

원인:

- `NATS_USER/NATS_PASSWORD`, `NATS_TOKEN`, `NATS_CREDS_FILE`를 중복 지정했습니다.

### `NATS_USER and NATS_PASSWORD must be provided together`

원인:

- user/password 모드에서 둘 중 하나만 설정했습니다.

### production 환경 SSL 제약

의미:

- `DOCMESH_SECURITY_MODE`가 설정되면 그 값으로 운영 여부를 판정합니다.
- 설정되지 않으면 소문자 `DOCMESH_ENV`가 `DOCMESH_PRODUCTION_ALIASES`에 포함될 때 보안 검증이 추가됩니다.

제약:

- `KEYCLOAK_VERIFY_SSL=false` 불가
- `MINIO_SECURE=false` 불가
- `MILVUS_SECURE=false` 불가

## 7. 문서 연계

- 사용 흐름: [README](../README.md)
- 공개 API: [api.md](./api.md)
- 실제 통합 예시: [examples.md](./examples.md)
- 요구사항 기준: [srs.md](./srs.md)
- 테스트 전략: [test.md](./test.md)
