---
title: SDK factory assembly
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [sdk, integration, architecture, operations]
sources: [raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK factory assembly

SDK interface 초안은 `create_sdk(env)` 같은 팩토리 진입점을 통해 소비 프로젝트가 초기화 세부사항을 숨길 수 있어야 한다고 제안한다. 이 팩토리는 `docmesh-py-core.load_settings(env)` 호출, `ServiceFactoryRegistry(settings)` 생성, metadata store와 object store 구현체 조립, 최종 `DocumentManagementSDK` 구현체 반환을 책임진다.

## 왜 중요한가
- 소비 프로젝트는 SDK 사용 전에 복잡한 인프라 조립 절차를 반복할 필요가 없다.
- 운영/테스트/로컬 환경 차이를 설정으로 캡슐화할 수 있다.
- lifecycle의 시작점과 종료점이 명확해진다.

## 설계 시사점
- 팩토리는 [[storage-backend-selection]] 규칙을 따라 PostgreSQL/SQLite 구현체를 선택해야 한다.
- 팩토리 결과물은 [[sdk-public-interface]]만 노출하고 내부 인프라 선택은 숨겨야 한다.
- `close()` 호출 위치와 ownership을 함께 정의해야 resource leak를 막을 수 있다.

## 관련 페이지
- [[sdk-public-interface]]
- [[sdk-consumption-patterns]]
- [[service-factory-registry]]
- [[storage-backend-selection]]
