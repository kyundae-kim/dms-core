---
title: FastAPI lifespan integration
created: 2026-06-15
updated: 2026-07-17
type: concept
tags: [integration, architecture, service, sdk]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md]
confidence: medium
---

# FastAPI lifespan integration

v0.3.0 예제 문서는 FastAPI lifespan 훅에서 `assemble_services()`로 설정 탐색, 필수 서비스 검증, client 생성, startup healthcheck를 한 번에 수행하고, context manager가 종료 cleanup을 맡기는 패턴을 제시한다. NATS 또는 async lifecycle이 필요하면 `RuntimePlan`과 `HealthcheckPolicy`를 전달한 `await assemble_service_runtime(plan=...)` 및 async context manager를 사용한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 권장 흐름
- `assemble_services(..., services={"postgres", "minio"}, required={...}, check_on_startup=True)`로 동기 의존성을 조립한다.
- `with bundle:`에서 `app.state.services`와 필요한 client를 저장한다.
- NATS를 포함하면 `async with runtime:`과 typed lookup인 `runtime.require(Service.NATS)`를 사용한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 장점
- 설정/연결 실패를 startup에서 즉시 발견할 수 있다.
- request handler가 직접 연결 생성 책임을 지지 않아도 된다.
- 종료 cleanup 위치가 명확하다.

## 문서 서비스 관점의 의미
문서 업로드/조회/삭제 API를 FastAPI로 제공한다면, MinIO와 PostgreSQL 같은 의존성 상태를 요청 처리 전에 검증할 수 있다. 또한 앱 수명주기 안에 SDK 자원 정리를 넣어 connection/resource leak 가능성을 줄일 수 있다.

## 관련 페이지
- [[sdk-consumption-patterns]]
- [[service-health-checking]]
- [[service-factory-registry]]
- [[docmesh-py-core]]
- [[service-runtime-assembly]]
- [[runtime-planning-and-environment-diagnosis]]
