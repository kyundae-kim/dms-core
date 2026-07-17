---
title: Runtime planning and environment diagnosis
created: 2026-07-17
updated: 2026-07-17
type: concept
tags: [sdk, service, configuration, lifecycle, reliability]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# Runtime planning and environment diagnosis

v0.3.0의 `docmesh-py-core`는 문자열 기반 서비스 선택을 typed `Service`, `ServiceSelection`, `RuntimePlan`, `HealthcheckPolicy`로 대체하는 방향을 제시한다. 새 비동기 조립 경로는 `RuntimePlan`을 받아 선택 서비스, readiness 필수성, one-of 대안 그룹, startup healthcheck와 timeout 정책을 하나의 불변 계약으로 검증한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 사전 진단

`diagnose_services()`는 client 생성이나 네트워크 연결 전에 환경과 계획을 검사해 서비스별 상태를 `absent`, `complete`, `partial`, `invalid`로 집계한다. `auto` 모드는 완전한 설정만 선택하고, `explicit`은 요청한 후보를 검사하며, `strict`은 대안 그룹에 복수의 완전한 서비스가 있으면 모호성 issue를 추가한다. production 환경에서는 placeholder secret 또는 example/localhost endpoint도 issue로 보고한다. 진단 결과는 secret 원문을 포함하지 않는 JSON-safe 구조다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 소비자 SDK에 주는 의미

문서 SDK는 PostgreSQL/SQLite 대안과 MinIO 같은 필수 의존성을 시작 전에 명시적으로 설명하고 검증할 수 있다. 이는 [[configuration-loading-and-validation]]의 환경변수 검증을 [[service-runtime-assembly]]의 lifecycle 조립과 연결하며, partial configuration을 요청 처리 시점이 아니라 부트스트랩 전에 노출하는 데 적합하다.

## 호환성 경계

기존 `services`, `required`, `one_of` 및 개별 health 인자는 호환성을 위해 유지되지만 deprecated이며, `assemble_service_runtime()` 및 `diagnose_services()`에서는 v0.4.0 제거가 목표다. 새 코드에서는 legacy 인자와 `plan=`을 섞지 않고 typed plan을 단일 정책 원천으로 사용해야 한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[configuration-loading-and-validation]]
- [[service-runtime-assembly]]
- [[service-health-checking]]
- [[postgres-configuration]]
