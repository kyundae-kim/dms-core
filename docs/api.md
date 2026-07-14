# API Reference

## 1. 개요

이 문서는 DMS SDK가 외부에 공개하는 Python API를 설명합니다.
현재 권장 공개 진입점은 root 패키지인 `dms`입니다.
`dms.sdk`도 주요 SDK 생성 함수, 구현체, 요청/응답 모델, 오류 타입을 re-export 하지만 root 패키지와 완전히 동일한 목록은 아닙니다.

공개 범위:
- SDK 생성 함수
- 기본 SDK 구현체
- 요청/응답 모델
- 문서 메타데이터 및 상태 모델
- 상태 점검 모델
- 공개 오류 타입

## 2. 공개 import

권장 예시:

```python
from dms import (
    ConfigurationError,
    ConsistencyError,
    DefaultDocumentManagementSDK,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentMetadata,
    DocumentNotFoundError,
    DocumentStatus,
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
    create_sdk_from_components,
    create_sdk_from_environment,
)
```

대부분의 SDK 사용 심볼은 `dms.sdk`에서도 import 할 수 있습니다.
단, 현재 코드 기준 `DocumentStatus`는 root 패키지 `dms`에서 공개되며 `dms.sdk`에서는 re-export 되지 않습니다.
새 사용 코드는 root 패키지 import를 권장합니다.

## 3. 생성 함수

### `create_sdk_from_environment(env, logger=None)`

환경 변수 매핑을 받아 `DefaultDocumentManagementSDK` 인스턴스를 생성합니다.

매개변수:
- `env: Mapping[str, str]`
  - SDK 조립에 사용할 환경 변수 매핑
- `logger: logging.Logger | None = None`
  - SDK 진단 로그에 사용할 선택적 로거

반환값:
- `DefaultDocumentManagementSDK`

예외:
- `ConfigurationError`
  - 필수 서비스 설정을 해석할 수 없는 경우
  - PostgreSQL/SQLite metadata 저장소를 선택할 수 없는 경우
  - MinIO bucket 설정이 없는 경우
- `HealthCheckFailedError`
  - 시작 단계 상태 점검이 활성화되어 있고 필수 서비스 점검이 실패한 경우

동작 규칙:
- `POSTGRES_` 설정이 있으면 PostgreSQL metadata 저장소를 우선 사용합니다.
- PostgreSQL 설정이 없고 `SQLITE_PATH`가 있으면 SQLite metadata 저장소를 사용합니다.
- 둘 다 없으면 생성이 실패합니다.
- MinIO는 항상 필요합니다.
- 상태 점검이 활성화되어 있으면 생성 시점에 선택된 metadata 저장소와 MinIO를 검사합니다.

### `create_sdk_from_components(...)`

저장소 구현체와 선택적 보조 의존성을 직접 전달해 SDK를 생성합니다.

