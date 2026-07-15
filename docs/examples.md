# API Examples

## 1. 개요

이 문서는 DMS SDK의 대표 사용 예시를 제공합니다.
예시는 현재 공개 API 기준으로 작성되며, 실제 서비스 코드에 바로 응용할 수 있는 흐름을 중심으로 구성합니다.
타입 시그니처, 예외 목록, 프로토콜 계약의 상세 설명은 `docs/api.md`를 기준 문서로 사용합니다.

관련 문서:
- `docs/api.md`
- `docs/prd.md`
- `docs/srs.md`

## 2. 기본 import

```python
from dms import UploadDocumentRequest, create_sdk_from_environment
```

## 3. 환경 기반으로 SDK 생성

가장 일반적인 시작 방식입니다.
환경 변수 매핑을 전달하면 SDK가 필요한 저장소를 조립합니다.

실행 전 최소 준비:
- PostgreSQL 사용 시: `POSTGRES_DSN`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`
- SQLite 사용 시: `SQLITE_PATH`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`
- 공통 설정 로더 검증 환경에 따라 `.env.example`의 추가 값이 함께 필요할 수 있습니다.

```python
import logging
from os import environ

from dms import create_sdk_from_environment

logger = logging.getLogger("dms.sdk")
sdk = create_sdk_from_environment(environ, logger=logger)
```

종료 시에는 반드시 `close()`를 호출해 리소스를 정리합니다.

```python
sdk.close()
```

권장 패턴:

```python
import logging
from os import environ

from dms import create_sdk_from_environment

sdk = create_sdk_from_environment(environ, logger=logging.getLogger("dms.sdk"))
try:
    ...
finally:
    sdk.close()
```

## 4. 명시적 의존성 주입으로 SDK 생성

테스트 코드나 사용자 정의 조립이 필요한 경우에는 의존성을 직접 전달할 수 있습니다.

개념 예시:

```python
from dms import create_sdk_from_components

sdk = create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
    logger=logger,
)
```

위 예시의 `metadata_store`, `object_store`, `logger`는 애플리케이션 또는 테스트 코드에서 준비한 객체입니다.

실제 구현체를 사용하는 예시:

```python
from sqlalchemy import create_engine
from minio import Minio

from dms import create_sdk_from_components
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore

engine = create_engine("postgresql+psycopg://user:password@localhost:5432/dms", future=True)
minio_client = Minio(
    "localhost:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    secure=False,
)

sdk = create_sdk_from_components(
    metadata_store=PostgresMetadataStore(engine),
    object_store=MinioObjectStore(client=minio_client, bucket_name="documents"),
)
```

### 4.1 SQLite metadata 저장소를 직접 연결하는 로컬 예시

SQLite는 문서 정보 저장소만 대체합니다.
문서 본문 저장소는 현재 MinIO가 필요합니다.

```python
from sqlalchemy import create_engine
from minio import Minio

from dms import create_sdk_from_components
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore

engine = create_engine("sqlite+pysqlite:////tmp/dms.db", future=True)
minio_client = Minio(
    "localhost:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    secure=False,
)

sdk = create_sdk_from_components(
    metadata_store=SqliteMetadataStore(engine),
    object_store=MinioObjectStore(client=minio_client, bucket_name="documents"),
)
```

## 5. 환경 준비 후 실행 가능한 최소 예제

다음 예제는 외부 저장소와 환경 변수가 준비된 상태에서 "환경 변수 준비 → SDK 생성 → 업로드 → 조회 → 삭제"의 최소 흐름을 보여줍니다.

```python
import logging
from os import environ

from dms import UploadDocumentRequest, create_sdk_from_environment

sdk = create_sdk_from_environment(environ, logger=logging.getLogger("dms.sdk"))
try:
    upload_result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="quickstart-doc-1",
            content=b"quickstart content",
            filename="quickstart.txt",
            content_type="text/plain",
        )
    )

    metadata = sdk.get_document_metadata(upload_result.document_id)
    content = sdk.get_document_content(upload_result.document_id)
    deleted = sdk.delete_document(upload_result.document_id, hard_delete=True)

    print(upload_result.storage_key)
    print(metadata.status)
    print(content.size)
    print(deleted.hard_deleted)
finally:
    sdk.close()
```

## 6. 문서 업로드

```python
from dms import UploadDocumentRequest

result = sdk.upload_document(
    UploadDocumentRequest(
        document_id="doc-001",
        content=b"hello world",
        filename="hello.txt",
        content_type="text/plain",
        metadata={"team": "platform", "category": "example"},
        created_by="tester",
    )
)

print(result.document_id)
print(result.storage_key)
print(result.metadata.status)
```

호출자가 `document_id`를 생략하면 SDK가 새 식별자를 생성합니다.

```python
result = sdk.upload_document(
    UploadDocumentRequest(
        content=b"auto id",
        filename="auto-id.txt",
        content_type="text/plain",
    )
)

print(result.document_id)
```

