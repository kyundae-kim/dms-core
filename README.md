# Document Management Service

호스트 애플리케이션이 제공하는 문서 정보 저장소와 문서 본문 저장소를 통해 문서 등록·조회·삭제·복구를 수행하는 Python SDK입니다.

`dms`는 독립 실행형 API 서버가 아니라 다른 프로젝트에서 import 해서 사용하는 라이브러리입니다.

## Installation

```bash
uv add "git+https://github.com/kyundae-kim/dms-core.git"
```

특정 ref/tag/branch를 지정해서 추가:

```bash
uv add "git+https://github.com/kyundae-kim/dms-core.git@main"
uv add "git+https://github.com/kyundae-kim/dms-core.git@v0.7.0"
```

## Quick start

호스트 애플리케이션이 저장소 포트 구현을 생성한 뒤 `create_sdk_from_components(...)`에 주입하거나, 이미 생성한 SQLAlchemy Engine과 MinIO client를 `DocumentManagementSDKFactory`에 전달하는 방식으로 조립합니다. SDK는 저장소 연결이나 인프라 client를 생성하지 않습니다.

```python
from dms import UploadDocumentRequest, create_sdk_from_components

sdk = create_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
)
result = sdk.upload_document(
    UploadDocumentRequest(
        content=b"hello world",
        filename="hello.txt",
        content_type="text/plain",
    )
)
```

이미 생성한 SQLAlchemy Engine과 MinIO client를 사용하는 경우에는 SQL dialect에 맞는 adapter와 업로드 작업 저장소가 자동으로 조립됩니다.

```python
from dms import DocumentManagementSDKFactory

sdk = DocumentManagementSDKFactory(
    engine=engine,
    minio_client=minio_client,
    bucket_name="documents",
).create()
```

주입된 저장소와 연결의 생성·readiness 확인·종료는 호스트 애플리케이션 또는 별도 인프라 통합 계층이 담당합니다. SDK는 호출자가 제공한 저장소를 종료하지 않습니다.
비동기 호스트는 동일한 구성 요소로 전체 비동기 facade를 조립할 수 있습니다.

```python
from dms import UploadDocumentRequest, create_async_sdk_from_components

sdk = create_async_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
)
result = await sdk.upload_document(
    UploadDocumentRequest(
        content=b"hello world",
        filename="hello.txt",
        content_type="text/plain",
    )
metadata = await sdk.get_document_metadata(result.document_id)
```

비동기 facade도 전역 client lifecycle을 소유하지 않습니다. `get_document_content_async_stream(...)`처럼 SDK가 직접 연 본문 스트림은 사용이 끝나면 `aclose()`로 정리해야 하며, 호출자가 제공한 입력 스트림은 SDK가 닫지 않습니다.

## Public API overview

공개 API는 package root의 export와 공개 계약 테스트를 기준으로 관리합니다.

기본 import 경계는 `from dms import ...`이며, 내부 adapter와 저장소 구현은 공개 API로 간주하지 않습니다. API 문서 끝의 추적성 매트릭스는 각 공개 영역을 구현 파일, 검증 테스트, 실행 예제에 연결합니다.

## Integration boundary

- 저장소 연결 생성, 환경변수 해석, bucket/database 준비, readiness 및 운영용 health endpoint는 호스트 애플리케이션 또는 별도 인프라 패키지가 담당합니다.
- SDK 공개 조립 API는 저장소 port를 받는 `create_sdk_from_components(...)`와 SQLAlchemy Engine·MinIO client를 받는 `DocumentManagementSDKFactory`/`create_sdk_from_clients(...)`입니다.
- SDK는 주입된 저장소와 연결의 소유권을 취득하지 않으며 전역 `close()`·`aclose()`를 제공하지 않습니다.
- SDK가 문서 처리 중 직접 연 파일·본문 스트림은 SDK가 닫고, 호출자가 제공한 스트림과 출력 대상은 닫지 않습니다.

