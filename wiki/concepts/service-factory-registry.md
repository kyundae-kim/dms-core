---
title: ServiceFactoryRegistry
created: 2026-06-15
updated: 2026-07-15
type: concept
tags: [sdk, service, integration, architecture]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md]
confidence: medium
---

# ServiceFactoryRegistry

`ServiceFactoryRegistry`는 설정 객체를 받아 서비스 이름별 클라이언트 생성 규칙을 캡슐화하는 과거 문서 중심 팩토리 패턴이다. v0.2.0의 공개 API 목록에는 이 registry가 없고, 일반 애플리케이션에는 `assemble_services()` 또는 `assemble_service_runtime()`을, 직접 제어가 필요한 경우에는 서비스별 `create_*_client()` 함수를 권장한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 제공 기능
- `create_client(service_name)`
- `create_clients(services)`
- `close_all()`

## 반환 모델
대부분의 서비스는 공통 인터페이스를 가진 `ServiceClientWrapper`를 반환하지만, `nats`는 예외적으로 `NatsConnectionBuilder`를 반환한다. `langfuse`는 비활성화 시 `None`일 수 있다. 최신 API 문서에서는 이 차이를 registry가 아니라 각 `create_*_client()` 함수의 반환 계약으로 직접 문서화한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 서비스 문서화 관점의 의미
문서 저장/메타데이터 서비스가 MinIO와 PostgreSQL을 함께 사용할 경우, 이 팩토리 패턴은 클라이언트 생성 위치를 한 군데로 모으고 헬스체크/종료 규약을 재사용할 수 있게 한다. 다만 현재 공개 계약을 따르는 소비 프로젝트라면 registry 존재 자체를 전제로 문서를 쓰기보다, 서비스별 생성 함수와 선택적 서비스 집합(`services={...}`) 조립 패턴을 우선 설명해야 한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[nats-connection-builder]]
- [[sdk-consumption-patterns]]
- [[fastapi-lifespan-integration]]
- [[service-runtime-assembly]]
