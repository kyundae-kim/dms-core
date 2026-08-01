# DMS SDK 공개 API 레퍼런스

- 기준 버전: `0.7.0`
- 지원 대상: 다른 Python 애플리케이션에서 import 하는 SDK
- 권장 import 경계: `dms` package root
- 공개 surface 근거: `dms/sdk/__init__.py`의 `__all__`과 `dms/__init__.py`가 추가하는 `DocumentStatus`
- 동작 근거: `test_dms/`의 공개 계약·동작·복구·비동기 테스트

이 문서는 공개 이름, 호출 시그니처, 반환 모델, 오류 및 자원 소유권을 현재 소스와 테스트에 연결한다. 내부 adapter, 저장소 구현, cursor 인코딩, 내부 요청 모델은 공개 API가 아니므로 이 문서의 import 예제에서 사용하지 않는다.

## 1. 공개 import 경계

소비 프로젝트는 다음과 같이 package root에서 import해야 한다.

```python
from dms import (
    UploadDocumentRequest,
    create_sdk_from_components,
)
```

`dms.sdk`는 대부분 같은 이름을 재-export하지만, 애플리케이션 코드의 안정된 계약은 `dms` root를 기준으로 한다. `dms.__all__`은 `dms/sdk/__init__.py`의 export 전체에 `DocumentStatus`를 추가한 표면이다.

### 1.1 전체 export 추적 목록

