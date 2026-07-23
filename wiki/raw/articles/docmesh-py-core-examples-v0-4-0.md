---
source_url: https://github.com/kyundae-kim/docmesh-py-core/wiki/Examples-v0.5.0
ingested: 2026-07-21
sha256: 99f5d6303d429cb96487af001c6924b93e6160023cf3eea63200ea5b90256135
---
# 사용 예제

이 문서는 소비 애플리케이션에서 복사해 조정할 수 있는 흐름을 제공한다. 모든 import는 package root 공개 API만 사용한다.

- 정확한 타입·함수·오류 계약: [API 레퍼런스](./api.md)
- 필수·조건부 환경변수와 기본값: [설정 레퍼런스](./config.md)
- 전체 환경변수 템플릿: [`.env.example`](../.env.example)

## 1. 최소 구성: SQLite runtime

환경변수:

```dotenv
SQLITE_PATH=:memory:
```

애플리케이션:

```python
import asyncio

from docmesh_py_core import (
    RuntimePlan,
    Service,
    assemble_service_runtime,
    diagnose_services,
)


async def main() -> None:
    plan = RuntimePlan(services=(Service.SQLITE.required(),))
    diagnosis = diagnose_services(plan=plan)
    if not diagnosis.ok:
        raise RuntimeError(diagnosis.to_dict())

    runtime = await assemble_service_runtime(plan=plan)
    async with runtime:
        sqlite = runtime.require(Service.SQLITE)
        with sqlite.connect() as connection:
            value = connection.exec_driver_sql("SELECT 1").scalar_one()
        assert value == 1


asyncio.run(main())
```

`ServiceRuntime`이 SQLite wrapper와 engine을 소유하며 `async with` 종료 시 dispose한다.

## 2. Production preset과 startup healthcheck

```python
import asyncio

from docmesh_py_core import (
    Service,
    assemble_service_runtime,
    production_runtime_plan,
)


async def main() -> None:
    plan = production_runtime_plan((Service.POSTGRES, Service.MINIO))
    runtime = await assemble_service_runtime(plan=plan)
    async with runtime:
        result = await runtime.check(
            parallel=True,
            timeout_seconds=5,
            overall_timeout_seconds=15,
        )
        print(result.to_dict())


asyncio.run(main())
```

이 preset은 선언한 서비스를 모두 필수로 두며 startup 검사 실패 시 runtime을 정리하고 `HealthCheckError`를 발생시킨다. 서비스별 timeout은 각 검사에, 전체 timeout은 전체 orchestration에 적용된다.

## 3. 인증 포함 preset

```python
from docmesh_py_core import Service, authenticated_runtime_plan

plan = authenticated_runtime_plan(
    (
        Service.POSTGRES.required(),
        Service.LANGFUSE.optional(),
    )
)

assert Service.KEYCLOAK in plan.required_services
assert Service.POSTGRES in plan.required_services
assert Service.LANGFUSE not in plan.required_services
```

## 4. Direct API: SQLite engine

CLI나 짧은 배치처럼 aggregate runtime이 필요하지 않을 때 사용한다.

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
        connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS jobs (id INTEGER)")
finally:
    sqlite.close()
```

설정은 프로세스 환경변수에서만 읽는다. `SqliteConfig(path=...)`처럼 생성자 값으로 우회하지 않는다.

## 5. 동기 bundle

NATS가 없는 동기 애플리케이션에서 여러 서비스를 함께 소유한다.

```python
from docmesh_py_core import assemble_services

with assemble_services(
    services={"sqlite", "minio"},
    required={"sqlite"},
    check_on_startup=True,
    parallel_healthchecks=True,
) as bundle:
    sqlite = bundle.get_client("sqlite")
    minio = bundle.get_client("minio")
    print(bundle.check(parallel=True).to_dict())
```

선택 집합에 NATS가 있으면 `assemble_services()`는 `ConfigError`를 발생시킨다. 이 경우 `assemble_service_runtime()`을 사용한다.

## 6. 독립 healthcheck 집계

```python
from docmesh_py_core import HealthCheckError, check_all_services


def database_check() -> None:
    return None


def optional_observability_check() -> None:
    raise RuntimeError("temporarily unavailable")


try:
    result = check_all_services(
        {
            "database": database_check,
            "observability": optional_observability_check,
        },
        required_services={"database"},
        parallel=True,
    )
except HealthCheckError as exc:
    print(exc.result.to_dict())
else:
    # 선택 서비스 실패는 result.ok=False로 남지만 예외를 만들지 않는다.
    print(result.to_dict())
```

비동기 함수나 서비스별/전체 timeout이 필요하면 `async_check_all_services()`를 사용한다.

## 7. NATS: 임시 검사와 지속 연결의 소유권

환경변수:

```dotenv
NATS_SERVERS=nats://localhost:4222
NATS_NAME=worker
```

```python
import asyncio

from docmesh_py_core import create_nats_client, load_service_configs


async def main() -> None:
    configs = load_service_configs(services={"nats"})
    builder = create_nats_client(configs.require_nats())

    # check()는 임시 연결을 flush한 뒤 내부에서 닫는다.
    await builder.check()

    # connect()가 반환한 지속 연결은 호출자가 소유한다.
    connection = await builder.connect()
    try:
        await connection.publish("jobs.created", b'{"id": 1}')
        await connection.flush()
    finally:
        await connection.drain()


