---
source_url: https://github.com/kyundae-kim/docmesh-py-core/wiki/API-Reference-v0.5.0
ingested: 2026-07-21
sha256: 1c6f4b9bc04043d03778890e7c33318cae8e34fb2a3771897b21fc9d8fb79b82
---
# 공개 API 레퍼런스

이 문서는 `docmesh_py_core` 패키지 루트에서 import할 수 있는 공개 API를 설명한다. 공개 범위의 기준은 `docmesh_py_core.__all__`이며, 하위 모듈의 비공개 이름은 호환성 계약에 포함되지 않는다.

```python
from docmesh_py_core import RuntimePlan, Service, assemble_service_runtime
```

소비 흐름은 [사용 예제](./examples.md), 환경변수는 [설정 레퍼런스](./config.md)를 먼저 참고한다.

## 공통 계약

- 서비스 설정 객체는 인자를 받지 않고 **프로세스 환경변수에서 직접** 읽는다. 예: `SqliteConfig()`.
- 일반 애플리케이션은 `RuntimePlan`과 `assemble_service_runtime()`을 사용한다.
- `assemble_services()`는 NATS가 없는 동기 전용 경로다.
- factory가 반환한 wrapper/container가 연결 자원을 소유한다. context manager 또는 `close()`로 정리한다.
- `NatsConnectionBuilder.check()`는 임시 연결을 열고 닫는다. 지속 연결이 필요하면 `connect()` 반환값을 호출자가 직접 소유하고 종료한다.
- `DocMeshError` 계열은 `service`, `reason_code`, `remediation`을 제공한다. Keycloak token/JWT 오류는 별도 공개 오류 계층을 사용한다.

## 설정·진단 API

### `load_service_configs(*, services: set[str] | None = None) -> ServiceConfigs`

명시한 서비스를 환경변수에서 로드한다. `services=None`이면 8개 서비스를 모두 대상으로 하므로, 부분 애플리케이션은 반드시 서비스 집합을 전달한다. 설정 실패 시 `ConfigError`를 발생시킨다.

### `load_available_service_configs(*, services: set[str] | None = None) -> ServiceConfigs`

후보 중 인식 가능한 환경변수가 하나라도 존재하는 서비스만 로드한다. runtime assembly가 선택 서비스의 부재와 부분 설정을 구분할 때 사용한다.

### `diagnose_services(*, plan: RuntimePlan, selection_mode="auto") -> EnvironmentDiagnosis`

네트워크 연결 전에 설정 상태(`absent`, `complete`, `partial`, `invalid`), non-secret 기본값, 필수/대안 서비스 위반, production placeholder 및 전송 보안 위반을 반환한다. `selection_mode="strict"`는 대안 그룹에서 둘 이상이 구성된 경우도 문제로 보고한다.

### 검증 helper

- `validate_service_requirements(configs, *, required=None, one_of=()) -> frozenset[str]`: 로드된 서비스의 필수/대안 정책을 검증한다.
- `validate_runtime_security(common, *, keycloak=None, minio=None, milvus=None, ollama=None) -> None`: production transport 보안 위반을 `ConfigError`로 거부한다.
- `require_minio_bucket(config) -> str`: 선택적으로 설정된 `MINIO_BUCKET`을 필수 계약으로 승격한다.

### 설정·진단 결과 객체

- `ServiceConfigs`: `common`과 8개 nullable 서비스 설정을 보관한다. `docmesh_env` property와 서비스별 `require_*()` 메서드를 제공하며 미로드 서비스는 `ConfigError`다.
- `ConfigIssue.to_dict()`: `service`, `env_key`, `reason`, `error_type`, `remediation`을 반환한다.
- `ServiceConfigurationDiagnosis.to_dict()`: 서비스 상태, issue, 적용된 non-secret 기본값을 반환한다.
- `EnvironmentDiagnosis.ok`: issue가 없으면 참이다. `to_dict()`는 전체 진단을 JSON-safe dict로 변환한다.
- `CommonConfig.is_production`: 명시적 security mode 또는 production alias로 운영 환경 여부를 판정한다.

## Runtime plan과 카탈로그

### `RuntimePlan`

