---
title: Service runtime assembly
created: 2026-07-15
updated: 2026-07-17
type: concept
tags: [sdk, service, lifecycle, integration, reliability]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md]
confidence: medium
---

# Service runtime assembly

v0.3.0 API 문서는 일반 애플리케이션의 서비스 lifecycle을 개별 factory 호출보다 assembly API로 먼저 표현하도록 권장한다. 동기 서비스만 조립할 때는 `assemble_services()`를, NATS를 포함하거나 sync·async lifecycle을 함께 다뤄야 할 때는 typed `RuntimePlan`을 전달한 `await assemble_service_runtime(plan=...)`을 사용한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 조립 계약

두 API는 환경 mapping 로딩, 사용 가능한 서비스 탐지, 선택·필수성·대안 그룹 검증, client 생성, 선택적 startup healthcheck를 한 흐름에 결합한다. `ServiceBundle`은 문자열 key를 쓰는 동기 context manager이고, `ServiceRuntime`은 `Service` enum key를 쓰는 async context manager다. typed runtime에서 `require()`는 미선택과 미초기화를 서로 다른 조회 오류로 구분한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

startup healthcheck 또는 생성이 실패하면 이미 만들어진 client를 정리한 뒤 원래 예외를 다시 발생시킨다. 비동기 runtime은 종료 실패가 있어도 남은 client를 best-effort로 계속 정리한다. 이 규약은 [[service-health-checking]]의 readiness 판단과 [[nats-connection-builder]]의 비동기 연결 특성을 같은 lifecycle 경계에서 관리하게 한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## direct API와의 구분

개별 `*Config()`과 `create_*_client()` factory는 CLI, 배치, 단일 서비스 검증, SDK hook 또는 client lifecycle을 명시적으로 제어해야 하는 경우에 적합하다. 소비 애플리케이션의 기본 bootstrap 경로는 [[docmesh-py-core]]가 제공하는 assembly-first 모델이며, 새 코드는 [[runtime-planning-and-environment-diagnosis]]의 typed plan을 사용해야 한다. v0.3.0 예제는 서비스별 direct recipe에도 `try`/`finally` cleanup을 포함한다. 과거 [[service-factory-registry]] 중심 설명은 보조적인 역사적 패턴으로 취급해야 한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[nats-connection-builder]]
- [[service-factory-registry]]
- [[runtime-planning-and-environment-diagnosis]]
