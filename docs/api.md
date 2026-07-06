# API Reference

## 1. 개요

이 문서는 DMS SDK가 외부에 공개하는 Python API를 설명합니다.
주요 공개 진입점은 `dms` 네임스페이스입니다.
`dms.sdk` 경로는 내부 모듈 구조 또는 하위 호환 관점에서 존재할 수 있으나,
신규 사용 코드는 `dms` 기준 import를 사용하는 것을 권장합니다.

공개 범위:
- SDK 생성 함수
- SDK 프로토콜 및 구현체
- 요청/응답 모델
- 문서 메타데이터 모델
- 상태 점검 모델
- 공개 오류 타입

## 2. 공개 import

```python
from dms import (
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

## 3. 생성 함수

### `create_sdk(...)`

`DefaultDocumentManagementSDK` 인스턴스를 생성합니다.

지원 호출 방식:

1. 환경 기반 조립

```python
sdk = create_sdk(env, logger=logger)
```

매개변수:
- `env: Mapping[str, str]`
  - SDK 조립에 사용할 환경 변수 매핑
- `logger: logging.Logger | None = None`
  - SDK 진단 로그에 사용할 선택적 로거

2. 명시적 의존성 주입

```python
sdk = create_sdk(
    metadata_store=metadata_store,
    object_store=object_store,
    logger=logger,
    id_generator=id_generator,
    service_checks=service_checks,
    close_callbacks=close_callbacks,
)
```

매개변수:
- `metadata_store: MetadataStore`
- `object_store: ObjectStore`
- `logger: logging.Logger | None = None`
- `id_generator: MetadataIdGenerator | None = None`
- `service_checks: Mapping[str, Callable[[], object]] | None = None`
- `close_callbacks: Iterable[Callable[[], object]] | None = None`

반환값:
- `DefaultDocumentManagementSDK`

예외:
- `TypeError`
  - 환경 기반 방식과 명시적 의존성 주입 방식을 함께 전달한 경우
  - 필수 명시적 의존성이 누락된 경우
- `ConfigurationError`
  - 환경 기반 조립에서 필수 서비스나 설정을 해석할 수 없는 경우
- `HealthCheckFailedError`
  - 필수 시작 단계 상태 점검이 실패한 경우

참고:
- PostgreSQL과 SQLite가 모두 설정되어 있으면 PostgreSQL을 우선 사용합니다.
- PostgreSQL이 없고 SQLite가 설정되어 있으면 SQLite를 대체 저장소로 사용합니다.

### `create_sdk_from_environment(env, logger=None)`

환경 기반 SDK 조립을 명시적으로 호출하는 별칭 함수입니다.

매개변수:
- `env: Mapping[str, str]`
- `logger: logging.Logger | None = None`

반환값:
- `DefaultDocumentManagementSDK`

예외:
- `ConfigurationError`
- `HealthCheckFailedError`

## 4. SDK 프로토콜

### `DocumentManagementSDK`

지원되는 공개 동작을 정의한 프로토콜입니다.

메서드:
- `upload_document(request: UploadDocumentRequest) -> UploadDocumentResult`
- `get_document_metadata(document_id: str) -> DocumentMetadata`
- `get_document_content(document_id: str) -> DocumentContent`
- `get_document_content_stream(document_id: str, *, chunk_size: int = 65536) -> DocumentContentStream`
- `delete_document(document_id: str, *, hard_delete: bool = False) -> DeleteDocumentResult`
- `check_health() -> HealthStatus`
- `close() -> None`

### `DefaultDocumentManagementSDK`

`dms`에서 공개하는 구체 구현체입니다.
구체 클래스 타입이 꼭 필요할 때만 직접 사용하고,
대부분의 호출자는 `DocumentManagementSDK`와 `create_sdk(...)`를 기준으로 사용하는 것을 권장합니다.

## 5. 요청 및 응답 모델

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

필드:
- `content`
  - 원본 문서 바이트
- `filename`
  - 호출자가 전달한 원본 파일명
- `content_type`
  - MIME type 또는 이에 준하는 콘텐츠 타입 문자열
- `document_id`
  - 호출자가 선택적으로 전달하는 문서 식별자
- `metadata`
  - 문서와 함께 저장할 추가 메타데이터
- `created_by`
  - 선택적 생성 주체 정보
- `checksum`
  - 선택적 체크섬 값이며, 생략하면 SDK가 SHA-256 값을 계산합니다.

검증 규칙:
- `content`는 비어 있으면 안 됩니다.
- `filename`은 trim 후 빈 문자열이면 안 됩니다.
- `content_type`은 trim 후 빈 문자열이면 안 됩니다.
- 정규화된 파일명은 `.` 또는 빈 문자열이 되면 안 됩니다.

### `UploadDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentResult:
    document_id: str
    storage_key: str
    metadata: DocumentMetadata
    created: bool = True