```python
RuntimePlan(
    services=(Service.SQLITE.required(), Service.NATS.optional()),
    one_of=((Service.SQLITE, Service.POSTGRES),),
    healthcheck=HealthcheckPolicy(...),
)
```

- `services`: 하나 이상의 `Service` 또는 `ServiceSelection`
- `one_of`: 선택된 서비스로만 구성된 대안 그룹
- `selected_services`, `required_services`, `alternative_groups`: 정규화된 조회 property
- 빈 선택, 중복 선택, 빈/미선택 대안 그룹은 `InvalidRuntimePlanError`

`Service`는 `KEYCLOAK`, `POSTGRES`, `SQLITE`, `MINIO`, `MILVUS`, `OLLAMA`, `LANGFUSE`, `NATS`를 제공한다. `required()`/`optional()`은 `ServiceSelection`을 만들고 `Service.parse()`는 enum 또는 대소문자를 무시한 문자열을 정규화한다.

### `HealthcheckPolicy`

- `on_startup=False`: 시작 시 검사 여부
- `parallel=False`: 병렬 검사 여부
- `timeout_seconds=None`: 서비스별 timeout
- `overall_timeout_seconds=None`: 전체 검사 timeout
- `failure_mode=StartupFailureMode.FAIL`: 실패 시 시작 중단 또는 결과 보고
- `attempts=1`, `retry_delay_seconds=0`: startup 검사 재시도

`timeout_seconds`와 `overall_timeout_seconds`는 양수, `attempts`는 1 이상, 재시도 간격은 0 이상이어야 한다.

### preset

- `production_runtime_plan(services)`: 모든 서비스를 필수로 하고 병렬 startup 검사, 10초 서비스 timeout, 30초 전체 timeout, 3회 시도를 적용한다.
- `authenticated_runtime_plan(services=(), *, healthcheck=None)`: Keycloak을 필수로 추가하고 나머지 선택 의미를 보존한다.

### `SERVICE_CATALOG`

`Service`를 `ServiceDescriptor`에 연결하는 읽기 전용 mapping이다. descriptor의 `environment_variables()`는 모든 환경변수 메타데이터를, `required_environment()`는 필수·조건부 필수 메타데이터를 반환한다. 값이나 secret 원문은 읽지 않는다.

## 조립과 lifecycle

### `assemble_service_runtime(*, plan: RuntimePlan) -> ServiceRuntime`

권장 비동기 bootstrap이다. 선택 설정을 로드하고 client를 생성한 뒤 plan에 따라 startup healthcheck를 수행한다. 생성 또는 검사 실패 시 이미 만든 자원을 best-effort로 정리한다.

`ServiceRuntime` 주요 API:

- `get(service) -> ServiceHandle | None`: 미선택 또는 미초기화면 `None`
- `require(service) -> ServiceHandle`: 미선택은 `ServiceNotSelectedError`, 미초기화는 `ServiceNotInitializedError`
- `get_client(service)`: 호환 조회 API이며 부재 시 `ConfigError`
- `check(...) -> HealthCheckResult`: sync/async check를 함께 처리
- `close()`: sync/async client를 모두 정리
- `async with runtime`: 종료 시 `close()` 호출
- `startup_healthcheck_result`: `REPORT` 모드의 실패 결과 포함

### `assemble_services(...) -> ServiceBundle`

동기 서비스 전용 조립 API다. `services`, `required`, `one_of`, `check_on_startup`, `parallel_healthchecks`를 받는다. NATS를 포함하면 `ConfigError`로 비동기 runtime 사용을 안내한다.

`ServiceBundle`은 `get_client()`, `check()`, `close()`와 동기 context manager를 제공한다.

## 서비스 factory

모든 factory는 검증된 서비스 설정만 받으며 호출 시 임의 SDK kwargs를 받지 않는다.

