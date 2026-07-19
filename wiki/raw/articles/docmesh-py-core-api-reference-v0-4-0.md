---
source_url: https://github.com/kyundae-kim/docmesh-py-core/wiki/API-Reference-v0.4.0
ingested: 2026-07-19
sha256: 519eeb198aac5900d089efe868fdbe4eca477405adb41db79261b7a6b5e603a2
---
# docmesh-py-core 공개 API 레퍼런스

> 기준: **v0.4.0** · Python 3.11+
>
> 이 문서는 패키지 루트 `docmesh_py_core`의 `__all__`을 공개 계약으로 삼는다. 구현 모듈의 비공개 심볼과 `docmesh_py_core.config`·`docmesh_py_core.factories`의 facade 전용 심볼은 신규 코드의 import 대상이 아니다. 설정값은 반드시 [Configuration Guide](./config.md)의 환경변수에서 읽고, 실행 흐름은 [Examples](./examples.md)를 따른다.

## 1. 선택 안내

| 목적 | 권장 공개 API | 예제 |
| --- | --- | --- |
| 일반 애플리케이션 bootstrap | `RuntimePlan`, `assemble_service_runtime` | [비동기 runtime](./examples.md#1-runtimeplan-기반-비동기-bootstrap) |
| 설정만 사전 점검 | `diagnose_services` | [사전 진단](./examples.md#2-네트워크-연결-전-설정-진단) |
| CLI·배치의 동기 통합 | `assemble_services` | [동기 SQLite](./examples.md#3-동기-direct-api-sqlite) |
| 특정 SDK 직접 사용 | `load_service_configs`, `create_*_client` | [direct API](./examples.md#3-동기-direct-api-sqlite) |
| 인증·JWT | `KeycloakAuthService` | [Keycloak](./examples.md#4-keycloak-token과-jwt-사용자-정보) |
| 선언형 Keycloak 초기화 | `KeycloakProvisioner` | [provisioning](./examples.md#5-keycloak-provisioning-dry-run) |

## 2. 공개 API 추적표

아래 표의 **모든 이름은 package root에서 import 가능**하며, `경로`는 세부 계약 또는 관련 가이드의 위치다. 이 표는 공개 API 변경 검토와 문서 누락 검증의 기준이다.

| 영역 | 공개 이름 | 역할 | 경로 |
| --- | --- | --- | --- |
| 설정 | `CommonConfig`, `KeycloakDiscoveryConfig`, `KeycloakConfig`, `PostgresConfig`, `SqliteConfig`, `MinioConfig`, `MilvusConfig`, `OllamaConfig`, `LangfuseConfig`, `NatsConfig` | 환경변수 기반 Pydantic 설정 모델 | [§3](#3-설정과-진단) / [config](./config.md) |
| 설정 | `ServiceConfigs`, `load_service_configs`, `load_available_service_configs`, `diagnose_services`, `require_minio_bucket`, `validate_service_requirements`, `validate_runtime_security` | 설정 로딩·진단·정책 검증 | [§3](#3-설정과-진단) |
| 설정 결과 | `ConfigIssue`, `ServiceConfigurationDiagnosis`, `EnvironmentDiagnosis`, `ConfigError` | secret-safe 진단 결과와 오류 | [§3](#3-설정과-진단) |
| 계획 | `Service`, `ServiceSelection`, `RuntimePlan`, `HealthcheckPolicy`, `StartupFailureMode`, `minimal_runtime_plan`, `production_runtime_plan`, `authenticated_runtime_plan` | 서비스 선택과 startup 정책 | [§4](#4-runtime-plan과-preset) |
| 카탈로그 | `SERVICE_CATALOG`, `ServiceDescriptor`, `EnvironmentRequirement` | 서비스·환경변수 메타데이터 조회 | [§5](#5-서비스-카탈로그) |
| 조립 | `assemble_service_runtime`, `assemble_services`, `ServiceRuntime`, `ServiceBundle` | async/sync lifecycle 소유 | [§6](#6-조립-lifecycle과-조회) |
| client | `create_keycloak_client`, `create_postgres_client`, `create_sqlite_client`, `create_minio_client`, `create_milvus_client`, `create_ollama_client`, `create_langfuse_client`, `create_nats_client` | 서비스별 factory | [§7](#7-서비스별-factory와-client-계약) |
| client | `ServiceClientWrapper`, `NatsConnectionBuilder`, `ServiceHandle`, `ServiceClientProtocol`, `ServiceContainerProtocol`, `ServiceClientError`, `ServiceClientWrapperError` | 공통 client/lifecycle 계약 | [§7](#7-서비스별-factory와-client-계약) |
| client 결과 | `MinioRuntimeDefaults`, `MilvusRuntimeDefaults`, `OllamaRuntimeDefaults` | wrapper가 보존하는 서비스 기본값 | [§7](#7-서비스별-factory와-client-계약) |
| 상태·종료 | `ServiceHealthStatus`, `HealthCheckResult`, `HealthCheckError`, `check_all_services`, `async_check_all_services`, `close_service_clients`, `async_close_service_clients`, `ServiceCloseFailure`, `ServiceCloseError` | 상태 집계와 best-effort 종료 | [§8](#8-healthcheck와-종료) |
| Keycloak | `KeycloakAuthService`, `KeycloakProvisioner`, `AccessTokenResult`, `AuthenticatedUser`, `ProvisioningResult` | token, JWT, provisioning | [§9](#9-keycloak) |
| Keycloak 오류 | `KeycloakTokenError`, `KeycloakTokenConfigurationError`, `KeycloakTokenAuthenticationError`, `KeycloakTokenTemporaryError`, `TokenValidationError` | 인증·검증 실패 분류 | [§9](#9-keycloak) |
| 공통 오류 | `DocMeshError`, `ConfigurationError`, `InvalidRuntimePlanError`, `UnknownServiceError`, `ServiceLookupError`, `ServiceNotSelectedError`, `ServiceNotInitializedError`, `ServiceUnavailableError`, `StartupCheckError`, `ShutdownError` | 안정적인 오류 분류 | [§10](#10-오류-계약) |
| 유틸리티 | `configure_logging`, `build_service_log_event`, `retry_call`, `mask_sensitive_value` | logging, event, retry, masking | [§11](#11-유틸리티) |

## 3. 설정과 진단

### 설정 모델

각 `*Config`는 **인자 없이** 생성하며 실행 프로세스 환경변수에서만 읽는다. `KeycloakDiscoveryConfig`는 issuer discovery에 필요한 `KEYCLOAK_URL`, `KEYCLOAK_REALM`만 읽고, 나머지 설정 모델은 해당 서비스의 전체 연결 설정을 검증한다. 필드·기본값·조건부 필수 규칙은 [Configuration Guide](./config.md#3-서비스별-환경변수-레퍼런스)를 참조한다.

```python
from docmesh_py_core import CommonConfig, SqliteConfig

common = CommonConfig()  # DOCMESH_* 환경변수
sqlite = SqliteConfig()  # SQLITE_* 환경변수
```

| API | 계약 |
| --- | --- |
| `ServiceConfigs` | `common`과 선택적으로 로드된 8개 설정을 담는다. `require_sqlite()` 등 `require_<service>()`는 미로드 상태에 `ConfigError`를 발생시킨다. |
| `load_service_configs(*, services: set[str] \| None = None)` | 선택 서비스의 설정을 모두 요구한다. `None`은 8개 전체를 선택한다. validation 오류를 구조화 `ConfigError`로 변환하고 production transport 보안을 확인한다. |
| `load_available_service_configs(*, services: set[str] \| None = None)` | 접두 환경변수가 전혀 없는 선택 서비스는 건너뛴다. 일부만 존재하는 서비스는 `ConfigError`다. |
| `diagnose_services(*, plan: RuntimePlan, selection_mode='auto')` | 네트워크 연결 없이 `EnvironmentDiagnosis`를 반환한다. `strict`는 대안 그룹에 둘 이상이 구성된 상태도 issue로 보고한다. |
| `require_minio_bucket(config)` | `MINIO_BUCKET`이 없으면 해당 키를 포함한 `ConfigError`를 발생시킨다. |
| `validate_service_requirements(configs, *, required=None, one_of=())` | 로드된 설정에 대해 required/one-of 정책을 확인하고 구성된 서비스 집합을 반환한다. |
| `validate_runtime_security(common, *, keycloak=None, minio=None, milvus=None)` | production에서 `KEYCLOAK_VERIFY_SSL`, `MINIO_SECURE`, `MILVUS_SECURE` 비활성화를 거부한다. |

### 진단 결과

- `ConfigIssue(service, env_key, reason, error_type, remediation=None)` — 한 개의 안전한 설정 문제이며 `to_dict()`를 제공한다.
- `ServiceConfigurationDiagnosis(service, state, issues=(), applied_defaults={})` — 상태는 `absent`, `complete`, `partial`, `invalid` 중 하나이며 `to_dict()`를 제공한다.
- `EnvironmentDiagnosis(services, selected_services, issues=(), warnings=())` — `ok` property와 JSON-safe `to_dict()`를 제공한다.
- `ConfigError(message, *, issues=())` — `issues`, `errors`, `env_keys`, `service`, `reason_code`, `remediation`을 제공한다.

## 4. Runtime plan과 preset

```python
RuntimePlan(
    services=(Service.SQLITE.required(), Service.NATS.optional()),
    one_of=((Service.SQLITE, Service.POSTGRES),),
    healthcheck=HealthcheckPolicy(on_startup=True, timeout_seconds=5),
)
```

| API | 계약 |
| --- | --- |
| `Service` | `KEYCLOAK`, `POSTGRES`, `SQLITE`, `MINIO`, `MILVUS`, `OLLAMA`, `LANGFUSE`, `NATS` enum. `parse()`, `required()`, `optional()`을 제공한다. |
| `ServiceSelection(service, required=False)` | 한 서비스와 readiness 필수 여부를 나타낸다. |
| `RuntimePlan(services, one_of=(), healthcheck=...)` | immutable 선언이다. 빈 선택·중복·비어 있는 대안 그룹·미선택 대안은 `InvalidRuntimePlanError`다. `selected_services`, `required_services`, `alternative_groups`를 제공한다. |
| `HealthcheckPolicy(...)` | `on_startup`, `parallel`, 서비스/전체 timeout, `failure_mode`, `attempts`, `retry_delay_seconds`를 가진다. timeout은 양수, attempts는 1 이상, delay는 0 이상이어야 한다. |
| `StartupFailureMode` | `FAIL`은 필수 startup 실패 시 종료, `REPORT`는 결과를 runtime에 남기고 반환한다. |
| `minimal_runtime_plan()` | required SQLite 한 개의 로컬 preset을 반환한다. |
| `production_runtime_plan(services)` | 선언한 모든 서비스를 required로 하고 병렬 startup check, 10초/30초 timeout, 3회 재시도를 적용한다. |
| `authenticated_runtime_plan(services=(), *, healthcheck=None)` | required Keycloak을 추가하고 다른 선택의 required/optional 의미를 유지한다. |

## 5. 서비스 카탈로그

`SERVICE_CATALOG: Mapping[Service, ServiceDescriptor]`는 8개 서비스의 설정 type, factory, sync runtime 지원 여부, 순서 및 환경변수 metadata의 immutable catalog다. 값 또는 secret 원문을 읽지 않는다.

- `ServiceDescriptor.required_environment()`는 required/conditional-required `EnvironmentRequirement`만 반환한다.
- `ServiceDescriptor.environment_variables()`는 required, 기본값, secret 여부, production constraint를 포함한 전체 metadata를 반환한다.
- `EnvironmentRequirement(key, secret=False, required_when=None, required=True, default=None, production_constraint=None)`는 한 환경변수의 safe metadata다.

## 6. 조립, lifecycle과 조회

| API | 계약 |
| --- | --- |
| `async assemble_service_runtime(*, plan, engine_options=None)` | 표준 bootstrap. plan으로 available 설정을 로드·검증하고 async `ServiceRuntime`을 만든다. factory 또는 startup check 실패 시 생성된 자원을 정리한다. `engine_options`는 `postgres`/`sqlite` SQLAlchemy engine 옵션에만 사용한다. |
| `assemble_services(*, services=None, required=None, one_of=(), engine_options=None, check_on_startup=False, parallel_healthchecks=False)` | 동기 direct API. NATS는 지원하지 않으며 포함 시 `ConfigError`가 발생한다. |
| `ServiceRuntime` | async container. `get()`은 미선택을 `None`으로, `require()`는 `ServiceNotSelectedError` 또는 `ServiceNotInitializedError`로 구분한다. `check()`, `close()`, `async with`와 `startup_healthcheck_result`를 제공한다. |
| `ServiceBundle` | sync container. `get_client()`, `check()`, `close()`, `with`를 제공한다. |

## 7. 서비스별 factory와 client 계약

모든 `create_*_client(config)` factory는 설정 모델을 받아 client 또는 `ServiceClientWrapper`를 반환한다. 예외는 `create_langfuse_client()`(disabled면 `None`)와 `create_nats_client()`(지연 연결 builder)다.

| API | 반환·healthcheck |
| --- | --- |
| `create_keycloak_client(KeycloakConfig)` | `ServiceClientWrapper[KeycloakAuthService]`; token 획득으로 상태 확인 |
| `create_postgres_client(PostgresConfig, *, engine_options=None)` | SQLAlchemy engine wrapper; `SELECT 1`; `close()`는 dispose |
| `create_sqlite_client(SqliteConfig, *, engine_options=None)` | SQLite engine wrapper; busy timeout/WAL을 적용하고 `SELECT 1` |
| `create_minio_client(MinioConfig)` | MinIO wrapper; bucket 목록으로 상태 확인; `MinioRuntimeDefaults(bucket, request_timeout_seconds, max_retries)` 보존 |
| `create_milvus_client(MilvusConfig)` | Milvus wrapper; collection 목록으로 상태 확인; `MilvusRuntimeDefaults(collection, connect_timeout_seconds, max_retries, secure)` 보존 |
| `create_ollama_client(OllamaConfig)` | Ollama wrapper; process 목록으로 상태 확인; `OllamaRuntimeDefaults(generation_model, embedding_model, max_retries)` 보존 |
| `create_langfuse_client(LangfuseConfig)` | enabled일 때 Langfuse wrapper와 `auth_check`, disabled일 때 `None` |
| `create_nats_client(NatsConfig)` | `NatsConnectionBuilder`; factory 시 네트워크 연결을 열지 않는다. |

`ServiceClientWrapper`는 `client`, `service_name`, `ping()`, `check()`, `close()`, `unwrap()`을 제공하며 client 오류를 secret-safe `ServiceClientWrapperError`/`ServiceClientError`로 감싼다. `NatsConnectionBuilder`는 `connect()`, 임시 연결을 정리하는 `ping()`/`check()`, no-op `close()`를 제공한다.

`ServiceHandle`, `ServiceClientProtocol`, `ServiceContainerProtocol`은 타입 계약용 Protocol이다. 소비자는 위 concrete wrapper/container를 사용하며, Protocol 구현에 의존하지 않는다.

## 8. Healthcheck와 종료

| API | 계약 |
| --- | --- |
| `check_all_services(service_checks, *, required_services=None, timer=time.perf_counter, parallel=False)` | 동기 check를 순차 또는 thread pool로 수행하고 입력 순서를 보존한다. |
| `async_check_all_services(service_checks, *, required_services=None, timer=time.perf_counter, parallel=False, timeout_seconds=None, overall_timeout_seconds=None)` | 동기 callable과 awaitable을 모두 처리한다. per-service와 전체 timeout을 지원한다. |
| `ServiceHealthStatus` | `service`, `ok`, `latency_ms`, `required`, `error`, `error_type`와 `to_dict()`를 제공한다. |
| `HealthCheckResult` | 전체 `ok`, 서비스 결과 목록과 `to_dict()`를 제공한다. 선택 서비스 실패도 `ok=False`에 반영된다. |
| `HealthCheckError` | 필수 서비스 실패 시 발생한다. `status`, `result`, `failures`를 제공한다. |
| `close_service_clients(clients)` / `async_close_service_clients(clients)` | 모든 close를 시도한 뒤 실패를 `ServiceCloseError`로 집계한다. async 버전은 awaitable close도 처리한다. |
| `ServiceCloseFailure` / `ServiceCloseError` | 실패 client와 exception, 또는 그 aggregate(`failures`)를 표현한다. |

## 9. Keycloak

| API | 계약 |
| --- | --- |
| `KeycloakAuthService(config, ...)` | `fetch_access_token(*, scope=None, username=None, password=None)`과 `extract_user_info(token)`을 제공한다. 기본 password grant는 인자 자격증명을 우선하고 생략 시 환경 설정 자격증명을 사용한다. |
| `AccessTokenResult` | `access_token`, `token_type`, `expires_in`, 선택 `refresh_token`, `scope` 결과다. 원문 token을 로그/예외에 기록하지 않는다. |
| `AuthenticatedUser` | `sub`, profile field, `realm_roles`, `client_roles`, 검증된 `claims`를 제공한다. Bearer/JWT 입력, HS256/RS256, issuer/exp/audience, JWKS cache·refresh를 지원한다. |
| `KeycloakProvisioner(config, *, admin_client)` | `provision()`으로 realm/client/role 선언을 적용한다. dry-run은 `planned`만 채우며 원격 리소스를 삭제하지 않는다. |
| `ProvisioningResult` | `created`, `updated`, `unchanged`, `failed`, `planned`, `dry_run`을 제공한다. |
| `KeycloakTokenError` | token 오류의 base class다. |
| `KeycloakTokenConfigurationError` | grant에 필요한 자격증명/설정이 없을 때 발생한다. |
| `KeycloakTokenAuthenticationError` | 400/401/403 등 영구 인증 실패이며 자동 재시도 대상이 아니다. |
| `KeycloakTokenTemporaryError` | 네트워크, 408/429, 5xx 등 재시도 가능한 실패다. |
| `TokenValidationError` | malformed token, algorithm, signature, claim, issuer/audience, JWKS 오류다. |

## 10. 오류 계약

모든 `DocMeshError` 계열은 `service`, `reason_code`, `remediation`을 제공한다.

| 오류 | 발생 시점 |
| --- | --- |
| `ConfigurationError` | 설정 또는 선언 정책 오류의 base class |
| `InvalidRuntimePlanError` | 빈/모순 runtime plan 또는 invalid health policy |
| `UnknownServiceError` | 카탈로그에 없는 service key |
| `ServiceLookupError` | runtime service 조회 오류 base class |
| `ServiceNotSelectedError` | plan 밖의 서비스를 `require()` |
| `ServiceNotInitializedError` | 선택됐으나 factory가 client를 만들지 않음 |
| `ServiceUnavailableError` | 초기화된 client 작업 실패 base class |
| `StartupCheckError` | required startup healthcheck 실패 base class |
| `ShutdownError` | 종료 실패 base class |

## 11. 유틸리티

| API | 계약 |
| --- | --- |
| `configure_logging(*, level=None, log_path=None, force=False, env=None, env_key='DOCMESH_LOG_LEVEL')` | stderr와 선택 파일 handler를 구성한다. level이 없으면 지정 env의 `DOCMESH_LOG_LEVEL`, 없거나 빈 값이면 `INFO`를 쓴다. |
| `build_service_log_event(*, service, operation, outcome, host=None, latency_ms=None, retry_count=None, error=None, extra=None)` | 표준 structured event dict를 만든다. `error`와 password/secret/token/key 성격의 extra key 값을 마스킹한다. |
| `retry_call(operation, *args, retry_on, max_attempts, base_delay_seconds=0.5, sleep=time.sleep, **kwargs)` | 지정 오류만 최대 횟수까지 지수 backoff로 재시도한다. `max_attempts < 1`은 `ValueError`다. |
| `mask_sensitive_value(raw)` | URI userinfo·sensitive query, Bearer/JWT 및 password/secret/token/key 값 패턴을 `***`로 마스킹한다. |
