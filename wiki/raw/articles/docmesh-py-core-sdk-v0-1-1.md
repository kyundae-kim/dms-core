---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.1/docs/sdk.md
ingested: 2026-06-15
sha256: 647f086cb5e70212422d09a2fa54ea5139180f59bd0d65d524cc9d5282d16cd6
---

# docmesh-py-core SDK 사용 가이드

이 문서는 `docmesh-py-core`를 **SDK 소비 프로젝트**에서 사용하는 개발자를 위한 메인 가이드다.

이 문서의 목표:

- 이 SDK가 어떤 문제를 해결하는지 빠르게 이해한다.
- 최소한의 설정으로 애플리케이션에 붙인다.
- 어떤 순서로 API를 호출해야 하는지 파악한다.
- PostgreSQL, SQLite, MinIO, NATS, Keycloak 같은 서비스 통합 패턴을 바로 적용한다.
- 세부 레퍼런스가 필요할 때 `config.md`, `api.md`, `test.md`로 자연스럽게 이동한다.

세부 환경변수 규칙은 [설정 가이드](./config.md), 공개 API 시그니처와 반환값은 [API 가이드](./api.md)를 참고한다.

---

## 1. 이 SDK가 해결하는 문제

`docmesh-py-core`는 DocMesh 계열 Python 서비스에서 반복되는 아래 작업을 공통화한다.

- 환경변수 기반 설정 로드와 검증
- 외부 서비스 client 생성
- 서비스별 health check 통합
- Keycloak 토큰 발급과 JWT 검증
- 민감정보 마스킹

즉, 소비 프로젝트는 서비스별 SDK 초기화 코드를 매번 직접 작성하는 대신 다음 흐름을 공통 패턴으로 사용할 수 있다.

1. 환경변수 준비
2. `load_settings()` 호출
3. `ServiceFactoryRegistry(settings)` 생성
4. 필요한 서비스 client 생성
5. `check()` 또는 실제 client 메서드 호출
6. 종료 시 `close_all()` 호출

---

## 2. 언제 이 SDK를 쓰면 좋은가

다음과 같은 프로젝트에 적합하다.

- FastAPI/Flask 같은 API 서버
- background worker / consumer
- 배치/CLI 작업
- 여러 외부 서비스(PostgreSQL, SQLite, MinIO, NATS, Keycloak 등)를 함께 쓰는 애플리케이션

특히 아래 조건이면 효과가 크다.

- 환경변수 검증을 서비스마다 따로 구현하고 싶지 않다.
- health endpoint 구성을 일관되게 맞추고 싶다.
- Keycloak 인증/토큰 처리 코드를 공통화하고 싶다.
- 로컬/테스트에서는 SQLite, 운영에서는 PostgreSQL처럼 저장소 구성을 유연하게 가져가고 싶다.

---

## 3. 빠른 시작

가장 작은 성공 예제는 아래와 같다.

```python
from os import environ

from docmesh_py_core import ServiceFactoryRegistry, load_settings

settings = load_settings(environ)
registry = ServiceFactoryRegistry(settings)

postgres = registry.create_client("postgres")
postgres.check()

with postgres.connect() as conn:
    conn.exec_driver_sql("SELECT 1")

registry.close_all()
```

SQLite를 사용할 때는 서비스명만 바뀐다.

```python
from os import environ

from docmesh_py_core import ServiceFactoryRegistry, load_settings

settings = load_settings(environ)
registry = ServiceFactoryRegistry(settings)

sqlite = registry.create_client("sqlite")
sqlite.check()

with sqlite.connect() as conn:
    conn.exec_driver_sql("SELECT 1")

registry.close_all()
```

핵심 포인트:

- 시작점은 항상 `load_settings()`다.
- client 생성은 항상 `ServiceFactoryRegistry`를 통해 수행한다.
- 서비스 연결 확인은 먼저 `check()`로 수행한다.
- 애플리케이션 종료 시 `registry.close_all()`로 자원을 정리한다.

---

## 4. 표준 사용 흐름

소비 프로젝트에서는 아래 순서를 공식 패턴으로 권장한다.

### 4.1 설정 로드

```python
from os import environ
from docmesh_py_core import load_settings

settings = load_settings(environ)
```

역할:

- 환경변수 읽기
- 타입 변환
- 필수값/조건부 필수값 검증
- 잘못된 설정에 대해 `ConfigError` 발생

### 4.2 registry 생성

```python
from docmesh_py_core import ServiceFactoryRegistry

registry = ServiceFactoryRegistry(settings)
```

역할:

