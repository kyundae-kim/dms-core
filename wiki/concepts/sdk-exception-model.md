---
title: SDK exception model
created: 2026-06-15
updated: 2026-06-18
type: concept
tags: [sdk, reliability, security, integration]
sources: [raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK exception model

SDK interface 문서는 예외를 단순 런타임 오류가 아니라 비즈니스 의미를 가진 계층으로 분리한 현재 public contract를 정리한다. 2026-06-18 재-ingest 기준 문서는 `AuthenticationError`를 포함한 전체 계층과 함께, 설정 로드/조립 실패, startup health check 실패, invalid request/token/chunk size, object storage 실패, metadata backend 실패, storage-metadata 불일치까지 주요 매핑을 명시한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 왜 중요한가
- 소비 프로젝트가 오류를 유형별로 처리할 수 있다.
- 민감정보를 숨긴 채 도메인 의미를 보존할 수 있다.
- object storage 실패와 metadata 저장 실패를 다른 복구 경로로 보낼 수 있다.
- Keycloak 토큰 발급 실패와 JWT 검증 실패를 `AuthenticationError`로 분리해 인증 관련 retry/redirect 처리를 명확히 할 수 있다.

## 현재 문서가 명시하는 매핑
- 설정 로드/서비스 조립 실패 → `ConfigurationError`
- startup health check 실패 → `HealthCheckFailedError`
- invalid request/token/chunk size → `ValidationError` 또는 `AuthenticationError`
- object storage 실패 → `StorageError`
- metadata backend 실패 → `MetadataStoreError`
- storage와 metadata 불일치 → `ConsistencyError`

## 설계 시사점
- 예외 모델은 [[document-lifecycle-and-consistency]] 정책과 직접 연결된다.
- health check 실패는 단순 false 반환보다 구조화된 상태/예외 조합으로 설계할 수 있다.
- public SDK가 안정되려면 구현체 내부 예외를 그대로 노출하지 말고 도메인 예외로 매핑해야 한다.

## 관련 페이지
- [[sdk-public-interface]]
- [[document-lifecycle-and-consistency]]
- [[service-health-checking]]
- [[dms-sdk]]