체크섬을 직접 지정할 수도 있습니다.

```python
result = sdk.upload_document(
    UploadDocumentRequest(
        content=b"important payload",
        filename="payload.bin",
        content_type="application/octet-stream",
        checksum="0123456789abcdef",
    )
)
```

### 6.1 파일 스트리밍 업로드

```python
from pathlib import Path
from dms import UploadDocumentStreamRequest

path = Path("large-report.pdf")
with path.open("rb") as source:
    result = sdk.upload_document_stream(UploadDocumentStreamRequest(
        stream=source,
        size=path.stat().st_size,
        filename=path.name,
        content_type="application/pdf",
        chunk_size=1024 * 1024,
        # checksum="<expected SHA-256 hex>",  # 선택 assertion
    ))
```

`size`와 `chunk_size`는 양수여야 한다. 스트림은 업로드 호출 동안 열려 있어야 하며,
SDK는 스트림 전체를 메모리에 복사하지 않는다.

## 7. 문서 메타데이터 조회

```python
metadata = sdk.get_document_metadata("doc-001")

print(metadata.document_id)
print(metadata.original_filename)
print(metadata.content_type)
print(metadata.file_size)
print(metadata.storage_key)
print(metadata.status)
```

## 8. 문서 본문 전체 조회

```python
content = sdk.get_document_content("doc-001")

print(content.filename)
print(content.content_type)
print(content.size)
print(content.content)
```

파일로 저장하는 예시:

```python
content = sdk.get_document_content("doc-001")

with open(content.filename, "wb") as f:
    f.write(content.content)
```

## 8.1 문서 목록 조회와 상태 필터

기본 목록 조회는 생성 시각과 문서 식별자 내림차순으로 정렬됩니다. 업무 검색이나 복합 필터는 제공하지 않습니다.

```python
from dms import DocumentStatus

recent = sdk.list_documents(offset=0, limit=50)
failed = sdk.list_documents(
    offset=0,
    limit=50,
    status=DocumentStatus.FAILED,
)
print([item.document_id for item in recent])
print([item.document_id for item in failed])
```

## 9. 문서 본문 스트리밍 조회

```python
stream = sdk.get_document_content_stream("doc-001")
try:
    for chunk in stream.iter_chunks():
        print(len(chunk))
finally:
    stream.close()
```

청크 크기를 직접 지정할 수도 있습니다.

```python
stream = sdk.get_document_content_stream("doc-001", chunk_size=1024 * 1024)
try:
    for chunk in stream.iter_chunks():
        # 애플리케이션별 청크 처리 로직을 여기에 둡니다.
        print(len(chunk))
finally:
    stream.close()
```

스트리밍으로 파일 저장 + 바이트 수 합산 예시:

```python
stream = sdk.get_document_content_stream("doc-001", chunk_size=1024 * 1024)
written = 0
try:
    with open("downloaded-doc-001.bin", "wb") as f:
        for chunk in stream.iter_chunks():
            f.write(chunk)
            written += len(chunk)
finally:
    stream.close()

print(written)
```

## 10. 문서 삭제

### 10.1 논리 삭제

```python
delete_result = sdk.delete_document("doc-001")

print(delete_result.document_id)
print(delete_result.deleted)
print(delete_result.hard_deleted)
print(delete_result.status)
```

### 10.2 완전 삭제

```python
delete_result = sdk.delete_document("doc-001", hard_delete=True)

print(delete_result.document_id)
print(delete_result.deleted)
print(delete_result.hard_deleted)
print(delete_result.status)
```

## 11. 상태 점검

```python
health = sdk.check_health()

print(health.ok)
print(health.checked_at)

for service in health.services:
    print(service.service, service.ok, service.latency_ms, service.error)
```

## 12. 예외 처리 예시

```python
from dms import (
    ConfigurationError,
    ConsistencyError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    StorageError,
    UploadDocumentRequest,
    ValidationError,
)

try:
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"hello",
            filename="hello.txt",
            content_type="text/plain",
        )
    )
except ValidationError as exc:
    print(f"입력값 오류: {exc}")
except DuplicateDocumentError as exc:
    print(f"중복 문서 오류: {exc}")
except ConfigurationError as exc:
    print(f"설정 오류: {exc}")
except StorageError as exc:
    print(f"저장소 오류: {exc}")
except ConsistencyError as exc:
    print(f"일관성 오류: {exc}")
```

문서 조회 시 문서 없음 오류를 처리하는 예시:

```python
from dms import DocumentNotFoundError

try:
    metadata = sdk.get_document_metadata("missing-doc")
except DocumentNotFoundError:
    print("문서를 찾을 수 없습니다.")
```

## 13. 자주 실패하는 입력 예시

대표적인 잘못된 입력 흐름만 예시로 보여줍니다. 전체 검증 규칙은 `docs/api.md`를 참고하세요.