```python
sdk = create_sdk_from_components(
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
- `id_generator: Callable[[], str] | None = None`
- `service_checks: Mapping[str, Callable[[], object]] | None = None`
- `close_callbacks: Iterable[Callable[[], object]] | None = None`

반환값:
- `DefaultDocumentManagementSDK`

## 4. SDK 구현체

### `DefaultDocumentManagementSDK`

공개 메서드:
- `upload_document(request: UploadDocumentRequest) -> UploadDocumentResult`
- `get_document_metadata(document_id: str) -> DocumentMetadata`
- `list_documents(*, offset: int = 0, limit: int = 100, status: DocumentStatus | None = None) -> list[DocumentMetadata]`
- `get_document_content(document_id: str) -> DocumentContent`
- `get_document_content_stream(document_id: str, *, chunk_size: int = 65536) -> DocumentContentStream`
- `delete_document(document_id: str, *, hard_delete: bool = False) -> DeleteDocumentResult`
- `check_health() -> HealthStatus`
- `close() -> None`

`DefaultDocumentManagementSDK`는 동기 컨텍스트 관리자입니다. `with sdk as entered:`에서
`entered`는 같은 SDK 인스턴스이며 블록 종료 시 `close()`가 호출됩니다. `close()`는 멱등적이어서
직접 호출과 컨텍스트 종료가 겹쳐도 등록된 cleanup callback은 한 번만 실행됩니다.

사용 권장:
- 일반 애플리케이션 코드는 구현체를 직접 생성하기보다 `create_sdk_from_environment(...)` 또는 `create_sdk_from_components(...)`를 통해 인스턴스를 얻는 방식을 권장합니다.
- `DefaultDocumentManagementSDK`를 직접 참조해야 하는 경우는 구체 타입 비교, 테스트, 래퍼 구현처럼 실제 클래스 타입이 필요한 상황으로 한정하는 것이 좋습니다.

## 5. 저장소 프로토콜 계약

`create_sdk_from_components(...)`로 커스텀 저장소를 연결하려면 아래 프로토콜 계약을 만족해야 합니다.

프로토콜과 저장소 요청/응답 보조 타입은 root 패키지에서 re-export 되지 않으므로, 커스텀 저장소 구현 시에는 아래 경로에서 import 합니다.

```python
from dms.domain.interfaces import (
    MetadataStore,
    ObjectStore,
    PutObjectRequest,
    StoredObject,
    StoredObjectStream,
)
```

### `MetadataStore`

필수 메서드:
- `save_metadata(metadata: DocumentMetadata) -> DocumentMetadata`
- `update_metadata(metadata: DocumentMetadata) -> DocumentMetadata`
- `get_metadata(document_id: str) -> DocumentMetadata`
- `list_metadata(*, offset: int, limit: int, status: DocumentStatus | None = None) -> list[DocumentMetadata]`
- `mark_deleted(document_id: str) -> DocumentMetadata`
- `hard_delete(document_id: str) -> None`
- `exists(document_id: str) -> bool`

기대 동작:
- `save_metadata(...)`는 신규 등록 전용(insert-only)이며 같은 `document_id`가 있으면 데이터베이스 무결성 충돌을 발생시켜야 합니다. 기존 행을 merge/overwrite하지 않습니다.
- `update_metadata(...)`는 삭제 상태 전환 같은 기존 문서 정보 변경에 사용됩니다.
- 존재하지 않는 문서를 조회하거나 삭제할 수 없을 때는 `LookupError` 계열 예외를 발생시키는 것이 좋습니다.
- 다른 예외는 SDK에서 metadata backend failure로 해석되어 `MetadataStoreError` 또는 `ConsistencyError`로 매핑될 수 있습니다.
- `mark_deleted(...)`는 soft delete 완료 후 `DocumentStatus.DELETED` 상태의 metadata를 반환해야 합니다.
- `list_metadata(...)`는 생성 시각과 문서 식별자의 내림차순으로 정렬한 결과에 상태 필터와 offset/limit을 적용해야 합니다.

### `ObjectStore`

필수 메서드:
- `put_object(request: PutObjectRequest) -> str`
- `get_object(document_id: str, storage_key: str) -> StoredObject`
- `get_object_stream(document_id: str, storage_key: str) -> StoredObjectStream`
- `delete_object(document_id: str, storage_key: str) -> None`
- `object_exists(document_id: str, storage_key: str) -> bool`

기대 동작:
- `put_object(...)`는 실제 저장된 key 문자열을 반환해야 합니다.
- `get_object(...)`는 문서 바이트, 콘텐츠 타입, 파일명, 크기를 포함한 `StoredObject`를 반환해야 합니다.
- `get_object_stream(...)`는 stream 리소스를 담은 `StoredObjectStream`을 반환해야 하며, `size` 값을 제공해야 합니다.
- object가 없거나 삭제할 수 없는 경우에는 저장소 구현 예외를 발생시킬 수 있으며, SDK는 이를 `StorageError` 또는 `ConsistencyError`로 매핑합니다.

## 6. 요청 및 응답 모델

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
- `content`는 비어 있으면 안 됩니다.
- `filename`은 trim 후 빈 문자열이면 안 됩니다.
- `content_type`은 trim 후 빈 문자열이면 안 됩니다.
- 정규화된 파일명이 `.` 또는 빈 문자열이면 안 됩니다.

### `UploadDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentResult:
    document_id: str
    storage_key: str
    metadata: DocumentMetadata
    created: bool = True
