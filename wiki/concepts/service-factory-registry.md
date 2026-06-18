---
title: ServiceFactoryRegistry
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [sdk, service, integration, architecture]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md]
confidence: medium
---

# ServiceFactoryRegistry

`ServiceFactoryRegistry`는 설정 객체를 받아 서비스 이름별 클라이언트 생성 규칙을 캡슐화하는 팩토리다. PostgreSQL, MinIO, Keycloak 등 여러 백엔드를 동일한 진입점에서 다루게 해 주며, 서비스 조합이 많은 애플리케이션에서 초기화 코드를 단순화한다. SDK 가이드에서는 이 registry를 소비 프로젝트 lifecycle의 중심 진입점으로 다룬다.

## 제공 기능
- `create_client(service_name)`
- `create_clients(services)`
- `close_all()`

## 반환 모델
대부분의 서비스는 공통 인터페이스를 가진 `ServiceClientWrapper`를 반환하지만, `nats`는 예외적으로 `NatsConnectionBuilder`를 반환한다. `langfuse`는 비활성화 시 `None`일 수 있다. 이 차이는 호출부에서 서비스별 분기 또는 명시적 타입 처리를 요구한다.

## 서비스 문서화 관점의 의미
문서 저장/메타데이터 서비스가 MinIO와 PostgreSQL을 함께 사용할 경우, 이 팩토리 패턴은 클라이언트 생성 위치를 한 군데로 모으고 헬스체크/종료 규약을 재사용할 수 있게 한다. 반면 NATS처럼 비동기 연결 semantics가 다른 서비스는 동일 추상화 아래에서도 사용법 차이를 문서에 분명히 남겨야 한다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[nats-connection-builder]]
- [[sdk-consumption-patterns]]
- [[fastapi-lifespan-integration]]
