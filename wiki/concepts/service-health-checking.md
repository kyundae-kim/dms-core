---
title: Service health checking
created: 2026-06-15
updated: 2026-07-21
type: concept
tags: [service, reliability, observability, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md, raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md, raw/articles/docmesh-py-core-api-reference-v0-4-0.md, raw/articles/docmesh-py-core-examples-v0-4-0.md]
confidence: medium
---

# Service health checking

`docmesh-py-core`는 개별 서비스의 `check()`와 집계형 `check_all_services()`를 통해 인프라 상태 점검을 표준화한다. 문서 저장 서비스 관점에서는 MinIO 접근성, PostgreSQL 연결성, 인증 서비스 토큰 발급 가능 여부를 하나의 헬스 모델로 다루게 해 준다. v0.5.0 예제는 필수 서비스 실패만 `HealthCheckError`로 올리고, 선택 서비스 실패는 `result.ok=False`에 남기는 구조화된 상태 모델을 명시한다.^[raw/articles/docmesh-py-core-examples-v0-4-0.md] 최신 SDK interface 초안은 이 헬스 정보를 `check_health()` public method와 startup 시 필수 의존성 점검으로 연결한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

설정 문서에는 `DOCMESH_HEALTHCHECK_ENABLED`가 공통 설정값으로 정의되어 있지만, assembly API의 `check_on_startup`에 자동 연결되지는 않는다. 각 서비스는 timeout/retry를 공통값이 아니라 서비스별 환경변수로 가지며, 소비 애플리케이션이 설정값을 읽어 startup 정책을 결정한다. 운영 환경에서는 `KEYCLOAK_VERIFY_SSL`, `MINIO_SECURE`, `MILVUS_SECURE`에 대한 추가 보안 제약이 활성화된다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 개별 check 규약
`ServiceClientWrapper`는 `ping()` / `check()` / `close()`를 공통 인터페이스로 제공한다. 기본 `check()` 동작은 서비스별로 다르며, 예를 들어 PostgreSQL과 SQLite는 `SELECT 1`, MinIO는 `list_buckets()`, Keycloak은 `fetch_access_token()`을 수행한다. wrapper가 헬스체크 중 예외를 만나면 `ServiceClientWrapperError`로 변환하고 오류 메시지는 `mask_sensitive_value()`를 거쳐 마스킹한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 집계 check 규약
`check_all_services(service_checks, required_services=None)`는 서비스별 성공 여부, 지연 시간, 오류를 수집한다. 최신 API 문서 기준으로는 `parallel=True`일 때 `ThreadPoolExecutor`로 병렬 실행할 수 있지만, 반환 순서는 입력 순서를 유지한다. 필수 서비스가 실패하면 `HealthCheckError`를 발생시키므로, readiness/boot-time validation에 적합하다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

비동기 lifecycle에는 `async_check_all_services()`가 동기·awaitable check를 함께 실행하며, 개별 및 전체 timeout을 지원한다. optional 서비스만 실패해도 반환된 결과의 `ok`는 `False`다. 종료는 동기·비동기 helper 모두 모든 client의 close를 시도한 뒤 실패를 aggregate error로 보고하며, `assemble_service_runtime()`은 이 healthcheck와 생성 실패 rollback을 [[runtime-planning-and-environment-diagnosis]]의 plan에 통합한다. v0.5.0은 모든 close 시도 후 `ServiceCloseError.failures`에 실패를 집계하는 계약을 명시한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

v0.4.0 예제는 `check_all_services()`의 `HealthCheckError`에서 상세 결과를 읽고, `close_service_clients()`의 `ServiceCloseError`에서 개별 close failure를 순회해 처리하는 패턴을 제시한다. 이는 상태와 종료 실패를 함께 관찰·기록해야 한다는 운영 규약을 구체화한다.^[raw/articles/docmesh-py-core-examples-v0-4-0.md]

## 설계 시사점
문서 CRUD 서비스에서는 조회/삭제 API가 살아 있어도 메타데이터 저장소나 인증 서비스가 깨져 있으면 실질적으로 요청 처리가 불가능할 수 있다. 따라서 집계형 헬스체크는 단순 프로세스 생존 확인보다, 핵심 의존성 상태를 반영하는 서비스 계약으로 다뤄야 한다.

DMS SRS는 이 헬스체크를 HTTP endpoint 자체보다 SDK 소비자가 호출할 수 있는 인터페이스로 규정하며, SDK interface 초안은 팩토리 초기화 시점 선제 점검과 runtime `check_health()` 반환 모델까지 요구사항을 확장한다.^[raw/articles/dms-srs-2026-06-15.md]^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[service-factory-registry]]
- [[keycloak-auth-service]]
- [[configuration-loading-and-validation]]
- [[document-lifecycle-and-consistency]]
- [[dms-sdk]]
- [[postgres-configuration]]
- [[minio-configuration]]
- [[service-runtime-assembly]]
- [[runtime-planning-and-environment-diagnosis]]
- [[public-api-contract]]