- 서비스별 client 생성 책임을 한곳으로 모은다.
- 서비스 SDK 초기화 코드를 애플리케이션 코드에서 분리한다.

### 4.3 필요한 서비스만 생성

```python
postgres = registry.create_client("postgres")
minio = registry.create_client("minio")
```

권장:

- 필요한 서비스만 생성한다.
- 전 서비스를 무조건 한 번에 띄우기보다, 실제 사용하는 구성만 명시적으로 만든다.

### 4.4 시작 시 health check 수행

```python
postgres.check()
minio.check()
```

역할:

- 설정만 맞는지 확인하는 것이 아니라 실제 연결 가능한지 검증한다.

### 4.5 종료 시 정리

```python
registry.close_all()
```

역할:

- engine/client/flush/dispose 등 종료 처리를 한곳에서 수행한다.

---

## 5. 서비스 선택 방식

이 SDK는 서비스 선택을 **환경변수 존재 여부** 기반으로 처리하는 패턴을 권장한다.

예를 들면 저장소는 아래처럼 구성한다.

- PostgreSQL 사용 시: `POSTGRES_*` 설정 제공
- SQLite 사용 시: `SQLITE_*` 설정 제공

명시적 backend selector 같은 별도 스위치보다, 실제 사용하는 서비스 설정을 주입하는 방식이 소비 프로젝트에 더 자연스럽다.

### 저장소 선택 예시

#### PostgreSQL 사용

```env
POSTGRES_DSN=postgresql://user:password@db.example.com:5432/app
```

```python
postgres = registry.create_client("postgres")
```

#### SQLite 사용

```env
SQLITE_PATH=/app/data/docmesh.db
SQLITE_ENABLE_WAL=true
SQLITE_BUSY_TIMEOUT_MS=5000
```

```python
sqlite = registry.create_client("sqlite")
```

#### 메모리 SQLite 사용

```env
SQLITE_PATH=:memory:
```

테스트/로컬 실행에서 유용하다.

---

## 6. 서비스별 통합 패턴

### 6.1 PostgreSQL

사용 시점:

- 운영 서비스의 주 저장소
- connection pool이 필요한 서버 애플리케이션

예시:

```python
postgres = registry.create_client("postgres")
postgres.check()

with postgres.connect() as conn:
    rows = conn.exec_driver_sql("SELECT 1")
```

문서상 계약:

- 기본 health check는 `SELECT 1`
- `POSTGRES_DSN`이 있으면 개별 host/user/password보다 우선

관련 문서:

- [설정 가이드 - PostgreSQL](./config.md)
- [API 가이드 - ServiceFactoryRegistry](./api.md)

### 6.2 SQLite

사용 시점:

- 로컬 개발
- 테스트 환경
- 단일 파일 기반 경량 저장소
- PostgreSQL이 필요 없는 간단한 소비 프로젝트

예시:

```python
sqlite = registry.create_client("sqlite")
sqlite.check()

with sqlite.connect() as conn:
    conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS example (id INTEGER PRIMARY KEY)")
```

문서상 계약:

- `SQLITE_PATH`가 필요하다.
- `:memory:` 사용 가능
- health check는 `SELECT 1`
- `SQLITE_ENABLE_WAL`, `SQLITE_BUSY_TIMEOUT_MS`로 동작 조정 가능

### 6.3 MinIO

사용 시점:

- S3 호환 객체 저장소 사용 시
- 업로드/다운로드/버킷 확인 기능이 필요한 서비스

예시:

```python
minio = registry.create_client("minio")
minio.check()
```

문서상 계약:

- 기본 health check는 `list_buckets()`

### 6.4 NATS

주의가 가장 필요한 서비스다.

`create_client("nats")`의 반환값은 연결된 동기 client가 아니라 `NatsConnectionBuilder`다.

예시:

```python
import asyncio

builder = registry.create_client("nats")

async def main() -> None:
    connection = await builder.connect()
    await connection.flush()

asyncio.run(main())
```

또는 연결 확인만 필요하면:

```python
import asyncio

builder = registry.create_client("nats")
asyncio.run(builder.check())
```

### 6.5 Keycloak

사용 시점:

- service-to-service access token 발급
- bearer token 검증
- 사용자/역할 정보 추출

예시:

```python
from docmesh_py_core import KeycloakAuthService

auth = KeycloakAuthService(settings)
token = auth.fetch_access_token()
```

JWT 검증 예시:

```python
from docmesh_py_core import KeycloakAuthService

auth = KeycloakAuthService(settings, allowed_algorithms=["RS256"])
user = auth.extract_user_info(raw_jwt)
```

---

