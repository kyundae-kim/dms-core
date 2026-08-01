# DMS SDK 조립·설정 레퍼런스

- 기준 버전: `0.7.0`
- 관련 문서: [공개 API](api.md), [사용 예제](examples.md)
- 핵심 원칙: DMS는 환경변수에서 인프라 client를 만들지 않고, 호스트가 만든 client 또는 저장소 구성요소를 주입받는다.

## 1. 설정 경계

현재 공개 factory는 다음 두 가지뿐이다.

| 조립 방식 | 공개 factory | 입력 | 반환 |
| --- | --- | --- | --- |
| client 기반 | `create_sdk_from_clients(...)` | SQLAlchemy `Engine`, MinIO client, bucket 이름 | `DefaultDocumentManagementSDK` |
| component 기반 | `create_sdk_from_components(...)` | metadata/object store와 선택적 operation store | `DefaultDocumentManagementSDK` |
| client 기반 비동기 | `create_async_sdk_from_clients(...)` | client 기반 입력과 동일 | `AsyncDocumentManagementSDK` |
| component 기반 비동기 | `create_async_sdk_from_components(...)` | component 기반 입력과 동일 | `AsyncDocumentManagementSDK` |

호스트 애플리케이션이 담당하는 일:

1. 설정 파일·환경변수·secret manager에서 값을 읽는다.
2. SQLAlchemy `Engine`과 MinIO client 또는 저장소 adapter를 생성한다.
3. 필요하면 health check, logger, 소유권과 종료 callback을 등록한다.
4. DMS factory에 주입한다.
5. 애플리케이션 종료 시 DMS의 `close()` 또는 `aclose()`를 호출한다.

DMS가 담당하는 일:

- 주입된 저장소를 하나의 문서 관리 facade로 연결한다.
- 문서 업로드·조회·삭제·복구 정책과 오류 매핑을 적용한다.
- `ResourceOwnership.SDK`로 명시된 자원과 종료 callback만 정리한다.
- 선택된 health check를 실행하고 `HealthStatus`로 반환한다.

### 1.1 환경변수에 대한 명시적 제한

현재 DMS package에는 환경변수를 읽는 공개 factory 또는 환경 진단 API가 없다. 따라서 다음 이름들은 DMS가 자동으로 해석하지 않는다.

- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `POSTGRES_DSN`
- `SQLITE_PATH`
- `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`
- `DMS_METADATA_BACKEND`, `DMS_CONFIGURATION_STRICT`, `DMS_AUTH_ENABLED`

위 값이 필요하면 호스트가 자체 설정 계층에서 사용한 뒤 client/component를 만들어 전달해야 한다. 이 저장소에는 DMS용 `.env.example`을 두지 않는다. 지원하지 않는 환경변수 템플릿을 제공하면 client 생성 책임과 DMS SDK 책임이 혼동되기 때문이다.

## 2. client 기반 factory

### `create_sdk_from_clients`

```text
create_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: Callable[[], str] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
    max_file_size: int | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> DefaultDocumentManagementSDK
```

동작 규칙:

- `engine.dialect.name == "postgresql"`이면 PostgreSQL metadata adapter를 선택한다.
- `engine.dialect.name == "sqlite"`이면 SQLite metadata adapter를 선택한다.
- 그 밖의 dialect는 `ConfigurationError`다.
- `bucket_name.strip()`이 빈 문자열이면 `ConfigurationError`다.
- MinIO client와 SQLAlchemy engine 자체는 호출자 소유다.
- upload operation 저장소는 engine으로부터 SDK 내부 adapter를 조립하므로 client factory에는 `operation_store` 인자가 없다.
- `close_callbacks`와 `managed_resources`를 명시한 경우에만 해당 종료 작업이 SDK lifecycle에 포함된다.

### 비동기 client factory

```text
create_async_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: Callable[[], str] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
    max_file_size: int | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> AsyncDocumentManagementSDK
```

반환 facade가 비동기일 뿐, 저장소 선택과 ownership 정책은 sync client factory와 동일하다. 동기 adapter 작업은 async facade가 worker thread에서 실행한다.

## 3. component 기반 factory

### `create_sdk_from_components`

