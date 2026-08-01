---
title: SDK public interface
created: 2026-06-15
updated: 2026-07-19
type: concept
tags: [sdk, integration, document, client-library]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK public interface

DMS SRS는 이 프로젝트의 외부 계약이 REST endpoint가 아니라 Python SDK 인터페이스라는 점을 분명히 한다. 현재 public interface는 package-root export, client/component factory, sync/async facade, 기능별 protocol, 요청·결과 모델, stream/cursor/delete/recovery, health/lifecycle, structured observer, 오류·HTTP projection까지 포함한다. 정확한 export·method 목록은 [`docs/api.md`](../../docs/api.md)의 source/test/example 추적성 매트릭스를 기준으로 한다.

## 최소 기능 집합
- 바이트 등록 `upload_document(...)`
- 파일 등록 `upload_file(...)`
- 크기가 확인된 동기 바이너리 스트림 등록 `upload_document_stream(...)`
- `get_document_metadata(document_id)`
- `get_document_content(document_id)`
- `get_document_content_stream(document_id, *, chunk_size=65536)`
- `delete_document(document_id, *, hard_delete=False)`
- `clear_all_data()`
- `initialize_for_data_load()`
- `check_health()`
- `close()`
- 비동기 대응 facade와 `get_document_content_async_stream(...)`
- cursor 기반 `list_documents(...)`와 `iter_documents(...)`
- 명시적 `get_internal_document_metadata(...)` 및 reconciliation 관리 경로

## 현재 계약에서 명확한 점
- runtime health check는 startup health check와 별개로 `HealthStatus`/`ServiceHealth` 반환 계약까지 포함한다.
- explicit dependency injection 경로(`create_sdk_from_components(metadata_store=..., object_store=...)`)와 client 기반 조립 경로가 제품 경계의 일부다.
- DMS는 환경변수에서 client를 만들지 않으며, 인증 helper나 자체 권한 저장소를 제공하지 않는다. 접근 제어는 host-provided `DocumentAccessPolicy` seam으로 주입한다.
- 문서는 구현 전 설계가 아니라 코드/테스트와 함께 갱신되는 계약이므로 README와 public export도 같은 기준으로 정렬되어야 한다.

## SDK interface 재-ingest로 강화된 점
- `dms.sdk` public import 목록에는 문서 작업 타입, 상태 타입, 구체 SDK 구현과 의존성 주입용 factory가 포함된다.
- `DocumentContentStream`이 독립 응답 타입이며 `iter_chunks()`와 `close()`를 가진다는 점이 명시됐다.
- client 기반 factory와 component 기반 explicit dependency injection factory가 first-class entrypoint로 문서화됐다.
- 로깅 계약이 단순 "logger 가능" 수준이 아니라 `dms_` prefix extra field 규약까지 포함하는 public 운영 규약으로 정리됐다.

## 구체화된 인터페이스 요소
- 핵심 프로토콜: `DocumentManagementClient`와 기능별 `DocumentWriter`/`DocumentReader`/`DocumentLister` 등
- 요청/응답: `UploadDocumentRequest`, `UploadDocumentStreamRequest`, `UploadDocumentResult`, `DocumentMetadata`, `DocumentContent`, `DocumentContentStream`, `DeleteDocumentResult`, `DataResetResult`, `HealthStatus`
- 관리 계약: `DataResetter`는 DMS가 관리하는 문서 정보, `documents/` prefix 본문 및 업로드 작업 기록을 전체 삭제하거나 신규 적재용 빈 상태로 초기화하는 경계를 표현한다.
- lifecycle: `close()`를 통해 registry/client/resource 종료
- assembly: 호출자가 생성한 client를 받는 `create_sdk_from_clients(...)`와 저장소 구현을 받는 `create_sdk_from_components(...)`를 제공
- diagnostics: 선택적 `logger`를 받아 operation 경계마다 structured log를 남길 수 있음
- 정책: `documents/{document_id}/{sanitized_filename}` storage key 규칙과 `document_id` 기준 충돌 정책. storage key는 일반 public result에서 숨긴다.
- 다운로드 정책: eager 바이트 조회와 chunked stream 조회를 둘 다 제공

## 새로 강화된 계약
- 업로드는 단일 bucket과 `documents/` prefix를 전제로 한다.
- 파일명은 trim, 경로 구분자 치환, `..` 축약을 거친 `sanitized_filename`으로 정규화되어야 한다.
- 동일한 `document_id` 재사용은 `DuplicateDocumentError`를 반환하고, 같은 파일명은 다른 `document_id` 아래에서 허용된다.
- 업로드 중 object 저장 성공 후 metadata 저장 실패 시 즉시 object를 삭제해 orphan을 남기지 않아야 한다.
- soft delete와 hard delete 모두 delete 시작 시 metadata를 `deleting`으로 전환하고, object 삭제 이후 metadata 후속 처리 순서를 계약 수준에서 드러낸다.
- object 삭제 자체가 실패하면 metadata를 `failed`로 남겨 호출자와 운영자가 부분 실패를 감지할 수 있어야 한다.
- 전체 데이터 삭제는 metadata에 없는 DMS 본문도 함께 정리하고, DMS가 아닌 다른 bucket prefix의 객체는 보존한다.
- 전체 삭제는 분산 트랜잭션을 주장하지 않으며, 한 저장소가 실패해도 나머지 저장소를 시도한 뒤 `DataResetError`와 저장소별 부분 건수를 반환한다.
- 부분 실패 시 `DataResetError.failed_stores`로 실패한 저장소를 식별할 수 있고, `error.result.ready_for_data_load`는 `False`가 된다. 작업 관찰 이벤트도 같은 준비 상태를 전달한다.
- 신규 적재 초기화는 전체 삭제와 같은 범위를 멱등적으로 비운 뒤 `ready_for_data_load` 상태를 반환한다.
- 운영 추적을 위해 `dms_event`, `dms_document_id`, `dms_storage_key`, `dms_duration_ms`, `dms_error_type` 같은 structured diagnostic field를 log에 남길 수 있어야 한다.
- 큰 파일 처리에서는 기존 `get_document_content()`와 별도로 `get_document_content_stream()`를 제공하고 caller가 명시적으로 stream을 닫도록 해야 한다.

## 설계 시사점
- public contract는 import 가능한 Python 타입과 정책 의미를 함께 표현해야 한다.
- `dms` package root는 공개 import 경계이며 `DocumentMetadata`를 포함한 root export가 API reference와 quick-start 예제에 반영되어야 한다.
- 인증은 DMS SDK 범위 밖이며, host가 만든 `AccessContext`와 `DocumentAccessPolicy`를 통해 업무 권한만 주입한다.
- SDK는 라이브러리답게 stdout 출력 대신 caller가 주입한 Python logger로 진단 정보를 흘려보내야 한다.
- 반환 모델에는 document identifier, metadata, deletion status 같은 도메인 의미가 반영되어야 하며, `storage_key`는 privileged 관리·복구 경로에서만 사용한다.
- 설정/초기화는 별도 lifecycle이지만 소비자는 단일 facade로 문서 기능을 사용해야 한다.
- 예외 계층과 팩토리 조립 방식까지 포함해야 안정적인 public contract가 된다.

## 관련 페이지
- [[dms-sdk]]
- [[sdk-consumption-patterns]]
- [[document-metadata-model]]
- [[document-lifecycle-and-consistency]]
- [[sdk-exception-model]]
- [[sdk-factory-assembly]]
