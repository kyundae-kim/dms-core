---
title: SDK public interface
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [sdk, integration, document, client-library]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK public interface

DMS SRS는 이 프로젝트의 외부 계약이 REST endpoint가 아니라 Python SDK 인터페이스라는 점을 분명히 한다. SDK interface 초안은 이를 더 구체화해 `DocumentManagementSDK` 프로토콜, 요청/응답 모델, `close()` 호출, 예외 계층, `create_sdk(env)` 팩토리 방향까지 제시한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 최소 기능 집합
- `upload_document(...)`
- `get_document_metadata(document_id)`
- `get_document_content(document_id)`
- `delete_document(document_id)`
- `check_health()`

## 구체화된 인터페이스 요소
- 핵심 프로토콜: `DocumentManagementSDK`
- 요청/응답: `UploadDocumentRequest`, `UploadDocumentResult`, `DocumentContent`, `DeleteDocumentResult`, `HealthStatus`
- lifecycle: `close()`를 통해 registry/client/resource 종료
- assembly: `create_sdk(env)` 팩토리 진입점

## 설계 시사점
- public contract는 import 가능한 Python 타입으로 표현되어야 한다.
- 반환 모델에는 document identifier, metadata, deletion status 같은 도메인 의미가 반영되어야 한다.
- 설정/초기화는 별도 lifecycle이지만 소비자는 단일 facade로 문서 기능을 사용해야 한다.
- 예외 계층과 팩토리 조립 방식까지 포함해야 안정적인 public contract가 된다.

## 관련 페이지
- [[dms-sdk]]
- [[sdk-consumption-patterns]]
- [[document-metadata-model]]
- [[document-lifecycle-and-consistency]]
- [[sdk-exception-model]]
- [[sdk-factory-assembly]]
