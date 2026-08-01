# Document Management Service

사용자 문서를 MinIO에 저장하고 문서 메타데이터를 PostgreSQL 또는 SQLite에 저장/관리하는 Python SDK입니다.

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

가장 일반적인 시작 방식은 호스트 애플리케이션이 생성한 SQLAlchemy `Engine`과 MinIO client를 주입하는 client 기반 조립입니다. 완성된 저장소 구현을 직접 주입하려면 `create_sdk_from_components(...)`를 사용할 수 있습니다.

```python
from dms import create_sdk_from_clients

sdk = create_sdk_from_clients(
    engine=engine,
    minio_client=minio_client,
    bucket_name="documents",
)
try:
    health = sdk.check_health()
finally:
    sdk.close()
```

주입된 client는 기본적으로 호출자 소유이며 `sdk.close()`가 종료하지 않습니다. SDK 종료 시 함께 실행할 정리 작업이 필요한 경우에만 `close_callbacks`에 명시적으로 전달합니다. client를 생성하는 callable을 받는 별도 API는 제공하지 않으며, 호출자가 client를 생성한 뒤 이 팩토리에 전달합니다.

비동기 호스트는 동일한 구성 요소로 전체 비동기 facade를 조립할 수 있습니다.

```python
from dms import UploadDocumentRequest, create_async_sdk_from_components

async with create_async_sdk_from_components(
    metadata_store=metadata_store,
    object_store=object_store,
) as sdk:
    result = await sdk.upload_document(
        UploadDocumentRequest(
            content=b"hello world",
            filename="hello.txt",
            content_type="text/plain",
        )
    )
    metadata = await sdk.get_document_metadata(result.document_id)
```

SDK는 환경변수나 설정 묶음에서 인프라 client를 직접 생성하지 않습니다. 호스트가 설정을 읽고 SQLAlchemy Engine과 MinIO client를 생성한 뒤 client 기반 팩토리에 전달하거나, 완성된 저장소 구현을 component 기반 팩토리에 주입해야 합니다.

호스트가 전달한 client와 component는 기본적으로 호출자 소유입니다. SDK가 종료해야 하는 자원만 `ManagedResource`와 `ResourceOwnership.SDK`로 명시하십시오. SDK 소유 자원은 조립 실패 시 rollback되고 정상 종료에서는 역순으로 정확히 한 번 정리됩니다.

## Public API overview

공개 API는 package root의 export와 공개 계약 테스트를 기준으로 관리합니다.

기본 import 경계는 `from dms import ...`이며, 내부 adapter와 저장소 구현은 공개 API로 간주하지 않습니다. API 문서 끝의 추적성 매트릭스는 각 공개 영역을 구현 파일, 검증 테스트, 실행 예제에 연결합니다.

## Minimum configuration overview

DMS는 환경변수에서 인프라 client를 직접 생성하지 않습니다. 호스트 애플리케이션이 SQLAlchemy `Engine`과 MinIO client를 만들고 `create_sdk_from_clients(...)`에 전달하거나, 완성된 metadata/object store를 `create_sdk_from_components(...)`에 주입해야 합니다.

- 현재 DMS가 자동으로 읽는 환경변수는 없습니다.
- DMS용 `.env.example`은 제공하지 않습니다. 지원하지 않는 client 생성 설정을 SDK 설정으로 오인하지 않도록 하기 위함입니다.
- SDK가 닫아야 하는 자원만 `ManagedResource(ownership=ResourceOwnership.SDK)` 또는 `close_callbacks`로 명시합니다.
- `DmsServiceConfigs`는 호스트 설정 계층에서 사용할 수 있는 value object일 뿐, client를 자동 생성하지 않습니다.

## 공개 문서 정보와 삭제 조회

- 업로드, 일반 문서 정보 조회, 목록 및 커서 페이지는 내부 저장 위치가 없는 `PublicDocumentMetadata`를 반환합니다.
- 저장 위치가 필요한 복구·관리 작업만 `get_internal_document_metadata()`를 명시적으로 사용해야 합니다.
- 일반 단건·목록·커서 조회는 논리 삭제 및 삭제 진행 상태의 문서를 숨깁니다. 삭제 상태 확인은 `get_internal_document_metadata()`와 복구 API처럼 명시적인 관리 경로를 사용해야 합니다.
- 삭제된 문서의 본문 및 본문 스트림 조회는 `DocumentDeletedError`를 발생시킵니다.
- `PublicDocumentMetadata.to_dict()`는 v0.6 호환 필드명을 유지하고, 외부 응답용 `to_public_dict()`는 업무 메타데이터를 `metadata` 필드로 직렬화합니다. `DocumentPage`, `UploadDocumentResult`, `DeleteDocumentResult`도 JSON 호환 `to_dict()`를 제공합니다.
- 공개 결과 모델은 `json_schema()`와 `model_json_schema()`로 직렬화 결과에 대응하는 JSON Schema를 제공합니다. 공개 dump와 schema에는 `storage_key`가 존재하지 않습니다.
- 모든 `DmsError` 하위 오류는 안정적인 `code`, 상위 `category`, `retryable` 값을 제공합니다. 문서 관련 오류는 가능한 경우 `document_id`도 제공합니다.
- SDK와 `DocumentContentStream`은 컨텍스트 관리자로 사용할 수 있습니다. 호스트가 본문 반복자만 전달하는 경우에는 `iter_chunks_closing()` 또는 `aiter_chunks_closing()`을 사용하면 정상 소진, 읽기 오류, 취소 및 반복자 명시 종료에서 SDK 소유 스트림을 정리합니다.

## 목록 페이지네이션

