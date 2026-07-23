---
title: docmesh-py-core
created: 2026-06-15
updated: 2026-07-21
type: entity
tags: [sdk, service, client-library, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md, raw/articles/docmesh-py-core-api-reference-v0-4-0.md, raw/articles/docmesh-py-core-configuration-v0-4-0.md, raw/articles/docmesh-py-core-examples-v0-4-0.md]
confidence: medium
---

# docmesh-py-core

`docmesh-py-core`는 여러 인프라 서비스에 대한 설정 검증, 클라이언트 생성, 헬스체크, 인증 보조 기능을 묶어 제공하는 Python SDK 코어 패키지다. v0.5.0 공개 API는 PostgreSQL, SQLite, MinIO, NATS, Keycloak, Milvus, Ollama, Langfuse 통합을 package root export로 제공하고, 일반 애플리케이션에는 typed `RuntimePlan`을 사용하는 비동기 `assemble_service_runtime()` 중심 lifecycle을 우선 안내한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 핵심 역할
- `CommonConfig()` 및 서비스별 `*Config()` 또는 `load_service_configs()`로 환경변수 기반 설정을 읽고 검증한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]^[raw/articles/docmesh-py-core-config-v0-1-1.md]
- `create_postgres_client()`, `create_minio_client()`, `create_nats_client()` 같은 서비스별 생성 함수로 클라이언트 조립 방식을 통일한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]
- `check_all_services()`와 개별 `check()` 인터페이스로 서비스 상태 점검을 표준화한다.
- `KeycloakAuthService`와 보안 유틸리티로 인증/민감정보 처리 계층을 지원한다.
- 설정은 모두 프로세스 환경변수 기반이며, 서비스별 timeout/retry/security 규칙을 별도 관리한다. `DOCMESH_ENV`가 `prod`/`production`이거나 `DOCMESH_SECURITY_MODE=production`이면 Keycloak, MinIO, Milvus, Ollama의 transport security와 placeholder 값 검증이 적용된다. `DOCMESH_LOG_LEVEL`처럼 공통 config 객체가 아니라 로깅 초기화 함수가 직접 읽는 환경변수도 존재한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]
- 소비 프로젝트용 최신 public lifecycle은 설정 mapping 준비 → `RuntimePlan`과 `HealthcheckPolicy` 선언 → `await assemble_service_runtime(plan=...)` → async context manager 기반 종료 흐름으로 정리된다. 현재 v0.5.0 공개 레퍼런스는 typed plan 경로를 standard bootstrap으로 제시하며, 개별 config와 `create_*_client()`는 CLI, 배치, 단일 서비스 시험 또는 SDK lifecycle 직접 제어에 적합한 direct API다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

## 설계 관점에서 중요한 점
- 공개 API는 패키지 루트의 `__all__`로 한정되며, 구현 모듈의 비공개 심볼은 신규 소비 코드의 import 대상이 아니다. `Service`, `RuntimePlan`, `HealthcheckPolicy`, `SERVICE_CATALOG`, `diagnose_services()`와 구조화된 오류 taxonomy는 typed runtime 계획과 사전 환경 진단을 명시한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]
- 동기 래퍼와 비동기 builder가 혼재하므로, 특히 NATS는 일반 서비스 클라이언트와 다른 사용 규칙을 갖는다.
- 이 SDK는 문서 저장 서비스 자체 구현보다, 서비스가 MinIO/PostgreSQL/Keycloak 등을 일관되게 연결하도록 돕는 통합 레이어 성격이 강하다.
- 운영/테스트/로컬 환경 차이는 코드가 아니라 환경변수 세트로 분리하도록 설계되어 있으며, production/prod 환경에서는 `validate_runtime_security()`가 Keycloak/MinIO/Milvus 보안 제약을 추가로 검사한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]
- FastAPI, worker, batch/CLI 같은 서로 다른 실행 모델에서도 같은 초기화/정리 패턴을 재사용하도록 가이드한다.
- v0.5.0 예제는 SQLite 최소 runtime, production/authenticated preset, NATS의 임시 검사·지속 연결 소유권, Keycloak provisioning, 선택적 MinIO bucket, 필수·선택 healthcheck, masking/retry/logging 및 오류 처리를 함께 제시한다.^[raw/articles/docmesh-py-core-examples-v0-4-0.md]

## 관련 페이지
- [[service-factory-registry]]
- [[service-health-checking]]
- [[service-runtime-assembly]]
- [[runtime-planning-and-environment-diagnosis]]
- [[keycloak-auth-service]]
- [[nats-connection-builder]]
- [[configuration-loading-and-validation]]
- [[sdk-consumption-patterns]]
- [[storage-backend-selection]]
- [[fastapi-lifespan-integration]]
- [[postgres-configuration]]
- [[public-api-contract]]
- [[minio-configuration]]