| Factory | 반환값 | 상태 확인 | 종료/소유권 |
| --- | --- | --- | --- |
| `create_keycloak_client` | `ServiceClientWrapper[KeycloakAuthService]` | token 획득 | wrapper 소유 |
| `create_postgres_client` | `ServiceClientWrapper[Engine]` | `SELECT 1` | `Engine.dispose()` |
| `create_sqlite_client` | `ServiceClientWrapper[Engine]` | `SELECT 1` | `Engine.dispose()` |
| `create_minio_client` | `ServiceClientWrapper[Minio]` | bucket 목록 | SDK close가 있으면 호출 |
| `create_milvus_client` | `ServiceClientWrapper[MilvusClient]` | collection 목록 | SDK close가 있으면 호출 |
| `create_ollama_client` | `ServiceClientWrapper[ollama.Client]` | process 목록 | SDK close가 있으면 호출 |
| `create_langfuse_client` | `ServiceClientWrapper | None` | auth check | disabled이면 `None`, enabled이면 flush |
| `create_nats_client` | `NatsConnectionBuilder` | 임시 연결+flush 후 종료 | 지속 연결은 호출자 소유 |

`ServiceClientWrapper`는 `unwrap()`, `ping()`, `check()` alias, `close()`를 제공하고 SDK 속성을 위임한다. MinIO/Milvus/Ollama의 constructor 밖 동작 기본값은 각각 `MinioRuntimeDefaults`, `MilvusRuntimeDefaults`, `OllamaRuntimeDefaults`에 보존된다.

## Healthcheck와 종료 helper

- `check_all_services(checks, *, required_services=None, parallel=False)`: 동기 검사. 필수 실패 시 `HealthCheckError`, 선택 실패는 결과에 기록한다.
- `async_check_all_services(checks, *, required_services=None, parallel=False, timeout_seconds=None, overall_timeout_seconds=None)`: 동기 함수와 awaitable을 처리한다. 서비스별 timeout과 전체 timeout은 별도 계약이다.
- `close_service_clients(clients)`: 모든 동기 close를 시도한 후 실패를 `ServiceCloseError.failures`로 집계한다.
- `async_close_service_clients(clients)`: sync/async close를 순차 처리하고 실패를 집계한다.

`HealthCheckResult.to_dict()`와 `ServiceHealthStatus.to_dict()`는 JSON-safe 결과를 반환한다.

`ServiceCloseError.failures`는 `ServiceCloseFailure(client, error)` tuple이다. 모든 client에 대한 종료 시도가 끝난 후 발생하므로 실패하지 않은 자원은 이미 정리된 상태다.

## Keycloak 인증과 프로비저닝

### `KeycloakAuthService`

- `fetch_access_token(*, scope=None, username=None, password=None) -> AccessTokenResult`
  - `password` grant는 호출 인자를 설정값보다 우선한다.
  - 일시 오류만 `KEYCLOAK_MAX_RETRIES + 1`회 시도한다.
  - 설정/인증/일시/기타 오류를 각각 공개 오류로 구분한다.
- `extract_user_info(token) -> AuthenticatedUser`
  - raw JWT와 `Bearer ...`를 지원한다.
  - issuer, 만료, 서명, 선택적 audience를 검증한다.
  - HS256은 `verification_key`, RS256은 JWKS와 cache를 사용한다.
- `issuer`, `token_endpoint`, `jwks_endpoint`: 계산된 endpoint property

`AccessTokenResult`는 `access_token`, `token_type`, `expires_in`, 선택적 `refresh_token`, `scope`를 제공한다. `AuthenticatedUser`는 `sub`, 표준 profile 필드, 분리된 `realm_roles`/`client_roles`, 검증된 원본 `claims`를 제공한다.

### `KeycloakProvisioner`

`provision() -> ProvisioningResult`는 realm, client, realm role, client role을 멱등적으로 ensure한다. dry-run이면 `planned`, 실제 적용이면 `created`, `updated`, `unchanged`, `failed`에 결과를 분류하며 선언에서 제거된 원격 자원을 삭제하지 않는다. 관리 SDK를 구현한 `admin_client`는 호출자가 주입한다.

## Logging, 보안, 재시도

