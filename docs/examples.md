# SDK 사용 예시

## 컨텍스트 관리자 빠른 시작

```python
from os import environ
from dms import UploadDocumentRequest, create_sdk_from_environment

with create_sdk_from_environment(environ) as sdk:
    result = sdk.upload_document(UploadDocumentRequest(
        content=b"hello",
        filename="hello.txt",
        content_type="text/plain",
        idempotency_key="upload-2026-001",
        idempotency_scope="tenant-a",
    ))
    print(result.document_id)
```

## 커서 페이지 순회

```python
from dms import DocumentStatus

cursor = None
while True:
    page = sdk.list_documents_page(
        cursor=cursor,
        limit=50,
        status=DocumentStatus.AVAILABLE,
    )
    for metadata in page.items:
        print(metadata.document_id)
    if not page.has_more:
        break
    cursor = page.next_cursor
```

`next_cursor`는 불투명 값이므로 해석하거나 수정하지 않습니다. 다음 요청에도 동일한 `status`를 전달합니다. 기존 `list_documents(offset=..., limit=...)`도 계속 사용할 수 있습니다.

## 크기를 모르는 스트림 등록

```python
from dms import UploadDocumentUnknownSizeStreamRequest

result = sdk.upload_document_unknown_size_stream(
    UploadDocumentUnknownSizeStreamRequest(
        stream=incoming_stream,
        max_size=20 * 1024 * 1024,
        filename="incoming.pdf",
        content_type="application/pdf",
    )
)
```

`storage_key`는 내부 저장소 필드이므로 사용자 응답 URL이나 외부 식별자로 사용하지 않습니다.

외부 응답에는 `public_metadata(result)`를 사용합니다. 이 projection에는 `storage_key`가 없습니다.

## 모델/parser callable 연결

```python
from dms import StructuredMetadataValidator, create_sdk_from_components

validator = StructuredMetadataValidator(
    schema_version="1",
    parser=ArticleModel.parse,          # caller-owned callable
    projector=lambda model: model.to_dict(),
)
sdk = create_sdk_from_components(
    metadata_store=metadata_store, object_store=object_store,
    metadata_validator=validator,
)
```

SDK는 특정 모델 라이브러리를 import하지 않습니다. parser는 field 오류를 `MetadataSchemaValidationError([MetadataValidationIssue(...)])`로 변환해 던질 수 있습니다.

## 안전한 복구 계획 실행과 감사

```python
def audit(event):
    audit_sink.write(event)  # 실패해도 복구 결과에는 영향 없음(best-effort)

sdk = create_sdk_from_components(..., recovery_audit_hook=audit)
preview = sdk.reconcile_documents(status=DocumentStatus.FAILED,
    action=RecoveryAction.MARK_FAILED, dry_run=True)
result = sdk.execute_reconciliation_plan(preview.to_plan(), actor="operator-42")
```

실행은 항목마다 현재 상태를 다시 점검하므로 preview 이후 상태가 바뀐 stale plan도 안전하게 거부됩니다.

## 명시적 삭제

```python
soft_result = sdk.soft_delete_document("doc-1")
hard_result = sdk.hard_delete_document("doc-2")

# 기존 호출도 호환됩니다.
legacy_result = sdk.delete_document("doc-3", hard_delete=True)
```

## 본문 스트림 닫기

```python
with sdk.get_document_content_stream("doc-1") as content:
    for chunk in content.iter_chunks():
        consume(chunk)
```
