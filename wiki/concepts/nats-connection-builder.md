---
title: NatsConnectionBuilder
created: 2026-06-15
updated: 2026-07-17
type: concept
tags: [service, integration, eventing, sdk]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md]
confidence: medium
---

# NatsConnectionBuilder

`NatsConnectionBuilder`는 NATS 연결 정보를 보관하고, 실제 연결 생성과 점검을 비동기적으로 수행하는 builder다. 최신 API 문서에서도 다른 서비스가 `ServiceClientWrapper`를 돌려주는 것과 달리, NATS는 `create_nats_client()`가 이 builder를 반환하는 예외 경로로 유지된다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 사용 규약
- `create_nats_client(config)`는 즉시 사용 가능한 동기 클라이언트를 반환하지 않는다.
- 실제 사용은 `await builder.connect()` 또는 `await builder.check()` 형태여야 한다.
- `ping()`/`check()`는 임시 연결 후 `flush()`까지 수행하고, 끝나면 연결을 정리한다.
- NATS를 다른 서비스와 함께 lifecycle로 관리해야 할 때는 `await assemble_service_runtime()`을 사용하며, 반환된 `ServiceRuntime`은 async context manager와 best-effort cleanup을 제공한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]
- 최신 예제는 `settings = load_service_configs(services={"nats"})` 후 `asyncio.run(builder.check())` 패턴을 제시한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]^[raw/articles/docmesh-py-core-examples-v0-1-4.md]
- v0.3.0 FastAPI 예제는 NATS를 SQLite와 함께 조립할 때 `RuntimePlan`과 `assemble_service_runtime(plan=...)`, `runtime.require(Service.NATS)`를 사용한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 설계 시사점
문서 저장 서비스가 이벤트 발행/비동기 후처리를 위해 NATS를 붙일 경우, PostgreSQL/MinIO와 동일한 wrapper 기반 동기 클라이언트로 오해하면 오용 가능성이 높다. 따라서 서비스 초기화 코드와 운영 문서에서 비동기 연결 semantics를 분리해 표현해야 하며, 종료 처리도 일반 `close_service_clients()` 순회와 동일하다고 가정하면 안 된다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-factory-registry]]
- [[service-health-checking]]
- [[sdk-consumption-patterns]]
- [[service-runtime-assembly]]
