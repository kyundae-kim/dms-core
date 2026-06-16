---
title: SDK public interface
created: 2026-06-15
updated: 2026-06-16
type: concept
tags: [sdk, integration, document, client-library]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK public interface

DMS SRS는 이 프로젝트의 외부 계약이 REST endpoint가 아니라 Python SDK 인터페이스라는 점을 분명히 한다. 2026-06-16 기준 SDK interface 초안은 이를 더 구체화해 `DocumentManagementSDK` 프로토콜, 요청/응답 모델, `close()` 호출, 예외 계층, `create_sdk(env)` 팩토리 방향뿐 아니라 storage key 규칙, 삭제 보상 정책, 식별자 충돌 기준까지 명시한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 최소 기능 집합
- `fetch_access_token(scope=None)`
- `get_authenticated_user(token)`
- `upload_document(...)`
- `get_document_metadata(document_id)`
- `get_document_content(document_id)`
- `delete_document(document_id, *, hard_delete=False)`
- `check_health()`
- `close()`

## 구체화된 인터페이스 요소
- 핵심 프로토콜: `DocumentManagementSDK`
- 요청/응답: `UploadDocumentRequest`, `UploadDocumentResult`, `DocumentMetadata`, `DocumentContent`, `DeleteDocumentResult`, `HealthStatus`
- lifecycle: `close()`를 통해 registry/client/resource 종료
- assembly: `create_sdk(env)`를 기본 public 팩토리로 사용하고, `create_sdk_from_environment(env)`는 하위 호환 alias로 유지
- auth helper: `DMS_AUTH_ENABLED=true`일 때만 Keycloak helper를 조립하고 `fetch_access_token(...)`, `get_authenticated_user(...)`를 제공
- 정책: `documents/{document_id}/{sanitized_filename}` storage key 규칙과 `document_id` 기준 충돌 정책

## 새로 강화된 계약
- 업로드는 단일 bucket과 `documents/` prefix를 전제로 한다.
- 파일명은 trim, 경로 구분자 치환, `..` 축약을 거친 `sanitized_filename`으로 정규화되어야 한다.
- 동일한 `document_id` 재사용은 `DuplicateDocumentError`를 반환하고, 같은 파일명은 다른 `document_id` 아래에서 허용된다.
- 업로드 중 object 저장 성공 후 metadata 저장 실패 시 즉시 object를 삭제해 orphan을 남기지 않아야 한다.
- soft delete와 hard delete 모두 object 삭제 이후 metadata 후속 처리 순서를 계약 수준에서 드러낸다.

## 설계 시사점
- public contract는 import 가능한 Python 타입과 정책 의미를 함께 표현해야 한다.
- `dms.sdk` namespace는 `DocumentMetadata`를 직접 export해야 문서 계약과 quick-start import 예시가 일치한다.
- 인증은 서버 미들웨어가 아니라 SDK helper 계약으로 노출되어, 소비자가 bearer token 검증과 service-to-service access token 발급을 재사용할 수 있어야 한다.
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
