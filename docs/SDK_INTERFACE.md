# SDK Public Interface

## 목적

이 문서는 현재 소스 코드 기준의 `dms.sdk` public interface를 정리한다. 초안 성격의 미래형 설명보다 실제 export, 메서드 시그니처, 반환 타입, 예외 모델을 우선한다.

## Public import

```python
from dms.sdk import (
    AccessTokenResult,
    AuthenticatedUser,
    AuthenticationError,
    ConfigurationError,
    ConsistencyError,
    DefaultDocumentManagementSDK,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentManagementSDK,
    DocumentMetadata,
    DocumentNotFoundError,
    DuplicateDocumentError,
    DmsError,
    HealthCheckFailedError,
    HealthStatus,
    MetadataStoreError,
    ServiceHealth,
    StorageError,
    UploadDocumentRequest,
    UploadDocumentResult,
    ValidationError,
    create_sdk,
    create_sdk_from_environment,
)
```

참고:
- `AccessTokenResult`, `AuthenticatedUser`는 `docmesh_py_core`에서 re-export 된다.
- `DocumentMetadata`는 `dms.domain.models`에서 정의되고 `dms.sdk`에서 re-export 된다.

## 핵심 프로토콜

```python
class DocumentManagementSDK(Protocol):
    def fetch_access_token(self, *, scope: str | None = None) -> AccessTokenResult: ...
    def get_authenticated_user(self, token: str) -> AuthenticatedUser: ...
    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult: ...
    def get_document_metadata(self, document_id: str) -> DocumentMetadata: ...
    def get_document_content(self, document_id: str) -> DocumentContent: ...
    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> DocumentContentStream: ...
    def delete_document(self, document_id: str, *, hard_delete: bool = False) -> DeleteDocumentResult: ...
    def check_health(self) -> HealthStatus: ...
    def close(self) -> None: ...
```

기본 구현체는 `DefaultDocumentManagementSDK`다.

## Factory entrypoints

### 1) 환경 기반 생성

```python
import logging
from os import environ

from dms.sdk import create_sdk

sdk = create_sdk(environ, logger=logging.getLogger("dms.sdk"))
try:
    ...
finally:
    sdk.close()
```

동작:
- 전달받은 `env`를 임시로 process environment에 overlay 한 뒤 `load_service_configs()` 호출
- MinIO 설정 존재 확인
- PostgreSQL 우선, 없으면 SQLite fallback
- 서비스별 `create_*_client()` wrapper로 metadata/object/auth 의존성 조립
- `DMS_AUTH_ENABLED`가 truthy면 Keycloak client 조립 시도
- healthcheck 활성화 시 startup health check 수행
- close 시 `close_service_clients()`가 실행되도록 callback 등록

### 2) 명시적 dependency 주입

```python
from dms.sdk import create_sdk

sdk = create_sdk(
    metadata_store=metadata_store,
    object_store=object_store,
    auth_service=auth_service,          # optional
    logger=logger,                      # optional
    id_generator=id_generator,          # optional
    service_checks=service_checks,      # optional
    close_callbacks=close_callbacks,    # optional
)
```

용도:
- 단위 테스트
- 직접 조립된 애플리케이션 컨테이너
- `docmesh-py-core` 없는 경량 사용 경로

### `create_sdk_from_environment(env)`

`create_sdk(environ)`와 같은 환경 기반 동작을 수행하는 명시적 alias다.

## 요청/응답 타입

### `UploadDocumentRequest`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentRequest:
    content: bytes
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None
    checksum: str | None = None
```

검증 규칙:
- `content`는 비어 있으면 안 된다.
- `filename`은 trim 후 비어 있으면 안 된다.
- `content_type`은 trim 후 비어 있으면 안 된다.
- filename 정규화 결과가 `.` 또는 빈 문자열이면 거부된다.

### `UploadDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentResult:
    document_id: str
    storage_key: str
    metadata: DocumentMetadata
    created: bool = True
```

### `DocumentMetadata`

```python
@dataclass(slots=True, kw_only=True)
class DocumentMetadata:
    document_id: str
    original_filename: str
    content_type: str
    file_size: int
    storage_key: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    checksum: str | None = None
    deleted_at: datetime | None = None
    created_by: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
```

`DocumentStatus` 값:
- `uploaded`
- `available`
- `deleting`
- `deleted`
- `failed`

현재 upload 성공 시 저장되는 기본 상태는 `available`이다.

### `DocumentContent`

```python
@dataclass(slots=True, kw_only=True)
class DocumentContent:
    document_id: str
    content: bytes
    content_type: str
    filename: str
    size: int
    checksum: str | None = None