## 7. 애플리케이션 통합 예제

### 7.1 FastAPI 초기화 예제

```python
from contextlib import asynccontextmanager
from os import environ

from fastapi import FastAPI

from docmesh_py_core import ServiceFactoryRegistry, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings(environ)
    registry = ServiceFactoryRegistry(settings)

    if settings.postgres is not None:
        registry.create_client("postgres").check()
    if settings.sqlite is not None:
        registry.create_client("sqlite").check()

    app.state.settings = settings
    app.state.registry = registry
    try:
        yield
    finally:
        registry.close_all()


app = FastAPI(lifespan=lifespan)
```

이 패턴의 장점:

- 시작 시점에 설정/연결 실패를 즉시 드러낼 수 있다.
- app state에 공유 자원을 모아둘 수 있다.
- 종료 시 close 처리를 한곳에서 보장한다.

### 7.2 배치/CLI 예제

```python
from os import environ

from docmesh_py_core import ServiceFactoryRegistry, load_settings


def main() -> None:
    settings = load_settings(environ)
    registry = ServiceFactoryRegistry(settings)
    try:
        if settings.sqlite is not None:
            db = registry.create_client("sqlite")
        else:
            db = registry.create_client("postgres")

        db.check()
        # 실제 배치 로직
    finally:
        registry.close_all()


if __name__ == "__main__":
    main()
```

---

## 8. Health endpoint 구성 패턴

여러 서비스를 한 번에 점검할 때는 `check_all_services()`를 사용한다.

```python
from docmesh_py_core import check_all_services

postgres = registry.create_client("postgres")
minio = registry.create_client("minio")

result = check_all_services(
    {
        "postgres": postgres.check,
        "minio": minio.check,
    },
    required_services={"postgres"},
)
```

권장 방식:

- 핵심 서비스는 `required_services`에 넣는다.
- 선택 서비스는 결과 집계만 하고, 전체 readiness 실패 기준에서는 분리할 수 있다.

예:

- PostgreSQL: required
- MinIO: optional
- Langfuse: optional

---

## 9. 자주 하는 실수

### `Settings()`를 바로 만들고 끝내는 것

가능하지만, 일반적인 앱 코드에서는 `load_settings()`를 우선 권장한다.

이유:

- 검증 흐름이 명확하다.
- 에러 메시지 정리가 일관된다.

### `create_client("nats")` 결과를 동기 client처럼 쓰는 것

반환값은 `NatsConnectionBuilder`다.
반드시 `await builder.connect()` 또는 `await builder.check()`를 사용해야 한다.

### 서비스 구성을 코드 분기로 직접 하드코딩하는 것

아래처럼 환경변수/설정 기준으로 자연스럽게 분기하는 패턴이 좋다.

```python
if settings.sqlite is not None:
    db = registry.create_client("sqlite")
elif settings.postgres is not None:
    db = registry.create_client("postgres")
else:
    raise RuntimeError("No database is configured")
```

### health check 없이 실제 로직부터 실행하는 것

특히 startup 시점에는 `check()`를 먼저 수행하는 편이 디버깅에 유리하다.

---

## 10. 문제 해결 가이드

### 설정 로드에서 실패한다

확인할 것:

- 필수 환경변수가 빠지지 않았는지
- boolean 값이 `true`/`false` 형식인지
- timeout, retry, pool 값이 유효한 정수인지
- 서비스별 조건부 필수값이 충족되는지

먼저 볼 문서:

- [설정 가이드](./config.md)

### `create_client()`에서 실패한다

확인할 것:

- 해당 서비스 설정이 실제로 로드되었는지
- 서비스명이 지원 목록에 있는지
- 외부 SDK 의존성이 설치되어 있는지

먼저 볼 문서:

- [API 가이드](./api.md)

### 연결은 되지만 health check가 실패한다

확인할 것:

- endpoint/credential이 올바른지
- 네트워크 접근이 가능한지
- optional 서비스인지 required 서비스인지

먼저 볼 문서:

- [테스트 가이드](./test.md)

---

## 11. 문서 읽기 순서 추천

SDK 소비 프로젝트 개발자에게는 아래 순서를 권장한다.

1. `sdk.md` — 전체 흐름과 통합 방식 이해
2. `config.md` — 필요한 환경변수 준비
3. `api.md` — 함수/클래스 세부 레퍼런스 확인
4. `test.md` — 소비 프로젝트에서 어떤 식으로 검증할지 확인

---

## 12. 다음에 볼 문서

- [설정 가이드](./config.md)
- [API 가이드](./api.md)
- [테스트 가이드](./test.md)
