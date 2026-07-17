---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.3.0/docs/api.md
ingested: 2026-07-17
sha256: caedd7c6a41357ddb3a6c5f8b0508088eec84ff39d525777d2ae095372e814d9
---

# docmesh-py-core API Reference

이 문서는 현재 소스코드(`docmesh_py_core/__init__.py`, 각 모듈 구현)를 기준으로 정리한 공개 API 레퍼런스입니다.

- 사용 흐름은 [README](../README.md)
- 환경변수/설정 규칙은 [config.md](./config.md)
- 실제 통합 예시는 [examples.md](./examples.md)

## 1. Public imports

패키지 루트에서 바로 import 가능한 공개 API는 다음과 같습니다.

```python
from docmesh_py_core import (
    AccessTokenResult,
    AuthenticatedUser,
    CommonConfig,
    ConfigError,
    ConfigIssue,
    ConfigurationError,
    DocMeshError,
    EnvironmentRequirement,
    EnvironmentDiagnosis,
    HealthCheckError,
    HealthCheckResult,
    HealthcheckPolicy,
    InvalidRuntimePlanError,
    KeycloakAuthService,
    KeycloakConfig,
    KeycloakDiscoveryConfig,
    KeycloakProvisioner,
    KeycloakTokenAuthenticationError,
    KeycloakTokenConfigurationError,
    KeycloakTokenError,
    KeycloakTokenTemporaryError,
    LangfuseConfig,
    MinioConfig,
    MinioRuntimeDefaults,
    MilvusConfig,
    MilvusRuntimeDefaults,
    NatsConnectionBuilder,
    NatsConfig,
    OllamaConfig,
    OllamaRuntimeDefaults,
    PostgresConfig,
    ProvisioningResult,
    RuntimePlan,
    SERVICE_CATALOG,
    Service,
    ServiceBundle,
    ServiceCloseError,
    ServiceCloseFailure,
    ServiceClientError,
    ServiceClientProtocol,
    ServiceConfigurationDiagnosis,
    ServiceContainerProtocol,
    ServiceDescriptor,
    ServiceHandle,
    ServiceLookupError,
    ServiceNotInitializedError,
    ServiceNotSelectedError,
    ServiceClientWrapper,
    ServiceClientWrapperError,
    ServiceConfigs,
    ServiceRuntime,
    ServiceSelection,
    ServiceHealthStatus,
    ServiceUnavailableError,
    ShutdownError,
    SqliteConfig,
    StartupCheckError,
    TokenValidationError,
    UnknownServiceError,
    assemble_services,
    assemble_service_runtime,
    async_check_all_services,
    async_close_service_clients,
    build_service_log_event,
    check_all_services,
    close_service_clients,
    configure_logging,
    create_keycloak_client,
    create_langfuse_client,
    create_milvus_client,
    create_minio_client,
    create_nats_client,
    create_ollama_client,
    create_postgres_client,
    create_sqlite_client,
    diagnose_services,
    load_available_service_configs,
    load_service_configs,
    require_minio_bucket,
    mask_sensitive_value,
    retry_call,
    validate_service_requirements,
    validate_runtime_security,
)
```

> 위 목록은 `docmesh_py_core/__init__.py`의 `__all__` 기준입니다.

`docmesh_py_core.config`와 `docmesh_py_core.factories`는 기존 import 경로를 보존하기 위한 호환 facade입니다. 신규 코드는 package root의 공개 API와 권장 assembly API를 사용하세요. facade 경로의 제거 일정은 없으며, 제거가 필요하면 별도 deprecation 주기와 major-version 변경으로 공지합니다.

### 공개 API 추적 인벤토리

아래 표는 package root의 `__all__` 83개 항목을 빠짐없이 추적하는 인덱스입니다. **설정** 열은 해당 API를 사용하기 전에 확인할 환경변수 계약, **예제** 열은 복사·응용 가능한 사용 경로를 가리킵니다. `—`는 환경변수나 독립 실행 예제가 필요 없는 타입/오류 계약입니다.

#### 설정·진단·계획 타입