```

### `DocumentContentStream`

```python
@dataclass(slots=True, kw_only=True)
class DocumentContentStream:
    document_id: str
    stream: BinaryIO
    content_type: str
    filename: str
    size: int
    checksum: str | None = None
    chunk_size: int = 65536

    def iter_chunks(self, chunk_size: int | None = None) -> Iterator[bytes]: ...
    def close(self) -> None: ...
```

동작:
- 기본 `chunk_size`는 `65536`
- `iter_chunks()`는 인자로 다른 chunk size를 임시 지정할 수 있다.
- `close()`는 내부 callback이 있으면 그것을 사용하고, 없으면 stream을 직접 닫는다.

### `DeleteDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class DeleteDocumentResult:
    document_id: str
    deleted: bool
    hard_deleted: bool
    status: DocumentStatus
```

### `ServiceHealth` / `HealthStatus`

```python
@dataclass(slots=True, kw_only=True)
class ServiceHealth:
    service: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None

@dataclass(slots=True, kw_only=True)
class HealthStatus:
    ok: bool
    services: list[ServiceHealth]
    checked_at: datetime
```

## Storage key 정책

object key는 SDK가 생성한다.

형식:
- `documents/{document_id}/{sanitized_filename}`

정규화 규칙:
- `filename.strip()`
- `..` → `.`
- `/` → `-`
- `\\` → `-`

예시:
- 입력: ` ../nested\\quarterly/report..pdf `
- 결과: `documents/<document_id>/.-nested-quarterly-report.pdf`

충돌 정책:
- 동일 `document_id` 재사용은 `DuplicateDocumentError`
- 동일 filename은 다른 `document_id`에서 허용

## 업로드/조회/삭제 semantics

### 업로드

- caller가 checksum을 주지 않으면 SDK가 SHA-256 hex digest를 계산한다.
- metadata 저장 전 object를 먼저 저장한다.
- metadata 저장 실패 시 object 삭제 rollback을 시도한다.
- rollback까지 실패하면 `ConsistencyError`를 반환한다.

### metadata 조회

- metadata가 없으면 `DocumentNotFoundError`
- backend 예외는 `MetadataStoreError`

### content 조회

- metadata는 있지만 object가 없으면 `ConsistencyError`
- 전체 바이트가 필요할 때 `get_document_content()` 사용
- 큰 파일이나 점진적 처리는 `get_document_content_stream()` 사용

### 삭제

삭제 순서:
1. metadata status를 `deleting`으로 저장
2. object 삭제 시도
3. soft delete면 metadata를 `deleted`로 저장
4. hard delete면 metadata row 삭제

실패 시 상태:
- object 삭제 실패: best-effort로 metadata를 `failed`로 바꾸고 `StorageError`
- object는 삭제됐지만 soft delete 후속 metadata 저장 실패: `ConsistencyError`, metadata는 `deleting` 상태로 남을 수 있음
- object는 삭제됐지만 hard delete 후속 metadata 삭제 실패: `ConsistencyError`, metadata는 `deleting` 상태로 남을 수 있음

## 인증 helper 계약

- auth helper는 기본 비활성이다.
- 환경 기반 factory에서는 `DMS_AUTH_ENABLED`가 truthy일 때만 Keycloak client를 조립한다.
- auth service가 없는 SDK 인스턴스에서:
  - `fetch_access_token()` → `ConfigurationError`
  - `get_authenticated_user()` → `ConfigurationError`
- `get_authenticated_user()`는 빈 문자열 token을 허용하지 않는다.
- Keycloak token 발급 실패/검증 실패는 `AuthenticationError`로 매핑된다.

## 오류 모델

```text
DmsError
├── ConfigurationError
├── ValidationError
├── AuthenticationError
├── DocumentNotFoundError
├── DuplicateDocumentError
├── StorageError
├── MetadataStoreError
├── ConsistencyError
└── HealthCheckFailedError
```

주요 매핑:
- 설정 로드/서비스 조립 실패 → `ConfigurationError`
- startup health check 실패 → `HealthCheckFailedError`
- invalid request/token/chunk size → `ValidationError` 또는 `AuthenticationError`
- object storage 실패 → `StorageError`
- metadata backend 실패 → `MetadataStoreError`
- storage와 metadata 불일치 → `ConsistencyError`

## 로깅 계약

SDK는 optional `logger`를 받아 structured logging을 남길 수 있다.

특징:
- message는 이벤트 이름 예: `document.upload.succeeded`
- extra field는 `dms_` prefix 사용
- 예: `dms_event`, `dms_document_id`, `dms_storage_key`, `dms_duration_ms`, `dms_error_type`
- raw token이나 document content는 로그에 남기지 않는다.

## 구현 범위 밖

현재 public interface에 포함되지 않는 항목:
- presigned URL API
- 검색/필터링 API
- 비동기 SDK
- NATS/Langfuse 연계 API
- 자체 authorization policy 관리 API
