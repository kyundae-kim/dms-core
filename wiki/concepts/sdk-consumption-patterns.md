---
title: SDK consumption patterns
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [sdk, integration, architecture, operations]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/dms-srs-2026-06-15.md]
confidence: medium
---

# SDK consumption patterns

`docmesh-py-core`의 SDK 사용 가이드는 소비 프로젝트가 서비스별 초기화 코드를 제각각 작성하지 않고, 공통 부트스트랩 흐름을 따르도록 설계되어 있다. 핵심 순서는 환경변수 준비 → `load_settings()` → `ServiceFactoryRegistry(settings)` → 필요한 client 생성 → `check()` 수행 → 종료 시 `close_all()`이다.

## 표준 사용 흐름
- 시작점은 항상 `load_settings()`다.
- client 생성은 `ServiceFactoryRegistry`를 통해 일원화한다.
- startup 시점에 `check()`를 먼저 수행해 설정 오류와 실제 연결 오류를 초기에 드러낸다.
- 종료 시 `registry.close_all()`로 engine/client/dispose 처리를 한곳에 모은다.

## 어떤 프로젝트에 잘 맞는가
- FastAPI/Flask 같은 API 서버
- background worker / consumer
- 배치/CLI 작업
- PostgreSQL, SQLite, MinIO, NATS, Keycloak을 함께 쓰는 애플리케이션

## 문서 서비스 관점의 의미
문서 저장 서비스와 SDK를 함께 배포할 때, 이 패턴은 MinIO/PostgreSQL/Keycloak 같은 의존성을 통일된 lifecycle 안에서 관리하게 해 준다. 덕분에 업로드/조회/삭제 기능과 메타데이터 저장 기능을 동일한 부트스트랩 규약으로 초기화할 수 있다.

DMS SRS는 이 소비 패턴이 API 서버 내부 규약이 아니라, 다른 프로젝트가 import 하는 SDK의 공식 lifecycle 계약이어야 한다고 못박는다.^[raw/articles/dms-srs-2026-06-15.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[configuration-loading-and-validation]]
- [[dms-sdk]]
- [[sdk-public-interface]]
- [[service-factory-registry]]
- [[service-health-checking]]
- [[fastapi-lifespan-integration]]