- `configure_logging(*, level=None, log_path=None, force=False, env=None, env_key="DOCMESH_LOG_LEVEL")`: 명시적 `level` > 환경변수 > `INFO` 순으로 level을 선택하고 stderr 및 선택적 파일 handler를 구성한다.
- `build_service_log_event(...) -> dict`: 서비스 이벤트의 표준 키를 만들고 민감 key의 추가값과 `error`를 마스킹한다.
- `mask_sensitive_value(raw)`: 비밀번호, token, secret, DSN/URI의 민감 부분을 마스킹한다.
- `retry_call(operation, *args, retry_on, max_attempts, base_delay_seconds=0.5, sleep=..., **kwargs)`: 지정 예외에만 지수 backoff를 적용한다.

## 공개 오류 계층

```text
DocMeshError
├── ConfigurationError
│   ├── ConfigError
│   ├── InvalidRuntimePlanError
│   └── UnknownServiceError
├── ServiceLookupError
│   ├── ServiceNotSelectedError
│   └── ServiceNotInitializedError
├── ServiceUnavailableError
│   └── StartupCheckError
│       └── HealthCheckError
└── ShutdownError
    └── ServiceCloseError
```

`ServiceClientError`와 `ServiceClientWrapperError`는 `ServiceUnavailableError` 기반의 operation 오류다. Keycloak의 `KeycloakTokenError` 계층과 `TokenValidationError`는 현재 `DocMeshError` 계층과 별도로 유지된다.

## 공개 API 인벤토리

아래 표의 86개 이름은 `docmesh_py_core.__all__`과 계약 테스트로 일치 여부를 검사한다.

