# API Examples

## 1. 개요

이 문서는 DMS SDK의 대표 사용 예시를 제공합니다.
예시는 공개 API 기준으로 작성되며, 실제 서비스 코드에 바로 응용할 수 있는 흐름을 중심으로 구성합니다.

관련 문서:
- `docs/api.md`
- `docs/prd.md`
- `docs/srs.md`

## 2. 기본 import

```python
from dms.sdk import UploadDocumentRequest, create_sdk
```

## 3. 환경 기반으로 SDK 생성

가장 일반적인 시작 방식입니다.
환경 변수 매핑을 전달하면 SDK가 필요한 저장소를 조립합니다.

```python
import logging
from os import environ

from dms.sdk import create_sdk

logger = logging.getLogger("dms.sdk")
sdk = create_sdk(environ, logger=logger)
```

종료 시에는 반드시 `close()`를 호출해 리소스를 정리합니다.

```python
sdk.close()
```

권장 패턴:

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

## 4. 명시적 의존성 주입으로 SDK 생성

테스트 코드나 사용자 정의 조립이 필요한 경우에는 의존성을 직접 전달할 수 있습니다.

```python
from dms.sdk import create_sdk

sdk = create_sdk(
    metadata_store=metadata_store,
    object_store=object_store,
    logger=logger,
)
```

## 5. 문서 업로드

가장 기본적인 업로드 예시입니다.

```python
from dms.sdk import UploadDocumentRequest

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

## 6. 문서 메타데이터 조회

문서 식별자로 메타데이터를 조회합니다.

```python
metadata = sdk.get_document_metadata("doc-001")

print(metadata.document_id)
print(metadata.original_filename)
print(metadata.content_type)
print(metadata.file_size)
print(metadata.storage_key)
print(metadata.status)
```

## 7. 문서 본문 전체 조회

문서 전체 바이트가 한 번에 필요한 경우 사용합니다.

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

## 8. 문서 본문 스트리밍 조회

대용량 문서나 메모리 사용량을 줄이고 싶은 경우 스트리밍 조회를 사용합니다.

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
        process(chunk)
finally:
    stream.close()
```

스트림을 파일로 저장하는 예시:

```python
stream = sdk.get_document_content_stream("doc-001")
try:
    with open(stream.filename, "wb") as f:
        for chunk in stream.iter_chunks():
            f.write(chunk)
finally:
    stream.close()
```

## 9. 문서 삭제

### 9.1 논리 삭제

기본 삭제는 논리 삭제입니다.

```python
delete_result = sdk.delete_document("doc-001")

print(delete_result.document_id)
print(delete_result.deleted)
print(delete_result.hard_deleted)
print(delete_result.status)
```

### 9.2 완전 삭제

문서 본문과 문서 정보를 모두 제거하려면 `hard_delete=True`를 사용합니다.

```python
delete_result = sdk.delete_document("doc-001", hard_delete=True)

print(delete_result.document_id)
print(delete_result.deleted)
print(delete_result.hard_deleted)
print(delete_result.status)
```

## 10. 상태 점검

실행 중 저장소 상태를 점검할 수 있습니다.

```python
health = sdk.check_health()

print(health.ok)
print(health.checked_at)

for service in health.services:
    print(service.service, service.ok, service.latency_ms, service.error)
```

실패한 서비스만 따로 확인하는 예시:

```python
health = sdk.check_health()
failed_services = [service for service in health.services if not service.ok]

for service in failed_services:
    print(service.service, service.error)
```

## 11. 예외 처리 예시

대표적인 오류를 구분해서 처리하는 예시입니다.

```python
from dms.sdk import (
    ConfigurationError,
    ConsistencyError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    StorageError,
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
from dms.sdk import DocumentNotFoundError

try:
    metadata = sdk.get_document_metadata("missing-doc")
except DocumentNotFoundError:
    print("문서를 찾을 수 없습니다.")
```

## 12. 전체 흐름 예시

생성 → 업로드 → 메타데이터 조회 → 본문 조회 → 상태 점검 → 삭제까지 한 번에 보여주는 예시입니다.

```python
import logging
from os import environ

from dms.sdk import UploadDocumentRequest, create_sdk

sdk = create_sdk(environ, logger=logging.getLogger("dms.sdk"))
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

## 13. 작성 시 주의사항

- SDK를 생성한 뒤에는 사용이 끝나면 반드시 `close()`를 호출합니다.
- 스트리밍 조회를 사용한 경우에는 반드시 `close()`로 스트림 리소스를 해제합니다.
- 대용량 파일은 전체 조회보다 스트리밍 조회를 우선 고려하는 것이 좋습니다.
- 운영 코드에서는 상태 점검 결과와 저장소 오류를 분리해서 기록하는 것을 권장합니다.
