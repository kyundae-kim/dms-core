---
title: SDK consumption patterns
created: 2026-06-15
updated: 2026-07-03
type: concept
tags: [sdk, integration, architecture, operations]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md, raw/articles/dms-srs-2026-06-15.md]
confidence: medium
---

# SDK consumption patterns

`docmesh-py-core`의 최신 사용 예시는 소비 프로젝트가 서비스별 초기화 코드를 제각각 작성하지 않고, 필요한 서비스만 골라 조립하는 공통 부트스트랩 흐름을 따르도록 설계되어 있다. 예제 문서 기준 핵심 순서는 환경변수 준비 → `load_service_configs(services={...})` 또는 필요한 config class 직접 생성 → 필요한 `create_*_client()` 호출 → `check()` 수행 → 종료 시 `close_service_clients()`다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 표준 사용 흐름
- 시작점은 보통 `load_service_configs(services={...})`다.
- 특정 서비스만 필요하면 `CommonConfig()`나 `KeycloakConfig()` 같은 config class를 직접 생성할 수도 있다.
- client 생성은 `create_*_client()` 함수로 일원화한다.
- startup 시점에 `check()`를 먼저 수행해 설정 오류와 실제 연결 오류를 초기에 드러낸다.
- 종료 시 `close_service_clients()`로 engine/client/dispose 처리를 한곳에 모은다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

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
- 최소 성공 예제는 PostgreSQL만 선택적으로 로드해 `postgres.check()` 후 닫는 흐름이다.
- FastAPI 예제는 startup에서 PostgreSQL/MinIO만 조립하고 shutdown에서 `close_service_clients([postgres, minio])`를 호출한다.
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