| 공개 이름 | 분류 | 계약 요약 |
| --- | --- | --- |
| `AccessTokenResult` | 결과 | Access/refresh token 응답 모델 |
| `AuthenticatedUser` | 결과 | 검증된 JWT의 표준 사용자 정보 |
| `CommonConfig` | 설정 | 환경·production 판정 설정 |
| `ConfigError` | 오류 | 구조화 설정 오류와 issue 목록 |
| `ConfigIssue` | 결과 | secret-safe 설정 문제 한 건 |
| `ConfigurationError` | 오류 | 설정·plan 오류 기반 클래스 |
| `DocMeshError` | 오류 | 구조화 오류 최상위 클래스 |
| `EnvironmentDiagnosis` | 결과 | 전체 preflight 진단 결과 |
| `EnvironmentRequirement` | 카탈로그 | 환경변수 요구 메타데이터 |
| `KeycloakDiscoveryConfig` | 설정 | issuer discovery 최소 설정 |
| `KeycloakConfig` | 설정 | 인증·token·provisioning 설정 |
| `configure_logging` | 관측성 | logging bootstrap |
| `HealthCheckError` | 오류 | 필수 healthcheck 실패 |
| `HealthCheckResult` | 결과 | 집계 healthcheck 결과 |
| `HealthcheckPolicy` | 계획 | startup 검사 정책 |
| `InvalidRuntimePlanError` | 오류 | 모순된 plan 오류 |
| `KeycloakAuthService` | 인증 | token 획득·JWT 검증 |
| `KeycloakProvisioner` | 인증 | realm/client/role ensure orchestration |
| `KeycloakTokenAuthenticationError` | 오류 | 영구 token 인증 실패 |
| `KeycloakTokenConfigurationError` | 오류 | token 호출 설정 실패 |
| `KeycloakTokenError` | 오류 | token 오류 기반 클래스 |
| `KeycloakTokenTemporaryError` | 오류 | 재시도 가능한 token 오류 |
| `LangfuseConfig` | 설정 | Langfuse 연결·tracing 설정 |
| `MinioConfig` | 설정 | MinIO 연결 설정 |
| `MinioRuntimeDefaults` | 결과 | MinIO operation 기본값 |
| `MilvusConfig` | 설정 | Milvus 연결 설정 |
| `MilvusRuntimeDefaults` | 결과 | Milvus operation 기본값 |
| `NatsConnectionBuilder` | client | 지연 NATS 연결 builder |
| `NatsConfig` | 설정 | NATS 연결·인증·재연결 설정 |
| `OllamaConfig` | 설정 | Ollama 연결·모델 설정 |
| `OllamaRuntimeDefaults` | 결과 | Ollama operation 기본값 |
| `PostgresConfig` | 설정 | PostgreSQL/SQLAlchemy 설정 |
| `ProvisioningResult` | 결과 | Keycloak provisioning 결과 |
| `RuntimePlan` | 계획 | immutable 서비스 조립 계획 |
| `SERVICE_CATALOG` | 카탈로그 | 서비스 descriptor mapping |
| `Service` | 계획 | 8개 서비스 typed key |
| `ServiceBundle` | container | 동기 서비스 lifecycle container |
| `ServiceClientError` | 오류 | 서비스 operation 오류 |
| `ServiceClientProtocol` | protocol | check/close 계약 |
| `ServiceClientWrapper` | client | SDK lifecycle adapter |
| `ServiceClientWrapperError` | 오류 | wrapper healthcheck 오류 |
| `ServiceCloseError` | 오류 | 종료 실패 집계 오류 |
| `ServiceCloseFailure` | 결과 | 종료 실패 한 건 |
| `ServiceConfigs` | 설정 | 선택 서비스 설정 aggregate |
| `ServiceConfigurationDiagnosis` | 결과 | 서비스별 설정 상태 |
| `ServiceContainerProtocol` | protocol | container 최소 계약 |
| `ServiceDescriptor` | 카탈로그 | config/factory/env metadata |
| `ServiceHandle` | protocol | 이름 있는 lifecycle handle |
| `ServiceHealthStatus` | 결과 | 서비스별 health 상태 |
| `ServiceLookupError` | 오류 | runtime 조회 오류 기반 클래스 |
| `ServiceNotInitializedError` | 오류 | 선택됐으나 client가 없는 오류 |
| `ServiceNotSelectedError` | 오류 | plan 밖 서비스 조회 오류 |
| `ServiceRuntime` | container | 비동기 typed lifecycle container |
| `ServiceSelection` | 계획 | 서비스와 required 정책 |
| `ServiceUnavailableError` | 오류 | 서비스 operation 불가 오류 |
| `ShutdownError` | 오류 | 종료 오류 기반 클래스 |
| `SqliteConfig` | 설정 | SQLite engine/pragma 설정 |
| `StartupCheckError` | 오류 | startup 검사 오류 기반 클래스 |
| `StartupFailureMode` | 계획 | `fail`/`report` 정책 enum |
| `TokenValidationError` | 오류 | JWT 검증 오류 |
| `UnknownServiceError` | 오류 | 미지원 서비스 key 오류 |
| `assemble_service_runtime` | 조립 | 권장 비동기 bootstrap |
| `assemble_services` | 조립 | 동기 서비스 조립 |
| `async_check_all_services` | health | 비동기 집계 healthcheck |
| `async_close_service_clients` | 종료 | sync/async client 종료 집계 |
| `authenticated_runtime_plan` | preset | Keycloak 필수 plan |
| `build_service_log_event` | 관측성 | 구조화 서비스 이벤트 생성 |
| `check_all_services` | health | 동기 집계 healthcheck |
| `close_service_clients` | 종료 | 동기 client 종료 집계 |
| `create_keycloak_client` | factory | Keycloak wrapper 생성 |
| `create_langfuse_client` | factory | Langfuse wrapper/None 생성 |
| `create_milvus_client` | factory | Milvus wrapper 생성 |
| `create_minio_client` | factory | MinIO wrapper 생성 |
| `create_nats_client` | factory | 지연 NATS builder 생성 |
| `create_ollama_client` | factory | Ollama wrapper 생성 |
| `create_postgres_client` | factory | PostgreSQL engine wrapper 생성 |
| `create_sqlite_client` | factory | SQLite engine wrapper 생성 |
| `diagnose_services` | 설정 | plan 기반 사전 진단 |
| `load_available_service_configs` | 설정 | 존재하는 후보 설정 로딩 |
| `load_service_configs` | 설정 | 선택 설정 로딩 |
| `mask_sensitive_value` | 보안 | 민감값 마스킹 |
| `production_runtime_plan` | preset | 엄격한 production plan |
| `require_minio_bucket` | 설정 | bucket 필수 검증 |
| `retry_call` | 안정성 | 동기 지수 backoff 재시도 |
| `validate_runtime_security` | 보안 | production transport 검증 |
| `validate_service_requirements` | 설정 | required/one-of 검증 |
