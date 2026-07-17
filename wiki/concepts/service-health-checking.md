---
title: Service health checking
created: 2026-06-15
updated: 2026-07-17
type: concept
tags: [service, reliability, observability, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md, raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# Service health checking

`docmesh-py-core`는 개별 서비스의 `check()`와 집계형 `check_all_services()`를 통해 인프라 상태 점검을 표준화한다. 문서 저장 서비스 관점에서는 MinIO 접근성, PostgreSQL 연결성, 인증 서비스 토큰 발급 가능 여부를 하나의 헬스 모델로 다루게 해 준다. 최신 API 문서는 집계 결과 타입을 `HealthCheckResult(ok, services)`와 `ServiceHealthStatus(service, ok, latency_ms, error=None)`로 명시해, 단순 성공/실패를 넘는 구조화된 상태 모델을 드러낸다.^[raw/articles/docmesh-py-core-api-v0-1-1.md] 최신 SDK interface 초안은 이 헬스 정보를 `check_health()` public method와 startup 시 필수 의존성 점검으로 연결한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

설정 문서에는 `DOCMESH_HEALTHCHECK_ENABLED`가 공통 설정값으로 정의되어 있지만, assembly API의 `check_on_startup`에 자동 연결되지는 않는다. 각 서비스는 timeout/retry를 공통값이 아니라 서비스별 환경변수로 가지며, 소비 애플리케이션이 설정값을 읽어 startup 정책을 결정한다. 운영 환경에서는 `KEYCLOAK_VERIFY_SSL`, `MINIO_SECURE`, `MILVUS_SECURE`에 대한 추가 보안 제약이 활성화된다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 개별 check 규약
`ServiceClientWrapper`는 `ping()` / `check()` / `close()`를 공통 인터페이스로 제공한다. 기본 `check()` 동작은 서비스별로 다르며, 예를 들어 PostgreSQL과 SQLite는 `SELECT 1`, MinIO는 `list_buckets()`, Keycloak은 `fetch_access_token()`을 수행한다. wrapper가 헬스체크 중 예외를 만나면 `ServiceClientWrapperError`로 변환하고 오류 메시지는 `mask_sensitive_value()`를 거쳐 마스킹한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 집계 check 규약
`check_all_services(service_checks, required_services=None)`는 서비스별 성공 여부, 지연 시간, 오류를 수집한다. 최신 API 문서 기준으로는 `parallel=True`일 때 `ThreadPoolExecutor`로 병렬 실행할 수 있지만, 반환 순서는 입력 순서를 유지한다. 필수 서비스가 실패하면 `HealthCheckError`를 발생시키므로, readiness/boot-time validation에 적합하다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

비동기 lifecycle에는 `async_check_all_services()`가 동기·awaitable check를 함께 실행하며, 개별 및 전체 timeout을 지원한다. 개별 timeout은 서비스 실패 상태로 집계되지만 전체 timeout은 부분 결과 없이 `asyncio.TimeoutError`를 직접 전파한다. optional 서비스만 실패해도 반환된 결과의 `ok`는 `False`다. `assemble_service_runtime()`은 이 healthcheck와 생성 실패 rollback을 [[runtime-planning-and-environment-diagnosis]]의 plan에 통합한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

최신 예제 문서는 FastAPI health endpoint에서 `check_all_services({...}, required_services={"postgres", "minio"}, parallel=True)`를 호출하고, 결과를 `ok`/`services[]` 구조로 직렬화하는 패턴을 보여 준다. 이는 이 헬스 모델이 내부 진단용 helper를 넘어 서비스 외부에 노출 가능한 상태 계약으로도 쓰인다는 점을 시사한다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

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
