---
title: Service health checking
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [service, reliability, observability, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# Service health checking

`docmesh-py-core`는 개별 서비스의 `check()`와 집계형 `check_all_services()`를 통해 인프라 상태 점검을 표준화한다. 문서 저장 서비스 관점에서는 MinIO 접근성, PostgreSQL 연결성, 인증 서비스 토큰 발급 가능 여부를 하나의 헬스 모델로 다루게 해 준다.

설정 문서에는 `DOCMESH_HEALTHCHECK_ENABLED`가 공통 토글로 정의되어 있으며, 각 서비스는 timeout/retry를 공통값이 아니라 서비스별 환경변수로 가진다. 따라서 헬스체크는 단순 on/off 기능이 아니라 서비스별 연결 특성을 반영하는 설정 계약과 연결된다.

## 개별 check 규약
`ServiceClientWrapper`는 `ping()` / `check()` / `close()`를 공통 인터페이스로 제공한다. 기본 `check()` 동작은 서비스별로 다르며, 예를 들어 PostgreSQL과 SQLite는 `SELECT 1`, MinIO는 `list_buckets()`, Keycloak은 `fetch_access_token()`을 수행한다.

## 집계 check 규약
`check_all_services(service_checks, required_services=None)`는 서비스별 성공 여부, 지연 시간, 오류를 수집한다. 필수 서비스가 실패하면 `HealthCheckError`를 발생시키므로, readiness/boot-time validation에 적합하다.

## 설계 시사점
문서 CRUD 서비스에서는 조회/삭제 API가 살아 있어도 메타데이터 저장소나 인증 서비스가 깨져 있으면 실질적으로 요청 처리가 불가능할 수 있다. 따라서 집계형 헬스체크는 단순 프로세스 생존 확인보다, 핵심 의존성 상태를 반영하는 서비스 계약으로 다뤄야 한다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-factory-registry]]
- [[keycloak-auth-service]]
- [[configuration-loading-and-validation]]
- [[postgres-configuration]]
- [[minio-configuration]]