```python
from dms import ValidationError

try:
    sdk.get_document_content_stream("doc-001", chunk_size=0)
except ValidationError as exc:
    print(exc)
```

## 14. 전체 흐름 예시

```python
import logging
from os import environ

from dms import UploadDocumentRequest, create_sdk_from_environment

sdk = create_sdk_from_environment(environ, logger=logging.getLogger("dms.sdk"))
try:
    upload_result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"example content",
            filename="example.txt",
            content_type="text/plain",
            metadata={"source": "examples-doc"},
            created_by="demo-user",
        )
    )

    metadata = sdk.get_document_metadata(upload_result.document_id)
    content = sdk.get_document_content(upload_result.document_id)
    health = sdk.check_health()
    delete_result = sdk.delete_document(upload_result.document_id)

    print(upload_result.document_id)
    print(metadata.status)
    print(content.size)
    print(health.ok)
    print(delete_result.deleted)
finally:
    sdk.close()
```

## 15. 작성 시 주의사항

- SDK 사용이 끝나면 반드시 `close()`를 호출합니다.
- 스트리밍 조회를 사용한 경우에는 반드시 `close()`로 스트림 리소스를 해제합니다.
- 대용량 파일은 전체 조회보다 스트리밍 조회를 우선 고려하는 것이 좋습니다.
- `chunk_size <= 0`은 `ValidationError` 입니다.

## 16. 멱등 업로드

```python
result = sdk.upload_document(UploadDocumentRequest(
    content=data, filename="report.pdf", content_type="application/pdf",
    created_by="user-42", idempotency_key="upload-2026-07-15-1",
))
# 성공한 동일 요청의 replay에서는 result.created == False
```

`UploadDocumentStreamRequest`에서 `idempotency_key`를 사용하면 호출자가 계산한 SHA-256 `checksum`도 반드시 전달합니다.

## 17. 운영 검사와 안전 복구

```python
from dms import DocumentStatus, RecoveryAction

inspection = sdk.inspect_document("doc-001")
print(inspection.metadata_exists, inspection.object_exists, inspection.issue.value)

preview = sdk.reconcile_document(
    "doc-001", RecoveryAction.COMPLETE_DELETION_SOFT, dry_run=True
)
print(preview.applied)  # False

batch = sdk.reconcile_documents(
    status=DocumentStatus.DELETING,
    action=RecoveryAction.COMPLETE_DELETION_SOFT,
    limit=100,
)
for item in batch.items:
    print(item.document_id, item.applied, item.error_type)

sdk.reconcile_document(
    "orphan-id", RecoveryAction.PURGE_ORPHAN_OBJECT,
    storage_key="documents/orphan-id/file.pdf",
)
```

SDK는 MinIO prefix를 scan하지 않는다. 공통 object 목록 계약이 없으므로 orphan key는 운영자가 안전하게 확보해 명시해야 한다.
## 18. 명시적 backend 선택과 사전 진단

```python
from dms import diagnose_environment, create_sdk_from_environment

env = {
    "DMS_METADATA_BACKEND": "sqlite",
    "SQLITE_PATH": "/tmp/dms.db",
    "MINIO_ENDPOINT": "localhost:9000",
    "MINIO_ACCESS_KEY": "...",
    "MINIO_SECRET_KEY": "...",
    "MINIO_BUCKET": "documents",
}
report = diagnose_environment(env)  # 연결·클라이언트 생성 없음
if not report.valid:
    raise RuntimeError(
        f"누락 설정: {', '.join(report.missing_required_keys)}; "
        f"경고: {', '.join(report.warnings)}"
    )
sdk = create_sdk_from_environment(env)
```

`DMS_METADATA_BACKEND`를 생략하면 자동 선택이며, PostgreSQL과 SQLite가 모두 있으면 PostgreSQL을
선택합니다. 이 모호성을 오류로 처리하려면 `DMS_CONFIGURATION_STRICT=true`를 추가합니다.

## 19. metadata 정책과 업로드 크기 제한

기본 정책은 JSON 직렬화 가능 metadata, 문자열 최상위 키, 최대 크기/깊이 및 민감 키 차단을 적용합니다.
`schema_version`은 권장 관례이며 필수는 아닙니다.

```python
from dms import UploadDocumentRequest, create_sdk_from_components

def normalize_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {"schema_version": "1", **metadata}

sdk = create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
    max_file_size=10 * 1024 * 1024,
    metadata_validator=normalize_metadata,
)
result = sdk.upload_document(UploadDocumentRequest(
    content=b"invoice", filename="invoice.txt", content_type="text/plain",
    metadata={"tags": ["invoice"]},
))
print(result.metadata.extra_metadata)
```

기본 정책의 한계만 조정하려면 `metadata_validator` 대신
`metadata_max_serialized_bytes`와 `metadata_max_depth`를 `create_sdk_from_components(...)` 또는
`create_sdk_from_environment(...)`에 전달합니다.