- `list_documents(cursor=None, limit=100, status=None)`는 기본 목록 API이며 `DocumentPage`를 반환합니다.
- 다음 페이지는 반환된 `next_cursor`를 같은 상태 필터와 페이지 크기로 전달하여 조회합니다. 마지막 페이지에서는 `next_cursor`가 `None`입니다.
- 커서는 상태 필터와 페이지 크기에 결합됩니다. 변조된 커서나 다른 조건에 재사용한 커서는 `ValidationError`로 거부됩니다.
- 목록 조회는 커서 방식만 지원합니다. 기존 오프셋 기반 목록 API는 제거되었습니다.

## 전체 데이터 삭제와 신규 적재 초기화

- `clear_all_data()`는 DMS가 관리하는 문서 본문(`documents/` prefix), 문서 정보 및 업로드 작업 기록을 완전 삭제하고 `DataResetResult`로 저장소별 삭제 건수를 반환합니다. 문서 정보가 없는 orphan 본문도 함께 정리합니다.
- `initialize_for_data_load()`는 같은 범위를 비운 뒤 새 데이터 적재를 시작할 수 있는 빈 상태를 반환합니다. 이미 빈 상태에서 호출해도 성공하는 멱등 작업입니다.
- 두 작업은 일반 문서 단건 삭제와 달리 DMS 전체 범위에 적용되는 관리 작업입니다. `DmsAssemblyPlan.access_policy`가 제공되면 각각 `data.clear_all`, `data.initialize_for_data_load` 작업으로 권한을 확인합니다.
- PostgreSQL/SQLite, MinIO 및 업로드 작업 저장소는 분산 트랜잭션으로 묶이지 않습니다. 한 저장소가 실패해도 나머지 저장소 정리를 시도하며, 전체 완료가 되지 않으면 부분 삭제 건수와 `failed_stores`를 가진 `DataResetError`를 발생시킵니다. 이때 `error.result.ready_for_data_load`는 `False`입니다.
- `AsyncDocumentManagementSDK`에서도 두 작업을 awaitable 방식으로 제공합니다.

## 업로드와 비동기 본문 스트리밍

- `AsyncDocumentManagementSDK`는 등록, 문서 정보 및 목록 조회, 본문 조회, 삭제, 복구, 상태 확인과 종료를 모두 awaitable 방식으로 제공합니다. 동기 저장소 작업은 event loop 밖에서 실행되며, 취소된 상태 변경 작업은 안전한 완료 지점에 도달한 뒤 취소를 전파합니다.
- 업로드 입력은 메모리 바이트, 파일 경로, 정확한 크기가 선언된 동기 바이너리 스트림의 세 범주를 지원합니다. 파일 경로는 SDK가 열고 닫으며, 호출자가 제공한 스트림은 SDK가 닫지 않습니다.
- 스트림 등록은 정확한 양수 크기를 필수로 받고, 실제 읽은 크기가 선언값과 다르면 업로드 객체를 정리한 뒤 유효성 오류를 반환합니다. 최대 파일 크기는 조립 시 설정한 공통 정책으로 적용합니다.
- 크기를 알 수 없는 입력, 비동기 입력 스트림, 요청별 최대 크기, 업로드 chunk 조절 및 스트림 멱등성은 지원하지 않습니다. 비동기 facade의 `upload_document_stream(...)`은 동기 바이너리 스트림 등록을 event loop 밖에서 실행합니다.
- `get_document_content_async_stream(...)`은 전체 본문을 메모리에 적재하지 않는 비동기 반복 스트림을 반환합니다.
- 다운로드 스트림은 성공, 실패, 취소 및 컨텍스트 종료 시 정리됩니다.
- SDK와 비동기 본문 스트림은 `async with`와 반복 호출에 안전한 `aclose()`를 지원합니다.

### 업로드 API 축소 이전 안내

- 크기를 알 수 없는 입력은 호출자가 임시 파일 등으로 먼저 크기를 확정한 뒤 파일 또는 동기 스트림 등록 경로를 사용해야 합니다.
- 제거된 bounded·unknown-size·비동기 입력 스트림 요청 타입과 메서드는 `UploadDocumentStreamRequest` 및 `upload_document_stream(...)`으로 자동 호환되지 않습니다. 호출자가 정확한 `size`를 제공해야 합니다.

## 권장 HTTP 오류 매핑

독립 실행형 API 서버는 제공하지 않지만, 호스트 애플리케이션은 `error_descriptor(error)`로 안정적인 code, category, retryable, 공개 메시지를 가진 전송 방식 중립 오류 설명자를 얻을 수 있습니다. `merge_error_descriptor(...)`는 기준 SDK 분류를 유지하면서 외부 코드, 공개 메시지 및 재시도 대기 시간을 합성합니다. `recommended_http_error(...)`는 설명자 또는 DMS 오류를 권장 HTTP 상태, JSON 호환 본문 및 선택적 `Retry-After` 헤더로 투영합니다. 설정·저장소·일관성 오류의 외부 메시지는 내부 연결 정보나 비밀값을 노출하지 않는 고정 메시지로 변환됩니다.

### v0.4 공개 반환값 이전 안내

- 기존 `result.storage_key` 사용 코드는 관리 작업에 한해 `sdk.get_internal_document_metadata(result.document_id).storage_key`로 이전해야 합니다.
- 기존 일반 조회와 목록에서 `storage_key`를 읽던 코드는 공개 반환값에서 해당 필드를 제거해야 합니다.
- 내부 저장 위치를 외부 응답이나 업무 메타데이터로 전달하지 말고, 명시적 관리·복구 경로 안에서만 사용해야 합니다.

## Document guide

- 제품 요구사항: `docs/prd.md`
- 소프트웨어 요구사항: `docs/srs.md`

## Integration tests

실제 PostgreSQL + MinIO integration test는 외부에 이미 준비된 서비스를 재사용합니다.
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
