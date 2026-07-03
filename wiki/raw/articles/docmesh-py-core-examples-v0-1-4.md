---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.4/docs/examples.md
ingested: 2026-07-03
sha256: b4b596fb4788b4d5cacc1633b96a588f36dd275485a7a427797038383a9e4da0
---

# docmesh-py-core Examples

이 문서는 현재 구현을 기준으로 `docmesh-py-core`를 실제 애플리케이션에 붙일 때 바로 복사·응용할 수 있는 예시를 제공합니다.

- 공개 API 설명은 [api.md](./api.md)
- 환경변수 계약은 [config.md](./config.md)
- 기본 소개는 [README](../README.md)

## 1. 가장 작은 성공 예제

```python
from docmesh_py_core import create_postgres_client, load_service_configs

settings = load_service_configs(services={"postgres"})
postgres = create_postgres_client(settings.postgres)

postgres.check()
postgres.close()
```

## 1.1 서비스별 config class를 직접 쓰는 예시

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

keycloak = KeycloakConfig()
keycloak.token_grant_type = "password"

auth = KeycloakAuthService(keycloak)
token = auth.fetch_access_token(username="alice", password="wonderland")

print(token.access_token)
```

포인트:

- 현재 구현은 `KEYCLOAK_TOKEN_USERNAME`, `KEYCLOAK_TOKEN_PASSWORD` 환경변수를 자동 사용하지 않습니다.
- password grant에서는 함수 인자 `username`, `password`를 넘겨야 합니다.

## 2. FastAPI startup / shutdown 예시

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from docmesh_py_core import (
    close_service_clients,
    create_minio_client,
    create_postgres_client,
    load_service_configs,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_service_configs(services={"postgres", "minio"})
    postgres = create_postgres_client(settings.postgres)
    minio = create_minio_client(settings.minio)

    app.state.settings = settings
    app.state.postgres = postgres
    app.state.minio = minio

    postgres.check()
    minio.check()

    try:
        yield
    finally:
        close_service_clients([postgres, minio])


app = FastAPI(lifespan=lifespan)
```

포인트:

- `load_service_configs()`는 startup 시 한 번만 호출
- 필요한 서비스만 `create_*_client()`로 조립
- 종료 시 `close_service_clients()` 호출

## 3. 필요한 서비스만 선택 로딩하는 예시

```python
from docmesh_py_core import create_langfuse_client, create_sqlite_client, load_service_configs

settings = load_service_configs(
    services={"sqlite", "langfuse"},
)

sqlite = create_sqlite_client(settings.sqlite)
sqlite.check()

langfuse = create_langfuse_client(settings.langfuse)
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

## 4. Health endpoint 구성 예시

```python
from fastapi import APIRouter, Request

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
        return {
            "ok": False,
            "error": str(exc),
        }

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
sqlite = create_sqlite_client(settings.sqlite)

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
builder = create_nats_client(settings.nats)

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