asyncio.run(main())
```

`ServiceRuntime.close()`는 builder의 no-op `close()`를 호출할 뿐 `connect()`로 별도 생성한 지속 연결을 대신 닫지 않는다.

## 8. Logging bootstrap과 구조화 이벤트

```python
import logging

from docmesh_py_core import build_service_log_event, configure_logging

logger = configure_logging(force=True)
event = build_service_log_event(
    service="postgres",
    operation="query",
    outcome="failure",
    latency_ms=42,
    error="postgresql://alice:secret@db.example.com/app",
    extra={"token": "raw-token", "rows": 0},
)
logging.getLogger(__name__).info("service_event", extra={"service_event": event})
```

`configure_logging()`의 level 우선순위는 함수 인자, `DOCMESH_LOG_LEVEL`, `INFO` 순서다. `error`와 민감 key의 `extra` 값은 마스킹되지만 일반 `host`와 호출자가 직접 남기는 로그까지 자동 정제하지는 않는다.

파일 로그가 필요하면 경로를 명시한다.

```python
from docmesh_py_core import configure_logging

configure_logging(level="DEBUG", log_path="./var/log/app.log", force=True)
```

## 9. Keycloak Access Token

password grant 환경변수에는 URL, realm, client와 함께 token username/password를 설정하거나 호출 시 자격증명을 넘긴다.

```python
from docmesh_py_core import KeycloakAuthService, KeycloakConfig

config = KeycloakConfig()
auth = KeycloakAuthService(config)
result = auth.fetch_access_token(
    username="alice",
    password="correct-horse-battery-staple",
    scope="openid profile email",
)

print(result.token_type, result.expires_in)
# access_token/refresh_token 원문은 로그로 남기지 않는다.
```

`client_credentials` grant는 `KEYCLOAK_TOKEN_GRANT_TYPE=client_credentials`로 선택하며 username/password를 사용하지 않는다.

## 10. JWT 사용자 정보: HS256과 RS256

HS256:

```python
from docmesh_py_core import KeycloakAuthService, KeycloakConfig

config = KeycloakConfig()
auth = KeycloakAuthService(
    config,
    verification_key="shared-verification-key",
    allowed_algorithms=["HS256"],
)
user = auth.extract_user_info("Bearer <signed-jwt>")
print(user.sub, user.realm_roles, user.client_roles)
```

RS256은 JWKS endpoint를 사용하며 key rotation 시 cache를 refresh한다.

```python
from docmesh_py_core import KeycloakAuthService, KeycloakConfig

config = KeycloakConfig()
auth = KeycloakAuthService(config, allowed_algorithms=["RS256"])
user = auth.extract_user_info("<rs256-jwt>")
```

검증은 서명, `exp`, issuer 및 설정된 경우 audience를 확인한다. 실패는 `TokenValidationError`다.

## 11. Keycloak provisioning

`KEYCLOAK_PROVISIONING_ENABLED=true`와 정확히 하나의 admin 인증 모드를 설정한다. 아래 adapter는 실제 관리 SDK에 맞게 구현한다.

```python
from typing import Any

from docmesh_py_core import KeycloakConfig, KeycloakProvisioner


class AdminAdapter:
    def ensure_realm(self, config: KeycloakConfig) -> str:
        return "unchanged"

    def ensure_client(self, config: KeycloakConfig) -> str:
        return "unchanged"

    def ensure_realm_role(self, realm: str, role_name: str) -> str:
        return "created"

    def ensure_client_role(
        self,
        realm: str,
        client_id: str,
        role_name: str,
    ) -> str:
        return "created"


config = KeycloakConfig()
if config.provisioning_enabled:
    result = KeycloakProvisioner(config, admin_client=AdminAdapter()).provision()
    print(result.created, result.updated, result.unchanged, result.failed)
```

`KeycloakProvisioner.provision()` 자체는 enabled 여부를 검사하지 않으므로 애플리케이션이 위처럼 호출을 gate한다. `KEYCLOAK_PROVISIONING_DRY_RUN=true`이면 원격 변경 없이 `result.planned`만 채운다. 선언에서 제거된 원격 리소스는 자동 삭제하지 않는다. concrete admin adapter의 세션과 종료도 호출자가 소유한다.

## 12. MinIO bucket을 애플리케이션 요구사항으로 승격

```python
from docmesh_py_core import load_service_configs, require_minio_bucket

configs = load_service_configs(services={"minio"})
bucket = require_minio_bucket(configs.minio)
print(bucket)
```

`MINIO_BUCKET`은 연결 자체에는 선택값이므로 bucket이 필요한 애플리케이션만 이 helper를 사용한다.

## 13. 서비스 카탈로그 조회

```python
from docmesh_py_core import SERVICE_CATALOG, Service

for requirement in SERVICE_CATALOG[Service.POSTGRES].environment_variables():
    print(
        requirement.key,
        requirement.required,
        requirement.required_when,
        requirement.default,
        requirement.secret,
    )
```

카탈로그는 환경변수 **메타데이터**만 제공하고 프로세스 값이나 secret 원문을 읽지 않는다.

## 14. 오류 처리 기본 패턴

```python
from docmesh_py_core import ConfigError, DocMeshError

try:
    # 설정 로딩, 조립 또는 서비스 operation
    ...
except ConfigError as exc:
    for issue in exc.issues:
        print(issue.env_key, issue.reason, issue.remediation)
except DocMeshError as exc:
    print(exc.service, exc.reason_code, exc.remediation)
```

Keycloak token/JWT 오류는 [API 레퍼런스](./api.md)의 별도 오류 계층을 참고한다.
