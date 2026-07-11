---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.4/docs/api.md
ingested: 2026-07-03
sha256: 54383e3a88b811dffdf7a09f95ed30b896bcdf09c279e50b93d62286ff637609
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
    HealthCheckError,
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
    MilvusConfig,
    NatsConnectionBuilder,
    NatsConfig,
    OllamaConfig,
    PostgresConfig,
    ServiceClientError,
    ServiceClientWrapper,
    ServiceClientWrapperError,
    ServiceConfigs,
    SqliteConfig,
    TokenValidationError,
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
    load_service_configs,
    mask_sensitive_value,
    retry_call,
    validate_runtime_security,
)
```

> 위 목록은 `docmesh_py_core/__init__.py`의 `__all__` 기준입니다.

루트에서 재-export되지 않는 타입도 있습니다.

- `HealthCheckResult`, `ServiceHealthStatus`는 `docmesh_py_core.health` 모듈에 존재하지만 패키지 루트 `__all__`에는 없습니다.
- `ProvisioningResult`는 `docmesh_py_core.keycloak` 모듈에 존재하지만 패키지 루트 `__all__`에는 없습니다.

## 2. 권장 사용 흐름

대부분의 소비 애플리케이션은 아래 순서로 사용합니다.

1. 환경변수 준비
2. `CommonConfig()` 또는 `load_service_configs()` 호출
3. 필요한 서비스만 `create_*_client()`로 조립
4. 시작 시점에 `check()` 또는 `check_all_services()` 실행
5. 종료 시 `close_service_clients()` 또는 개별 `close()` 호출

주의:

- `nats`만 예외적으로 `NatsConnectionBuilder`를 반환하며, 실제 네트워크 연결은 `await connect()` / `await ping()` / `await check()`에서 일어납니다.
- `langfuse`는 `LANGFUSE_ENABLED=false`면 `create_langfuse_client()`가 `None`을 반환할 수 있습니다.
- `CommonConfig.env`는 자유 문자열이며 enum 검증을 하지 않습니다. 런타임 보안 제약은 `production` 또는 `prod`일 때만 적용됩니다.

## 3. Service config API

### 권장 public config entrypoint

> 아래 내용은 현재 서비스 config API의 핵심 진입점을 설명합니다.

### 3.1 권장 public config entrypoint

서비스별 설정만 필요하면 aggregate `ServiceConfigs`보다 서비스별 config class 직접 생성을 우선 사용하는 것을 권장합니다.

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

### 3.2 `load_service_configs(*, services=None) -> ServiceConfigs`

현재 프로세스 환경변수에서 설정을 읽고 검증합니다.

주요 동작:

- `services=None`이면 지원 서비스 전체(`keycloak`, `postgres`, `sqlite`, `minio`, `milvus`, `ollama`, `langfuse`, `nats`)를 검증합니다.
- `services={...}`를 주면 지정한 서비스만 검증하고, 나머지 필드는 `None`으로 둡니다.
- 지원하지 않는 서비스 이름이 들어오면 `ConfigError`가 발생합니다.
- 선택된 서비스에서 필수 env가 없거나 타입/범위 검증에 실패하면 `ConfigError`가 발생합니다.
- 마지막에 `validate_runtime_security()`를 호출해 production 계열 보안 제약을 확인합니다.

예시:

```python
from docmesh_py_core import create_nats_client, create_sqlite_client, load_service_configs

settings = load_service_configs(services={"sqlite", "nats"})

sqlite = create_sqlite_client(settings.sqlite)
builder = create_nats_client(settings.nats)

assert settings.keycloak is None
assert settings.minio is None
```

### 3.3 `ServiceConfigs`

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

## 4. Client creation API

현재 권장 경로는 서비스별 `create_*_client()` 함수입니다.

### `create_keycloak_client(config: KeycloakConfig) -> ServiceClientWrapper`

- 내부적으로 `KeycloakAuthService(config)`를 생성합니다.
- `check()` / `ping()`는 `fetch_access_token()`을 호출합니다.

### `create_postgres_client(config: PostgresConfig) -> ServiceClientWrapper`

- SQLAlchemy engine을 생성합니다.
- `config.dsn`이 있으면 그 값을 사용하고, 없으면 host/db/user/password 조합으로 URL을 만듭니다.
- `check()` / `ping()`는 `SELECT 1`을 실행합니다.
- `close()`는 내부 `dispose()`를 호출합니다.

### `create_sqlite_client(config: SqliteConfig) -> ServiceClientWrapper`

- SQLAlchemy engine을 생성합니다.
- `config.path == ":memory:"`를 지원합니다.
- `readonly`, `enable_wal`, `busy_timeout_ms`를 반영합니다.
- `check()` / `ping()`는 `SELECT 1`을 실행합니다.
- `close()`는 내부 `dispose()`를 호출합니다.

### `create_minio_client(config: MinioConfig) -> ServiceClientWrapper`

- `Minio(...)` 클라이언트를 즉시 생성합니다.
- `secure` 값은 `cert_check`에도 그대로 반영됩니다.
- `check()` / `ping()`는 `list_buckets()`를 호출합니다.

### `create_milvus_client(config: MilvusConfig) -> ServiceClientWrapper`

- `MilvusClient(...)`를 생성합니다.
- `check()` / `ping()`는 `list_collections()`를 호출합니다.

### `create_ollama_client(config: OllamaConfig) -> ServiceClientWrapper`

- `ollama.Client(...)`를 생성합니다.
- `check()` / `ping()`는 `ps()`를 호출합니다.

### `create_langfuse_client(config: LangfuseConfig) -> ServiceClientWrapper | None`

- `config.enabled`가 `False`면 `None`을 반환합니다.
- 활성화 시 `Langfuse(...)`를 생성합니다.
- `check()` / `ping()`는 `auth_check()`를 호출합니다.
- `close()`는 `flush()`를 호출합니다.

### `create_nats_client(config: NatsConfig) -> NatsConnectionBuilder`

- 즉시 연결하지 않습니다.
- 실제 네트워크 연결은 `await builder.connect()` / `await builder.ping()` / `await builder.check()`에서 일어납니다.
- `ping()` / `check()`는 임시 연결 후 `flush()`를 수행하고, 끝나면 연결을 정리합니다.

예시:

```python
from docmesh_py_core import create_postgres_client, load_service_configs