아래 표의 모든 이름은 package root에서 공개된다. `추적 ID`는 아래의 [추적성 매트릭스](#10-추적성-매트릭스)에서 source, test, example 근거로 연결된다.

#### 조립·호스트 통합

| 공개 이름 | 추적 ID |
| --- | --- |
| `create_sdk_from_clients`, `create_async_sdk_from_clients` | API-ASM |
| `create_sdk_from_components`, `create_async_sdk_from_components` | API-ASM |
| `DefaultDocumentManagementSDK`, `AsyncDocumentManagementSDK` | API-ASM |
| `ScopedDocumentManagementSDK`, `AsyncScopedDocumentManagementSDK` | API-ASM |
| `DmsAssemblyPlan`, `DmsServiceConfigs` | API-ASM |
| `ManagedResource`, `ResourceOwnership` | API-LIFE |
| `AccessContext`, `DocumentAccessPolicy` | API-POLICY |
| `DmsOperationContext` | API-POLICY |
| `OperationEvent`, `OperationObserver` | API-OBS |

#### 기능별 계약(protocol)

| 공개 이름 | 추적 ID |
| --- | --- |
| `DocumentWriter`, `DocumentReader`, `DocumentLister` | API-CONTRACT |
| `DocumentDeleter`, `DataResetter`, `DocumentHealth` | API-CONTRACT |
| `DocumentManagementClient` | API-CONTRACT |
| `DocumentCopyResult` | API-READ |

#### 업로드·조회·삭제 결과

| 공개 이름 | 추적 ID |
| --- | --- |
| `UploadDocumentRequest`, `UploadDocumentStreamRequest` | API-UPL |
| `UploadDocumentResult`, `UploadOperationResult` | API-UPL |
| `PublicDocumentMetadata`, `DocumentMetadata` | API-DATA |
| `DocumentStatus` | API-DATA |
| `DocumentContent`, `DocumentContentStream`, `AsyncDocumentContentStream` | API-READ |
| `DocumentPage` | API-READ |
| `DeleteDocumentResult` | API-DEL |
| `DataResetResult` | API-RESET |
| `HealthStatus`, `ServiceHealth` | API-OPS |

#### 복구·정합성

| 공개 이름 | 추적 ID |
| --- | --- |
| `RecoveryAction`, `RecoveryIssue` | API-REC |
| `DocumentInspection`, `ReconciliationResult` | API-REC |
| `BatchReconciliationResult` | API-REC |
| `ReconciliationPlan`, `ReconciliationPlanItem` | API-REC |
| `RecoveryAuditEvent` | API-REC |

#### 부가 정보 정책

| 공개 이름 | 추적 ID |
| --- | --- |
| `DefaultMetadataPolicy` | API-META |
| `MetadataValidator`, `MetadataNormalizer` | API-META |
| `MetadataValidationIssue`, `MetadataSchemaValidationError` | API-META |
| `StructuredMetadataValidator` | API-META |
| `public_metadata` | API-DATA |

#### 오류

| 공개 이름 | 추적 ID |
| --- | --- |
| `DmsError` | API-ERR |
| `ConfigurationError`, `ValidationError`, `AccessDeniedError` | API-ERR |
| `PayloadTooLargeError`, `DocumentNotFoundError`, `DocumentDeletedError` | API-ERR |
| `DuplicateDocumentError`, `IdempotencyConflictError`, `IdempotencyInProgressError` | API-ERR |
| `UploadOperationNotFoundError` | API-ERR |
| `StorageError`, `MetadataStoreError`, `ConsistencyError` | API-ERR |
| `ResourceCleanupError`, `DataResetError`, `HealthCheckFailedError` | API-ERR |

#### 전송 계층 변환

| 공개 이름 | 추적 ID |
| --- | --- |
| `ErrorDescriptor`, `RecommendedHttpError` | API-HTTP |
| `error_descriptor`, `merge_error_descriptor`, `recommended_http_error` | API-HTTP |

## 2. SDK 조립 API

### 2.1 client 기반 조립

호스트가 생성한 SQLAlchemy `Engine`과 MinIO client를 adapter에 연결한다. client는 기본적으로 호출자 소유이며, SDK는 전달받은 client를 자동으로 닫지 않는다.

```text
def create_sdk_from_clients(
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

- `engine.dialect.name`이 `postgresql` 또는 `sqlite`여야 한다.
- 빈 `bucket_name`과 지원하지 않는 dialect는 `ConfigurationError`다.
- `operation_store`는 client factory에서 자동으로 SQLAlchemy 기반 저장소로 조립된다.
- `plan`을 주면 plan의 정책을 사용한다. `plan`이 없을 때만 개별 정책 인자가 `DmsAssemblyPlan`으로 조립된다.
- `check_on_startup=True`인 plan은 조립 중 health check를 수행하며 실패하면 SDK 소유 자원을 rollback한다.

비동기 facade 조립은 같은 입력과 정책을 사용한다.

```python
async_sdk = create_async_sdk_from_clients(
    engine=engine,
    minio_client=minio_client,
    bucket_name="documents",
    plan=DmsAssemblyPlan(check_on_startup=True),
)
```

`create_async_sdk_from_clients(...)`의 반환값은 `AsyncDocumentManagementSDK`이다. 저장소 adapter는 동기 구현이지만 비동기 facade가 event loop 밖에서 실행한다.

### 2.2 component 기반 조립

저장소 구현을 직접 주입한다. 이 경로는 테스트, 호스트 애플리케이션의 adapter, 이미 조립된 저장소를 사용할 때 권장된다.

```text
def create_sdk_from_components(
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

`create_async_sdk_from_components(...)`는 같은 인자를 받고 `AsyncDocumentManagementSDK`를 반환한다. `metadata_store`, `object_store`, `operation_store`는 구조적 계약을 충족하는 호스트 구성요소여야 한다. 이 내부 protocol을 소비 프로젝트가 import해야 한다는 뜻은 아니다.

### 2.3 직접 구현체 생성

일반 소비자는 factory를 사용한다. 공개 구현체를 직접 생성하는 경우의 생성자는 다음과 같다.

```text
DefaultDocumentManagementSDK(
    *,
    metadata_store,
    object_store,
    logger=None,
    id_generator=None,
    service_checks=None,
    close_callbacks=None,
    managed_resources=None,
    max_file_size=None,
    operation_store=None,
    metadata_validator=None,
    recovery_audit_hook=None,
    access_policy=None,
    operation_observer=None,
)

AsyncDocumentManagementSDK(sdk: DefaultDocumentManagementSDK)
```

직접 생성과 factory 모두 같은 공개 작업·오류·종료 계약을 적용한다. `ScopedDocumentManagementSDK`와 `AsyncScopedDocumentManagementSDK`는 `sdk.scoped(context)`가 반환하는 operation-scoped facade로 사용하는 것이 기본이다.

## 3. 조립 정책·생명주기·권한

### 3.1 `DmsAssemblyPlan`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DmsAssemblyPlan:
    metadata_backend: Literal["auto", "postgresql", "sqlite"] = "auto"
    strict_configuration: bool = False
    metadata_validator: MetadataValidator | None = None
    metadata_max_serialized_bytes: int = 16_384
    metadata_max_depth: int = 8
    max_file_size: int | None = None
    check_on_startup: bool = False
    startup_timeout_seconds: float | None = None
    logger: logging.Logger | None = None
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None
    operation_observer: OperationObserver | None = None
    access_policy: DocumentAccessPolicy | None = None
```

- `metadata_backend`는 `auto`, `postgresql`, `sqlite` 중 하나여야 한다.
- `metadata_max_serialized_bytes`, `metadata_max_depth`, `max_file_size`, `startup_timeout_seconds`는 지정할 경우 양수여야 한다.
- 현재 client/component factory는 caller가 이미 선택·생성한 저장소를 받는다. 따라서 `metadata_backend`와 `strict_configuration`은 호스트가 plan을 공유할 때 사용할 정책 값이며, 환경변수를 읽어 backend를 자동 선택하는 API가 아니다.
- `access_policy`가 없으면 기존과 같이 접근 제한 없이 동작한다.
- `operation_observer`와 `recovery_audit_hook`의 실패는 원래 문서 작업 결과를 바꾸지 않는다. audit hook 실패는 로그로 남기고, observer 실패도 로그로 남긴다.

### 3.2 자원 소유권

```python
class ResourceOwnership(StrEnum):
    CALLER = "caller"
    SDK = "sdk"

@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedResource:
    resource: object
    ownership: ResourceOwnership = ResourceOwnership.CALLER
    close: Callable[[], object] | None = None
    aclose: Callable[[], object] | None = None
    name: str | None = None
```

`ResourceOwnership.SDK`인 자원은 `close` 또는 `aclose` 중 하나를 반드시 제공해야 한다. SDK가 소유한 자원과 `close_callbacks`는 등록 역순으로 종료하고, 한 자원의 종료 실패가 있어도 나머지를 시도한다. 실패가 있으면 `ResourceCleanupError.errors`에서 모든 종료 예외를 확인할 수 있다. `close()`와 `aclose()`는 반복 호출에 안전하다.

### 3.3 접근 맥락과 작업 범위

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AccessContext:
    subject: str | None = None
    tenant: str | None = None
    roles: frozenset[str] = frozenset()

class DocumentAccessPolicy(Protocol):
    def allows(
        self,
        *,
        operation: str,
        context: AccessContext | None,
        metadata: PublicDocumentMetadata | None,
    ) -> bool: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class DmsOperationContext:
    access: AccessContext | None = None
    created_by: str | None = None
    idempotency_scope: str | None = None
    audit_actor: str | None = None
    default_metadata: Mapping[str, object] = field(default_factory=dict)
```

- 정책은 호스트가 정의하며, SDK는 특정 사용자·tenant·role 체계를 해석하지 않는다.
- 일반 조회, 목록, 본문, 삭제, 전체 데이터 삭제, 내부 metadata 조회, 복구 작업에 접근 정책이 적용된다.
- 목록 정책은 페이지 생성 후 제거하지 않고 허용된 항목을 기준으로 커서와 페이지 크기를 유지한다.
- `sdk.scoped(context)`는 공유 SDK를 변경하지 않는 immutable facade다. 작업의 `created_by`, `idempotency_scope`, `audit_actor`, 기본 metadata를 주입하며 작업 호출에 명시한 값이 우선한다.

### 3.4 작업 관찰

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OperationEvent:
    operation: str
    succeeded: bool
    started_at: datetime
    completed_at: datetime
    document_id: str | None = None
    conditions: Mapping[str, object] = field(default_factory=dict)
    error_code: str | None = None

class OperationObserver(Protocol):
    def __call__(self, event: OperationEvent) -> object: ...
```

`OperationEvent.to_dict()`는 날짜·시각을 timezone-aware ISO 8601 문자열로 만든다. 이벤트에는 문서 본문, credential, 내부 `storage_key`를 포함하지 않는다. 대표 operation 이름은 `upload`, `metadata.get`, `documents.list`, `content.get`, `document.delete`, `data.clear_all`, `health.check`, `recovery.execute` 등이다.

## 4. SDK 작업 API

### 4.1 메서드 전체 coverage

아래 표는 export된 네 facade의 public method를 모두 나열한다. `DefaultDocumentManagementSDK`와 `AsyncDocumentManagementSDK`에는 SDK lifecycle dunder도 포함된다. Async 열의 메서드는 coroutine이며, async iterator 반환 메서드는 `async for`로 소비한다.

| 메서드 | 기본 sync | scoped sync | 기본 async | scoped async |
| --- | :---: | :---: | :---: | :---: |
| `__enter__`, `__exit__` | ✓ |  |  |  |
| `__aenter__`, `__aexit__` | ✓ |  | ✓ |  |
| `scoped` | ✓ |  | ✓ |  |
| `upload_document` | ✓ | ✓ | ✓ | ✓ |
| `upload_file` | ✓ | ✓ | ✓ | ✓ |
| `upload_document_stream` | ✓ | ✓ | ✓ | ✓ |
| `get_upload_operation` | ✓ | ✓ | ✓ | ✓ |
| `get_internal_document_metadata` | ✓ | ✓ | ✓ | ✓ |
| `get_document_metadata` | ✓ | ✓ | ✓ | ✓ |
| `list_documents` | ✓ | ✓ | ✓ | ✓ |
| `list_documents_page` | ✓ | ✓ | ✓ | ✓ |
| `iter_documents` | ✓ | ✓ | ✓ | ✓ |
| `inspect_document` | ✓ | ✓ | ✓ | ✓ |
| `list_recovery_candidates` | ✓ | ✓ | ✓ | ✓ |
| `iter_recovery_candidates` | ✓ | ✓ | ✓ | ✓ |
| `reconcile_document` | ✓ | ✓ | ✓ | ✓ |
| `execute_reconciliation_plan` | ✓ | ✓ | ✓ | ✓ |
| `reconcile_documents` | ✓ | ✓ | ✓ | ✓ |
| `get_document_content` | ✓ | ✓ | ✓ | ✓ |
| `get_document_content_stream` | ✓ | ✓ | ✓ | ✓ |
| `get_document_content_async_stream` | ✓ | ✓ | ✓ | ✓ |
| `iter_document_chunks` | ✓ | ✓ | ✓ | ✓ |
| `copy_document_to` | ✓ | ✓ | ✓ | ✓ |
| `delete_document` | ✓ | ✓ | ✓ | ✓ |
| `soft_delete_document` | ✓ | ✓ | ✓ | ✓ |
| `hard_delete_document` | ✓ | ✓ | ✓ | ✓ |
| `clear_all_data` | ✓ | ✓ | ✓ | ✓ |
| `initialize_for_data_load` | ✓ | ✓ | ✓ | ✓ |
| `check_health` | ✓ | ✓ | ✓ | ✓ |
| `close` | ✓ |  | ✓ |  |
| `aclose` | ✓ |  | ✓ |  |

### 4.2 기본 sync facade의 시그니처

```text
__enter__(self) -> DefaultDocumentManagementSDK
__exit__(self, exc_type, exc_value, traceback) -> None
async __aenter__(self) -> DefaultDocumentManagementSDK
async __aexit__(self, exc_type, exc_value, traceback) -> None
scoped(self, context: DmsOperationContext) -> ScopedDocumentManagementSDK

upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult
upload_file(
    self,
    path: str | Path,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    document_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
    created_by: str | None = None,
) -> UploadDocumentResult
upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult
get_upload_operation(self, *, scope: str, idempotency_key: str) -> UploadOperationResult

get_internal_document_metadata(
    self, document_id: str, *, access_context: AccessContext | None = None,
) -> DocumentMetadata
get_document_metadata(
    self, document_id: str, *, access_context: AccessContext | None = None,
) -> PublicDocumentMetadata
list_documents(
    self, *, cursor: str | None = None, limit: int = 100,
    status: DocumentStatus | None = None, access_context: AccessContext | None = None,
) -> DocumentPage
list_documents_page(
    self, *, cursor: str | None = None, limit: int = 100,
    status: DocumentStatus | None = None, access_context: AccessContext | None = None,
) -> DocumentPage
iter_documents(
    self, *, status: DocumentStatus | None = None, page_size: int = 100,
    access_context: AccessContext | None = None,
) -> Iterator[PublicDocumentMetadata]

inspect_document(
    self, document_id: str, *, access_context: AccessContext | None = None,
) -> DocumentInspection
list_recovery_candidates(
    self, *, status: DocumentStatus, offset: int = 0, limit: int = 100,
    access_context: AccessContext | None = None,
) -> list[DocumentMetadata]
iter_recovery_candidates(
    self, *, status: DocumentStatus, page_size: int = 100,
    access_context: AccessContext | None = None,
) -> Iterator[DocumentMetadata]
reconcile_document(
    self, document_id: str, action: RecoveryAction, *, storage_key: str | None = None,
    dry_run: bool = False, actor: str | None = None,
    access_context: AccessContext | None = None,
) -> ReconciliationResult
execute_reconciliation_plan(
    self, plan: ReconciliationPlan, *, actor: str | None = None,
    access_context: AccessContext | None = None,
) -> BatchReconciliationResult
reconcile_documents(
    self, *, status: DocumentStatus, action: RecoveryAction, offset: int = 0,
    limit: int = 100, dry_run: bool = False, actor: str | None = None,
    access_context: AccessContext | None = None,
) -> BatchReconciliationResult

get_document_content(
    self, document_id: str, *, access_context: AccessContext | None = None,
) -> DocumentContent
get_document_content_stream(
    self, document_id: str, *, chunk_size: int = 65536,
    access_context: AccessContext | None = None,
) -> DocumentContentStream
iter_document_chunks(
    self, document_id: str, *, chunk_size: int = 65536,
    access_context: AccessContext | None = None,
) -> Iterator[bytes]
copy_document_to(
    self, document_id: str, sink: BinaryIO, *, chunk_size: int = 65536,
    verify_checksum: bool = True, access_context: AccessContext | None = None,
) -> DocumentCopyResult
async get_document_content_async_stream(
    self, document_id: str, *, chunk_size: int = 65536,
    access_context: AccessContext | None = None,
) -> AsyncDocumentContentStream

delete_document(
    self, document_id: str, *, hard_delete: bool = False,
    access_context: AccessContext | None = None,
) -> DeleteDocumentResult
soft_delete_document(
    self, document_id: str, *, access_context: AccessContext | None = None,
) -> DeleteDocumentResult
hard_delete_document(
    self, document_id: str, *, access_context: AccessContext | None = None,
) -> DeleteDocumentResult
clear_all_data(self, *, access_context: AccessContext | None = None) -> DataResetResult
initialize_for_data_load(
    self, *, access_context: AccessContext | None = None,
) -> DataResetResult
check_health(self) -> HealthStatus
close(self) -> None
async aclose(self) -> None
```

### 4.3 scoped facade

`ScopedDocumentManagementSDK`는 [DmsOperationContext](#33-접근-맥락과-작업-범위)의 `access`를 모든 작업에 적용한다. 따라서 sync scoped 메서드에는 `access_context` 인자가 없고, 작업 범위의 값이 자동으로 적용된다. 다음 public method 전체가 제공된다.

```text
upload_document
upload_file
upload_document_stream
get_upload_operation
get_internal_document_metadata
get_document_metadata
list_documents
list_documents_page
iter_documents
get_document_content
get_document_content_stream
get_document_content_async_stream
iter_document_chunks
copy_document_to
delete_document
soft_delete_document
hard_delete_document
clear_all_data
initialize_for_data_load
inspect_document
list_recovery_candidates
iter_recovery_candidates
reconcile_document
execute_reconciliation_plan
reconcile_documents
check_health
```

`ScopedDocumentManagementSDK.get_upload_operation(...)`의 `scope`는 선택값이며 context의 `idempotency_scope`를 기본값으로 사용한다. context에도 scope가 없고 호출에도 scope가 없으면 `ValidationError`다. scoped facade는 shared SDK의 lifecycle을 소유하지 않으므로 `close()`/`aclose()`를 제공하지 않는다.

### 4.4 async facade

`AsyncDocumentManagementSDK`는 기본 sync facade의 공개 작업에 대응하는 awaitable method를 제공한다. `AsyncScopedDocumentManagementSDK`는 scoped sync facade와 같은 이름 집합을 awaitable로 제공한다.

- `await sdk.upload_document(...)`, `await sdk.list_documents(...)`, `await sdk.delete_document(...)`처럼 사용한다.
- `async for item in sdk.iter_documents(...)`와 `async for item in sdk.iter_recovery_candidates(...)`를 지원한다.
- `get_document_content_stream(...)`과 `get_document_content_async_stream(...)`은 `AsyncDocumentContentStream`을 반환한다.
- 동기 저장소 작업은 event loop를 직접 차단하지 않도록 worker thread에서 실행한다.
- 이미 시작한 동기 변경 작업은 취소가 하위 작업을 중단시키지 않는다. SDK는 정합성 경계까지 완료한 뒤 `CancelledError`를 전파하므로, 호출자는 operation 조회 등으로 최종 상태를 확인해야 한다.

## 5. 기능별 동작 계약

### 5.1 업로드

#### `UploadDocumentRequest`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentRequest:
    content: bytes
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: dict[str, Any] = {}
    created_by: str | None = None
    checksum: str | None = None
    idempotency_key: str | None = None
    idempotency_scope: str | None = None
```

- `content`는 비어 있으면 안 된다.
- `filename`, `content_type`, 선택 문자열은 문자열이고 trim 후 비어 있지 않아야 한다.
- filename은 양 끝 공백을 제거하고 `..`을 `.`, `/`와 `\\`를 `-`로 정규화한다. 정규화 결과가 `.` 또는 빈 문자열이면 거부한다.
- checksum을 주지 않으면 SHA-256 hex digest를 계산한다. 제공한 checksum은 바이트 업로드 결과 저장에 사용된다.
- `idempotency_key`를 사용하면 같은 요청에 `idempotency_scope`와 영속 `operation_store`가 반드시 있어야 한다.

#### `UploadDocumentStreamRequest`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentStreamRequest:
    stream: BinaryIO
    size: int
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: dict[str, Any] = {}
    created_by: str | None = None
```

- `size`는 정확한 양수여야 한다.
- `stream.read()`가 bytes를 반환해야 하며, 실제 읽은 크기가 선언값과 달라지면 `ValidationError`다.
- SDK는 호출자가 제공한 입력 stream을 닫지 않는다. 파일 경로 API가 내부적으로 연 파일만 SDK가 닫는다.
- 요청별 checksum, idempotency, chunk size, unknown-size 또는 async input stream은 지원하지 않는다.
- 조립 시 `max_file_size`가 있으면 bytes/file/known-size stream 모두 같은 한도를 적용하며 초과는 `PayloadTooLargeError`다.

#### `UploadDocumentResult`

```python
@dataclass(slots=True, kw_only=True)
class UploadDocumentResult:
    document_id: str
    metadata: PublicDocumentMetadata
    created: bool = True
```

본문 object를 먼저 저장하고 metadata를 저장한다. metadata 저장 실패 시 object 삭제 rollback을 시도하며, rollback까지 실패하면 `ConsistencyError`가 된다. 같은 `document_id`는 `DuplicateDocumentError`다. 같은 idempotency 요청의 replay는 `created=False`인 결과를 반환한다.

#### `UploadOperationResult`

```python
@dataclass(slots=True, kw_only=True)
class UploadOperationResult:
    scope: str
    idempotency_key: str
    document_id: str
    state: UploadOperationState
    created_at: datetime
    updated_at: datetime
```

`state`의 외부 값은 `pending`, `succeeded`, `failed`다. fingerprint와 같은 내부 비교 정보는 노출하지 않는다. 정확한 scope/key 조합이 없으면 `UploadOperationNotFoundError`다.

### 5.2 공개 문서 정보와 내부 metadata

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PublicDocumentMetadata:
    document_id: str
    original_filename: str
    content_type: str
    file_size: int
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    checksum: str | None = None
    deleted_at: datetime | None = None
    created_by: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
```

`PublicDocumentMetadata`에는 `storage_key`가 구조적으로 없다. `to_dict()`는 기존 호환 필드명인 `extra_metadata`를 유지하고, `to_public_dict()`는 외부 canonical 필드명인 `metadata`를 사용한다. 날짜·시각은 timezone-aware ISO 8601 문자열, enum은 문자열 value, 부가 정보는 JSON-compatible 값으로 직렬화한다.

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

`DocumentMetadata`는 `storage_key`를 포함하는 관리·복구용 모델이다. 일반 upload/get/list 결과에는 사용하지 않는다. 저장 위치가 필요한 경우에만 `get_internal_document_metadata(...)`, `inspect_document(...)`, 복구 API 같은 명시적인 관리 경로를 사용한다.

```python
class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    AVAILABLE = "available"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"
```

정상 새 업로드의 상태는 `AVAILABLE`이다. `UPLOADED`는 이전 데이터 호환을 위한 값이며 일반 새 흐름에서 생성하지 않는다. 일반 metadata/list는 `DELETING`과 `DELETED`를 숨긴다.

`public_metadata(value)`는 `DocumentMetadata`, `PublicDocumentMetadata`, `UploadDocumentResult`를 public-safe `PublicDocumentMetadata`로 투영한다. 투영 결과는 입력 부가 정보와 별도 복사본이다.

### 5.3 본문 반환·스트리밍

```python
@dataclass(slots=True, kw_only=True)
class DocumentContent:
    document_id: str
    content: bytes
    content_type: str
    filename: str
    size: int
    checksum: str | None = None

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

`DocumentContentStream`의 public method는 `iter_chunks(chunk_size=None)`, `iter_chunks_closing(chunk_size=None)`, `close()`, `__enter__`, `__exit__`다.

- `chunk_size`는 양수여야 한다.
- `with` 사용 시 정상·예외 종료에서 stream을 닫는다.
- `iter_chunks_closing()`은 전체 소진, 읽기 오류, iterator의 명시적 `close()`에서 SDK 소유 stream을 정리한다.
- 읽기 오류와 close 오류가 동시에 있으면 최초 읽기 오류를 보존한다.
- `copy_document_to()`는 source stream을 닫지만 caller가 제공한 sink는 닫지 않는다. 크기 또는 checksum 검증 불일치는 `ConsistencyError`다.

```python
@dataclass(slots=True, kw_only=True)
class AsyncDocumentContentStream:
    document_id: str
    _source: DocumentContentStream  # SDK가 생성하며 호출자가 직접 주입하지 않는다.
```

`AsyncDocumentContentStream`의 public property는 `content_type`, `filename`, `size`, `checksum`, `closed`다. public method는 `iter_chunks()`, `aiter_chunks_closing()`, `aclose()`, `__aenter__`, `__aexit__`다. 읽기와 close는 비동기이며 정상 소진·예외·취소·조기 `aclose()`에서 반복 호출에 안전하게 정리한다.

### 5.4 목록과 cursor

```python
@dataclass(slots=True, kw_only=True)
class DocumentPage:
    items: list[PublicDocumentMetadata]
    next_cursor: str | None
    has_more: bool
```

- 정렬은 `created_at`, `document_id` 내림차순 복합 순서다.
- `limit`는 1 이상 1000 이하여야 한다.
- 첫 조회는 `cursor=None`으로 시작한다.
- 다음 조회에는 이전 `next_cursor`를 동일한 `status`와 `limit`으로 전달해야 한다.
- cursor는 불투명 값이며 status filter와 page size에 결합된다. 변조하거나 다른 조건·페이지 크기로 재사용하면 `ValidationError`다.
- 현재 공개 목록은 cursor 방식만 지원한다. `offset` 인자와 별도의 offset API는 공개하지 않는다.
- `DocumentPage` 자체는 `items`를 순회할 수 있어 기존 `for item in page` 소비도 가능하다.
- `iter_documents()`는 cursor를 내부에서 유지하고 전체 공개 문서를 sync/async iterator로 순회한다.

### 5.5 삭제와 전체 초기화

```python
@dataclass(slots=True, kw_only=True)
class DeleteDocumentResult:
    document_id: str
    deleted: bool
    hard_deleted: bool
    status: DocumentStatus

@dataclass(frozen=True, slots=True, kw_only=True)
class DataResetResult:
    metadata_deleted: int
    objects_deleted: int
    upload_operations_deleted: int
    ready_for_data_load: bool = True

    @property
    def total_deleted(self) -> int: ...
```

`delete_document(..., hard_delete=False)`는 논리 삭제, `soft_delete_document(...)`와 `hard_delete_document(...)`는 명시적인 convenience method다. 삭제 순서는 metadata를 `DELETING`으로 표시하고 object를 삭제한 뒤 metadata를 `DELETED`로 표시하거나 hard delete한다.

- object 삭제 실패: metadata를 best-effort로 `FAILED`로 표시하고 `StorageError`.
- object 삭제 후 metadata 후속 처리가 실패: `ConsistencyError`; metadata는 `DELETING`일 수 있다.
- 논리 삭제 결과는 `hard_deleted=False`, 완전 삭제 결과는 `hard_deleted=True`다.

`clear_all_data()`와 `initialize_for_data_load()`는 개별 document 삭제와 다른 전역 관리 작업이다. DMS가 관리하는 metadata, `documents/` prefix object, 설정된 upload operation record를 모두 대상으로 하며 orphan object도 정리한다. 두 작업은 분산 transaction을 주장하지 않는다. 한 store가 실패해도 나머지를 시도하며 `DataResetError.result`, `failed_stores`, `errors`로 부분 결과를 제공한다. 부분 실패 결과의 `ready_for_data_load`는 `False`다. `initialize_for_data_load()`는 빈 상태에서도 성공하는 멱등 작업이다.

### 5.6 상태 점검과 복구

```python
class RecoveryIssue(StrEnum):
    NONE = "none"
    METADATA_MISSING = "metadata_missing"
    OBJECT_MISSING = "object_missing"
    DELETION_INCOMPLETE = "deletion_incomplete"
    FAILED_STATUS = "failed_status"

class RecoveryAction(StrEnum):
    COMPLETE_DELETION_SOFT = "complete_deletion_soft"
    COMPLETE_DELETION_HARD = "complete_deletion_hard"
    MARK_FAILED = "mark_failed"
    PURGE_ORPHAN_OBJECT = "purge_orphan_object"

@dataclass(slots=True, kw_only=True)
class DocumentInspection:
    document_id: str
    metadata_exists: bool
    object_exists: bool | None
    status: DocumentStatus | None
    consistent: bool
    issue: RecoveryIssue
    storage_key: str | None = None
```

`inspect_document()`은 metadata가 없어도 `DocumentNotFoundError` 대신 `metadata_exists=False`인 검사 결과를 반환한다. `storage_key`를 포함할 수 있으므로 public 일반 조회와 분리된 관리 경로다.

복구 method는 다음과 같다.

- `list_recovery_candidates(status=..., offset=0, limit=100)`: `FAILED` 또는 `DELETING`만 허용하며 limit은 1~1000이다. 반환값은 내부 `DocumentMetadata` 목록이다.
- `iter_recovery_candidates(...)`: offset을 내부에서 유지하는 전체 순회다.
- `reconcile_document(document_id, action, storage_key=None, dry_run=False, actor=None)`: 단일 항목을 재검사하고 조건이 맞을 때 복구한다.
- `reconcile_documents(status, action, offset=0, limit=100, dry_run=False, actor=None)`: 제한된 범위의 일괄 복구다.
- `BatchReconciliationResult.to_plan()`: dry-run 결과에서만 실행 계획을 내보낸다. 실행 계획은 실행 시 각 항목을 다시 검사한다.
- `execute_reconciliation_plan(plan, actor=None)`: 계획을 다시 검사한 뒤 항목별 결과를 반환한다.

```python
@dataclass(slots=True, kw_only=True)
class ReconciliationResult:
    document_id: str
    action: RecoveryAction
    applied: bool
    inspection: DocumentInspection | None
    error_type: str | None = None
    error_message: str | None = None

@dataclass(slots=True, kw_only=True)
class BatchReconciliationResult:
    status: DocumentStatus
    action: RecoveryAction
    dry_run: bool
    offset: int
    limit: int
    items: list[ReconciliationResult]
```

`BatchReconciliationResult`의 계산 property는 `scanned`, `failed`, `eligible`, `applied`, `skipped`다. 복구 callback/audit hook 실패가 다른 항목 처리를 가리지 않는 best-effort 운영 경계를 제공한다.

`RecoveryAction.PURGE_ORPHAN_OBJECT`는 metadata가 없는 object와 호출자가 명시한 `storage_key`가 모두 있어야 한다. 일반 public metadata로 저장 위치를 얻어 복구하는 방식은 지원하지 않는다.

## 6. 공개 protocol과 data model

### 6.1 기능별 protocol

기능별 protocol은 호스트가 구체 SDK 구현을 상속하지 않고 테스트 대역이나 facade를 작성할 수 있는 최소 계약이다.

```python
class DocumentWriter(Protocol):
    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult: ...
    def upload_file(self, path: str | Path, *, filename=None, content_type=None,
                    document_id=None, metadata=None, created_by=None) -> UploadDocumentResult: ...
    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult: ...

class DocumentReader(Protocol):
    def get_document_metadata(self, document_id: str, *, access_context=None) -> PublicDocumentMetadata: ...
    def get_document_content(self, document_id: str, *, access_context=None) -> DocumentContent: ...
    def get_document_content_stream(self, document_id: str, *, chunk_size=65536,
                                    access_context=None) -> DocumentContentStream: ...
    def copy_document_to(self, document_id: str, sink: BinaryIO, *, chunk_size=65536,
                         verify_checksum=True, access_context=None) -> DocumentCopyResult: ...

class DocumentLister(Protocol):
    def list_documents(self, *, cursor=None, limit=100, status=None,
                       access_context=None) -> DocumentPage: ...
    def iter_documents(self, *, status=None, page_size=100,
                       access_context=None) -> Iterator[PublicDocumentMetadata]: ...

class DocumentDeleter(Protocol):
    def delete_document(self, document_id: str, *, hard_delete=False,
                        access_context=None) -> DeleteDocumentResult: ...

class DataResetter(Protocol):
    def clear_all_data(self, *, access_context=None) -> DataResetResult: ...
    def initialize_for_data_load(self, *, access_context=None) -> DataResetResult: ...

class DocumentHealth(Protocol):
    def check_health(self) -> HealthStatus: ...

class DocumentManagementClient(
    DocumentWriter, DocumentReader, DocumentLister, DocumentDeleter,
    DataResetter, DocumentHealth, Protocol,
):
    pass
```

`DefaultDocumentManagementSDK`는 위 기능별 protocol과 `DocumentManagementClient`를 runtime-checkable하게 만족한다. 복구 method, 내부 metadata method, operation 상태 조회, 정책·관찰 callback은 facade의 확장 계약이며 기능별 protocol의 최소 표면에는 포함되지 않는다.

### 6.2 본문 복사·health 모델

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentCopyResult:
    document_id: str
    bytes_copied: int
    checksum: str
    checksum_verified: bool

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

`check_health()`는 factory에 전달한 `service_checks`를 모두 실행하고, 한 check가 실패해도 나머지를 계속 확인한다. 전체 `ok`가 false이면 해당 service의 error와 latency를 확인한다. `DmsAssemblyPlan(check_on_startup=True)`에서는 startup failure가 `HealthCheckFailedError`로 변환된다.

### 6.3 JSON 직렬화

다음 공개 결과는 `to_dict()`, JSON-compatible 값, JSON Schema를 제공한다.

- `PublicDocumentMetadata`
- `UploadDocumentResult`
- `DocumentPage`
- `DeleteDocumentResult`
- `DataResetResult`

`json_schema()`와 `model_json_schema()`는 같은 schema를 반환한다. schema와 canonical dump에는 `storage_key`가 없다. `DocumentCopyResult`, `DocumentInspection`, `ReconciliationResult`, `BatchReconciliationResult`, `ReconciliationPlan`, `ReconciliationPlanItem`, `RecoveryAuditEvent`, `HealthStatus`, `ServiceHealth`, `OperationEvent`, `UploadOperationResult`도 `to_dict()`로 JSON-compatible 표현을 제공한다. 관리·복구 결과의 `storage_key`는 일반 외부 응답으로 전달하지 않도록 호스트가 별도 경계를 유지해야 한다.

## 7. 부가 정보 정책

```python
class MetadataValidator(Protocol):
    def __call__(self, metadata: Mapping[str, Any]) -> dict[str, Any]: ...

MetadataNormalizer = Callable[[Mapping[str, Any]], dict[str, Any]]

@dataclass(frozen=True, slots=True)
class MetadataValidationIssue:
    path: tuple[str | int, ...]
    code: str
    message: str

class MetadataSchemaValidationError(ValidationError):
    issues: tuple[MetadataValidationIssue, ...]

@dataclass(frozen=True, slots=True)
class StructuredMetadataValidator:
    parser: Callable[[Mapping[str, Any]], object]
    schema_version: str
    version_field: str = "schema_version"
    projector: Callable[[object], Mapping[str, Any]] | None = None
    policy: MetadataValidator = DefaultMetadataPolicy()

@dataclass(frozen=True)
class DefaultMetadataPolicy:
    max_serialized_bytes: int = 16_384
    max_depth: int = 8
    blocked_keys: frozenset[str] = frozenset({
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "access_token", "refresh_token", "authorization", "credential",
        "credentials", "private_key",
    })
```

기본 정책은 JSON serializable mapping, 문자열 key, 최대 깊이, serialized byte 크기 및 credential 성격의 key를 검사한다. 검증 실패는 upload가 storage를 건드리기 전에 `ValidationError` 계열로 반환한다. `StructuredMetadataValidator`는 먼저 `schema_version`을 확인하고 parser/projector를 실행한 뒤 공통 policy를 적용한다.

## 8. 오류 모델

모든 공개 SDK 오류는 `DmsError`에서 파생되며 class-level `code`, `category`, `retryable`을 가진다. 인스턴스는 가능한 경우 `document_id`와 진단 객체를 제공한다.

| 오류 | code | category | retryable | 호출자 조치 |
| --- | --- | --- | :---: | --- |
| `ConfigurationError` | `configuration_invalid` | `configuration` | 아니오 | factory 입력과 dialect/bucket 확인 |
| `ValidationError` | `validation_invalid` | `validation` | 아니오 | 요청·cursor·정책 값 수정 |
| `AccessDeniedError` | `access_denied` | `access` | 아니오 | `AccessContext`/호스트 권한 확인 |
| `PayloadTooLargeError` | `document_too_large` | `validation` | 아니오 | 파일 크기 또는 `max_file_size` 확인 |
| `DocumentNotFoundError` | `document_not_found` | `not_found` | 아니오 | id 또는 삭제 은닉 정책 확인 |
| `DocumentDeletedError` | `document_deleted` | `unavailable` | 아니오 | 관리 metadata/복구 경로 사용 |
| `DuplicateDocumentError` | `document_duplicate` | `conflict` | 아니오 | 다른 id 또는 기존 문서 사용 |
| `IdempotencyConflictError` | `idempotency_conflict` | `conflict` | 아니오 | 같은 key로 다른 요청을 보내지 않음 |
| `IdempotencyInProgressError` | `idempotency_in_progress` | `conflict` | 예 | 같은 operation을 상태 조회 후 재시도 |
| `UploadOperationNotFoundError` | `upload_operation_not_found` | `not_found` | 아니오 | 정확한 scope/key 확인 |
| `StorageError` | `object_storage_failed` | `storage` | 예 | object storage 상태 확인 후 재시도 |
| `MetadataStoreError` | `metadata_store_failed` | `storage` | 예 | metadata store 상태 확인 후 재시도 |
| `MetadataSchemaValidationError` | `validation_invalid` | `validation` | 아니오 | `issues`의 field path별 metadata 수정 |
| `ConsistencyError` | `document_inconsistent` | `consistency` | 아니오 | inspect/reconciliation 수행 |
| `DataResetError` | `data_reset_failed` | `consistency` | 예 | `result`와 `failed_stores` 확인 후 재실행 |
| `ResourceCleanupError` | `resource_cleanup_failed` | `lifecycle` | 아니오 | `errors`를 운영 로그에 기록 |
| `HealthCheckFailedError` | `startup_health_failed` | `health` | 예 | service/reason 확인 후 startup 재시도 |
| `DmsError` | `dms_error` | `internal` | 아니오 | 외부 메시지는 secret-safe descriptor로 변환 |

`DataResetError`는 `result`, `errors`, `failed_stores`를 제공한다. `HealthCheckFailedError`는 `service`, `reason`을 제공한다. `ResourceCleanupError`는 모든 cleanup 예외의 `errors` tuple을 제공한다.

## 9. 전송 방식 중립 오류와 HTTP 권고

```python
@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    code: str
    category: str
    retryable: bool
    message: str
    retry_after_seconds: int | None = None
    external_code: str | None = None

@dataclass(frozen=True, slots=True)
class RecommendedHttpError:
    status: int
    body: dict[str, object]
    headers: dict[str, str] = field(default_factory=dict)

def error_descriptor(
    error: DmsError, *, retry_after_seconds: int | None = None,
) -> ErrorDescriptor: ...

def merge_error_descriptor(
    descriptor: ErrorDescriptor, *, message: str | None = None,
    external_code: str | None = None, retry_after_seconds: int | None = None,
) -> ErrorDescriptor: ...

def recommended_http_error(
    error: DmsError | ErrorDescriptor,
) -> RecommendedHttpError: ...
```

- `error_descriptor()`는 SDK의 canonical code/category/retryability를 유지하고 설정·저장소 계열의 내부 메시지를 고정된 public message로 바꾼다.
- `merge_error_descriptor()`는 host message/external code/retry-after만 합성하며 canonical 분류를 덮어쓰지 않는다.
- `recommended_http_error()`는 SDK exception을 HTTP exception으로 바꾸지 않고 권장 status, JSON body, 선택적 `Retry-After` header를 별도 모델로 반환한다.

| 오류 code/category | 권장 status |
| --- | ---: |
| `access_denied` | 403 |
| validation (`validation_invalid`) | 400 |
| `document_too_large` | 413 |
| not found | 404 |
| conflict/deleted | 409 |
| idempotency in progress | 425 |
| storage/metadata/health | 503 |
| configuration/consistency/reset/기타 | 500 |

## 10. 추적성 매트릭스

각 공개 영역을 source 구현, 실행 테스트, 사용 예제로 연결한다. 테스트 경로는 현재 repository 기준이며, 예제는 `docs/examples.md`의 명시적 anchor를 사용한다.

| 추적 ID | 공개 영역 | source 근거 | test 근거 | example |
| --- | --- | --- | --- | --- |
| API-ASM | factory와 sync/async facade | `dms/sdk/factory.py`, `dms/sdk/implementation.py`, `dms/sdk/async_sdk.py` | `test_sdk_contract_completion.py`, `test_sdk_public_contract.py` | [조립과 기본 업로드](examples.md#example-assembly) |
| API-LIFE | ownership, close/rollback | `dms/sdk/contracts.py`, `dms/sdk/lifecycle.py` | `test_sdk_contract_completion.py`, `test_sdk_lifecycle_and_conflicts.py` | [자원 소유권](examples.md#example-ownership) |
| API-POLICY | access/context/scoped facade | `dms/sdk/contracts.py`, `dms/sdk/implementation.py` | `test_sdk_consumer_integration_contracts.py` | [접근 정책과 scoped](examples.md#example-policy) |
| API-OBS | operation observer/audit event | `dms/sdk/contracts.py`, `dms/sdk/implementation.py` | `test_sdk_consumer_integration_contracts.py`, `test_sdk_data_reset.py` | [관찰 이벤트](examples.md#example-observer) |
| API-CONTRACT | 기능별 runtime-checkable protocol | `dms/sdk/contracts.py` | `test_sdk_contract_completion.py` | [호스트 protocol 사용](examples.md#example-contracts) |
| API-UPL | bytes/file/known-size stream/idempotency | `dms/sdk/types.py`, `dms/sdk/upload.py` | `test_sdk_behavior.py`, `test_sdk_stream_upload_contract.py`, `test_sdk_idempotency.py`, `test_sdk_upload_surface_reduction.py` | [업로드](examples.md#example-upload), [멱등성](examples.md#example-idempotency) |
| API-DATA | public/internal metadata와 status | `dms/sdk/types.py`, `dms/domain/models.py` | `test_sdk_public_contract.py`, `test_sdk_metadata.py` | [공개 metadata](examples.md#example-metadata) |
| API-READ | content/stream/cursor/copy | `dms/sdk/types.py`, `dms/sdk/documents.py`, `dms/sdk/pagination.py` | `test_sdk_behavior.py`, `test_sdk_pagination.py`, `test_sdk_contract_completion.py` | [스트림·복사](examples.md#example-stream), [목록](examples.md#example-pagination) |
| API-DEL | soft/hard delete와 상태 | `dms/sdk/implementation.py`, `dms/sdk/documents.py` | `test_sdk_behavior.py`, `test_sdk_lifecycle_and_conflicts.py` | [삭제](examples.md#example-delete) |
| API-RESET | 전체 삭제와 적재 초기화 | `dms/sdk/implementation.py`, `dms/sdk/types.py` | `test_sdk_data_reset.py` | [전체 reset](examples.md#example-reset) |
| API-REC | inspect/candidate/reconciliation/plan | `dms/sdk/reconciliation.py`, `dms/sdk/types.py` | `test_sdk_reconciliation.py`, `test_sdk_reconciliation_core.py` | [복구 dry-run](examples.md#example-recovery) |
| API-OPS | health와 SDK lifecycle | `dms/sdk/lifecycle.py`, `dms/sdk/types.py` | `test_sdk_behavior.py`, `test_sdk_contract_completion.py` | [health와 종료](examples.md#example-health) |
| API-META | metadata validator/policy/schema | `dms/sdk/metadata.py` | `test_sdk_configuration_and_metadata_policy.py`, `test_sdk_metadata.py` | [metadata 정책](examples.md#example-metadata-policy) |
| API-ERR | 예외 hierarchy와 stable descriptor | `dms/sdk/errors.py` | `test_sdk_behavior.py`, `test_sdk_contract_completion.py`, `test_sdk_data_reset.py` | [오류 분기](examples.md#example-errors) |
| API-HTTP | error descriptor와 HTTP projection | `dms/sdk/http.py` | `test_sdk_contract_completion.py`, `test_sdk_feedback_http_async_cursor.py` | [HTTP 변환](examples.md#example-http) |

### 문서 검증 명령

다음 명령은 package `__all__`, root 추가 export, 기본 SDK class의 public method 및 문서 존재 여부를 기계적으로 확인한다.

```bash
python .hermes/skills/software-development/requirements-documentation/scripts/verify_sdk_doc_traceability.py \
  --package-init dms/sdk/__init__.py \
  --extra-export DocumentStatus \
  --sdk-file dms/sdk/implementation.py \
  --sdk-class DefaultDocumentManagementSDK \
  --api-doc docs/api.md
```

환경변수를 읽는 SDK source가 현재 존재하지 않으므로 `--environment-source`, `--config-doc`, `--env-example`는 사용하지 않는다. 설정 계약은 `docs/config.md`의 component/client 조립 문서에서 추적한다.

## 11. 공개하지 않는 범위

현재 공개 API에 포함하지 않는 항목은 다음과 같다.

- 환경변수를 읽어 client를 생성하는 factory
- SDK가 자체 관리하는 인증 helper 또는 권한 정책 저장소
- 문서 검색·일반 필터링 API
- presigned URL 발급
- 메시지 broker 연계 API
- unknown-size/async input stream 직접 업로드
- 독립 실행형 API 서버