```text
create_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: Callable[[], str] | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> DefaultDocumentManagementSDK
```

### `create_async_sdk_from_components`

`create_async_sdk_from_components(...)`는 위와 같은 keyword를 받고 `AsyncDocumentManagementSDK`를 반환한다.

### 공통 option 표

| option | 기본값 | 적용 범위 | 설명 |
| --- | --- | --- | --- |
| `logger` | `None` | 모든 작업 | 없으면 `dms.sdk` logger를 사용한다. SDK는 stdout에 직접 출력하지 않는다. |
| `id_generator` | UUID 생성기 | 업로드 | `document_id`가 없는 요청의 id를 만든다. |
| `service_checks` | `{}` | component factory | 이름별 callable을 health/startup check에서 실행한다. |
| `close_callbacks` | `()` | lifecycle | 전달된 callable을 SDK 소유 cleanup으로 등록한다. |
| `managed_resources` | `()` | lifecycle | `ResourceOwnership.SDK`인 항목만 종료한다. |
| `plan` | `None` | 모든 공통 정책 | 제공하면 plan의 정책이 개별 option보다 우선한다. |
| `max_file_size` | `None` | upload | bytes/file/known-size stream에 공통 적용되는 양수 byte 한도다. |
| `operation_store` | `None` | component factory | bytes upload의 영속 idempotency와 operation 조회에 필요하다. |
| `metadata_validator` | `None` | upload | 없으면 `DefaultMetadataPolicy`를 사용한다. |
| `metadata_max_serialized_bytes` | `16_384` | 기본 metadata policy | JSON 직렬화 후 최대 byte 수다. |
| `metadata_max_depth` | `8` | 기본 metadata policy | 중첩 metadata 최대 깊이다. |
| `recovery_audit_hook` | `None` | 복구 | `RecoveryAuditEvent`를 best-effort로 전달한다. |

다음 정책은 factory 개별 option이 아니라 `DmsAssemblyPlan`으로 전달한다.

- `metadata_backend`
- `strict_configuration`
- `check_on_startup`
- `startup_timeout_seconds`
- `operation_observer`
- `access_policy`
- plan 안의 `logger`, `metadata_validator`, metadata limit, `max_file_size`, `recovery_audit_hook`

`plan`을 전달하면 plan에 저장된 값이 사용되므로 개별 option과 섞어 사용하지 않는 것이 좋다.

## 4. `DmsAssemblyPlan` 설정

```text
DmsAssemblyPlan(
    metadata_backend="auto",
    strict_configuration=False,
    metadata_validator=None,
    metadata_max_serialized_bytes=16_384,
    metadata_max_depth=8,
    max_file_size=None,
    check_on_startup=False,
    startup_timeout_seconds=None,
    logger=None,
    recovery_audit_hook=None,
    operation_observer=None,
    access_policy=None,
)
```

### 값 검증

- `metadata_backend`: `auto`, `postgresql`, `sqlite`만 허용한다.
- `metadata_max_serialized_bytes`: 0보다 커야 한다.
- `metadata_max_depth`: 0보다 커야 한다.
- `max_file_size`: 지정하면 0보다 커야 한다.
- `startup_timeout_seconds`: 지정하면 0보다 커야 한다.

현재 factory는 호스트가 이미 생성한 `metadata_store`/`object_store`를 받는다. `metadata_backend`는 host policy를 한 객체로 전달하고 기록하기 위한 공개 설정 값이며, 환경변수에서 client를 찾거나 만드는 selector로 해석하면 안 된다.

### startup health check

```python
plan = DmsAssemblyPlan(
    check_on_startup=True,
    startup_timeout_seconds=5.0,
)
```

- `check_on_startup=False`가 기본이다.
- 활성화하면 등록한 `service_checks`를 조립 직후 실행한다.
- 하나라도 실패하면 `HealthCheckFailedError`가 발생하고 `service`, `reason`을 확인할 수 있다.
- timeout도 `HealthCheckFailedError`로 변환된다.
- startup 실패 시 이미 SDK 소유로 등록한 자원을 역순으로 rollback한다.
- caller-owned engine/client는 명시적 `ManagedResource` 등록이 없으면 rollback 대상이 아니다.

