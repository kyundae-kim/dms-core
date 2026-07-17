---
title: PostgreSQL configuration
created: 2026-06-15
updated: 2026-07-17
type: concept
tags: [postgres, database, metadata, configuration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# PostgreSQL configuration

v0.3.0 API 문서 기준으로 `POSTGRES_DSN`은 하위 호환용 deprecated 설정이며 사용 시 `DeprecationWarning`이 발생한다. 새 구성은 host/port/db/user/password 조합을 사용하며, DSN과 개별 연결 필드를 함께 설정하면 오류가 발생한다. pool, connect timeout, SSL 설정은 SQLAlchemy engine 생성 옵션에 직접 반영되며, 개별 검증은 `PostgresConfig()` 또는 선택적 config loader로도 수행할 수 있다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 핵심 환경변수
- `POSTGRES_DSN` (deprecated)
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_SSLMODE`
- `POSTGRES_CONNECT_TIMEOUT_SECONDS`
- `POSTGRES_POOL_SIZE`
- `POSTGRES_MAX_OVERFLOW`

## 운영 규칙
- 연결 문자열 원문은 로그나 예외에 그대로 남기지 않는다.
- 기본 health check는 `SELECT 1`이다.
- metadata 저장소로 쓰는 경우, 연결 실패는 문서 조회/삭제/업로드의 핵심 실패 조건으로 취급해야 한다.
- 풀 크기와 overflow는 설정 계약에 포함되며, SDK 소비자는 서비스 특성에 맞는 연결 동시성을 별도 운영 정책으로 가져가야 한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 문서 서비스 관점
이 위키의 도메인에서는 PostgreSQL이 문서 연관 metadata의 정합성과 조회 성능을 책임지는 핵심 저장소다. 따라서 deprecated DSN의 제거 계획, 풀 크기, 연결 타임아웃은 단순 설정값이 아니라 SDK 기본값과 서비스 운영 정책을 함께 결정하는 축이다.

## 관련 페이지
- [[configuration-loading-and-validation]]
- [[service-health-checking]]
- [[docmesh-py-core]]
- [[minio-configuration]]
- [[service-runtime-assembly]]
