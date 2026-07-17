---
title: SDK consumption patterns
created: 2026-06-15
updated: 2026-07-17
type: concept
tags: [sdk, integration, architecture, operations]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md, raw/articles/dms-srs-2026-06-15.md]
confidence: medium
---

# SDK consumption patterns

`docmesh-py-core`의 v0.3.0 예시는 소비 프로젝트가 서비스별 초기화 코드를 제각각 작성하지 않고 assembly-first lifecycle을 따르도록 설계되어 있다. 동기 서비스는 `assemble_services()`, NATS 또는 async lifecycle은 typed `RuntimePlan`을 전달한 `assemble_service_runtime()`으로 조립하며, direct config/factory API는 특정 SDK 제어, CLI·배치, 테스트에 한정한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 표준 사용 흐름
- 시작점은 보통 `assemble_services(..., required=..., check_on_startup=True)`다.
- NATS 또는 async health/close가 포함되면 `RuntimePlan`/`HealthcheckPolicy`와 `await assemble_service_runtime(..., plan=plan)`을 쓰며, 문자열 기반 legacy 인자는 v0.4.0 제거가 목표다.
- `one_of`로 PostgreSQL/SQLite처럼 대체 가능한 의존성 그룹을 선언할 수 있다.
- 특정 서비스만 필요하면 `load_service_configs(services={...})`와 `create_*_client()` 또는 `KeycloakConfig()` 같은 direct API를 사용할 수 있다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 어떤 프로젝트에 잘 맞는가
- FastAPI/Flask 같은 API 서버
- background worker / consumer
- 배치/CLI 작업
- PostgreSQL, SQLite, MinIO, NATS, Keycloak을 함께 쓰는 애플리케이션

## 문서 서비스 관점의 의미
문서 저장 서비스와 SDK를 함께 배포할 때, 이 패턴은 MinIO/PostgreSQL/Keycloak 같은 의존성을 통일된 lifecycle 안에서 관리하게 해 준다. 덕분에 업로드/조회/삭제 기능과 메타데이터 저장 기능을 동일한 부트스트랩 규약으로 초기화할 수 있다.

DMS SRS는 이 소비 패턴이 API 서버 내부 규약이 아니라, 다른 프로젝트가 import 하는 SDK의 공식 lifecycle 계약이어야 한다고 못박는다. 2026-06-18 갱신본은 여기에 환경 기반 factory뿐 아니라 명시적 dependency injection 조립 경로도 함께 문서화해, 테스트/내장 사용 시 registry 없이 SDK를 구성할 수 있다는 점을 제품 계약에 포함시킨다.^[raw/articles/dms-srs-2026-06-15.md]

## 추가된 소비 패턴
- 운영/통합 경로: `create_sdk(environ, logger=...)`
- 테스트/내장 조립 경로: `create_sdk(metadata_store=..., object_store=..., ...)`
- 두 경로 모두 `check_health()`와 `close()`를 동일한 facade 계약으로 노출해야 한다.

## 예제 문서가 보여 주는 최신 소비 패턴
- 최소 성공 예제는 SQLite를 `assemble_services()`로 조립하고 context manager에서 healthcheck를 수행한다.
- FastAPI 예제는 PostgreSQL/MinIO를 개별 연결 필드로 `assemble_services()`로 조립하며, NATS를 함께 쓸 때는 typed async runtime으로 전환한다.
- 부분 기능 소비 예제는 SQLite/Langfuse만 로드하고 선택되지 않은 서비스가 `None`임을 명시적으로 확인한다.
- 로깅은 `configure_logging()`를 별도로 호출하며, `DOCMESH_LOG_LEVEL`이 간접적으로 이 초기화에 영향을 준다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[configuration-loading-and-validation]]
- [[dms-sdk]]
- [[sdk-public-interface]]
- [[service-factory-registry]]
- [[service-health-checking]]
- [[fastapi-lifespan-integration]]
- [[service-runtime-assembly]]
- [[runtime-planning-and-environment-diagnosis]]
