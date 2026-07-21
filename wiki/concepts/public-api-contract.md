---
title: Public API contract
created: 2026-07-19
updated: 2026-07-21
type: concept
tags: [sdk, client-library, integration, lifecycle]
sources: [raw/articles/docmesh-py-core-api-reference-v0-4-0.md]
confidence: medium
---

# Public API contract

`docmesh-py-core` v0.5.0은 패키지 루트의 `__all__`을 공개 계약의 경계로 선언한다. 소비 코드는 package root에서 공개 이름을 import해야 하며, 하위 모듈의 비공개 심볼을 신규 코드의 의존 대상으로 삼지 않는다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 계약의 구성

공개 surface는 환경 기반 설정·진단, `RuntimePlan` 기반 서비스 선택, async/sync runtime 조립, 서비스별 client factory, healthcheck·종료, Keycloak 인증·provisioning, 구조화 오류 및 secret-safe 유틸리티를 포함한다. v0.5.0 inventory는 이 계약을 86개 package-root 이름으로 검증한다. 이 구성은 [[service-runtime-assembly]]가 lifecycle을 소유하고 [[runtime-planning-and-environment-diagnosis]]가 연결 전 설정 적합성을 판별하는 역할 분리를 명확히 한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 소비자 SDK에 주는 의미

DMS 같은 소비 SDK는 upstream 내부 모듈이 아니라 안정적인 root export에만 결합해야 한다. 서비스 bootstrap에는 `RuntimePlan`과 async assembly를 우선 적용하고, CLI·배치·단일 서비스 검증 같은 제한된 경우에만 direct config/factory API를 사용한다. 오류·logging·masking 계약은 [[service-health-checking]] 및 [[sdk-consumption-patterns]]에서 다루는 운영 경로에도 함께 적용된다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[service-runtime-assembly]]
- [[runtime-planning-and-environment-diagnosis]]
- [[service-health-checking]]
- [[sdk-consumption-patterns]]
