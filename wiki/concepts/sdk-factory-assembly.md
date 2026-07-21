---
title: SDK factory assembly
created: 2026-06-15
updated: 2026-07-19
type: concept
tags: [sdk, integration, architecture, operations]
sources: [raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# SDK factory assembly

SDK factory는 소비 프로젝트에서 인프라 초기화 세부사항을 숨긴다. 현재 환경 기반 경로는 docmesh-py-core v0.4.0의 `assemble_services()`로 설정 로딩, 서비스 요구사항 검증, client 생성, startup health check와 실패 rollback을 수행한다. DMS는 반환된 `ServiceBundle`의 client를 metadata/object adapter로 연결하고 SDK 종료 시 bundle을 닫는다.

## 왜 중요한가
- 소비 프로젝트는 SDK 사용 전에 복잡한 인프라 조립 절차를 반복할 필요가 없다.
- 운영/테스트/로컬 환경 차이를 설정으로 캡슐화할 수 있다.
- lifecycle의 시작점과 종료점이 명확해진다.
- 부트 시점 health check를 팩토리 안으로 밀어 넣으면 잘못된 설정과 실제 연결 실패를 초기화 단계에서 분리할 수 있다.

## 현재 조립 경로
- 환경 기반 조립: 프로세스 환경을 사용하는 `create_sdk_from_environment(logger=...)`
- 설정 묶음 기반 조립: 검증된 서비스 설정으로 client를 생성하는 `create_sdk_from_service_configs(configs, ...)`
- client 기반 조립: 호출자 소유 SQLAlchemy Engine과 MinIO client를 adapter로 연결하는 `create_sdk_from_clients(...)`
- 명시적 주입 조립: `create_sdk_from_components(metadata_store=..., object_store=..., ...)`
- 사전 진단: 연결 없이 별도 mapping을 검사하는 `diagnose_environment(env)`

## 설계 시사점
- 팩토리는 [[storage-backend-selection]] 규칙을 따라 PostgreSQL/SQLite 구현체를 선택해야 한다.
- 환경 기반 팩토리를 호출하기 전에 프로세스 환경을 확정해야 하며 호출 중 관련 환경변수를 변경하지 않아야 한다.
- 팩토리 결과물은 [[sdk-public-interface]]만 노출하고 내부 인프라 선택은 숨겨야 한다.
- `close()` 호출 위치와 ownership을 함께 정의해야 resource leak를 막을 수 있다.
- client 기반 조립의 주입 자원은 기본적으로 호출자가 소유하며, 명시적으로 전달한 정리 callback만 SDK 종료 시 실행한다.
- client factory callable은 별도로 받지 않고 호출자가 생성한 client를 주입하도록 하여 생성 시점과 실패 책임을 명확히 한다.
- health check 실패 시 [[sdk-exception-model]]과 [[service-health-checking]]의 오류/상태 모델이 일관되게 맞물려야 한다.

## 관련 페이지
- [[sdk-public-interface]]
- [[sdk-consumption-patterns]]
- [[service-factory-registry]]
- [[storage-backend-selection]]
- [[service-health-checking]]
- [[sdk-exception-model]]