| 공개 API | 계약 / 이 문서의 상세 위치 | 설정 | 예제 |
| --- | --- | --- | --- |
| `CommonConfig` | 공통 환경 설정 모델; [Service config API](#3-service-config-api) | [공통 환경변수](./config.md#2-공통-환경변수) | [직접 config](./examples.md#11-필요-시-서비스별-config-class를-직접-쓰는-예시) |
| `KeycloakDiscoveryConfig` | Keycloak URL·realm discovery 설정 | [Keycloak](./config.md#31-keycloak-discovery--auth) | [Keycloak recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `KeycloakConfig` | Keycloak auth/JWT/provisioning 설정 | [Keycloak](./config.md#31-keycloak-discovery--auth) | [JWT 및 provisioning](./examples.md#9-jwt-검증-및-사용자-정보-추출) |
| `PostgresConfig` | PostgreSQL 연결 설정 | [PostgreSQL](./config.md#32-postgresql) | [PostgreSQL recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `SqliteConfig` | SQLite 연결 설정 | [SQLite](./config.md#33-sqlite) | [SQLite 로컬 개발](./examples.md#5-sqlite-로컬-개발-예시) |
| `MinioConfig` | MinIO 연결 설정 | [MinIO](./config.md#34-minio) | [MinIO recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `MilvusConfig` | Milvus 연결 설정 | [Milvus](./config.md#35-milvus) | [Milvus recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `OllamaConfig` | Ollama 연결 설정 | [Ollama](./config.md#36-ollama) | [Ollama recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `LangfuseConfig` | Langfuse 활성화·연결 설정 | [Langfuse](./config.md#37-langfuse) | [Langfuse recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `NatsConfig` | NATS 연결·인증 설정 | [NATS](./config.md#38-nats) | [NATS](./examples.md#6-nats-사용-예시) |
| `ServiceConfigs` | 선택적으로 로드된 config 묶음; `require_*()` 제공 | [설정 로딩 원칙](./config.md#1-공통-원칙) | [선택 로딩](./examples.md#3-필요한-서비스만-선택-로딩하는-예시) |
| `ConfigIssue` | 구조화된 환경변수 검증 문제 | [트러블슈팅](./config.md#6-자주-실패하는-설정-패턴--트러블슈팅) | [사전 진단](./examples.md#11-공개-api-레시피-인덱스) |
| `ServiceConfigurationDiagnosis` | 서비스 하나의 `absent`/`complete`/`partial`/`invalid` 진단 | [사전 설정 진단](./config.md#사전-설정-진단과-서비스-선택) | [사전 진단](./examples.md#11-공개-api-레시피-인덱스) |
| `EnvironmentDiagnosis` | 전체 환경 진단과 JSON-safe `to_dict()` | [사전 설정 진단](./config.md#사전-설정-진단과-서비스-선택) | [사전 진단](./examples.md#11-공개-api-레시피-인덱스) |
| `Service` | 지원 서비스의 typed enum; `required()`/`optional()`/`parse()` | [최소 구성](./config.md#4-최소-구성-가이드) | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `ServiceSelection` | `Service`와 readiness 필수 여부의 immutable 묶음 | [설정 진단](./config.md#사전-설정-진단과-서비스-선택) | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `HealthcheckPolicy` | startup·병렬·개별/전체 timeout 정책 | [공통 원칙](./config.md#1-공통-원칙) | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `RuntimePlan` | typed 서비스 선택, one-of, health 정책 선언 | [사전 설정 진단](./config.md#사전-설정-진단과-서비스-선택) | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `EnvironmentRequirement` | secret을 노출하지 않는 필수 환경변수 metadata | [최소 구성](./config.md#4-최소-구성-가이드) | [catalog 조회](./examples.md#11-공개-api-레시피-인덱스) |
| `ServiceDescriptor` | 서비스 key·config·factory·환경 metadata | [설정값 적용 단계](./config.md#설정값-적용-단계) | [catalog 조회](./examples.md#11-공개-api-레시피-인덱스) |
| `SERVICE_CATALOG` | 불변 `Service` → `ServiceDescriptor` mapping | [서비스별 설정](./config.md#3-서비스별-설정) | [catalog 조회](./examples.md#11-공개-api-레시피-인덱스) |

#### Lifecycle·factory·health API

| 공개 API | 계약 / 이 문서의 상세 위치 | 설정 | 예제 |
| --- | --- | --- | --- |
| `ServiceClientProtocol` | runtime-checkable `check()`/`close()` protocol | — | [custom client hook](./examples.md#11-공개-api-레시피-인덱스) |
| `ServiceHandle` | 이름이 있는 공통 lifecycle handle protocol | — | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `ServiceContainerProtocol` | sync/async container 공통 consumer contract | — | [FastAPI lifecycle](./examples.md#2-fastapi-startup--shutdown-예시) |
| `ServiceClientWrapper` | SDK client의 `check()`/`close()` wrapper; [공통 wrapper](#serviceclientwrapper) | 서비스별 설정 | [서비스별 recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `NatsConnectionBuilder` | lazy NATS connection 및 임시 healthcheck builder | [NATS](./config.md#38-nats) | [NATS](./examples.md#6-nats-사용-예시) |
| `MinioRuntimeDefaults` | MinIO bucket/timeout/retry 보존값 | [MinIO](./config.md#34-minio) | [서비스별 recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `MilvusRuntimeDefaults` | Milvus collection/timeout/retry/TLS 보존값 | [Milvus](./config.md#35-milvus) | [서비스별 recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `OllamaRuntimeDefaults` | Ollama model/retry 보존값 | [Ollama](./config.md#36-ollama) | [서비스별 recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `ServiceBundle` | 문자열 key 동기 lifecycle container | 서비스별 설정 | [동기 assembly](./examples.md#1-권장-가장-작은-assembly-성공-예제) |
| `ServiceRuntime` | `Service` key 비동기 lifecycle container | 서비스별 설정 | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `assemble_services` | 동기 config→factory→health orchestration | [공통 원칙](./config.md#1-공통-원칙) | [동기 assembly](./examples.md#1-권장-가장-작은-assembly-성공-예제) |
| `assemble_service_runtime` | typed async config→factory→health orchestration | [사전 설정 진단](./config.md#사전-설정-진단과-서비스-선택) | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `create_keycloak_client` | `KeycloakAuthService` wrapper factory | [Keycloak](./config.md#31-keycloak-discovery--auth) | [Keycloak recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_postgres_client` | SQLAlchemy PostgreSQL wrapper factory | [PostgreSQL](./config.md#32-postgresql) | [PostgreSQL recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_sqlite_client` | SQLAlchemy SQLite wrapper factory | [SQLite](./config.md#33-sqlite) | [SQLite recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_minio_client` | MinIO wrapper factory | [MinIO](./config.md#34-minio) | [MinIO recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_milvus_client` | Milvus wrapper factory | [Milvus](./config.md#35-milvus) | [Milvus recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_ollama_client` | Ollama wrapper factory | [Ollama](./config.md#36-ollama) | [Ollama recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_langfuse_client` | Langfuse wrapper factory 또는 비활성 시 `None` | [Langfuse](./config.md#37-langfuse) | [Langfuse recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `create_nats_client` | `NatsConnectionBuilder` factory | [NATS](./config.md#38-nats) | [NATS](./examples.md#6-nats-사용-예시) |
| `close_service_clients` | 동기 best-effort close와 실패 집계 | — | [cleanup helper](./examples.md#11-공개-api-레시피-인덱스) |
| `async_close_service_clients` | sync/async close와 실패 집계 | — | [cleanup helper](./examples.md#11-공개-api-레시피-인덱스) |
| `check_all_services` | 동기 서비스 health aggregation | — | [health endpoint](./examples.md#4-health-endpoint-구성-예시) |
| `async_check_all_services` | sync/async health aggregation 및 timeout | — | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `HealthCheckResult` | aggregate health 결과와 `to_dict()` | — | [health endpoint](./examples.md#4-health-endpoint-구성-예시) |
| `ServiceHealthStatus` | 서비스별 health 상태와 latency/error | — | [health endpoint](./examples.md#4-health-endpoint-구성-예시) |

#### 설정 helper·Keycloak·관측성 API

| 공개 API | 계약 / 이 문서의 상세 위치 | 설정 | 예제 |
| --- | --- | --- | --- |
| `load_service_configs` | 선택한 서비스의 환경 설정을 엄격히 로드 | [공통 원칙](./config.md#1-공통-원칙) | [선택 로딩](./examples.md#3-필요한-서비스만-선택-로딩하는-예시) |
| `load_available_service_configs` | 존재하는 후보 설정만 로드하고 부분 설정은 실패 | [공통 원칙](./config.md#1-공통-원칙) | [대안 storage](./examples.md#31-postgresql-또는-sqlite-중-하나-조립하기) |
| `diagnose_services` | client 생성 전 환경/선택 정책 진단 | [사전 설정 진단](./config.md#사전-설정-진단과-서비스-선택) | [사전 진단](./examples.md#11-공개-api-레시피-인덱스) |
| `validate_service_requirements` | required/one-of config 조합 검증 | [공통 원칙](./config.md#1-공통-원칙) | [대안 storage](./examples.md#31-postgresql-또는-sqlite-중-하나-조립하기) |
| `require_minio_bucket` | bucket 사용 제품의 opt-in bucket 검증 | [MinIO](./config.md#34-minio) | [MinIO bucket](./examples.md#11-공개-api-레시피-인덱스) |
| `validate_runtime_security` | production TLS 보안 제약 검증 | [보안 운영](./config.md#5-보안-운영-가이드) | [security validation](./examples.md#11-공개-api-레시피-인덱스) |
| `KeycloakAuthService` | 토큰 획득/JWT 검증 service | [Keycloak](./config.md#31-keycloak-discovery--auth) | [JWT](./examples.md#9-jwt-검증-및-사용자-정보-추출) |
| `AccessTokenResult` | access/refresh token 결과 데이터 | [토큰 획득](./config.md#토큰-획득) | [password grant](./examples.md#12-password-grant-예시) |
| `AuthenticatedUser` | 검증한 JWT 사용자/role/claims 데이터 | [Keycloak](./config.md#31-keycloak-discovery--auth) | [JWT](./examples.md#9-jwt-검증-및-사용자-정보-추출) |
| `KeycloakProvisioner` | 주입한 admin client로 realm/client/role 조립 | [프로비저닝](./config.md#프로비저닝) | [Keycloak provisioning](./examples.md#10-keycloak-프로비저닝) |
| `ProvisioningResult` | created/updated/unchanged/failed/planned 결과 | [프로비저닝](./config.md#프로비저닝) | [Keycloak provisioning](./examples.md#10-keycloak-프로비저닝) |
| `configure_logging` | root logger 구성 | [로깅 규칙](./config.md#로깅-규칙) | [로깅](./examples.md#8-로깅-설정-예시) |
| `build_service_log_event` | 민감값을 마스킹한 구조화 이벤트 생성 | [보안 운영](./config.md#5-보안-운영-가이드) | [관측성 helper](./examples.md#11-공개-api-레시피-인덱스) |
| `mask_sensitive_value` | secret/token/DSN 마스킹 | [보안 운영](./config.md#5-보안-운영-가이드) | [관측성 helper](./examples.md#11-공개-api-레시피-인덱스) |
| `retry_call` | 동기 operation의 지수 backoff 재시도 | — | [관측성 helper](./examples.md#11-공개-api-레시피-인덱스) |

#### 오류 API

모든 오류는 `DocMeshError` 계열의 `service`, `reason_code`, `remediation` 계약과 아래 [오류 taxonomy](#안정적인-오류-taxonomy)를 따릅니다. `KeycloakToken*`과 `TokenValidationError`는 Keycloak service가 발생시키는 구체 오류입니다.

| 공개 API | 발생 지점 | 설정 / 예제 |
| --- | --- | --- |
| `DocMeshError` | 공통 구조화 오류 기반 타입 | [트러블슈팅](./config.md#6-자주-실패하는-설정-패턴--트러블슈팅) |
| `ConfigurationError` | 설정·계획 오류 기반 타입 | [트러블슈팅](./config.md#6-자주-실패하는-설정-패턴--트러블슈팅) |
| `ConfigError` | 환경 설정 로딩/조합 오류; `issues` 제공 | [트러블슈팅](./config.md#6-자주-실패하는-설정-패턴--트러블슈팅) |
| `InvalidRuntimePlanError` | 빈/중복/불일치 runtime plan | [사전 설정 진단](./config.md#사전-설정-진단과-서비스-선택) |
| `UnknownServiceError` | 미지원 서비스 이름 | [공통 원칙](./config.md#1-공통-원칙) |
| `ServiceLookupError` | runtime 조회 오류 기반 타입 | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `ServiceNotSelectedError` | `ServiceRuntime.require()`에서 미선택 서비스 | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `ServiceNotInitializedError` | 선택했지만 client가 없는 서비스 | [async runtime](./examples.md#2-fastapi-startup--shutdown-예시) |
| `ServiceUnavailableError` | 가용성 오류 기반 타입 | [health endpoint](./examples.md#4-health-endpoint-구성-예시) |
| `StartupCheckError` | startup healthcheck 오류 기반 타입 | [health endpoint](./examples.md#4-health-endpoint-구성-예시) |
| `HealthCheckError` | required healthcheck 실패; result/failures 제공 | [health endpoint](./examples.md#4-health-endpoint-구성-예시) |
| `ServiceClientError` | service client operation의 secret-safe 오류 | [서비스별 recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `ServiceClientWrapperError` | wrapper healthcheck 오류 | [서비스별 recipe](./examples.md#7-서비스별-최소-config--check--close-recipe) |
| `ShutdownError` | 종료 오류 기반 타입 | [cleanup helper](./examples.md#11-공개-api-레시피-인덱스) |
| `ServiceCloseFailure` | best-effort cleanup 중 하나의 실패 | [cleanup helper](./examples.md#11-공개-api-레시피-인덱스) |
| `ServiceCloseError` | cleanup 후 전체 실패 집계 | [cleanup helper](./examples.md#11-공개-api-레시피-인덱스) |
| `KeycloakTokenError` | 잘못된 Keycloak token 응답 | [토큰 획득](./config.md#토큰-획득) |
| `KeycloakTokenConfigurationError` | token grant 자격증명 누락 | [password grant](./examples.md#12-password-grant-예시) |
| `KeycloakTokenAuthenticationError` | token endpoint 400/401/403 | [토큰 획득](./config.md#토큰-획득) |
| `KeycloakTokenTemporaryError` | 408/429/5xx 일시 오류 및 재시도 | [토큰 획득](./config.md#토큰-획득) |
| `TokenValidationError` | JWT 형식/서명/claim 검증 실패 | [JWT](./examples.md#9-jwt-검증-및-사용자-정보-추출) |

### 공개 결과 및 오류 데이터 구조

#### `AccessTokenResult`

- `access_token`: `str`; 토큰 원문이므로 로그에 기록하지 않습니다.
- `token_type`: `str`
- `expires_in`: `int`
- `refresh_token`: `str | None`; 토큰 원문이므로 로그에 기록하지 않습니다.
- `scope`: `str | None`

#### `AuthenticatedUser`

- 필수 식별자: `sub: str` (`sub`가 없으면 검증된 `jti`를 사용)
- 선택 사용자 필드: `preferred_username`, `email`, `given_name`, `family_name`, `name`은 모두 `str | None`
- 권한 필드: `realm_roles: list[str]`, `client_roles: dict[str, list[str]]`
- 검증된 전체 JWT payload: `claims: dict[str, Any]`

#### `ProvisioningResult`

- `created`, `updated`, `unchanged`, `planned`: 리소스 식별자 목록
- `failed`: `(리소스 식별자, 마스킹된 오류)` tuple 목록
- `dry_run`: dry-run 실행 여부

#### `ConfigIssue`

- `service`, `env_key`, `reason`, `error_type`, `remediation`
- `ConfigError.issues`와 호환 별칭인 `ConfigError.errors`에서 확인할 수 있습니다.

#### `ServiceCloseFailure`

- `client`: 종료에 실패한 클라이언트 또는 wrapper
- `error`: 원래 종료 예외
- 여러 실패는 `ServiceCloseError.failures`에 tuple로 보존됩니다.

#### 안정적인 오류 taxonomy

모든 공통 오류는 `DocMeshError`를 기준으로 분류되며 `service`, `reason_code`, `remediation` 속성을 제공합니다.

- 설정/계획: `ConfigurationError` → `ConfigError`, `InvalidRuntimePlanError`, `UnknownServiceError`
- 조회: `ServiceLookupError` → `ServiceNotSelectedError`, `ServiceNotInitializedError`
- 가용성: `ServiceUnavailableError` → `ServiceClientError`, `StartupCheckError`; `HealthCheckError`는 `StartupCheckError`의 하위 타입입니다.
- 종료: `ShutdownError` → `ServiceCloseError`

`ServiceRuntime.require()`는 미선택과 미초기화를 조회 오류로 구분합니다. 반면 `ServiceBundle.get_client()`와 `ServiceRuntime.get_client()`는 호환 container API로서 사용할 수 없는 client에 `ConfigError`를 발생시킵니다.

#### `ServiceConfigurationDiagnosis` / `EnvironmentDiagnosis`

- `ServiceConfigurationDiagnosis`: 서비스별 `state`(`absent`, `complete`, `partial`, `invalid`)와 `ConfigIssue` 목록
- `EnvironmentDiagnosis`: 서비스별 진단, `selected_services`, 전역 `issues`, `warnings`, `ok`
- `EnvironmentDiagnosis.to_dict()`는 JSON-friendly dict를 반환하며 raw 환경변수 값이나 secret을 포함하지 않습니다.

#### Runtime defaults

`ServiceClientWrapper.runtime_defaults`에는 SDK 생성자에 직접 전달되지 않은 typed 기본값이 저장될 수 있습니다.

- `MinioRuntimeDefaults`: `bucket`, `request_timeout_seconds`, `max_retries`
- `MilvusRuntimeDefaults`: `collection`, `connect_timeout_seconds`, `max_retries`, `secure`
- `OllamaRuntimeDefaults`: `generation_model`, `embedding_model`, `max_retries`

## 2. 권장 사용 흐름

### Typed service catalog와 runtime plan

- `Service`는 지원 서비스 이름의 canonical typed key입니다.
- `SERVICE_CATALOG`는 변경할 수 없는 `Mapping[Service, ServiceDescriptor]`이며 config type, factory, sync runtime 지원 여부, 생성 순서와 안전한 환경변수 메타데이터를 제공합니다.
- `ServiceDescriptor` 필드는 `service`, `config_type`, `factory`, `supports_sync_runtime`, `order`, `environment`입니다.
- `ServiceDescriptor.required_environment()`는 실제 값이나 secret을 읽지 않고 `EnvironmentRequirement(key, secret=False, required_when=None)` 목록을 반환합니다. 이 목록은 안전한 연결 키 힌트이며 provisioning, 인증 mode, deprecated 대안 등 전체 조건부 validation schema가 아닙니다. 실제 필수 조건은 config model validation과 [config.md](./config.md)를 기준으로 합니다.
- `ServiceSelection`은 하나의 `Service`와 required-readiness 여부를 묶습니다. `Service.required()` / `optional()`이 이 값을 생성합니다.
- `RuntimePlan`은 선택 서비스, required 정책, one-of 그룹과 `HealthcheckPolicy`를 하나의 immutable 객체로 검증합니다. 빈 선택, 중복 서비스, 빈 대안 그룹, 선택되지 않은 대안 서비스, 0 이하 timeout은 `InvalidRuntimePlanError`입니다.
- `ServiceHandle`은 runtime에 저장되는 공통 client 계약으로 `service_name`, `check()`, `close()`를 요구합니다. 동기 `ServiceClientWrapper`와 비동기 `NatsConnectionBuilder`가 이 protocol을 충족합니다.
- `ServiceRuntime.get(Service.X)`는 선택됐지만 초기화되지 않은 경우 `None`을 반환하고, `require(Service.X)`는 미선택과 미초기화를 각각 `ServiceNotSelectedError`, `ServiceNotInitializedError`로 구분합니다.

기존 문자열 기반 `services`, `required`, `one_of` 및 개별 health 인자는 호환성을 위해 유지되지만 deprecated API이며 `DeprecationWarning`이 발생합니다. 새 코드에서는 `plan=`과 typed `Service`를 사용합니다. `diagnose_services()`와 `assemble_service_runtime()`의 legacy 선택/health 인자는 v0.4.0 제거를 목표로 하며, `plan`과 legacy 인자를 한 호출에 혼합하면 오류가 발생합니다.

이 라이브러리는 **assembly-first, direct-api-when-needed** 정책을 따릅니다.

| 상황 | 우선 API | direct API가 필요한 경우 |
| --- | --- | --- |
| 동기 서비스 lifecycle 조립 | `assemble_services()` | 특정 SDK factory hook 또는 client lifecycle을 직접 제어할 때 |
| NATS 또는 async lifecycle 조립 | `assemble_service_runtime()` | NATS builder/SDK 연결을 직접 제어할 때 |
| Keycloak 토큰/JWT 기능만 사용 | `KeycloakAuthService(KeycloakConfig())` | 해당 direct API가 기본 경로 |
| CLI, 배치, 단일 서비스 테스트 | 서비스별 `*Config()` + `create_*_client()` | 해당 direct API가 기본 경로 |

일반 애플리케이션은 아래 순서로 assembly API를 사용합니다.

1. 환경변수 또는 명시적 mapping 준비
2. 동기 서비스는 `assemble_services()`, NATS/async 서비스는 `await assemble_service_runtime()` 호출
3. `RuntimePlan`과 `HealthcheckPolicy`로 구성·startup 정책 선언
4. `ServiceBundle` 또는 `ServiceRuntime`의 context manager로 lifecycle 관리

주의:

- `nats`만 예외적으로 `NatsConnectionBuilder`를 반환하며, 실제 네트워크 연결은 `await connect()` / `await ping()` / `await check()`에서 일어납니다.
- `langfuse`는 `LANGFUSE_ENABLED=false`면 `create_langfuse_client()`가 `None`을 반환할 수 있습니다.
- `CommonConfig.env`는 자유 문자열이며 enum 검증을 하지 않습니다. 운영 판정은 `DOCMESH_SECURITY_MODE`가 있으면 그 값을 우선하고, 없으면 `DOCMESH_PRODUCTION_ALIASES`(기본값 `prod,production`)와 환경 이름을 비교합니다.

## 3. Service config API

### Direct API용 config entrypoint

서비스별 config class 직접 생성은 direct-api-when-needed 경로입니다. 일반 애플리케이션 lifecycle 조립에는 먼저 [assembly API](#5-공통-wrapper--helper-api)의 `assemble_services()` 또는 `assemble_service_runtime()`을 고려하세요.

- 공통: `CommonConfig()`
- Keycloak discovery 전용: `KeycloakDiscoveryConfig()`
- Keycloak 전체: `KeycloakConfig()`
- PostgreSQL: `PostgresConfig()`
- SQLite: `SqliteConfig()`
- MinIO: `MinioConfig()`
- Milvus: `MilvusConfig()`
- Ollama: `OllamaConfig()`
- Langfuse: `LangfuseConfig()`
- NATS: `NatsConfig()`

규칙:

- 서비스별 `*Config()` 직접 생성은 pydantic `ValidationError`를 그대로 발생시킵니다.
- `load_service_configs()`는 선택된 서비스만 읽고, 검증 실패를 `ConfigError`로 다시 감싸서 반환합니다.
- `LANGFUSE_ENVIRONMENT`가 비어 있으면 `CommonConfig().env` 값을 상속합니다.

예시:

```python
from docmesh_py_core import CommonConfig, KeycloakAuthService, KeycloakConfig

common = CommonConfig()
keycloak = KeycloakConfig()

auth = KeycloakAuthService(keycloak)

assert isinstance(common.env, str)
assert keycloak.client_id
```

### 3.2 `load_service_configs(env=None, *, services=None) -> ServiceConfigs`

설정을 읽고 검증합니다. `env`를 생략하면 현재 프로세스 환경변수를 읽고,
`Mapping[str, str]`을 전달하면 해당 mapping만 사용하며 `os.environ`과 병합하거나
수정하지 않습니다.

주요 동작:

- `services=None`이면 지원 서비스 전체(`keycloak`, `postgres`, `sqlite`, `minio`, `milvus`, `ollama`, `langfuse`, `nats`)를 검증합니다.
- `services={...}`를 주면 지정한 서비스만 검증하고, 나머지 필드는 `None`으로 둡니다.
- 지원하지 않는 서비스 이름이 들어오면 `ConfigError`가 발생합니다.
- 선택된 서비스에서 필수 env가 없거나 타입/범위 검증에 실패하면 `ConfigError`가 발생합니다.
- 마지막에 `validate_runtime_security()`를 호출해 production 계열 보안 제약을 확인합니다.

### 3.3 `load_available_service_configs(env, *, services=None) -> ServiceConfigs`

명시한 후보 서비스 중 관련 prefix가 존재하는 서비스만 로딩합니다.

- 관련 키가 전혀 없는 서비스는 결과에서 `None`입니다.
- 관련 키가 하나라도 있지만 설정이 불완전하면 `ConfigError`가 발생합니다.
- 단순 prefix 존재를 유효한 설정으로 간주하지 않고 실제 config validation을 수행합니다.

PostgreSQL과 SQLite 같은 대안 서비스 후보를 전역 backend selector 없이 탐색할 때 사용할 수 있습니다.

예시:

```python
from docmesh_py_core import load_available_service_configs

settings = load_available_service_configs(
    {"SQLITE_PATH": ":memory:"},
    services={"postgres", "sqlite"},
)

assert settings.postgres is None
assert settings.sqlite is not None
```

### 3.4 `diagnose_services(env, *, plan=None, services=None, required=None, one_of=(), selection_mode="auto") -> EnvironmentDiagnosis`

실제 client 생성이나 네트워크 접속 없이 환경변수와 서비스 조합 정책을 진단합니다.

- `auto`: 완전한 설정을 가진 후보만 `selected_services`에 포함합니다.
- `explicit`: 호출자가 전달한 후보만 검사합니다.
- `strict`: 대안 그룹에서 복수의 완전한 서비스가 발견되면 `ambiguous_service_alternative` issue를 추가합니다.
- 부분 설정과 validation 오류는 예외로 즉시 중단하지 않고, 서비스별 및 전역 `issues`로 집계합니다.

### 3.5 서비스 조합 및 MinIO bucket 검증

- `validate_service_requirements(configs, required=..., one_of=...)`는 필수 서비스와 대안 서비스 그룹을 검증하고 현재 구성된 서비스 이름을 반환합니다.
- `require_minio_bucket(config)`은 제품이 bucket을 필수로 사용할 때 opt-in으로 검증하고 bucket 이름을 반환합니다.
- 두 helper의 실패는 구조화된 `ConfigError.issues`로 제공됩니다.

### 3.6 `ServiceConfigs`

서비스 설정 묶음 dataclass입니다.

필드:

- `common: CommonConfig`
- `keycloak: KeycloakConfig | None`
- `postgres: PostgresConfig | None`
- `sqlite: SqliteConfig | None`
- `minio: MinioConfig | None`
- `milvus: MilvusConfig | None`
- `ollama: OllamaConfig | None`
- `langfuse: LangfuseConfig | None`
- `nats: NatsConfig | None`

추가 속성:

- `docmesh_env -> str`: `common.env`를 그대로 반환하는 convenience property

각 optional 필드에는 `require_keycloak()`, `require_postgres()`, `require_sqlite()`, `require_minio()`, `require_milvus()`, `require_ollama()`, `require_langfuse()`, `require_nats()`가 대응합니다. 로딩된 config는 non-optional 타입으로 반환하고, 로딩되지 않은 서비스는 구조화된 `ConfigError`를 발생시킵니다.

## 4. Client creation API

서비스별 `create_*_client()` 함수는 direct-api-when-needed 경로입니다. 일반 애플리케이션 lifecycle 조립에는 `assemble_services()` 또는 `assemble_service_runtime()`을 우선 사용합니다.

모든 factory는 테스트와 특수 실행 환경을 위해 keyword-only `client_factory` hook을 제공합니다. NATS는 `connect_factory`, SQLite는 추가로 `configure_engine`을 지원합니다.

### Factory 확장 hook

- `client_factory`: 기본 SDK 생성자를 대체합니다. 기본 생성자와 같은 인자를 받고 호환 client를 반환해야 합니다.
- `connect_factory`: NATS 연결 함수를 대체합니다. `NatsConnectionBuilder.connect_kwargs`를 받아 client 또는 awaitable client를 반환해야 합니다.
- `configure_engine`: `(engine, SqliteConfig)`를 받아 SQLite pragma/listener 구성을 대체합니다.
- `engine_options`: PostgreSQL/SQLite의 SQLAlchemy 옵션을 확장합니다. `connect_args`는 기본값과 중첩 병합됩니다.
- `factory_overrides`: `assemble_service_runtime()`에서 서비스 이름별 `(config) -> client` factory를 대체합니다.

이 hook들은 mock 기반 단위 테스트나 명시적인 실행 환경 대체에 적합합니다. 반환 객체는 해당 서비스의 healthcheck와 lifecycle 계약을 충족해야 합니다.

### `create_keycloak_client(config: KeycloakConfig, *, client_factory=None) -> ServiceClientWrapper`

- 내부적으로 `KeycloakAuthService(config)`를 생성합니다.
- `check()` / `ping()`는 `fetch_access_token()`을 호출합니다.
- 기본 `password` grant에서 startup healthcheck를 사용하려면 config의 `token_username`과 `token_password`가 모두 필요합니다. `client_credentials`를 명시한 경우에는 client secret 경로를 사용합니다.

### `create_postgres_client(config: PostgresConfig, *, engine_options=None, client_factory=None) -> ServiceClientWrapper[Engine]`

- SQLAlchemy engine을 생성합니다.
- `POSTGRES_DSN`은 deprecated이며 사용 시 `DeprecationWarning`이 발생합니다. 새 설정은 host/port/db/user/password 조합을 사용합니다.
- 하위 호환용 DSN과 개별 연결 필드를 함께 설정하면 설정 오류가 발생합니다.
- `check()` / `ping()`는 `SELECT 1`을 실행합니다.
- `close()`는 내부 `dispose()`를 호출합니다.
- `engine_options`는 SQLAlchemy `create_engine()` 옵션을 확장하며, 중첩된 `connect_args`는 기본 연결 옵션과 병합됩니다.

### `create_sqlite_client(config: SqliteConfig, *, engine_options=None, client_factory=None, configure_engine=None) -> ServiceClientWrapper[Engine]`

- SQLAlchemy engine을 생성합니다.
- `config.path == ":memory:"`를 지원합니다.
- `readonly`, `enable_wal`, `busy_timeout_ms`를 반영합니다.
- `check()` / `ping()`는 `SELECT 1`을 실행합니다.
- `close()`는 내부 `dispose()`를 호출합니다.
- `engine_options`와 `connect_args`를 추가하거나 기본값 위에 덮어쓸 수 있습니다.

### `create_minio_client(config: MinioConfig, *, client_factory=None) -> ServiceClientWrapper`

- `Minio(...)` 클라이언트를 즉시 생성합니다.
- `secure` 값은 `cert_check`에도 그대로 반영됩니다.
- `check()` / `ping()`는 `list_buckets()`를 호출합니다.

### `create_milvus_client(config: MilvusConfig, *, client_factory=None) -> ServiceClientWrapper`

- `MilvusClient(...)`를 생성합니다.
- `check()` / `ping()`는 `list_collections()`를 호출합니다.

### `create_ollama_client(config: OllamaConfig, *, client_factory=None) -> ServiceClientWrapper`

- `ollama.Client(...)`를 생성합니다.
- `check()` / `ping()`는 `ps()`를 호출합니다.

### `create_langfuse_client(config: LangfuseConfig, *, client_factory=None) -> ServiceClientWrapper | None`

- `config.enabled`가 `False`면 `None`을 반환합니다.
- 활성화 시 `Langfuse(...)`를 생성합니다.
- `check()` / `ping()`는 `auth_check()`를 호출합니다.
- `close()`는 `flush()`를 호출합니다.

### `create_nats_client(config: NatsConfig, *, connect_factory=None) -> NatsConnectionBuilder`

- 즉시 연결하지 않습니다.
- 실제 네트워크 연결은 `await builder.connect()` / `await builder.ping()` / `await builder.check()`에서 일어납니다.
- `connect()`가 반환한 연결은 호출자가 종료해야 합니다. builder는 지속 연결을 소유하지 않으며 `builder.close()`는 no-op입니다.
- `ping()` / `check()`는 임시 연결 후 `flush()`를 수행하고 연결을 정리합니다. 반환값은 이미 종료된 임시 연결이므로 지속 작업에 사용하지 않습니다.

예시:

```python
from docmesh_py_core import create_postgres_client, load_service_configs

settings = load_service_configs(services={"postgres"})
postgres = create_postgres_client(settings.require_postgres())

postgres.check()
postgres.close()
```

## 5. 공통 wrapper / helper API

### `ServiceClientWrapper`

서비스 클라이언트를 표준 인터페이스로 감싸는 `ServiceClientWrapper[T]` 제네릭 wrapper입니다.
underlying `client`의 타입을 보존합니다.

주요 메서드:

- `check()` / `ping()`
- `close()`
- `unwrap() -> T`
- `__getattr__()` 위임

동작 규칙:

- healthcheck 호출 중 예외가 발생하면 `ServiceClientWrapperError`로 변환합니다.
- 오류 메시지는 `mask_sensitive_value()`를 거쳐 민감정보를 숨깁니다.
- `close_fn`이 있으면 그 함수를 우선 호출하고, 없으면 내부 client의 `close()`를 찾습니다.
- SDK 생성자에 직접 전달할 수 없는 기본 resource/retry 값은 서비스별 typed `runtime_defaults`로 보존됩니다.

### `close_service_clients(clients: Iterable[Any]) -> None`

여러 wrapper/client에 대해 `close()`를 순회 호출합니다. `None` 값은 무시합니다.

### `async_close_service_clients(clients) -> None`

동기·비동기 `close()` 반환을 모두 수용합니다. 한 client의 종료 실패와 관계없이 나머지 client를 계속 정리하며, 실패가 있으면 전체 `ServiceCloseFailure`를 담은 `ServiceCloseError`를 발생시킵니다.

### `assemble_services(...) -> ServiceBundle`

mapping 기반 설정 로딩, available 서비스 탐지, required/one-of 검증, 클라이언트 생성과 선택적 startup healthcheck를 한 번에 수행합니다.

- `services`: 탐색할 서비스 후보
- `required`: 반드시 구성되어야 하는 서비스
- `one_of`: 각 그룹에서 하나 이상 필요한 대안 서비스 조합
- `engine_options`: `postgres`/`sqlite`별 SQLAlchemy 옵션
- `factory_overrides`: 서비스 이름별 `(config) -> ServiceClientWrapper | None` factory 대체
- `healthcheck_overrides`: 서비스 이름별 startup/수동 healthcheck 함수 대체
- `lifecycle_hook`: client 생성 뒤 `(service_name, wrapper)`를 받는 hook
- `check_on_startup`: 생성 직후 healthcheck 실행 여부
- `parallel_healthchecks`: startup healthcheck 병렬 실행 여부

`ServiceBundle`은 문자열 키를 사용합니다(`clients: dict[str, ...]`, `selected_services: frozenset[str]`). `configs`, `clients`, `checks`, `selected_services`, `required_services`를 제공하며 `get_client()`, 동기 `check()`/`close()`와 `with` context manager를 지원합니다. factory 생성, lifecycle hook 또는 startup healthcheck가 실패하면 이미 생성된 클라이언트의 종료를 시도합니다. cleanup 실패는 원래 예외의 note에 추가됩니다.

NATS는 비동기 lifecycle이므로 동기 `ServiceBundle` 조립 대상에서 제외되며 `create_nats_client()`로 별도 생성해야 합니다.

### `assemble_service_runtime(...) -> ServiceRuntime`

NATS를 포함해 동기·비동기 서비스를 함께 조립하는 비동기 runtime API입니다. `await assemble_service_runtime(...)`으로 생성하며 `async with`를 지원합니다.

`ServiceRuntime`은 `Service` enum 키를 사용합니다(`clients: dict[Service, ServiceHandle]`, `selected_services: frozenset[Service]`). `required_services`도 `frozenset[Service]`이며 `check()`와 `close()`는 비동기입니다.

`plan=None`으로 호출하는 기존 인자 방식은 deprecated이며 `DeprecationWarning`을 발생시킵니다. 이 legacy 인자들은 v0.4.0 제거를 목표로 합니다. `services`, `required`, `one_of`, `check_on_startup`, `parallel_healthchecks`와 timeout 인자 대신 `RuntimePlan`을 `plan=`으로 전달하세요. 같은 계획은 `diagnose_services(env, plan=plan)`에도 재사용할 수 있으며, 해당 API의 legacy 선택 인자도 동일한 제거 정책을 따릅니다.

- sync/async health check를 한 API에서 실행
- 개별 health check timeout과 전체 timeout 지원
- 생성 또는 startup health check 실패 시 생성 완료 client rollback
- 종료 실패와 관계없이 모든 client에 best-effort cleanup 수행
- `factory_overrides`로 명시적인 서비스별 factory 대체 지원
- `runtime.require(name)`으로 생성된 client 조회

### `async_check_all_services(...)`

동기 함수와 awaitable health check를 모두 실행합니다. `parallel`, `timeout_seconds`, `overall_timeout_seconds`를 지원합니다. 개별 `timeout_seconds`는 서비스 실패 상태로 변환되며 required 실패 시 `HealthCheckError.result`와 `failures`에서 전체 상태를 확인할 수 있습니다. 전체 제한인 `overall_timeout_seconds`를 넘으면 부분 결과를 만들지 않고 `asyncio.TimeoutError`가 직접 전파됩니다. optional 서비스만 실패해도 반환된 `HealthCheckResult.ok`는 `False`입니다.

### `ServiceContainerProtocol`

소비자 SDK가 내부 `clients` dict나 `ServiceClientWrapper` 구조에 직접 결합하지 않도록 하는 최소 runtime 계약입니다.

- `configs`
- `selected_services`
- `get_client(service)`
- `check()`
- `close()`

`ServiceBundle`과 `ServiceRuntime` 모두 이 protocol을 충족합니다. `get_client()`는 client가 없으면 `ConfigError`를 발생시킵니다. `ServiceRuntime.require()`는 typed runtime 전용 조회 API로, 미선택과 미초기화를 각각 `ServiceNotSelectedError`, `ServiceNotInitializedError`로 구분합니다.

### 주요 예외 및 cleanup 계약

| API | 주요 실패 | cleanup 계약 |
| --- | --- | --- |
| `load_service_configs()` | `ConfigError` | 클라이언트를 생성하지 않음 |
| `ServiceClientWrapper.check()` | `ServiceClientWrapperError` | 자동 종료하지 않음 |
| `check_all_services()` / `async_check_all_services()` | required 실패 시 `HealthCheckError` | 호출자가 lifecycle을 관리 |
| `assemble_services()` | 설정/생성/hook/startup healthcheck 예외 | 이미 생성한 client 종료를 시도하며 cleanup 실패는 원래 예외 note에 추가 |
| `assemble_service_runtime()` 생성 단계 | 설정/생성 예외 | 이미 생성한 client를 닫고 cleanup 실패는 원래 예외 note에 추가 |
| `assemble_service_runtime()` startup 단계 | healthcheck/overall timeout 예외 | `runtime.close()`를 시도하며, close도 실패하면 현재 구현에서는 `ServiceCloseError`가 원래 startup 예외를 대체할 수 있음 |
| `async_close_service_clients()` | 종료 실패 시 `ServiceCloseError` | 나머지 client 종료를 계속 시도하고 전체 실패를 보존 |

동기 `close_service_clients()`와 비동기 `async_close_service_clients()`는 모두 종료를 가능한 한 계속 시도하고, 하나 이상 실패하면 `ServiceCloseError.failures`에 전체 실패를 집계합니다.

### `check_all_services(service_checks, *, required_services=None, timer=time.perf_counter, parallel=False)`

서비스 헬스체크 함수를 모아 실행합니다.

반환값:

- `HealthCheckResult(ok: bool, services: list[ServiceHealthStatus])`

각 항목:

- `ServiceHealthStatus(service, ok, latency_ms, required=False, error=None, error_type=None)`
- `HealthCheckResult.to_dict()`와 `ServiceHealthStatus.to_dict()`는 JSON-friendly dict를 반환합니다.

규칙:

- `parallel=False`면 입력 순서대로 순차 실행합니다.
- `parallel=True`면 `ThreadPoolExecutor`로 병렬 실행하지만 반환 순서는 입력 순서를 유지합니다.
- required 서비스가 실패하면 `HealthCheckError`를 발생시킵니다.
- `HealthCheckError.status`는 첫 번째 required 서비스 실패 상태를 제공합니다.
- `HealthCheckError.failures`는 실패한 required 서비스 전체를 제공합니다.
- `HealthCheckError.result`는 optional 서비스를 포함한 전체 healthcheck 결과를 제공합니다.
- 오류 문자열은 마스킹됩니다.

### `mask_sensitive_value(value: str | None) -> str | None`

민감정보를 로그 친화적으로 마스킹합니다.

주요 동작:

- URL/DSN이면 사용자정보와 민감 query parameter를 마스킹합니다.
- raw token/secret/password 계열 문자열도 `***` 또는 `key=***` 형태로 변환합니다.
- 민감 키워드가 없는 일반 진단 문자열은 보존합니다.

### `retry_call(operation, *args, retry_on=..., max_attempts=..., base_delay_seconds=0.5, sleep=time.sleep, **kwargs)`

동기 함수 재시도 helper입니다.

- `max_attempts`는 1 이상이어야 합니다.
- 실패 간격은 지수 백오프(`0.5`, `1.0`, `2.0`, ...)입니다.
- 재시도 대상 예외만 다시 시도하고, 마지막 시도에서도 실패하면 원래 예외를 그대로 올립니다.

### `build_service_log_event(...) -> dict[str, Any]`

서비스 이벤트를 구조화된 dict로 생성합니다.

기본 키:

- `service`
- `operation`
- `outcome`
- optional: `host`, `latency_ms`, `retry_count`, `error`

`error`와 민감한 `extra` 필드는 마스킹됩니다.

`host`는 진단용 문자열로 그대로 저장되므로 credential이나 민감 query parameter가 포함된 URL/DSN을 전달하면 안 됩니다. generic `log_function_boundary()`도 예외 메시지를 별도로 마스킹하지 않으므로, 호출자는 예외를 발생시키기 전에 민감값을 제거하거나 `mask_sensitive_value()`를 적용해야 합니다.

### `configure_logging(*, level=None, log_path=None, force=False, env=None, env_key="DOCMESH_LOG_LEVEL") -> logging.Logger`

루트 로거를 설정합니다.

동작:

- `level`이 주어지면 그 값을 우선 사용합니다.
- 아니면 `DOCMESH_LOG_LEVEL` 환경변수를 읽습니다.
- 값이 없거나 빈 문자열이면 `INFO`를 사용합니다.
- 잘못된 로그 레벨이면 `ValueError`를 발생시킵니다.
- `log_path`가 있으면 부모 디렉터리를 생성한 뒤 파일 핸들러를 추가합니다.

## 6. Keycloak API

### `KeycloakAuthService(config: KeycloakConfig, *, http_client=None, verification_key=None, allowed_algorithms=None, logger=None, event_logger=None, timer=..., sleep=..., current_time=...)`

Keycloak 토큰 획득과 JWT 검증을 담당합니다.

주요 속성/메서드:

- `issuer`
- `token_endpoint`
- `jwks_endpoint`
- `fetch_access_token(...) -> AccessTokenResult`
- `extract_user_info(token: str) -> AuthenticatedUser`

기본 `allowed_algorithms`는 `['HS256']`입니다. RS256 검증을 사용하려면 `allowed_algorithms=['RS256']` 또는 필요한 허용 목록을 명시합니다. `http_client`, clock/sleep/logger 인자는 테스트와 실행 환경 확장 hook입니다.

### `fetch_access_token(*, scope=None, username=None, password=None) -> AccessTokenResult`

- 기본 grant type은 `password`이며 `client_credentials`도 명시적으로 선택할 수 있습니다.
- password grant는 함수 인자를 우선 사용하고, 생략된 값은 `config.token_username`, `config.token_password`에서 가져옵니다.
- 두 입력 경로에도 username/password가 모두 갖춰지지 않으면 `KeycloakTokenConfigurationError`가 발생합니다.
- 일시적 장애(`KeycloakTokenTemporaryError`)는 `config.max_retries + 1`번까지 재시도합니다.
- 재시도 이벤트는 `build_service_log_event()` 형식으로 로깅됩니다.
- 자격증명 누락은 `KeycloakTokenConfigurationError`, HTTP 400/401/403은 `KeycloakTokenAuthenticationError`, 408/429/5xx는 `KeycloakTokenTemporaryError`, 그 밖의 잘못된 응답은 `KeycloakTokenError`입니다. 자동 재시도 대상은 temporary 오류뿐입니다.

### `extract_user_info(token: str) -> AuthenticatedUser`

- `Bearer <jwt>` 형식과 raw JWT 문자열을 모두 받습니다.
- `HS256`과 `RS256` 검증 경로를 지원합니다.
- `audience`가 설정되면 audience 검증을 수행하고, 없으면 audience 검증을 끕니다.
- RS256에서는 JWKS 캐시(`jwks_cache_ttl_seconds`)를 사용하고, 필요 시 refresh합니다.
- 반환 객체에는 `sub`, `preferred_username`, `email`, `given_name`, `family_name`, `name`, `realm_roles`, `client_roles`, `claims`가 포함됩니다.

### `KeycloakProvisioner(config: KeycloakConfig, *, admin_client)`

Realm / Client / Role 프로비저닝 orchestration을 담당합니다.

- `config.provisioning_dry_run=True`면 실제 변경 없이 `planned`만 채웁니다.
- 실제 실행 시 결과를 `created`, `updated`, `unchanged`, `failed`로 나눕니다.
- 선언에서 빠진 리소스를 자동 삭제하지 않습니다.

## 7. Runtime security API

### `validate_runtime_security(common, *, keycloak=None, minio=None, milvus=None) -> None`

현재 구현은 `CommonConfig.is_production`이 참인 환경에서 아래 제약만 검사합니다.

- `KEYCLOAK_VERIFY_SSL=false` 금지
- `MINIO_SECURE=false` 금지
- `MILVUS_SECURE=false` 금지

`is_production`은 `security_mode`가 명시되면 그 값을 사용하고, 아니면 소문자 환경 이름이 `production_aliases`에 포함되는지 확인합니다.