```

필드:
- `document_id`
- `storage_key`
- `metadata`
- `created`

### `DeleteDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class DeleteDocumentResult:
    document_id: str
    deleted: bool
    hard_deleted: bool
    status: DocumentStatus
```

필드:
- `document_id`
- `deleted`
- `hard_deleted`
- `status`

## 6. 문서 모델

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

### `DocumentStatus`

열거형 값:
- `uploaded`
- `available`
- `deleting`
- `deleted`
- `failed`

업로드 성공 후 기본 저장 상태:
- `available`

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
```

메서드:
- `iter_chunks(chunk_size: int | None = None) -> Iterator[bytes]`
- `close() -> None`

동작:
- 기본 청크 크기는 `65536`입니다.
- `iter_chunks()`는 EOF까지 청크를 순차 반환합니다.
- `close()`는 내부 스트림 리소스를 해제합니다.

## 7. 상태 점검 모델

### `ServiceHealth`

```python
@dataclass(slots=True, kw_only=True)
class ServiceHealth:
    service: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None
```

### `HealthStatus`

```python
@dataclass(slots=True, kw_only=True)
class HealthStatus:
    ok: bool
    services: list[ServiceHealth]
    checked_at: datetime
```

## 8. 공개 오류 타입

### 기본 오류
- `DmsError`

### 설정 및 검증
- `ConfigurationError`
- `ValidationError`

### 문서 생명주기
- `DocumentNotFoundError`
- `DuplicateDocumentError`

### 저장소 및 일관성
- `StorageError`
- `MetadataStoreError`
- `ConsistencyError`

### 상태 점검
- `HealthCheckFailedError`

오류 설명:
- `ConfigurationError`
  - SDK 설정이 잘못되었거나 필수 초기화 구성이 부족한 경우
- `ValidationError`
  - 요청 payload 또는 메서드 입력값이 유효하지 않은 경우
- `DocumentNotFoundError`
  - 요청한 문서 식별자가 존재하지 않는 경우
- `DuplicateDocumentError`
  - 요청한 문서 식별자가 이미 존재하는 경우
- `StorageError`
  - 객체 저장소 접근이 실패한 경우
- `MetadataStoreError`
  - 메타데이터 저장 또는 조회가 실패한 경우
- `ConsistencyError`
  - 메타데이터와 객체 저장소 상태가 일치하지 않는 경우
- `HealthCheckFailedError`
  - 필수 서비스 상태 점검이 실패한 경우

## 9. 동작 의미

### 업로드
- 문서 본문은 메타데이터 저장보다 먼저 저장됩니다.
- 메타데이터 저장이 실패하면 문서 본문 정리를 시도합니다.
- 메타데이터 저장과 정리 모두 실패하면 SDK는 `ConsistencyError`를 발생시킵니다.

### 다운로드
- 문서 본문 조회 전 메타데이터를 먼저 확인합니다.
- 메타데이터는 존재하지만 문서 본문이 없으면 SDK는 `ConsistencyError`를 발생시킵니다.

### 삭제
- 삭제 시작 시 메타데이터 상태를 `deleting`으로 표시합니다.
- 문서 본문 삭제 실패 시 best-effort로 `failed` 상태 전환을 시도합니다.
- 논리 삭제는 메타데이터를 `deleted` 상태로 남깁니다.
- 완전 삭제는 메타데이터 행을 제거합니다.

### 상태 점검
- 환경 기반 조립에서 활성화된 경우 SDK 반환 전에 시작 단계 상태 점검을 수행합니다.
- 실행 중 상태 점검은 `check_health()`로 수행할 수 있습니다.

## 10. 최소 사용 예제

### 환경 기반 조립

```python
import logging
from os import environ

from dms import UploadDocumentRequest, create_sdk

sdk = create_sdk(environ, logger=logging.getLogger("dms"))
try:
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"hello world",
            filename="hello.txt",
            content_type="text/plain",
            metadata={"team": "platform"},
            created_by="tester",
        )
    )

    metadata = sdk.get_document_metadata(result.document_id)
    content = sdk.get_document_content(result.document_id)
    stream = sdk.get_document_content_stream(result.document_id)
    health = sdk.check_health()

    print(result.storage_key)
    print(metadata.status)
    print(content.size)
    print(health.ok)
    stream.close()
finally:
    sdk.close()
```

### 명시적 의존성 주입

```python
from dms import create_sdk

sdk = create_sdk(
    metadata_store=metadata_store,
    object_store=object_store,
)
```

## 11. 관련 문서

- `docs/prd.md`
- `docs/srs.md`
