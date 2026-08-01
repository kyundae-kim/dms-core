# DMS SDK 사용 예제

- 기준 버전: `0.7.0`
- 공개 API 상세: [api.md](api.md)
- 조립·설정 상세: [config.md](config.md)

이 문서의 `metadata_store`, `object_store`, `operation_store`, `engine`, `minio_client`는 호스트 애플리케이션이 미리 생성해 둔 객체를 뜻한다. DMS는 이 객체를 만들기 위해 환경변수를 읽지 않는다. 예제의 secret과 endpoint는 실제 운영 값으로 복사하지 않는다.

<a id="example-assembly"></a>

## 1. component 기반 동기 조립과 기본 업로드

가장 작은 통합 경로는 호스트가 완성된 저장소 구성요소를 주입하는 방식이다.

```python
from dms import UploadDocumentRequest, create_sdk_from_components

# Host application creates these adapters and owns them by default.
metadata_store = application.metadata_store
object_store = application.object_store

with create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
) as sdk:
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"hello world",
            filename="hello.txt",
            content_type="text/plain",
            metadata={"category": "greeting"},
            created_by="batch-worker",
        )
    )

    metadata = sdk.get_document_metadata(result.document_id)
    content = sdk.get_document_content(result.document_id)

assert result.created is True
assert metadata.document_id == result.document_id
assert content.content == b"hello world"
```