settings = load_service_configs(services={"postgres"})
postgres = create_postgres_client(settings.postgres)

postgres.check()
postgres.close()
```

## 5. 공통 wrapper / helper API

### `ServiceClientWrapper`

서비스 클라이언트를 표준 인터페이스로 감싸는 wrapper입니다.

주요 메서드:

- `check()` / `ping()`
- `close()`
- `__getattr__()` 위임

동작 규칙:

- healthcheck 호출 중 예외가 발생하면 `ServiceClientWrapperError`로 변환합니다.
- 오류 메시지는 `mask_sensitive_value()`를 거쳐 민감정보를 숨깁니다.
- `close_fn`이 있으면 그 함수를 우선 호출하고, 없으면 내부 client의 `close()`를 찾습니다.

### `close_service_clients(clients: Iterable[Any]) -> None`

여러 wrapper/client에 대해 `close()`를 순회 호출합니다. `None` 값은 무시합니다.

### `check_all_services(service_checks, *, required_services=None, timer=time.perf_counter, parallel=False)`

서비스 헬스체크 함수를 모아 실행합니다.

반환값:

- `HealthCheckResult(ok: bool, services: list[ServiceHealthStatus])`

각 항목:

- `ServiceHealthStatus(service, ok, latency_ms, error=None)`

규칙:

- `parallel=False`면 입력 순서대로 순차 실행합니다.
- `parallel=True`면 `ThreadPoolExecutor`로 병렬 실행하지만 반환 순서는 입력 순서를 유지합니다.
- required 서비스가 실패하면 `HealthCheckError`를 발생시킵니다.
- 오류 문자열은 마스킹됩니다.

### `mask_sensitive_value(value: str | None) -> str | None`

민감정보를 로그 친화적으로 마스킹합니다.

주요 동작:

- URL/DSN이면 사용자정보와 민감 query parameter를 마스킹합니다.
- raw token/secret/password 계열 문자열도 `***` 또는 `key=***` 형태로 변환합니다.
- 민감 키워드가 없는 일반 문자열도 최종적으로 `***`가 될 수 있으므로, 이 함수는 "안전한 로그 표현" 용도로 사용해야 합니다.

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

### `configure_logging(*, level=None, log_path=None, force=False, env=None, env_key="DOCMESH_LOG_LEVEL") -> logging.Logger`

루트 로거를 설정합니다.

동작:

- `level`이 주어지면 그 값을 우선 사용합니다.
- 아니면 `DOCMESH_LOG_LEVEL` 환경변수를 읽습니다.
- 값이 없거나 빈 문자열이면 `INFO`를 사용합니다.
- 잘못된 로그 레벨이면 `ValueError`를 발생시킵니다.
- `log_path`가 있으면 부모 디렉터리를 생성한 뒤 파일 핸들러를 추가합니다.

## 6. Keycloak API

### `KeycloakAuthService(config: KeycloakConfig, ...)`

Keycloak 토큰 획득과 JWT 검증을 담당합니다.

주요 속성/메서드:

- `issuer`
- `token_endpoint`
- `jwks_endpoint`
- `fetch_access_token(...) -> AccessTokenResult`
- `extract_user_info(token: str) -> AuthenticatedUser`

### `fetch_access_token(*, scope=None, username=None, password=None) -> AccessTokenResult`

- 기본 grant type은 `client_credentials`입니다.
- `config.token_grant_type == "password"`일 때는 설정 객체 필드와 무관하게 함수 인자 `username`, `password`를 반드시 전달해야 합니다.
- 일시적 장애(`KeycloakTokenTemporaryError`)는 `config.max_retries + 1`번까지 재시도합니다.
- 재시도 이벤트는 `build_service_log_event()` 형식으로 로깅됩니다.

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

현재 구현은 production 계열 환경에서 아래 제약만 검사합니다.

- `KEYCLOAK_VERIFY_SSL=false` 금지
- `MINIO_SECURE=false` 금지
- `MILVUS_SECURE=false` 금지

`common.env.lower()`가 `production` 또는 `prod`가 아니면 아무 것도 하지 않습니다.
