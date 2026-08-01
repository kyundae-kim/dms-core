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

현재 DMS API reference는 예외를 단순 런타임 오류가 아니라 운영·복구 의미를 가진 계층으로 분리한다. 설정/조립, validation, access, payload size, not found/deleted, duplicate/idempotency, object/metadata store, consistency/reset, cleanup, health failure와 transport-neutral HTTP projection을 공개 계약으로 추적한다. 인증 오류 계층은 DMS 공개 범위가 아니다.

## 왜 중요한가
- 소비 프로젝트가 오류를 유형별로 처리할 수 있다.
- 민감정보를 숨긴 채 도메인 의미를 보존할 수 있다.
- object storage 실패와 metadata 저장 실패를 다른 복구 경로로 보낼 수 있다.
- 오류마다 안정적인 `code`, `category`, `retryable`을 사용해 host가 재시도·복구·외부 응답을 분리할 수 있다.

## 현재 문서가 명시하는 매핑
- 설정 로드/서비스 조립 실패 → `ConfigurationError`
- startup health check 실패 → `HealthCheckFailedError`
- invalid request/cursor/chunk size → `ValidationError`
- oversized payload → `PayloadTooLargeError`
- access policy 거부 → `AccessDeniedError`
- idempotency 충돌/진행 중 → `IdempotencyConflictError` 또는 `IdempotencyInProgressError`
- object storage 실패 → `StorageError`
- metadata backend 실패 → `MetadataStoreError`
- storage와 metadata 불일치 → `ConsistencyError`
- 전체 reset 부분 실패 → `DataResetError`

## 설계 시사점
- 예외 모델은 [[document-lifecycle-and-consistency]] 정책과 직접 연결된다.
- health check 실패는 단순 false 반환보다 구조화된 상태/예외 조합으로 설계할 수 있다.
- public SDK가 안정되려면 구현체 내부 예외를 그대로 노출하지 말고 도메인 예외로 매핑해야 한다.

## 관련 페이지
- [[sdk-public-interface]]
- [[document-lifecycle-and-consistency]]
- [[service-health-checking]]
- [[dms-sdk]]
