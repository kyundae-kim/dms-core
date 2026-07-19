---
source_url: https://github.com/kyundae-kim/docmesh-py-core/wiki/Examples-v0.4.0
ingested: 2026-07-19
sha256: 1d1d4277f3ac3a8bd259de91b42b7c7047de3926cae21f59322e07f625eb4fa5
---
# docmesh-py-core Examples

> 기준: **v0.4.0**. 환경변수 전체 목록은 [Configuration Guide](./config.md), 정확한 반환값·오류 계약은 [API Reference](./api.md)를 참조한다. 예제의 secret 값은 deployment secret injection으로 교체해야 하며 source code에 넣지 않는다.

## 1. `RuntimePlan` 기반 비동기 bootstrap

일반 애플리케이션의 표준 경로다. plan이 서비스 선택, 필수 readiness, startup healthcheck를 함께 선언한다.

```bash
export DOCMESH_ENV=development
export SQLITE_PATH=:memory:
export NATS_SERVERS=nats://nats.internal:4222
```

```python
import asyncio

from docmesh_py_core import (
    HealthcheckPolicy,
    RuntimePlan,
    Service,
    assemble_service_runtime,
    diagnose_services,
)


async def main() -> None:
    plan = RuntimePlan(
        services=(Service.SQLITE.required(), Service.NATS.optional()),
        healthcheck=HealthcheckPolicy(
            on_startup=True,
            parallel=True,
            timeout_seconds=5,
        ),
    )

    diagnosis = diagnose_services(plan=plan)
    if not diagnosis.ok:
        raise RuntimeError(diagnosis.to_dict())

    async with await assemble_service_runtime(plan=plan) as runtime:
        sqlite = runtime.require(Service.SQLITE)
        sqlite.check()

        # NATS는 factory 시 연결하지 않는다. 필요 시 builder로 실제 연결한다.
        nats = runtime.get(Service.NATS)
        if nats is not None:
            connection = await nats.connect()
            try:
                await connection.publish("events.created", b"example")
            finally:
                await connection.drain()


asyncio.run(main())
```

