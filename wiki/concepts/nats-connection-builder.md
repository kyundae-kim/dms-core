---
title: NatsConnectionBuilder
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [service, integration, eventing, sdk]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md]
confidence: medium
---

# NatsConnectionBuilder

`NatsConnectionBuilder`는 NATS 연결 정보를 보관하고, 실제 연결 생성과 점검을 비동기적으로 수행하는 builder다. 다른 서비스가 `ServiceClientWrapper`를 돌려주는 것과 달리, NATS는 연결 시점이 지연된 별도 모델을 사용한다. SDK 가이드에서도 가장 주의가 필요한 서비스로 별도 강조된다.

## 사용 규약
- `create_client("nats")`는 즉시 사용 가능한 동기 클라이언트를 반환하지 않는다.
- 실제 사용은 `await builder.connect()` 또는 `await builder.check()` 형태여야 한다.
- `check()`는 연결 후 `flush()`까지 수행한다.

## 설계 시사점
문서 저장 서비스가 이벤트 발행/비동기 후처리를 위해 NATS를 붙일 경우, PostgreSQL/MinIO와 동일한 방식으로 다루면 오용 가능성이 높다. 따라서 서비스 초기화 코드와 운영 문서에서 비동기 연결 semantics를 분리해 표현해야 한다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-factory-registry]]
- [[service-health-checking]]
- [[sdk-consumption-patterns]]
