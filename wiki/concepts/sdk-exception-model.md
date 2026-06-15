---
title: SDK exception model
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [sdk, reliability, security, integration]
sources: [raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK exception model

SDK interface 초안은 예외를 단순 런타임 오류가 아니라 비즈니스 의미를 가진 계층으로 분리할 것을 제안한다. 예시 계층에는 `ConfigurationError`, `ValidationError`, `DocumentNotFoundError`, `DuplicateDocumentError`, `StorageError`, `MetadataStoreError`, `ConsistencyError`, `HealthCheckFailedError`가 포함된다.

## 왜 중요한가
- 소비 프로젝트가 오류를 유형별로 처리할 수 있다.
- 민감정보를 숨긴 채 도메인 의미를 보존할 수 있다.
- object storage 실패와 metadata 저장 실패를 다른 복구 경로로 보낼 수 있다.

## 설계 시사점
- 예외 모델은 [[document-lifecycle-and-consistency]] 정책과 직접 연결된다.
- health check 실패는 단순 false 반환보다 구조화된 상태/예외 조합으로 설계할 수 있다.
- public SDK가 안정되려면 구현체 내부 예외를 그대로 노출하지 말고 도메인 예외로 매핑해야 한다.

## 관련 페이지
- [[sdk-public-interface]]
- [[document-lifecycle-and-consistency]]
- [[service-health-checking]]
- [[dms-sdk]]