## 공개 문서 정보와 삭제 조회

- 업로드, 일반 문서 정보 조회, 목록 및 커서 페이지는 내부 저장 위치가 없는 `PublicDocumentMetadata`를 반환합니다.
- 저장 위치가 필요한 복구·관리 작업만 `get_internal_document_metadata()`를 명시적으로 사용해야 합니다.
- 일반 단건·목록·커서 조회는 논리 삭제 및 삭제 진행 상태의 문서를 숨깁니다. 삭제 상태 확인은 `get_internal_document_metadata()`와 복구 API처럼 명시적인 관리 경로를 사용해야 합니다.
- 삭제된 문서의 본문 및 본문 스트림 조회는 `DocumentDeletedError`를 발생시킵니다.
- `PublicDocumentMetadata.to_dict()`는 v0.6 호환 필드명을 유지하고, 외부 응답용 `to_public_dict()`는 업무 메타데이터를 `metadata` 필드로 직렬화합니다. `DocumentPage`, `UploadDocumentResult`, `DeleteDocumentResult`도 JSON 호환 `to_dict()`를 제공합니다.
- 공개 결과 모델은 `json_schema()`와 `model_json_schema()`로 직렬화 결과에 대응하는 JSON Schema를 제공합니다. 공개 dump와 schema에는 `storage_key`가 존재하지 않습니다.
- 모든 `DmsError` 하위 오류는 안정적인 `code`, 상위 `category`, `retryable` 값을 제공합니다. 문서 관련 오류는 가능한 경우 `document_id`도 제공합니다.
- `DocumentContentStream`은 컨텍스트 관리자로 사용할 수 있습니다. 호스트가 본문 반복자만 전달하는 경우에는 `iter_chunks_closing()` 또는 `aiter_chunks_closing()`을 사용하면 정상 소진, 읽기 오류, 취소 및 반복자 명시 종료에서 SDK 소유 스트림을 정리합니다.

## 목록 페이지네이션

- `list_documents(cursor=None, limit=100, status=None)`는 기본 목록 API이며 `DocumentPage`를 반환합니다.
- 다음 페이지는 반환된 `next_cursor`를 같은 상태 필터와 페이지 크기로 전달하여 조회합니다. 마지막 페이지에서는 `next_cursor`가 `None`입니다.
- 커서는 상태 필터와 페이지 크기에 결합됩니다. 변조된 커서나 다른 조건에 재사용한 커서는 `ValidationError`로 거부됩니다.
- 목록 조회는 커서 방식만 지원합니다. 기존 오프셋 기반 목록 API는 제거되었습니다.

## 전체 데이터 삭제와 신규 적재 초기화

- `clear_all_data()`는 DMS가 관리하는 문서 본문(`documents/` prefix), 문서 정보 및 업로드 작업 기록을 완전 삭제하고 `DataResetResult`로 저장소별 삭제 건수를 반환합니다. 문서 정보가 없는 orphan 본문도 함께 정리합니다.
- `initialize_for_data_load()`는 같은 범위를 비운 뒤 새 데이터 적재를 시작할 수 있는 빈 상태를 반환합니다. 이미 빈 상태에서 호출해도 성공하는 멱등 작업입니다.
- 두 작업은 일반 문서 단건 삭제와 달리 DMS 전체 범위에 적용되는 관리 작업입니다. 조립 시 `access_policy`가 제공되면 각각 `data.clear_all`, `data.initialize_for_data_load` 작업으로 권한을 확인합니다.
- 문서 정보 저장소, 문서 본문 저장소 및 업로드 작업 저장소는 분산 트랜잭션으로 묶이지 않습니다. 한 저장소가 실패해도 나머지 저장소 정리를 시도하며, 전체 완료가 되지 않으면 부분 삭제 건수와 `failed_stores`를 가진 `DataResetError`를 발생시킵니다. 이때 `error.result.ready_for_data_load`는 `False`입니다.
- `AsyncDocumentManagementSDK`에서도 두 작업을 awaitable 방식으로 제공합니다.

