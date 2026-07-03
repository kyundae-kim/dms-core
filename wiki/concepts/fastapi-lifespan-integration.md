---
title: FastAPI lifespan integration
created: 2026-06-15
updated: 2026-07-03
type: concept
tags: [integration, architecture, service, sdk]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md]
confidence: medium
---

# FastAPI lifespan integration

최신 예제 문서는 FastAPI의 lifespan 훅에서 선택적 설정 로드, 필요한 클라이언트 생성, startup health check, 종료 시 `close_service_clients()` 호출을 수행하는 패턴을 제시한다. 이는 애플리케이션 시작 실패를 조기에 드러내고 공유 자원을 `app.state`에 모으는 구조다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 권장 흐름
- `load_service_configs(services={"postgres", "minio"})`처럼 필요한 서비스만 읽는다.
- `create_postgres_client()`와 `create_minio_client()`로 필요한 client를 만든다.
- `app.state`에는 registry 대신 실제 client와 settings를 저장한다.
- startup에서 `postgres.check()`와 `minio.check()`를 수행한다.
- 종료 시점에 `close_service_clients([postgres, minio])`를 호출한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

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
