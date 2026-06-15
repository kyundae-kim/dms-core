---
title: docmesh-py-core
created: 2026-06-15
updated: 2026-06-15
type: entity
tags: [sdk, service, client-library, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md]
confidence: medium
---

# docmesh-py-core

`docmesh-py-core`는 여러 인프라 서비스에 대한 설정 로딩, 클라이언트 생성, 헬스체크, 인증 보조 기능을 묶어 제공하는 Python SDK 코어 패키지다. 현재 API 및 설정 문서 기준으로 PostgreSQL, SQLite, MinIO, NATS, Keycloak과 같은 서비스 통합을 하나의 설정/팩토리 모델로 노출한다.

## 핵심 역할
- `load_settings()`로 환경변수 기반 설정을 일관되게 읽고 검증한다.
- `ServiceFactoryRegistry`를 통해 서비스별 클라이언트 생성 방식을 통일한다.
- `check_all_services()`와 개별 `check()` 인터페이스로 서비스 상태 점검을 표준화한다.
- `KeycloakAuthService`와 보안 유틸리티로 인증/민감정보 처리 계층을 지원한다.
- 설정은 모두 환경변수 기반이며, 서비스별 timeout/retry/security 규칙을 별도 관리한다.
- 소비 프로젝트용 표준 lifecycle은 `load_settings()` → registry 생성 → 필요한 client 생성 → `check()` → `close_all()` 흐름으로 정리된다.

## 설계 관점에서 중요한 점
- 서비스 소비자는 하위 모듈 대신 패키지 루트 import를 쓰는 것이 권장된다.
- 동기 래퍼와 비동기 builder가 혼재하므로, 특히 NATS는 일반 서비스 클라이언트와 다른 사용 규칙을 갖는다.
- 이 SDK는 문서 저장 서비스 자체 구현보다, 서비스가 MinIO/PostgreSQL/Keycloak 등을 일관되게 연결하도록 돕는 통합 레이어 성격이 강하다.
- 운영/테스트/로컬 환경 차이는 코드가 아니라 환경변수 세트로 분리하도록 설계되어 있다.
- FastAPI, worker, batch/CLI 같은 서로 다른 실행 모델에서도 같은 초기화/정리 패턴을 재사용하도록 가이드한다.

## 관련 페이지
- [[service-factory-registry]]
- [[service-health-checking]]
- [[keycloak-auth-service]]
- [[nats-connection-builder]]
- [[configuration-loading-and-validation]]
- [[sdk-consumption-patterns]]
- [[storage-backend-selection]]
- [[fastapi-lifespan-integration]]
- [[postgres-configuration]]
- [[minio-configuration]]
