---
title: FastAPI lifespan integration
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [integration, architecture, service, sdk]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md]
confidence: medium
---

# FastAPI lifespan integration

SDK 가이드는 FastAPI의 lifespan 훅에서 설정 로드, registry 생성, 선택적 health check, 종료 시 `close_all()` 호출을 수행하는 패턴을 제시한다. 이는 애플리케이션 시작 실패를 조기에 드러내고 공유 자원을 `app.state`에 모으는 구조다.

## 권장 흐름
- `load_settings(environ)`으로 시작 시점에 설정을 읽는다.
- `ServiceFactoryRegistry(settings)`를 생성한다.
- 실제 활성화된 저장소(`settings.postgres`, `settings.sqlite`)에 대해서만 client를 만들고 `check()`를 수행한다.
- `settings`와 `registry`를 `app.state`에 저장한다.
- 종료 시점에 `registry.close_all()`을 호출한다.

## 장점
- 설정/연결 실패를 startup에서 즉시 발견할 수 있다.
- request handler가 직접 연결 생성 책임을 지지 않아도 된다.
- 종료 cleanup 위치가 명확하다.

## 문서 서비스 관점의 의미
문서 업로드/조회/삭제 API를 FastAPI로 제공한다면, MinIO와 PostgreSQL 같은 의존성 상태를 요청 처리 전에 검증할 수 있다. 또한 앱 수명주기 안에 SDK 자원 정리를 넣어 connection/resource leak 가능성을 줄일 수 있다.

## 관련 페이지
- [[sdk-consumption-patterns]]
- [[service-health-checking]]
- [[service-factory-registry]]
- [[docmesh-py-core]]
