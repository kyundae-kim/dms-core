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

SDK factory는 소비 프로젝트가 생성한 인프라 client 또는 저장소 구현을 DMS SDK에 연결한다. 환경변수 해석과 설정 묶음에 따른 client 생성은 호스트 애플리케이션이 담당하며, DMS는 전달받은 자원의 소유권과 lifecycle 규칙을 명시적으로 적용한다.

## 왜 중요한가
- 소비 프로젝트는 자체 설정 체계로 인프라 client 생성 방식을 통제할 수 있다.
- 운영/테스트/로컬 환경 차이가 DMS SDK의 생성 API에 결합되지 않는다.
- lifecycle의 시작점과 종료점이 명확해진다.
- 부트 시점 health check를 팩토리 안으로 밀어 넣으면 잘못된 설정과 실제 연결 실패를 초기화 단계에서 분리할 수 있다.

## 현재 조립 경로
- client 기반 조립: 호출자 소유 SQLAlchemy Engine과 MinIO client를 adapter로 연결하는 `DocumentManagementSDKFactory` 또는 `create_sdk_from_clients(...)`
- 명시적 주입 조립: `create_sdk_from_components(metadata_store=..., object_store=..., ...)`

## 설계 시사점
- 팩토리는 [[storage-backend-selection]] 규칙을 따라 PostgreSQL/SQLite 구현체를 선택해야 한다.
- 환경변수 해석과 client 생성 실패는 호스트 애플리케이션이 책임진다.
- 팩토리 결과물은 [[sdk-public-interface]]만 노출하고 내부 인프라 선택은 숨겨야 한다.
- `close()` 호출 위치와 ownership을 함께 정의해야 resource leak를 막을 수 있다.
- client 기반 조립의 주입 자원은 호출자가 소유하며, SDK는 주입된 client를 자동으로 종료하지 않는다.
- client factory callable은 별도로 받지 않고 호출자가 생성한 client를 주입하도록 하여 생성 시점과 실패 책임을 명확히 한다.
- health check 실패 시 [[sdk-exception-model]]과 [[service-health-checking]]의 오류/상태 모델이 일관되게 맞물려야 한다.

## 관련 페이지
- [[sdk-public-interface]]
- [[sdk-consumption-patterns]]
- [[service-factory-registry]]
- [[storage-backend-selection]]
- [[service-health-checking]]
- [[sdk-exception-model]]
