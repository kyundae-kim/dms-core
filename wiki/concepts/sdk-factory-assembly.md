---
title: SDK factory assembly
created: 2026-06-15
updated: 2026-06-18
type: concept
tags: [sdk, integration, architecture, operations]
sources: [raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK factory assembly

SDK interface 문서는 `create_sdk(...)` 팩토리 진입점을 통해 소비 프로젝트가 초기화 세부사항을 숨길 수 있어야 한다는 점을 현재형 계약으로 정리한다. 2026-06-18 재-ingest 기준으로 이 문서는 환경 기반 경로와 explicit dependency injection 경로를 모두 first-class factory로 기술하며, `docmesh-py-core.load_settings(env)` 호출, `ServiceFactoryRegistry(settings)` 생성, metadata store와 object store 구현체 조립, startup 시 필수 의존성 health check 수행, 최종 `DocumentManagementSDK` 구현체 반환을 환경 경로의 책임으로 명시한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 왜 중요한가
- 소비 프로젝트는 SDK 사용 전에 복잡한 인프라 조립 절차를 반복할 필요가 없다.
- 운영/테스트/로컬 환경 차이를 설정으로 캡슐화할 수 있다.
- lifecycle의 시작점과 종료점이 명확해진다.
- 부트 시점 health check를 팩토리 안으로 밀어 넣으면 잘못된 설정과 실제 연결 실패를 초기화 단계에서 분리할 수 있다.

## 현재 문서가 드러내는 두 조립 경로
- 환경 기반 조립: `create_sdk(environ, logger=...)`
- 명시적 주입 조립: `create_sdk(metadata_store=..., object_store=..., auth_service=..., ...)`
- 호환 alias: `create_sdk_from_environment(env)`

## 설계 시사점
- 팩토리는 [[storage-backend-selection]] 규칙을 따라 PostgreSQL/SQLite 구현체를 선택해야 한다.
- 팩토리 결과물은 [[sdk-public-interface]]만 노출하고 내부 인프라 선택은 숨겨야 한다.
- `close()` 호출 위치와 ownership을 함께 정의해야 resource leak를 막을 수 있다.
- health check 실패 시 [[sdk-exception-model]]과 [[service-health-checking]]의 오류/상태 모델이 일관되게 맞물려야 한다.

## 관련 페이지
- [[sdk-public-interface]]
- [[sdk-consumption-patterns]]
- [[service-factory-registry]]
- [[storage-backend-selection]]
- [[service-health-checking]]
- [[sdk-exception-model]]
