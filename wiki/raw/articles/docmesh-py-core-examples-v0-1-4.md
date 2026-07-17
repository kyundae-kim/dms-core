---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.3.0/docs/examples.md
ingested: 2026-07-17
sha256: 81ae15aba7e008b9435e751ccf7f1fdb3c780eb954780d99c2ce83aaf4127c83
---

# docmesh-py-core Examples

이 문서는 현재 구현을 기준으로 `docmesh-py-core`를 실제 애플리케이션에 붙일 때 바로 복사·응용할 수 있는 예시를 제공합니다.

- 공개 API 설명은 [api.md](./api.md)
- 환경변수 계약은 [config.md](./config.md)
- 기본 소개는 [README](../README.md)

## 1. 권장: 가장 작은 assembly 성공 예제

```python
from docmesh_py_core import assemble_services

bundle = assemble_services(
    {"SQLITE_PATH": ":memory:"},
    services={"sqlite"},
    required={"sqlite"},
    check_on_startup=True,
)

with bundle:
    bundle.clients["sqlite"].check()
```

일반 애플리케이션 lifecycle에는 **assembly-first, direct-api-when-needed** 정책을 적용합니다. 동기 서비스는 `assemble_services()`, NATS 또는 async lifecycle은 `assemble_service_runtime()`을 우선 사용합니다. 서비스별 config/factory API는 아래와 같은 직접 사용 상황에 둡니다.

## 1.1 필요 시: 서비스별 config class를 직접 쓰는 예시

```python
from docmesh_py_core import CommonConfig, KeycloakAuthService, KeycloakConfig

common = CommonConfig()
keycloak = KeycloakConfig()

auth = KeycloakAuthService(keycloak)
token = auth.fetch_access_token(username="alice", password="wonderland")

print(common.env)
print(token.token_type)
```

적합한 상황:

- aggregate `ServiceConfigs` 전체가 필요 없을 때
- 특정 서비스 SDK만 직접 구성하고 싶을 때
- 기능 단위로 config 의존 범위를 줄이고 싶을 때

## 1.2 password grant 예시

```python
from docmesh_py_core import KeycloakAuthService, KeycloakConfig

# KEYCLOAK_TOKEN_GRANT_TYPE=password가 기본값이며 필요한 Keycloak 환경변수를 설정합니다.
keycloak = KeycloakConfig()

auth = KeycloakAuthService(keycloak)
token = auth.fetch_access_token(username="alice", password="wonderland")

print(token.token_type, token.expires_in, bool(token.access_token))
```

포인트:

- 함수 인자 `username`, `password`가 환경변수보다 우선합니다.
- 함수 인자를 생략하면 `KEYCLOAK_TOKEN_USERNAME`, `KEYCLOAK_TOKEN_PASSWORD`를 fallback으로 사용합니다.

