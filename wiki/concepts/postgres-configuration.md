---
title: PostgreSQL configuration
created: 2026-06-15
updated: 2026-07-03
type: concept
tags: [postgres, database, metadata, configuration]
sources: [raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# PostgreSQL configuration

`docmesh-py-core`는 PostgreSQL 연결 구성을 DSN 우선 모델로 정의한다. `POSTGRES_DSN`이 있으면 개별 host/port/db/user/password보다 우선하며, DSN 미사용 시에는 연결 구성요소를 모두 채워야 한다. 최신 설정 문서는 이 규칙이 여전히 유지된다고 확인하면서도, 검증 진입점이 `PostgresConfig()` 직접 생성 또는 `load_service_configs(services={"postgres"})`처럼 더 선택적인 경로로 설명된다는 점을 보강한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 핵심 환경변수
- `POSTGRES_DSN`
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
이 위키의 도메인에서는 PostgreSQL이 문서 연관 metadata의 정합성과 조회 성능을 책임지는 핵심 저장소다. 따라서 DSN 우선 규칙, 풀 크기, 연결 타임아웃은 단순 설정값이 아니라 SDK 기본값과 서비스 운영 정책을 함께 결정하는 축이다.

## 관련 페이지
- [[configuration-loading-and-validation]]
- [[service-health-checking]]
- [[docmesh-py-core]]
- [[minio-configuration]]