**추적 API:** `RuntimePlan`, `Service`, `HealthcheckPolicy`, `diagnose_services`, `assemble_service_runtime`, `ServiceRuntime.require`, `ServiceRuntime.get` — [API Reference §4·§6](./api.md#4-runtime-plan과-preset)

## 2. 네트워크 연결 전 설정 진단

`diagnose_services()`는 client를 만들지 않는다. CI/CD 또는 application startup에서 secret을 출력하지 않고 설정 문제를 확인할 때 사용한다.

```python
from docmesh_py_core import RuntimePlan, Service, diagnose_services

plan = RuntimePlan(
    services=(Service.POSTGRES.required(), Service.SQLITE.optional()),
    one_of=((Service.POSTGRES, Service.SQLITE),),
)
diagnosis = diagnose_services(plan=plan, selection_mode="strict")

for service, item in diagnosis.services.items():
    print(service, item.state, item.applied_defaults)
for issue in diagnosis.issues:
    print(issue.service, issue.env_key, issue.reason, issue.remediation)

if not diagnosis.ok:
    raise SystemExit(2)
```

`selection_mode="strict"`는 one-of 그룹에서 둘 이상의 서비스가 모두 구성돼 모호한 경우도 issue로 보고한다.

**추적 API:** `EnvironmentDiagnosis`, `ServiceConfigurationDiagnosis`, `ConfigIssue`, `RuntimePlan`, `Service`, `diagnose_services` — [API Reference §3](./api.md#3-설정과-진단)

## 3. 동기 direct API: SQLite

NATS를 사용하지 않는 CLI·배치·단위 테스트에서만 동기 조립을 사용한다. 구성값을 Python 인자로 전달하지 말고 실행 환경에서 제공한다.

```bash
export SQLITE_PATH=./var/local.db
export SQLITE_ENABLE_WAL=true
export SQLITE_BUSY_TIMEOUT_MS=5000
```

```python
from docmesh_py_core import (
    create_sqlite_client,
    load_service_configs,
)

configs = load_service_configs(services={"sqlite"})
sqlite = create_sqlite_client(configs.require_sqlite())
try:
    sqlite.check()
    with sqlite.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS example (id INTEGER PRIMARY KEY)")
finally:
    sqlite.close()
```

동기 lifecycle 전체를 소유해야 하면 다음처럼 `ServiceBundle`을 쓴다.

```python
from docmesh_py_core import assemble_services

with assemble_services(
    services={"sqlite"},
    required={"sqlite"},
    check_on_startup=True,
) as bundle:
    sqlite = bundle.get_client("sqlite")
    sqlite.check()
```

**추적 API:** `load_service_configs`, `ServiceConfigs.require_sqlite`, `create_sqlite_client`, `ServiceClientWrapper`, `assemble_services`, `ServiceBundle` — [API Reference §3·§6·§7](./api.md#6-조립-lifecycle과-조회)

## 4. Keycloak token과 JWT 사용자 정보

```bash
export KEYCLOAK_URL=https://keycloak.internal
export KEYCLOAK_REALM=docmesh
export KEYCLOAK_CLIENT_ID=backend
export KEYCLOAK_CLIENT_SECRET='injected-secret'
export KEYCLOAK_TOKEN_USERNAME=service-user
export KEYCLOAK_TOKEN_PASSWORD='injected-password'
```

```python
from docmesh_py_core import KeycloakAuthService, KeycloakConfig

config = KeycloakConfig()
auth = KeycloakAuthService(config, verification_key="hs256-verification-key")

token = auth.fetch_access_token()
# access_token과 refresh_token 원문은 로그에 기록하지 않는다.
print(token.token_type, token.expires_in)

user = auth.extract_user_info("Bearer <JWT_FROM_REQUEST>")
print(user.sub, user.preferred_username, user.realm_roles)
```

- password grant 호출 인자 `username`/`password`는 설정의 `KEYCLOAK_TOKEN_USERNAME`/`KEYCLOAK_TOKEN_PASSWORD`보다 우선한다.
- RS256이면 `verification_key` 대신 JWKS endpoint를 사용하고 cache/rotation을 처리한다.
- `KeycloakTokenAuthenticationError`는 재시도하지 않고, `KeycloakTokenTemporaryError`만 재시도 대상이다.

**추적 API:** `KeycloakConfig`, `KeycloakAuthService`, `AccessTokenResult`, `AuthenticatedUser`, `KeycloakTokenError`, `TokenValidationError` — [API Reference §9](./api.md#9-keycloak)

## 5. Keycloak provisioning dry-run

`KeycloakProvisioner`는 실제 Keycloak admin API를 구현한 `admin_client`를 application에서 제공받는다. 라이브러리는 선언에서 삭제된 원격 리소스를 자동 삭제하지 않는다.

```python
from docmesh_py_core import KeycloakConfig, KeycloakProvisioner

# KEYCLOAK_PROVISIONING_ENABLED=true
# KEYCLOAK_PROVISIONING_DRY_RUN=true
config = KeycloakConfig()

admin_client = ...  # ensure_realm/config, ensure_client/config, ensure_*_role 구현
result = KeycloakProvisioner(config, admin_client=admin_client).provision()
assert result.dry_run is True
print(result.planned)
```

**추적 API:** `KeycloakProvisioner`, `ProvisioningResult`, `KeycloakConfig` — [API Reference §9](./api.md#9-keycloak)

## 6. MinIO bucket을 사용하는 application

`MINIO_BUCKET`은 client 생성 자체에는 필요 없다. 업무 코드가 bucket을 반드시 요구할 때만 `require_minio_bucket()`으로 명시한다.

```python
from docmesh_py_core import (
    create_minio_client,
    load_service_configs,
    require_minio_bucket,
)

configs = load_service_configs(services={"minio"})
minio_config = configs.require_minio()
bucket = require_minio_bucket(minio_config)
client = create_minio_client(minio_config)

try:
    client.check()
    print(client.bucket_exists(bucket))
finally:
    client.close()
```

**추적 API:** `MinioConfig`, `create_minio_client`, `MinioRuntimeDefaults`, `require_minio_bucket`, `ConfigError` — [API Reference §3·§7](./api.md#7-서비스별-factory와-client-계약)

## 7. Healthcheck 결과와 종료 오류 처리

```python
from docmesh_py_core import (
    HealthCheckError,
    ServiceCloseError,
    check_all_services,
    close_service_clients,
)

clients = [postgres, minio]
try:
    result = check_all_services(
        {"postgres": postgres.check, "minio": minio.check},
        required_services={"postgres"},
        parallel=True,
    )
    print(result.to_dict())
except HealthCheckError as exc:
    # exc.result는 각 서비스 상태를 포함한다.
    print(exc.result.to_dict() if exc.result else exc.status.to_dict())
    raise
finally:
    try:
        close_service_clients(clients)
    except ServiceCloseError as exc:
        for failure in exc.failures:
            print(f"close failed: {failure.client!r}: {failure.error}")
        raise
```

**추적 API:** `check_all_services`, `async_check_all_services`, `ServiceHealthStatus`, `HealthCheckResult`, `HealthCheckError`, `close_service_clients`, `async_close_service_clients`, `ServiceCloseFailure`, `ServiceCloseError` — [API Reference §8](./api.md#8-healthcheck와-종료)

## 8. Structured event, masking, retry와 logging

```python
from docmesh_py_core import (
    build_service_log_event,
    configure_logging,
    mask_sensitive_value,
    retry_call,
)

configure_logging()
event = build_service_log_event(
    service="payments",
    operation="publish",
    outcome="temporary_error",
    host="nats.internal",
    retry_count=1,
    error="token=very-secret",
)
assert event["error"] == "token=***"
assert mask_sensitive_value("Bearer eyJ.example.signature") == "***"

result = retry_call(
    publish_once,
    retry_on=(TimeoutError,),
    max_attempts=3,
    base_delay_seconds=0.5,
)
```

`retry_call()`은 명시한 `retry_on` 예외만 재시도하며, 다른 예외는 즉시 전파한다. 함수 경계 logging과 host 값은 임의 값 전체를 자동 정제하지 않으므로 secret-safe 값을 전달한다.

**추적 API:** `configure_logging`, `build_service_log_event`, `mask_sensitive_value`, `retry_call` — [API Reference §11](./api.md#11-유틸리티)

## 9. Preset 선택

```python
from docmesh_py_core import (
    Service,
    authenticated_runtime_plan,
    minimal_runtime_plan,
    production_runtime_plan,
)

local = minimal_runtime_plan()  # required SQLite
production = production_runtime_plan((Service.POSTGRES, Service.MINIO))
authenticated = authenticated_runtime_plan((Service.POSTGRES.optional(),))
```

| 상황 | preset | 결과 |
| --- | --- | --- |
| 로컬 최소 실행 | `minimal_runtime_plan()` | required SQLite, startup check off |
| 선언한 모든 서비스를 엄격하게 확인 | `production_runtime_plan(services)` | all required, 병렬 startup check, 3회 재시도 |
| Keycloak가 필요한 application | `authenticated_runtime_plan(services)` | required Keycloak + 기존 selection 의미 유지 |

**추적 API:** `minimal_runtime_plan`, `production_runtime_plan`, `authenticated_runtime_plan`, `ServiceSelection`, `StartupFailureMode` — [API Reference §4](./api.md#4-runtime-plan과-preset)

## 10. 예제-API-설정 추적표

| 예제 | 공개 API 기준 | Configuration Guide |
| --- | --- | --- |
| §1 Runtime bootstrap | `RuntimePlan`, `assemble_service_runtime`, `ServiceRuntime` | [공통/NATS](./config.md#2-공통-환경변수), [NATS](./config.md#nats--natsconfig) |
| §2 사전 진단 | `diagnose_services`, `EnvironmentDiagnosis`, `ConfigIssue` | [Production 보안](./config.md#4-production-보안과-진단) |
| §3 SQLite | `load_service_configs`, `create_sqlite_client`, `assemble_services` | [SQLite](./config.md#sqlite--sqliteconfig) |
| §4–5 Keycloak | `KeycloakAuthService`, `KeycloakProvisioner` | [Keycloak](./config.md#keycloak--keycloakconfig) |
| §6 MinIO | `create_minio_client`, `require_minio_bucket` | [MinIO](./config.md#minio--minioconfig) |
| §7 상태·종료 | health 및 close APIs | 선택 서비스의 config section |
| §8 유틸리티 | logging/masking/retry APIs | [공통](./config.md#2-공통-환경변수) |
| §9 preset | preset APIs | 선택 서비스의 config section |
