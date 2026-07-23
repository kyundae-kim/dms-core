---
title: Runtime planning and environment diagnosis
created: 2026-07-17
updated: 2026-07-21
type: concept
tags: [sdk, service, configuration, lifecycle, reliability]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-api-reference-v0-4-0.md, raw/articles/docmesh-py-core-configuration-v0-4-0.md]
confidence: medium
---

# Runtime planning and environment diagnosis

v0.5.0의 `docmesh-py-core`는 typed `Service`, `ServiceSelection`, `RuntimePlan`, `HealthcheckPolicy`를 통해 서비스 선택과 startup 정책을 표현한다. 비동기 조립 경로는 `RuntimePlan`을 받아 선택 서비스, readiness 필수성, one-of 대안 그룹, startup healthcheck와 timeout 정책을 하나의 불변 계약으로 검증한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 사전 진단

`diagnose_services()`는 client 생성이나 네트워크 연결 전에 환경과 계획을 검사해 서비스별 상태를 `absent`, `complete`, `partial`, `invalid`로 집계한다. `auto` 모드는 완전한 설정만 선택하고, `explicit`은 요청한 후보를 검사하며, `strict`은 대안 그룹에 복수의 완전한 서비스가 있으면 모호성 issue를 추가한다. `DOCMESH_ENV`가 `prod`/`production`이거나 `DOCMESH_SECURITY_MODE=production`이면 placeholder secret 또는 example/localhost endpoint와 Keycloak·MinIO·Milvus·Ollama의 transport-security 위반도 issue로 보고한다. 진단 결과는 secret 원문을 포함하지 않는 JSON-safe 구조다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 소비자 SDK에 주는 의미

문서 SDK는 PostgreSQL/SQLite 대안과 MinIO 같은 필수 의존성을 시작 전에 명시적으로 설명하고 검증할 수 있다. 이는 [[configuration-loading-and-validation]]의 환경변수 검증을 [[service-runtime-assembly]]의 lifecycle 조립과 연결하며, partial configuration을 요청 처리 시점이 아니라 부트스트랩 전에 노출하는 데 적합하다.

## 호환성 경계

v0.5.0 공개 계약은 `RuntimePlan`과 `HealthcheckPolicy`를 standard bootstrap 선택으로 제시한다. 새 코드는 선택·필수성·대안 그룹과 startup 정책을 typed plan 하나에 선언하고, 개별 client factory 경로는 CLI·배치·단일 서비스 검증처럼 lifecycle을 직접 소유해야 하는 경우로 한정해야 한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[configuration-loading-and-validation]]
- [[service-runtime-assembly]]
- [[service-health-checking]]
- [[postgres-configuration]]
- [[public-api-contract]]
