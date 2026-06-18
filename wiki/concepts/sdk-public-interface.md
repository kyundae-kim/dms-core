---
title: SDK public interface
created: 2026-06-15
updated: 2026-06-18
type: concept
tags: [sdk, integration, document, client-library]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK public interface

DMS SRS는 이 프로젝트의 외부 계약이 REST endpoint가 아니라 Python SDK 인터페이스라는 점을 분명히 하며, 2026-06-18 갱신본은 그 계약을 “미래 설계 초안”이 아니라 현재 코드와 테스트 기준의 실제 동작 문서로 재정의한다. 같은 날짜의 SDK interface 문서도 초안 중심 표현에서 실제 export, 메서드 시그니처, factory 진입점, auth helper, stream 타입, logging 계약을 직접 기술하는 현재형 문서로 갱신되었다. 따라서 public interface는 `DocumentManagementSDK` 프로토콜과 요청/응답 타입만이 아니라 factory 진입점, runtime health/auth helper, stream 다운로드, structured logging, 실패 semantics까지 포함하는 운영 계약으로 읽어야 한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 최소 기능 집합
- `fetch_access_token(scope=None)`
- `get_authenticated_user(token)`
- `upload_document(...)`
- `get_document_metadata(document_id)`
- `get_document_content(document_id)`
- `get_document_content_stream(document_id, *, chunk_size=65536)`
- `delete_document(document_id, *, hard_delete=False)`
- `check_health()`
- `close()`

## SRS 갱신으로 명확해진 점
- SRS는 `fetch_access_token()`과 `get_authenticated_user()`를 선택적 auth helper 요구사항으로 명시한다.
- runtime health check는 startup health check와 별개로 `HealthStatus`/`ServiceHealth` 반환 계약까지 포함한다.
- explicit dependency injection 경로(`create_sdk(metadata_store=..., object_store=...)`)도 제품 경계의 일부로 간주된다.
- 문서는 구현 전 설계가 아니라 코드/테스트와 함께 갱신되는 계약이므로 README와 public export도 같은 기준으로 정렬되어야 한다.

## SDK interface 재-ingest로 강화된 점
- `dms.sdk` public import 목록에 `AccessTokenResult`, `AuthenticatedUser`, `ServiceHealth`, `DefaultDocumentManagementSDK`, `create_sdk_from_environment`까지 포함된다는 점이 분명해졌다.
- `DocumentContentStream`이 독립 응답 타입이며 `iter_chunks()`와 `close()`를 가진다는 점이 명시됐다.
- 환경 기반 factory와 explicit dependency injection factory가 둘 다 first-class entrypoint로 문서화됐다.
- 로깅 계약이 단순 "logger 가능" 수준이 아니라 `dms_` prefix extra field 규약까지 포함하는 public 운영 규약으로 정리됐다.

## 구체화된 인터페이스 요소
- 핵심 프로토콜: `DocumentManagementSDK`
- 요청/응답: `UploadDocumentRequest`, `UploadDocumentResult`, `DocumentMetadata`, `DocumentContent`, `DocumentContentStream`, `DeleteDocumentResult`, `HealthStatus`
- lifecycle: `close()`를 통해 registry/client/resource 종료
- assembly: `create_sdk(env)`를 기본 public 팩토리로 사용하고, `create_sdk_from_environment(env)`는 하위 호환 alias로 유지
- diagnostics: 선택적 `logger`를 받아 operation 경계마다 structured log를 남길 수 있음
- auth helper: `DMS_AUTH_ENABLED=true`일 때만 Keycloak helper를 조립하고 `fetch_access_token(...)`, `get_authenticated_user(...)`를 제공
- 정책: `documents/{document_id}/{sanitized_filename}` storage key 규칙과 `document_id` 기준 충돌 정책
- 다운로드 정책: eager 바이트 조회와 chunked stream 조회를 둘 다 제공

## 새로 강화된 계약
- 업로드는 단일 bucket과 `documents/` prefix를 전제로 한다.
- 파일명은 trim, 경로 구분자 치환, `..` 축약을 거친 `sanitized_filename`으로 정규화되어야 한다.
- 동일한 `document_id` 재사용은 `DuplicateDocumentError`를 반환하고, 같은 파일명은 다른 `document_id` 아래에서 허용된다.
- 업로드 중 object 저장 성공 후 metadata 저장 실패 시 즉시 object를 삭제해 orphan을 남기지 않아야 한다.
- soft delete와 hard delete 모두 delete 시작 시 metadata를 `deleting`으로 전환하고, object 삭제 이후 metadata 후속 처리 순서를 계약 수준에서 드러낸다.
- object 삭제 자체가 실패하면 metadata를 `failed`로 남겨 호출자와 운영자가 부분 실패를 감지할 수 있어야 한다.
- 운영 추적을 위해 `dms_event`, `dms_document_id`, `dms_storage_key`, `dms_duration_ms`, `dms_error_type` 같은 structured diagnostic field를 log에 남길 수 있어야 한다.
- 큰 파일 처리에서는 기존 `get_document_content()`와 별도로 `get_document_content_stream()`를 제공하고 caller가 명시적으로 stream을 닫도록 해야 한다.

## 설계 시사점
- public contract는 import 가능한 Python 타입과 정책 의미를 함께 표현해야 한다.
- `dms.sdk` namespace는 `DocumentMetadata`를 직접 export해야 문서 계약과 quick-start import 예시가 일치한다.
- 인증은 서버 미들웨어가 아니라 SDK helper 계약으로 노출되어, 소비자가 bearer token 검증과 service-to-service access token 발급을 재사용할 수 있어야 한다.
- SDK는 라이브러리답게 stdout 출력 대신 caller가 주입한 Python logger로 진단 정보를 흘려보내야 한다.
- 반환 모델에는 document identifier, metadata, deletion status, storage key 같은 도메인 의미가 반영되어야 한다.
- 설정/초기화는 별도 lifecycle이지만 소비자는 단일 facade로 문서 기능을 사용해야 한다.
- 예외 계층과 팩토리 조립 방식까지 포함해야 안정적인 public contract가 된다.

## 관련 페이지
- [[dms-sdk]]
- [[sdk-consumption-patterns]]
- [[document-metadata-model]]
- [[document-lifecycle-and-consistency]]
- [[sdk-exception-model]]
- [[sdk-factory-assembly]]