`with`가 호출자 소유 component를 닫는 것은 아니다. SDK가 종료해야 할 자원은 [ownership 예제](#example-ownership)처럼 명시적으로 등록한다.

<a id="example-client-factory"></a>

## 2. host client 기반 조립

호스트가 SQLAlchemy `Engine`과 MinIO client를 이미 관리하는 경우 client factory를 사용한다.

```python
from dms import create_sdk_from_clients

# Created by the host application, not by DMS.
engine = application.sqlalchemy_engine
minio_client = application.minio_client

with create_sdk_from_clients(
    engine=engine,
    minio_client=minio_client,
    bucket_name="documents",
) as sdk:
    health = sdk.check_health()
```

`engine` dialect는 `postgresql` 또는 `sqlite`여야 한다. client factory는 전달받은 engine/client를 자동으로 close하지 않는다.

<a id="example-ownership"></a>

## 3. SDK가 소유할 자원만 명시하기

```python
from dms import (
    ManagedResource,
    ResourceOwnership,
    create_sdk_from_components,
)

resource = application.client_that_must_close_with_dms

sdk = create_sdk_from_components(
    metadata_store=application.metadata_store,
    object_store=application.object_store,
    managed_resources=[
        ManagedResource(
            resource=resource,
            ownership=ResourceOwnership.SDK,
            close=resource.close,
            name="application-document-client",
        ),
    ],
)
try:
    sdk.check_health()
finally:
    sdk.close()  # SDK-owned resources are closed in reverse registration order.
```

호출자가 소유하는 engine/client는 `ManagedResource(ownership=CALLER)`를 생략하거나 명시한다. cleanup이 여러 개 실패하면 `ResourceCleanupError.errors`에서 모든 원인을 확인한다.

<a id="example-upload"></a>

## 4. bytes·파일·정확한 크기의 stream 업로드

세 입력 경로는 같은 filename/content type/metadata/size 정책을 공유한다.

```python
from io import BytesIO
from pathlib import Path

from dms import UploadDocumentRequest, UploadDocumentStreamRequest

# 1) In-memory bytes.
bytes_result = sdk.upload_document(
    UploadDocumentRequest(
        content=b"bytes payload",
        filename="bytes.txt",
        content_type="text/plain",
        document_id="bytes-document",
    )
)

# 2) File path. DMS opens and closes this file itself.
file_result = sdk.upload_file(
    Path("./payload.pdf"),
    content_type="application/pdf",
    document_id="file-document",
)

# 3) Caller-provided known-size binary stream. DMS does not close it.
payload = b"stream payload"
source = BytesIO(payload)
stream_result = sdk.upload_document_stream(
    UploadDocumentStreamRequest(
        stream=source,
        size=len(payload),
        filename="stream.txt",
        content_type="text/plain",
        document_id="stream-document",
    )
)
assert source.closed is False
source.close()
```

크기를 알 수 없는 stream, async input stream, 요청별 checksum/idempotency/chunk size는 현재 업로드 API에서 지원하지 않는다. stream의 실제 읽기 크기와 `size`가 다르면 storage를 rollback한 뒤 `ValidationError`를 발생시킨다.

<a id="example-metadata"></a>

## 5. 공개 metadata와 관리 metadata 구분

일반 결과에는 내부 저장 위치가 없다. 복구나 관리에만 명시적인 internal path를 사용한다.

```python
from dms import public_metadata

public = sdk.get_document_metadata(result.document_id)
assert not hasattr(public, "storage_key")
assert "storage_key" not in public.to_public_dict()

# This is a privileged/recovery path and must not be sent to an external response.
internal = sdk.get_internal_document_metadata(result.document_id)
assert internal.storage_key.startswith("documents/")

# Projection is also available for an upload result or internal metadata value.
public_again = public_metadata(internal)
assert public_again.document_id == result.document_id
```

`PublicDocumentMetadata.to_dict()`는 호환 필드명 `extra_metadata`를 유지한다. 외부 canonical 응답은 `to_public_dict()`의 `metadata` 필드와 `json_schema()`를 사용한다.

<a id="example-metadata-policy"></a>

## 6. metadata schema validator 주입

```python
from collections.abc import Mapping
from typing import Any

from dms import (
    DmsAssemblyPlan,
    StructuredMetadataValidator,
    UploadDocumentRequest,
    create_sdk_from_components,
)


def parse_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if "title" not in value:
        raise ValueError("title is required")
    return {
        "schema_version": value["schema_version"],
        "title": str(value["title"]).strip(),
    }

plan = DmsAssemblyPlan(
    metadata_validator=StructuredMetadataValidator(
        parser=parse_metadata,
        schema_version="1",
    ),
)

with create_sdk_from_components(
    metadata_store=application.metadata_store,
    object_store=application.object_store,
    plan=plan,
) as sdk:
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"validated",
            filename="validated.txt",
            content_type="text/plain",
            metadata={"schema_version": "1", "title": " Document title "},
        )
    )

assert result.metadata.extra_metadata["title"] == "Document title"
```

기본 정책은 JSON-compatible value, 문자열 key, serialized size, depth와 credential 성격 key를 검사한다. parser가 field-level issue를 제공해야 하면 `MetadataSchemaValidationError`와 `MetadataValidationIssue`를 사용한다.

<a id="example-idempotency"></a>

## 7. idempotent upload와 operation 상태 조회

영속 `operation_store`를 component factory에 주입하고 bytes request에 scope/key를 함께 지정한다.

```python
from dms import UploadDocumentRequest, create_sdk_from_components

sdk = create_sdk_from_components(
    metadata_store=application.metadata_store,
    object_store=application.object_store,
    operation_store=application.upload_operation_store,
)
try:
    request = UploadDocumentRequest(
        content=b"one logical upload",
        filename="one.txt",
        content_type="text/plain",
        idempotency_scope="tenant-a",
        idempotency_key="request-2026-08-01-001",
    )

    first = sdk.upload_document(request)
    replay = sdk.upload_document(request)
    operation = sdk.get_upload_operation(
        scope="tenant-a",
        idempotency_key="request-2026-08-01-001",
    )
finally:
    sdk.close()

assert first.created is True
assert replay.created is False
assert replay.document_id == first.document_id
assert operation.document_id == first.document_id
```

같은 scope/key로 다른 fingerprint를 전송하면 `IdempotencyConflictError`, 기존 작업이 pending이면 `IdempotencyInProgressError`다. scope가 없는 idempotency request는 storage를 건드리기 전에 `ValidationError`다.

<a id="example-stream"></a>

## 8. 본문 stream 소비와 출력 대상 복사

### sync stream context manager

```python
from io import BytesIO

with sdk.get_document_content_stream(
    result.document_id,
    chunk_size=64 * 1024,
) as content:
    for chunk in content.iter_chunks():
        response_writer.write(chunk)
# SDK-owned response stream is closed here.
```

호스트 프레임워크가 stream 객체가 아니라 반복자만 소비하는 경우에는 종료 보장 iterator를 사용한다.

```python
for chunk in sdk.get_document_content_stream(result.document_id).iter_chunks_closing():
    response_writer.write(chunk)
```

반복자를 일부만 소비하고 전송 계층이 중단하는 경우에는 iterator의 `close()` 또는 stream의 `close()`를 명시적으로 호출한다. 더 간단한 전체 순회에는 `iter_document_chunks()`를 사용할 수 있다.

### sink로 복사

```python
sink = BytesIO()
copy_result = sdk.copy_document_to(
    result.document_id,
    sink,
    chunk_size=1024 * 1024,
    verify_checksum=True,
)

assert sink.closed is False  # caller-owned sink remains open
assert copy_result.bytes_copied == len(sink.getvalue())
```

SDK가 연 source stream은 닫지만 sink는 닫지 않는다. 크기나 checksum 불일치는 `ConsistencyError`다.

<a id="example-pagination"></a>

## 9. cursor pagination과 전체 순회

cursor는 opaque 값이므로 내용을 해석하거나 저장 규칙에 의존하지 않는다.

```python
from dms import DocumentStatus

page = sdk.list_documents(
    limit=100,
    status=DocumentStatus.AVAILABLE,
)
while True:
    for metadata in page.items:
        consume(metadata)

    if page.next_cursor is None:
        break
    page = sdk.list_documents(
        cursor=page.next_cursor,
        limit=100,
        status=DocumentStatus.AVAILABLE,
    )
```

`next_cursor`를 재사용할 때는 최초 조회와 같은 `limit`과 `status`를 전달한다. 삭제 완료·삭제 진행 문서는 일반 목록에 포함되지 않는다. cursor와 offset을 섞거나, 변조 cursor를 전달하거나, `limit`을 1~1000 밖으로 지정하면 `ValidationError`다.

cursor를 직접 다루지 않으려면 다음과 같이 순회한다.

```python
for metadata in sdk.iter_documents(
    status=DocumentStatus.AVAILABLE,
    page_size=100,
):
    consume(metadata)
```

<a id="example-delete"></a>

## 10. 논리 삭제와 완전 삭제

```python
# Explicit soft-delete convenience method.
soft = sdk.soft_delete_document(result.document_id)
assert soft.deleted is True
assert soft.hard_deleted is False
assert soft.status.value == "deleted"

# A later document can be permanently deleted.
hard = sdk.delete_document(other_id, hard_delete=True)
assert hard.hard_deleted is True
```

삭제 중 object 삭제가 실패하면 문서는 `failed` 상태로 남을 수 있고 `StorageError`가 발생한다. object는 제거됐지만 metadata 후속 처리가 실패하면 `ConsistencyError`가 발생하며 `deleting` 상태를 복구 경로에서 확인한다. 논리 삭제 문서의 일반 metadata 조회는 `DocumentNotFoundError`, 본문 조회는 `DocumentDeletedError`다.

<a id="example-reset"></a>

## 11. 전체 데이터 삭제와 신규 적재 초기화

두 API는 DMS 관리 범위 전체에 적용되므로 일반 document delete와 구분한다.

```python
from dms import DataResetError

try:
    reset = sdk.initialize_for_data_load()
except DataResetError as error:
    # Other stores may already have been cleared.
    print(error.failed_stores)
    print(error.result.to_dict())
    assert error.result.ready_for_data_load is False
    raise
else:
    assert reset.ready_for_data_load is True
    print(reset.metadata_deleted)
    print(reset.objects_deleted)
    print(reset.upload_operations_deleted)
    print(reset.total_deleted)
```

`clear_all_data()`는 같은 범위를 비우고 결과를 반환한다. 한 store가 실패해도 나머지 store의 cleanup을 시도하며 `failed_stores`와 부분 count를 보존한다. operation observer가 등록되어 있으면 `data.clear_all` 또는 `data.initialize_for_data_load` 이벤트를 받는다.

<a id="example-recovery"></a>

## 12. 복구 점검·dry-run 계획·실행

복구는 일반 조회가 아닌 관리 경로다. 예제에서는 호스트가 `FAILED` 후보를 만들어 둔 상태라고 가정한다.

```python
from dms import DocumentStatus, RecoveryAction

inspection = sdk.inspect_document(candidate_id)
print(inspection.to_dict())

preview = sdk.reconcile_documents(
    status=DocumentStatus.FAILED,
    action=RecoveryAction.MARK_FAILED,
    limit=100,
    dry_run=True,
    actor="operator-42",
)

# A plan is exportable only from a dry-run result.
plan = preview.to_plan()

# Plan execution re-inspects every item before applying it.
applied = sdk.execute_reconciliation_plan(
    plan,
    actor="operator-42",
)
for item in applied.items:
    print(item.to_dict())
```

지원 action은 `COMPLETE_DELETION_SOFT`, `COMPLETE_DELETION_HARD`, `MARK_FAILED`, `PURGE_ORPHAN_OBJECT`다. orphan purge에는 metadata가 없어야 하고 호출자가 정확한 `storage_key`를 별도로 제공해야 한다. 복구 audit hook은 각 시도에 대해 `RecoveryAuditEvent`를 받지만 hook 실패가 결과를 가리지 않는다.

<a id="example-policy"></a>

## 13. 접근 정책과 operation-scoped facade

```python
from dms import AccessContext, DmsAssemblyPlan, DmsOperationContext

class TenantPolicy:
    def allows(self, *, operation, context, metadata):
        if context is None:
            return False
        if metadata is None:  # reset or another global management operation
            return "admin" in context.roles
        return metadata.extra_metadata.get("tenant") == context.tenant

plan = DmsAssemblyPlan(access_policy=TenantPolicy())
with create_sdk_from_components(
    metadata_store=application.metadata_store,
    object_store=application.object_store,
    plan=plan,
) as sdk:
    scoped = sdk.scoped(
        DmsOperationContext(
            access=AccessContext(
                subject="user-a",
                tenant="tenant-a",
                roles=frozenset({"reader"}),
            ),
            created_by="user-a",
            idempotency_scope="tenant-a",
            audit_actor="user-a",
            default_metadata={"tenant": "tenant-a"},
        )
    )
    result = scoped.upload_document(
        UploadDocumentRequest(
            content=b"tenant data",
            filename="tenant.txt",
            content_type="text/plain",
        )
    )
    metadata = scoped.get_document_metadata(result.document_id)
```

scoped 호출은 context의 접근·작성자·idempotency scope·audit actor·기본 metadata를 사용한다. 호출에 명시한 `created_by`나 metadata 값은 context 기본값보다 우선한다. 접근 거부는 `AccessDeniedError`다.

<a id="example-observer"></a>

## 14. 구조화된 operation observer

```python
from dms import DmsAssemblyPlan, OperationEvent

observed: list[OperationEvent] = []

def observe(event: OperationEvent) -> None:
    observed.append(event)
    logger.info(
        "dms operation",
        extra={
            "operation": event.operation,
            "succeeded": event.succeeded,
            "document_id": event.document_id,
            "error_code": event.error_code,
        },
    )

plan = DmsAssemblyPlan(operation_observer=observe)
sdk = create_sdk_from_components(
    metadata_store=application.metadata_store,
    object_store=application.object_store,
    plan=plan,
)
try:
    sdk.get_document_metadata("missing")
except Exception:
    pass
finally:
    sdk.close()

assert observed[-1].succeeded is False
assert observed[-1].error_code == "document_not_found"
```

observer가 자체적으로 실패해도 SDK 작업의 성공/실패를 바꾸지 않는다. 이벤트 `to_dict()`에는 내부 storage locator나 content가 없다.

<a id="example-health"></a>

## 15. health와 lifecycle

```python
from dms import DmsAssemblyPlan, HealthCheckFailedError

plan = DmsAssemblyPlan(
    check_on_startup=True,
    startup_timeout_seconds=5.0,
)

try:
    with create_sdk_from_components(
        metadata_store=application.metadata_store,
        object_store=application.object_store,
        service_checks=application.service_checks,
        plan=plan,
    ) as sdk:
        health = sdk.check_health()
        if not health.ok:
            for service in health.services:
                if not service.ok:
                    logger.error("dependency unavailable: %s", service.service)
except HealthCheckFailedError as error:
    logger.error("startup check failed for %s: %s", error.service, error.reason)
```

startup check가 실패하면 SDK factory가 이미 등록한 SDK-owned resource를 rollback하고 예외를 다시 발생시킨다. runtime `check_health()`는 예외 대신 `HealthStatus`를 반환하므로, startup mandatory check와 runtime observation을 구분할 수 있다.

<a id="example-async"></a>

## 16. 비동기 facade와 async 본문 stream

```python
from dms import UploadDocumentRequest, create_async_sdk_from_components

async def run() -> None:
    async with create_async_sdk_from_components(
        metadata_store=application.metadata_store,
        object_store=application.object_store,
    ) as sdk:
        result = await sdk.upload_document(
            UploadDocumentRequest(
                content=b"async payload",
                filename="async.txt",
                content_type="text/plain",
            )
        )

        metadata = await sdk.get_document_metadata(result.document_id)
        assert metadata.document_id == result.document_id

        async for item in sdk.iter_documents(page_size=100):
            consume(item)

        content = await sdk.get_document_content_async_stream(result.document_id)
        async with content:
            async for chunk in content.iter_chunks():
                await response_writer.write(chunk)
```

동일한 facade에서 `await sdk.get_document_content_stream(...)`도 `AsyncDocumentContentStream`을 반환한다. stream은 `async with`, `aiter_chunks_closing()`, `aclose()`를 지원한다.

동기 저장소 작업이 이미 시작된 뒤 task가 취소되면 async facade는 worker가 정합성 경계에 도달할 때까지 기다린 뒤 취소를 전파한다. 취소를 성공이나 rollback 완료로 간주하지 말고, 필요한 경우 `get_upload_operation()` 또는 metadata 조회로 최종 상태를 확인한다.

<a id="example-contracts"></a>

## 17. 기능별 protocol을 받는 host 함수

호스트는 전체 구현체에 의존하지 않고 필요한 기능별 계약만 받을 수 있다.

```python
from dms import DocumentReader, PublicDocumentMetadata


def render_title(reader: DocumentReader, document_id: str) -> str:
    metadata: PublicDocumentMetadata = reader.get_document_metadata(document_id)
    return metadata.original_filename

# DefaultDocumentManagementSDK and test doubles satisfying DocumentReader are valid.
title = render_title(sdk, result.document_id)
```

`DocumentWriter`, `DocumentReader`, `DocumentLister`, `DocumentDeleter`, `DataResetter`, `DocumentHealth`, `DocumentManagementClient`는 runtime-checkable protocol이다. 내부 adapter class를 상속할 필요가 없다.

<a id="example-errors"></a>

## 18. 오류 분기

```python
from dms import (
    ConsistencyError,
    DocumentDeletedError,
    DocumentNotFoundError,
    DmsError,
    PayloadTooLargeError,
    StorageError,
    ValidationError,
    error_descriptor,
)

try:
    content = sdk.get_document_content(document_id)
except DocumentNotFoundError:
    handle_missing_document()
except DocumentDeletedError:
    handle_deleted_document()
except ConsistencyError:
    enqueue_reconciliation(document_id)
except PayloadTooLargeError:
    reject_large_upload()
except StorageError:
    retry_dependency_operation()
except ValidationError:
    reject_invalid_request()
except DmsError as error:
    descriptor = error_descriptor(error)
    logger.error("DMS operation failed: %s", descriptor.to_dict())
    raise
```

예외의 `code`, `category`, `retryable`은 유형명보다 안정적인 분기 기준이다. 저장소 내부 exception text를 외부 응답에 그대로 전달하지 않는다.

<a id="example-http"></a>

## 19. HTTP 응답으로의 권고 투영

DMS 자체는 HTTP server가 아니지만, host API가 public error를 HTTP 응답으로 바꿀 때 transport-neutral descriptor를 사용할 수 있다.

```python
from dms import DmsError, error_descriptor, merge_error_descriptor, recommended_http_error

try:
    sdk.get_document_metadata("missing")
except DmsError as error:
    descriptor = error_descriptor(error)
    descriptor = merge_error_descriptor(
        descriptor,
        external_code="HOST_DOCUMENT_MISSING",
        message="문서를 찾을 수 없습니다",
    )
    response = recommended_http_error(descriptor)
    return response.status, response.body, response.headers
```

기준 SDK `code`, `category`, `retryable`은 유지되고 host별 `external_code`만 추가된다. `StorageError`와 `MetadataStoreError`는 권장 status 503, `PayloadTooLargeError`는 413, validation은 400이다. `Retry-After`는 retryable descriptor에만 설정한다.

## 20. 실행 전 확인

- host가 engine/client 또는 component를 만들었는가?
- `upload_document_stream()`의 `size`가 실제 bytes 길이와 같은가?
- caller-owned input stream과 SDK-owned output stream의 close 책임을 구분했는가?
- 일반 외부 응답에 `DocumentMetadata.storage_key`를 포함하지 않았는가?
- cursor 다음 호출에 같은 status/limit을 전달했는가?
- reset/recovery가 관리 권한으로 보호되어 있는가?
- idempotency 사용 시 persistent operation store와 non-empty scope를 전달했는가?
- public error descriptor로 외부 메시지를 만들고 내부 exception text를 숨겼는가?