## 업로드와 비동기 본문 스트리밍

- `AsyncDocumentManagementSDK`는 등록, 문서 정보 및 목록 조회, 본문 조회, 삭제, 복구 및 초기화를 awaitable 방식으로 제공합니다. 동기 저장소 작업은 event loop 밖에서 실행되며, 취소된 상태 변경 작업은 안전한 완료 지점에 도달한 뒤 취소를 전파합니다.
- 업로드 입력은 메모리 바이트, 파일 경로, 정확한 크기가 선언된 동기 바이너리 스트림의 세 범주를 지원합니다. 파일 경로는 SDK가 열고 닫으며, 호출자가 제공한 스트림은 SDK가 닫지 않습니다.
- 스트림 등록은 정확한 양수 크기를 필수로 받고, 실제 읽은 크기가 선언값과 다르면 업로드 객체를 정리한 뒤 유효성 오류를 반환합니다. 최대 파일 크기는 조립 시 설정한 공통 정책으로 적용합니다.
- 크기를 알 수 없는 입력, 비동기 입력 스트림, 요청별 최대 크기, 업로드 chunk 조절 및 스트림 멱등성은 지원하지 않습니다. 비동기 facade의 `upload_document_stream(...)`은 동기 바이너리 스트림 등록을 event loop 밖에서 실행합니다.
- `get_document_content_async_stream(...)`은 전체 본문을 메모리에 적재하지 않는 비동기 반복 스트림을 반환합니다.
- 다운로드 스트림은 성공, 실패, 취소 및 컨텍스트 종료 시 정리됩니다.
- 비동기 본문 스트림은 `async with`와 반복 호출에 안전한 `aclose()`를 지원합니다. 비동기 SDK 자체는 전역 lifecycle을 관리하지 않습니다.

### 업로드 API 축소 이전 안내

- 크기를 알 수 없는 입력은 호출자가 임시 파일 등으로 먼저 크기를 확정한 뒤 파일 또는 동기 스트림 등록 경로를 사용해야 합니다.
- 제거된 bounded·unknown-size·비동기 입력 스트림 요청 타입과 메서드는 `UploadDocumentStreamRequest` 및 `upload_document_stream(...)`으로 자동 호환되지 않습니다. 호출자가 정확한 `size`를 제공해야 합니다.

## v0.4 공개 반환값 이전 안내

- 기존 `result.storage_key` 사용 코드는 관리 작업에 한해 `sdk.get_internal_document_metadata(result.document_id).storage_key`로 이전해야 합니다.
- 기존 일반 조회와 목록에서 `storage_key`를 읽던 코드는 공개 반환값에서 해당 필드를 제거해야 합니다.
- 내부 저장 위치를 외부 응답이나 업무 메타데이터로 전달하지 말고, 명시적 관리·복구 경로 안에서만 사용해야 합니다.

## Document guide

- 제품 요구사항: `docs/prd.md`
- 소프트웨어 요구사항: `docs/srs.md`

## Integration tests

저장소 adapter와 실제 외부 서비스 readiness 검증은 호스트 애플리케이션 또는 별도 인프라 패키지의 책임입니다. 이 저장소의 핵심 테스트는 포트 구현 대역을 주입하여 문서 서비스 계약을 검증합니다.
테스트가 Docker Compose를 생성하거나 실행하지 않습니다.

```bash
uv run pytest test_dms -q
```

## Out of scope

현재 범위 밖 항목:
- 인증 helper
- presigned URL 발급
- 문서 검색/필터링
- 독립 실행형 비동기 작업 처리 서비스
- 메시지 브로커 연계 API
- 자체 권한 정책 관리 API
- PostgreSQL·SQLite·MinIO client 생성 및 client lifecycle 관리
- 인프라 readiness 또는 운영용 health endpoint