## 5. 자원 소유권과 종료

```python
ManagedResource(
    resource=client,
    ownership=ResourceOwnership.SDK,
    close=client.close,
    name="host-client",
)
```

| 등록 방식 | SDK 종료 시 처리 |
| --- | --- |
| 기본 주입 client/component | 닫지 않음 |
| `close_callbacks=[callback]` | callback을 SDK 소유 자원으로 등록하고 역순 실행 |
| `ManagedResource(ownership=CALLER)` | 닫지 않음 |
| `ManagedResource(ownership=SDK, close=...)` | `close()`에서 실행 |
| `ManagedResource(ownership=SDK, aclose=...)` | `aclose()`에서 비동기 실행 |

- SDK 소유 자원은 등록 역순으로 한 번만 정리한다.
- 한 cleanup이 실패해도 나머지를 시도한다.
- 모든 cleanup 실패는 `ResourceCleanupError.errors`에 모은다.
- `with sdk:`와 `async with sdk:`를 사용할 수 있다.
- `close()`와 `aclose()`를 반복 호출해도 이미 정리한 자원을 다시 호출하지 않는다.
- scoped facade는 shared SDK의 lifecycle을 소유하지 않는다.

## 6. `DmsServiceConfigs`

`DmsServiceConfigs`는 호스트 설정 계층에서 사용할 수 있는 immutable configuration value object다. 이 객체가 환경을 읽거나 client를 생성하지는 않는다.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DmsServiceConfigs:
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool = False
    sqlite_path: str | None = None
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_database: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
```

검증 규칙:

- MinIO endpoint, access key, secret key, bucket은 비어 있지 않아야 한다.
- SQLite 설정과 PostgreSQL 설정 중 정확히 하나만 제공해야 한다.
- PostgreSQL을 선택하면 host/database/user/password를 모두 제공해야 한다.
- `postgres_port`는 양수여야 한다.
- secret 값은 로그·오류 메시지·문서 예제에 기록하지 않는다.

현재 public factory는 이 value object를 자동으로 소비하지 않는다. 호스트가 이 값을 이용해 engine/MinIO client를 만든 뒤 client factory에 전달하거나, host adapter를 만들어 component factory에 전달해야 한다.

## 7. metadata 정책 설정

### 기본 정책

```python
plan = DmsAssemblyPlan(
    metadata_max_serialized_bytes=32_768,
    metadata_max_depth=6,
)
```

기본 정책은 다음을 검사한다.

- mapping과 문자열 key
- JSON serializable 값
- 최대 serialized byte
- 최대 중첩 depth
- `password`, `secret`, `token`, `api_key`, `authorization`, `credential` 등 민감 key

실패는 저장소 쓰기 전에 `ValidationError`로 반환한다. policy는 입력 mapping을 변형하지 않고 JSON round-trip으로 독립된 normalized mapping을 반환한다.

### 사용자 validator

```python
from collections.abc import Mapping
from typing import Any

from dms import StructuredMetadataValidator


def parse_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if "title" not in value:
        raise ValueError("title is required")
    return {"schema_version": value["schema_version"], "title": str(value["title"]).strip()}

