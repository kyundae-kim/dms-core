---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.2.0/docs/examples.md
ingested: 2026-07-15
sha256: d76e2b460693ba11659fce056f72be9f08d5748936cb3e283a84b4fefd127b90
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
token = auth.fetch_access_token()

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

# 실행 전에 KEYCLOAK_TOKEN_GRANT_TYPE=*** 필요한 Keycloak 환경변수를 설정합니다.
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
            "POSTGRES_DSN": "postgresql+psycopg://user:password@localhost/docmesh",
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

from docmesh_py_core import assemble_service_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = await assemble_service_runtime(
        {
            "SQLITE_PATH": ":memory:",
            "NATS_SERVERS": "nats://localhost:4222",
        },
        services={"sqlite", "nats"},
        required={"sqlite", "nats"},
        check_on_startup=True,
        parallel_healthchecks=True,
        healthcheck_timeout_seconds=5,
    )
    async with runtime:
        app.state.services = runtime
        app.state.nats = runtime.require("nats")
        yield


app = FastAPI(lifespan=lifespan)
```

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

`load_available_service_configs()`를 사용하는 `assemble_services()`는 환경변수가 존재하는 후보만 로딩합니다. 다음 예제는 PostgreSQL과 SQLite 중 하나 이상을 요구합니다.

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
KEYCLOAK_CLIENT_SECRET=***
SQLITE_PATH=./data/docmesh.sqlite3
MINIO_ENDPOINT=minio.example.com:9000
MINIO_ACCESS_KEY=replace-me
MINIO_SECRET_KEY=***
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

## 7. 로깅 설정 예시

```python
from pathlib import Path

from docmesh_py_core import configure_logging

configure_logging(log_path=Path("./logs/docmesh.log"), force=True)
```

포인트:

- `level`을 주지 않으면 `DOCMESH_LOG_LEVEL`을 읽습니다.
- `log_path` 부모 디렉터리는 자동 생성됩니다.

## 8. JWT 검증 및 사용자 정보 추출

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

## 9. Keycloak 프로비저닝

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