## 2. FastAPI startup / shutdown 예시

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from docmesh_py_core import (
    assemble_services,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = assemble_services(
        {
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "docmesh",
            "POSTGRES_USER": "user",
            "POSTGRES_PASSWORD": "password",
            "MINIO_ENDPOINT": "minio.example.com:9000",
            "MINIO_ACCESS_KEY": "access-key",
            "MINIO_SECRET_KEY": "secret-key",
        },
        services={"postgres", "minio"},
        required={"postgres", "minio"},
        check_on_startup=True,
    )
    with bundle:
        app.state.services = bundle
        app.state.postgres = bundle.clients["postgres"]
        app.state.minio = bundle.clients["minio"]
        yield


app = FastAPI(lifespan=lifespan)
```

포인트:

- `assemble_services()`가 설정 탐색, 필수 서비스 검증, client 생성, startup healthcheck를 한 번에 처리
- `with bundle:` 종료 시 생성된 client를 정리

NATS를 포함하거나 event loop 안에서 health/close를 수행할 때는 async runtime을 사용합니다.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from docmesh_py_core import HealthcheckPolicy, RuntimePlan, Service, assemble_service_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    plan = RuntimePlan(
        services=(Service.SQLITE.required(), Service.NATS.required()),
        healthcheck=HealthcheckPolicy(
            on_startup=True,
            parallel=True,
            timeout_seconds=5,
        ),
    )
    runtime = await assemble_service_runtime(
        {
            "SQLITE_PATH": ":memory:",
            "NATS_SERVERS": "nats://localhost:4222",
        },
        plan=plan,
    )
    async with runtime:
        app.state.services = runtime
        app.state.nats = runtime.require(Service.NATS)
        yield


app = FastAPI(lifespan=lifespan)
```

신규 비동기 조립 코드는 위처럼 `RuntimePlan`을 `plan=`으로 전달합니다. `assemble_service_runtime()`의 문자열 기반 `services`/`required`/`one_of` 및 개별 health 인자는 deprecated이며 v0.4.0 제거를 목표로 합니다. 사전 진단에도 같은 plan을 `diagnose_services(env, plan=plan)` 형태로 재사용할 수 있습니다.

## 3. 필요한 서비스만 선택 로딩하는 예시

```python
from docmesh_py_core import create_langfuse_client, create_sqlite_client, load_service_configs

settings = load_service_configs(
    services={"sqlite", "langfuse"},
)

sqlite = create_sqlite_client(settings.require_sqlite())
sqlite.check()

langfuse = create_langfuse_client(settings.require_langfuse())
if langfuse is not None:
    langfuse.check()

assert settings.keycloak is None
assert settings.minio is None
assert settings.nats is None
```

포인트:

- 공용 라이브러리를 부분 기능만 쓸 때 불필요한 서비스 env 검증을 피할 수 있습니다.
- 선택되지 않은 서비스는 `ServiceConfigs`에서 `None`입니다.
- `LANGFUSE_ENABLED=false`면 `create_langfuse_client(...)` 결과가 `None`입니다.

## 3.1 PostgreSQL 또는 SQLite 중 하나 조립하기

내부적으로 `load_available_service_configs()`를 사용하는 `assemble_services()`는 환경변수가 존재하는 후보만 로딩합니다. 다음 예제는 PostgreSQL과 SQLite 중 하나 이상을 요구합니다.

```python
from docmesh_py_core import assemble_services

bundle = assemble_services(
    {"SQLITE_PATH": ":memory:"},
    services={"postgres", "sqlite"},
    one_of=({"postgres", "sqlite"},),
    check_on_startup=True,
)

with bundle:
    sqlite = bundle.clients["sqlite"]
    with sqlite.connect() as connection:
        value = connection.exec_driver_sql("SELECT 1").scalar_one()
        assert value == 1
```

`one_of`의 각 집합에서는 최소 한 서비스가 구성되어야 합니다. NATS는 동기 `ServiceBundle`에 포함할 수 없으므로 `assemble_service_runtime()`을 사용합니다.

## 4. Health endpoint 구성 예시

```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from docmesh_py_core import HealthCheckError, check_all_services

router = APIRouter()


@router.get("/health")
def health(request: Request):
    postgres = request.app.state.postgres
    minio = request.app.state.minio
    ollama = request.app.state.ollama

    try:
        result = check_all_services(
            {
                "postgres": postgres.check,
                "minio": minio.check,
                "ollama": ollama.check,
            },
            required_services={"postgres", "minio"},
            parallel=True,
        )
    except HealthCheckError as exc:
        return JSONResponse(
            status_code=503,
            content=exc.result.to_dict(),
        )

    return {
        "ok": result.ok,
        "services": [
            {
                "service": item.service,
                "ok": item.ok,
                "latency_ms": item.latency_ms,
                "error": item.error,
            }
            for item in result.services
        ],
    }
```

## 5. SQLite 로컬 개발 예시

환경변수 예:

```env
DOCMESH_ENV=development
KEYCLOAK_URL=https://keycloak.example.com
KEYCLOAK_REALM=docmesh
KEYCLOAK_CLIENT_ID=docmesh-backend
KEYCLOAK_CLIENT_SECRET=replace-me
SQLITE_PATH=./data/docmesh.sqlite3
MINIO_ENDPOINT=minio.example.com:9000
MINIO_ACCESS_KEY=replace-me
MINIO_SECRET_KEY=replace-me
MILVUS_URI=http://milvus.example.com:19530
OLLAMA_HOST=http://ollama.example.com:11434
LANGFUSE_ENABLED=false
NATS_SERVERS=nats://localhost:4222
```

사용 코드:

```python
from docmesh_py_core import create_sqlite_client, load_service_configs

settings = load_service_configs(services={"sqlite"})
sqlite = create_sqlite_client(settings.require_sqlite())

sqlite.check()

with sqlite.connect() as conn:
    row = conn.exec_driver_sql("SELECT 1").scalar_one()
    print(row)

sqlite.close()
```

## 6. NATS 사용 예시

```python
import asyncio

from docmesh_py_core import create_nats_client, load_service_configs

settings = load_service_configs(services={"nats"})
builder = create_nats_client(settings.require_nats())

asyncio.run(builder.check())
```

포인트:

- `create_nats_client(...)`는 연결된 클라이언트가 아니라 `NatsConnectionBuilder`를 반환합니다.
- 실제 연결은 `await builder.connect()` / `await builder.check()` 에서 일어납니다.
- `builder.check()`는 임시 연결 후 `flush()`를 수행하고 연결을 정리합니다.

## 7. 서비스별 최소 config / check / close recipe

아래 direct API recipe는 각 서비스의 최소 lifecycle을 보여 줍니다. 일반 애플리케이션에서는 먼저 `RuntimePlan`과 `assemble_service_runtime()`을 사용하고, SDK별 직접 제어가 필요할 때만 이 경로를 사용합니다.

### Keycloak

실행 전 [Keycloak 설정 계약](./config.md#31-keycloak-discovery--auth)을 준비하세요. 기본 password grant로 `client.check()`를 실행하려면 `KEYCLOAK_TOKEN_USERNAME`과 `KEYCLOAK_TOKEN_PASSWORD`도 모두 필요합니다.

```python
from docmesh_py_core import create_keycloak_client, load_service_configs

# 기본 password grant의 healthcheck에는
# KEYCLOAK_TOKEN_USERNAME과 KEYCLOAK_TOKEN_PASSWORD가 필요합니다.
configs = load_service_configs(services={"keycloak"})
client = create_keycloak_client(configs.require_keycloak())
try:
    client.check()
finally:
    client.close()
```

### PostgreSQL

실행 전 [PostgreSQL 최소 설정](./config.md#32-postgresql)을 준비하세요. 권장 경로는 `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` 조합입니다. legacy 연결 URI 호환 경로의 사용 여부와 제거 일정은 설정 문서에서 확인하세요.

```python
from docmesh_py_core import create_postgres_client, load_service_configs

configs = load_service_configs(services={"postgres"})
client = create_postgres_client(configs.require_postgres())
try:
    client.check()
finally:
    client.close()
```

### SQLite

실행 전 [SQLite 설정](./config.md#33-sqlite)에서 `SQLITE_PATH`를 설정하세요. 로컬 smoke test에는 `:memory:`를 사용할 수 있습니다.

```python
from docmesh_py_core import create_sqlite_client, load_service_configs

configs = load_service_configs(services={"sqlite"})
client = create_sqlite_client(configs.require_sqlite())
try:
    client.check()
finally:
    client.close()
```

### MinIO

실행 전 [MinIO 최소 설정](./config.md#34-minio)인 `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`를 준비하세요. production 환경에서는 `MINIO_SECURE=true`를 유지해야 합니다.

```python
from docmesh_py_core import create_minio_client, load_service_configs

configs = load_service_configs(services={"minio"})
client = create_minio_client(configs.require_minio())
try:
    client.check()
finally:
    client.close()
```

### Milvus

실행 전 [Milvus 설정](./config.md#35-milvus)에서 `MILVUS_URI`를 설정하세요. production 환경에서는 `MILVUS_SECURE=true`가 필요합니다.

```python
from docmesh_py_core import create_milvus_client, load_service_configs

configs = load_service_configs(services={"milvus"})
client = create_milvus_client(configs.require_milvus())
try:
    client.check()
finally:
    client.close()
```

### Ollama

실행 전 [Ollama 설정](./config.md#36-ollama)에서 `OLLAMA_HOST`를 설정하세요.

```python
from docmesh_py_core import create_ollama_client, load_service_configs

configs = load_service_configs(services={"ollama"})
client = create_ollama_client(configs.require_ollama())
try:
    client.check()
finally:
    client.close()
```

### Langfuse

실행 전 [Langfuse 설정](./config.md#37-langfuse)을 확인하세요. `LANGFUSE_ENABLED=false`이면 필수 key 없이 설정을 읽고 factory는 `None`을 반환합니다.

```python
from docmesh_py_core import create_langfuse_client, load_service_configs

configs = load_service_configs(services={"langfuse"})
client = create_langfuse_client(configs.require_langfuse())
if client is not None:
    try:
        client.check()
    finally:
        client.close()
```

### NATS

실행 전 [NATS 설정 및 인증 모드](./config.md#38-nats)를 준비하세요. `builder.check()`는 임시 연결을 종료하며, 지속 연결이 필요하면 `await builder.connect()`의 반환값을 호출자가 관리해야 합니다.

```python
from docmesh_py_core import create_nats_client, load_service_configs

configs = load_service_configs(services={"nats"})
builder = create_nats_client(configs.require_nats())
try:
    await builder.check()
finally:
    await builder.close()
```

통합 runtime에서는 typed lookup을 사용합니다.

```python
from docmesh_py_core import RuntimePlan, Service, assemble_service_runtime

plan = RuntimePlan(services=(Service.SQLITE.required(),))
runtime = await assemble_service_runtime({"SQLITE_PATH": ":memory:"}, plan=plan)
async with runtime:
    sqlite = runtime.require(Service.SQLITE)
    sqlite.check()
```

## 8. 로깅 설정 예시

```python
from pathlib import Path

from docmesh_py_core import configure_logging

configure_logging(log_path=Path("./logs/docmesh.log"), force=True)
```

포인트:

- `level`을 주지 않으면 `DOCMESH_LOG_LEVEL`을 읽습니다.
- `log_path` 부모 디렉터리는 자동 생성됩니다.

## 9. JWT 검증 및 사용자 정보 추출

RS256 토큰은 JWKS endpoint에서 검증 키를 가져옵니다. Keycloak 설정의 issuer 및 선택적 audience 검증도 함께 수행됩니다.

```python
from docmesh_py_core import KeycloakAuthService, KeycloakConfig

keycloak = KeycloakConfig()
auth = KeycloakAuthService(keycloak, allowed_algorithms=["RS256"])

user = auth.extract_user_info("Bearer <access-token>")

print(user.sub, user.preferred_username)
print(user.realm_roles, user.client_roles)
```

실제 토큰 원문이나 `user.claims` 전체는 로그에 기록하지 않습니다.

## 10. Keycloak 프로비저닝

라이브러리는 Admin SDK 구현을 직접 생성하지 않습니다. 소비 애플리케이션이 `ensure_realm()`, `ensure_client()`, `ensure_realm_role()`, `ensure_client_role()` 계약을 구현한 `admin_client`를 주입합니다.

```python
from docmesh_py_core import KeycloakConfig, KeycloakProvisioner


def provision_keycloak(admin_client):
    keycloak = KeycloakConfig()
    provisioner = KeycloakProvisioner(keycloak, admin_client=admin_client)
    result = provisioner.provision()

    return {
        "created": result.created,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "failed": result.failed,
        "planned": result.planned,
        "dry_run": result.dry_run,
    }
```

`KEYCLOAK_PROVISIONING_DRY_RUN=true`이면 실제 Admin API 변경 없이 `planned`만 채웁니다. 선언에서 제거된 리소스는 자동 삭제하지 않습니다.

## 11. 공개 API 레시피 인덱스

이 문서는 실행 흐름 중심의 예제이며, package root의 모든 공개 API는 [API Reference의 추적 인벤토리](./api.md#공개-api-추적-인벤토리)에서 설정 문서와 함께 역추적할 수 있습니다. 아래 예제는 앞선 lifecycle recipe에 없는 고급·보조 공개 API의 최소 사용 형태를 제공합니다.

### 사전 진단, catalog, MinIO bucket, production 보안

```python
from docmesh_py_core import (
    SERVICE_CATALOG,
    RuntimePlan,
    Service,
    diagnose_services,
    load_service_configs,
    require_minio_bucket,
    validate_runtime_security,
)

env = {"SQLITE_PATH": ":memory:"}
plan = RuntimePlan(services=(Service.SQLITE.required(),))
diagnosis = diagnose_services(env, plan=plan)
assert diagnosis.ok

# catalog metadata는 실제 secret 값을 읽거나 노출하지 않습니다.
sqlite_descriptor = SERVICE_CATALOG[Service.SQLITE]
assert sqlite_descriptor.required_environment()[0].key == "SQLITE_PATH"

configs = load_service_configs(env, services={"sqlite"})
validate_runtime_security(configs.common)

# MinIO를 제품 기능에서 실제로 사용할 때에만 opt-in 검증합니다.
# bucket = require_minio_bucket(configs.require_minio())
```

### custom client, cleanup, 관측성 helper

```python
from docmesh_py_core import (
    ServiceClientProtocol,
    ServiceClientWrapper,
    async_close_service_clients,
    build_service_log_event,
    close_service_clients,
    mask_sensitive_value,
    retry_call,
)


class InMemoryClient:
    def close(self) -> None:
        pass


client = InMemoryClient()
wrapper = ServiceClientWrapper(
    client=client,
    service_name="example",
    healthcheck=lambda: True,
)
assert isinstance(wrapper, ServiceClientProtocol)
assert wrapper.check() is True

event = build_service_log_event(service="example", operation="check", outcome="ok")
assert event["outcome"] == "ok"
assert mask_sensitive_value("token=secret") == "token=***"
assert retry_call(lambda: "ok", retry_on=(RuntimeError,), max_attempts=1) == "ok"

close_service_clients([wrapper])
# async context에서는: await async_close_service_clients([wrapper])
```

`ServiceContainerProtocol`은 기존 `ServiceBundle`과 `ServiceRuntime`을 소비자 코드에서 같은 최소 계약으로 다루기 위한 typing protocol입니다. `ServiceHandle`은 `ServiceRuntime.require()`가 반환하는 named lifecycle handle 계약입니다. 각각의 구체 lifecycle 사용은 [FastAPI 예시](#2-fastapi-startup--shutdown-예시)를 따르세요.

### 오류 처리 규칙

`ConfigError`, `HealthCheckError`, `ServiceCloseError`, `ServiceClientWrapperError` 및 Keycloak 오류(`KeycloakTokenError`, `KeycloakTokenConfigurationError`, `KeycloakTokenAuthenticationError`, `KeycloakTokenTemporaryError`, `TokenValidationError`)는 모두 [API Reference 오류 인벤토리](./api.md#오류-api)에서 발생 조건과 상위 타입을 확인합니다. 애플리케이션은 구체 오류를 처리해야 할 때만 catch하고, `DocMeshError`의 `service`, `reason_code`, `remediation`을 안전한 사용자/운영자 메시지에 사용하세요.