plan = DmsAssemblyPlan(
    metadata_validator=StructuredMetadataValidator(
        parser=parse_metadata,
        schema_version="1",
    ),
)
```

field-level schema 오류를 표현하려면 `MetadataValidationIssue` 목록을 가진 `MetadataSchemaValidationError`를 raise한다. 사용자 validator가 일반 예외를 raise하면 SDK가 public `ValidationError`로 감싼다.

## 8. upload 정책 설정

### 최대 파일 크기

```python
sdk = create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
    max_file_size=10 * 1024 * 1024,
)
```

bytes, file path, 정확한 size가 선언된 동기 binary stream에 동일하게 적용한다. 초과 시 `PayloadTooLargeError`이며 storage에 쓰기 전에 거부한다.

### 영속 idempotency

bytes upload의 `idempotency_key`를 지원하려면 component factory에 `operation_store`를 전달해야 한다. 요청에도 비어 있지 않은 `idempotency_scope`를 지정한다.

```python
sdk = create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
    operation_store=operation_store,
)
```

- 같은 scope/key와 같은 fingerprint: 기존 결과를 `created=False`로 반환한다.
- 같은 scope/key의 다른 fingerprint: `IdempotencyConflictError`다.
- 기존 작업이 pending이면 `IdempotencyInProgressError`다.
- operation 조회에는 정확한 `scope`, `idempotency_key`를 사용한다.

## 9. 권한·관찰·복구 policy

```python
plan = DmsAssemblyPlan(
    access_policy=host_access_policy,
    operation_observer=host_observer,
    recovery_audit_hook=record_recovery_audit,
)
```

- `access_policy`가 없으면 모든 작업을 허용한다.
- 정책이 false를 반환하거나 정책 실행 자체가 실패하면 `AccessDeniedError`다.
- 목록에서는 허용된 범위에 대해 cursor/page semantics를 유지한다.
- `operation_observer`는 성공·실패 `OperationEvent`를 받는다. observer가 실패해도 원래 작업은 보존된다.
- `recovery_audit_hook`는 복구 시도별 `RecoveryAuditEvent`를 받는다. hook 실패가 복구 결과를 덮지 않는다.
- 정책 callback에는 `PublicDocumentMetadata`가 전달되며 내부 `storage_key`는 전달되지 않는다.

## 10. health·logging·외부 오류 변환

### runtime health

```python
sdk = create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
    service_checks={
        "metadata": application.check_metadata_store,
        "object": application.check_object_store,
    },
)
health = sdk.check_health()
```

`service_checks` callable의 반환값 자체는 사용하지 않고, 정상 return이면 `ok=True`, 예외면 `ok=False`와 오류 문자열을 기록한다. `HealthStatus`에는 전체 `ok`, service별 결과, `checked_at`이 있다.

### structured logging

사용자 logger를 주입하면 SDK는 `dms_` prefix extra field를 사용한다. 예시는 다음과 같다.

- `dms_event`
- `dms_document_id`
- `dms_file_size`
- `dms_duration_ms`
- `dms_error_type`
- 내부 작업 로그에 한정된 `dms_storage_key`

본문, token, password 등 secret은 로그에 기록하지 않는다. 외부 응답에는 내부 log field를 그대로 노출하지 말고 `error_descriptor()` 또는 `recommended_http_error()`를 사용한다.

### HTTP 권고

DMS는 HTTP server가 아니다. host가 HTTP 응답을 만들 때만 다음을 사용한다.

```python
from dms import DmsError, error_descriptor, recommended_http_error

try:
    sdk.get_document_metadata(document_id)
except DmsError as error:
    response = recommended_http_error(error_descriptor(error))
```

설정·storage·metadata 오류의 외부 message는 내부 연결 정보와 secret을 제거한 고정 메시지다. 권장 status/body/header는 [API 오류 모델](api.md#9-전송-방식-중립-오류와-http-권고)을 따른다.

## 11. 조립 전 확인 목록

- [ ] 호스트가 engine/MinIO client 또는 두 storage component를 먼저 생성했는가?
- [ ] SQLAlchemy dialect가 `postgresql` 또는 `sqlite`인가?
- [ ] bucket 이름이 비어 있지 않은가?
- [ ] caller-owned 자원과 SDK-owned 자원을 구분했는가?
- [ ] SDK가 닫아야 할 자원만 `close_callbacks` 또는 `ManagedResource(SDK)`로 등록했는가?
- [ ] bytes idempotency를 사용한다면 `operation_store`와 scope를 제공했는가?
- [ ] metadata policy의 민감 key·depth·serialized size를 확인했는가?
- [ ] production startup에 health check/timeout이 필요한가?
- [ ] access policy가 일반·관리·복구·reset 작업을 모두 다루는가?
- [ ] 외부 HTTP 계층에서 stable code/category/retryability를 보존하는가?

## 12. 범위 밖 설정

다음 설정은 현재 DMS 공개 계약이 아니다.

- DMS가 직접 읽는 `.env` 파일 또는 환경변수
- DMS가 직접 생성·관리하는 PostgreSQL/SQLite/MinIO connection
- `DMS_AUTH_ENABLED` 기반 인증 helper
- DMS 자체 authorization policy 저장소
- presigned URL, search, message broker 설정