```

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

주의:
- SDK 진입점인 `get_document_content_stream(..., chunk_size=...)`는 0 이하 값을 `ValidationError`로 거부합니다.
- 반환된 `DocumentContentStream.iter_chunks(chunk_size=...)`에 `None`을 전달하면 객체의 기본 `chunk_size`를 사용합니다.
- 스트림 사용 후에는 `close()`를 호출해야 합니다.
- 동기 컨텍스트 관리자(`with sdk.get_document_content_stream(...) as stream:`)를 지원하며 블록 종료 시 자동으로 닫힙니다.
- `close()`는 멱등적이며 실제 stream 정리는 한 번만 수행됩니다.

### `DeleteDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class DeleteDocumentResult:
    document_id: str
    deleted: bool
    hard_deleted: bool
    status: DocumentStatus
```

## 7. 문서 모델

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

주의:
- 현재 업로드 성공 직후 저장되는 상태는 `available` 입니다.
- `uploaded` 값은 enum 호환성/확장 여지를 위해 정의되어 있지만 현재 기본 업로드/조회/삭제 흐름에서는 사용되지 않습니다.
- 현재 권장 import 경로는 root 패키지 `dms`입니다.

## 8. 상태 점검 모델

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

## 9. 공개 오류 타입

- `DmsError`
- `ConfigurationError`
- `ValidationError`
- `DocumentNotFoundError`
- `DuplicateDocumentError`
- `StorageError`
- `MetadataStoreError`
- `ConsistencyError`
- `HealthCheckFailedError`

오류 의미:
- `ConfigurationError`: 환경 기반 조립에 필요한 설정이 부족하거나 해석할 수 없는 경우
- `ValidationError`: 요청 payload 또는 입력값이 유효하지 않은 경우
- `DocumentNotFoundError`: 요청한 문서 식별자가 존재하지 않는 경우
- `DuplicateDocumentError`: 요청한 문서 식별자가 이미 존재하는 경우
- `StorageError`: 객체 저장소 접근이 실패한 경우
- `MetadataStoreError`: 메타데이터 저장소 접근 또는 SDK 종료 중 등록된 cleanup callback 실행이 실패한 경우
- `ConsistencyError`: 메타데이터와 객체 저장소 상태가 어긋난 경우
- `HealthCheckFailedError`: 필수 서비스 상태 점검이 실패한 경우

## 10. 동작 의미

### 업로드
- 문서 본문은 메타데이터 저장보다 먼저 저장됩니다.
- 체크섬이 없으면 SHA-256으로 계산합니다.
- 메타데이터 저장이 실패하면 문서 본문 정리를 시도합니다.
- 메타데이터 저장과 정리 모두 실패하면 `ConsistencyError`를 발생시킵니다.
- 사전 중복 확인과 insert 사이의 경쟁으로 데이터베이스 충돌이 발생하면 본문을 롤백한 뒤 `DuplicateDocumentError`를 발생시킵니다.

### 다운로드
- 문서 본문 조회 전 메타데이터를 먼저 확인합니다.
- 메타데이터는 존재하지만 문서 본문이 없으면 `ConsistencyError`를 발생시킵니다.

### 목록 조회
- 기본 페이지는 offset 0, limit 100입니다.
- 상태를 지정하면 해당 상태의 문서만 반환합니다.
- offset은 0 이상, limit은 1 이상이어야 하며 잘못된 값은 `ValidationError`로 거부합니다.
- 메타데이터 저장소 조회 실패는 `MetadataStoreError`로 변환합니다.
- 이 API는 상태 하나를 고르는 기본 필터만 제공합니다. 파일명, 추가 metadata, 생성 주체 또는 본문 대상 업무 검색과 복합 필터는 제공하지 않습니다.

### 삭제
- 삭제 시작 시 메타데이터 상태를 `deleting`으로 저장합니다.
- 문서 본문 삭제 실패 시 best-effort로 `failed` 상태 전환을 시도합니다.
- soft delete는 메타데이터를 `deleted` 상태로 남깁니다.
- hard delete는 메타데이터 행을 제거합니다.

### 상태 점검
- 환경 기반 조립에서 활성화된 경우 SDK 반환 전에 시작 단계 상태 점검을 수행합니다.
- 실행 중 상태 점검은 `check_health()`로 수행할 수 있습니다.

## 11. 관련 문서

- 실행 흐름 중심 예시: `docs/examples.md`
- 환경 변수 및 조립 규칙: `docs/config.md`
## 스트리밍 업로드 (Release 2)

`UploadDocumentStreamRequest`는 `BinaryIO` 입력을 위한 공개 요청 타입이다. `stream`, 알려진
양의 `size`, `filename`, `content_type`이 필수이며 `chunk_size` 기본값은 65,536이다.
`checksum`을 지정하면 SHA-256(hex) assertion으로 사용한다.

```python
sdk.upload_document_stream(UploadDocumentStreamRequest(
    stream=file, size=file_size, filename="report.pdf",
    content_type="application/pdf", chunk_size=1024 * 1024,
    checksum=expected_sha256,
))
```

SDK는 소비되는 동안 SHA-256과 실제 바이트 수를 계산하며 전체 본문을 메모리에 적재하지
않는다. 선언 크기와 실제 읽은 크기가 다르거나 체크섬이 다르면 `ValidationError`이며,
이미 생성된 객체는 롤백한다. `create_sdk_from_components(..., max_file_size=N)`으로 bytes와
stream 업로드에 공통인 양의 최대 크기 정책을 설정할 수 있다. `ObjectStore` 구현은
`put_object_stream(PutObjectStreamRequest)`를 제공해야 한다.

## 7. 영속 업로드 멱등성

두 업로드 요청은 `idempotency_key`를 지원한다. 키는 `created_by`(없으면 고정 `anonymous`)로 범위가 나뉘며 선택된 PostgreSQL/SQLite 엔진에 영속 저장된다. 동일 요청의 성공 재호출은 `created=False`, 변경된 요청은 `IdempotencyConflictError`, 진행 중 요청은 재시도 가능한 `IdempotencyInProgressError`를 반환한다. 실패 상태는 동일 fingerprint로 재시도하며 기존 document ID를 재사용한다. 스트리밍 멱등 요청에는 소비 전에 fingerprint를 확정할 SHA-256 `checksum`이 필수다.

## 8. Release 4 운영 복구

공개 메서드는 `inspect_document`, `list_recovery_candidates`, `reconcile_document`, `reconcile_documents`이다. `DocumentInspection`은 metadata/object 존재(`object_exists`는 key 미상 시 `None`), 상태, 일관성, `RecoveryIssue`를 구분한다. metadata 부재는 예외가 아니다.

`RecoveryAction`은 `COMPLETE_DELETION_SOFT`, `COMPLETE_DELETION_HARD`, `MARK_FAILED`, `PURGE_ORPHAN_OBJECT`로 제한한다. 삭제 완료는 DELETING+object 부재, 실패 표시는 metadata 존재+object 부재, orphan purge는 metadata 부재+호출자가 제공한 알려진 storage key+object 존재 조건에서만 허용한다. batch는 FAILED/DELETING과 기존 offset/limit만 사용하며 limit은 1..1000, dry-run 및 항목별 공개 SDK 오류 결과를 제공한다.

ObjectStore에 backend-neutral 목록 연산이 없으므로 MinIO prefix scan과 orphan 자동 발견은 미래 범위다.
# Release 5 configuration and metadata API

`diagnose_environment(env) -> EnvironmentDiagnosis` is a public, side-effect-free and secret-safe preflight API. `create_sdk_from_environment` accepts the same metadata policy options as the component factory. `create_sdk_from_components(..., metadata_validator=..., metadata_max_serialized_bytes=16384, metadata_max_depth=8)` injects a callable normalizer. Validator failures are exposed as `ValidationError` before either bytes or stream object upload.

`DefaultMetadataPolicy` requires JSON-serializable metadata with string top-level keys, bounded encoded UTF-8 size/depth, and blocks common credential keys case-insensitively. `schema_version` is a recommended user convention, not a required field.
