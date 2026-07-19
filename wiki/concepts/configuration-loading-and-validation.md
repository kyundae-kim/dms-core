---
title: Configuration loading and validation
created: 2026-06-15
updated: 2026-07-19
type: concept
tags: [sdk, configuration, integration, security]
sources: [raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-env-example.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md, raw/articles/docmesh-py-core-configuration-v0-4-0.md]
confidence: medium
---

# Configuration loading and validation

`docmesh-py-core`의 설정 모델은 모든 외부 서비스 연결 정보를 프로세스 환경변수로만 읽고 검증하며, 생성자 인자 주입은 허용하지 않는다. v0.4.0 Configuration Guide는 일반 애플리케이션 lifecycle에 typed `RuntimePlan`을 쓰는 `assemble_service_runtime()`을 우선 안내하고, 서비스별 config class와 `create_*_client()`는 CLI·배치·테스트·확장 hook 제어 같은 direct API 필요 시점에 사용하도록 구분한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

v0.2.0 `.env.example`은 공통 설정과 Keycloak, PostgreSQL, SQLite, MinIO, Milvus, Ollama, Langfuse, NATS의 전체 환경변수 골격을 placeholder로 제공한다. 이 파일은 배포 템플릿이며 실제 secret을 저장소에 기록하지 않는다는 원칙을 명시한다.^[raw/articles/docmesh-py-core-env-example.md]

## 핵심 원칙
- URL, 계정, 비밀번호, 토큰, secret key를 코드에 하드코딩하지 않는다.
- 공백 문자열은 미입력으로 간주한다.
- boolean·숫자형 값은 Pydantic coercion으로 파싱하고, timeout·pool·retry 값은 의미 있는 범위까지 검증한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]
- timeout/retry/pool은 공통값 대신 서비스별 환경변수로 분리한다.
- `load_service_configs()` 경로의 검증 오류는 `ConfigError`로 래핑된다.
- `load_available_service_configs()`는 관련 prefix가 있는 후보만 실제 validation하고, 부분 설정은 오류로 처리한다.
- `DOCMESH_HEALTHCHECK_ENABLED`는 설정값만 제공하며 startup healthcheck를 자동 활성화하지 않는다. 소비자가 이를 읽어 assembly API의 `HealthcheckPolicy`를 정한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]
- `DOCMESH_ENV`가 `prod`/`production`이거나 `DOCMESH_SECURITY_MODE=production`이면 Keycloak/MinIO/Milvus의 TLS와 placeholder secret·endpoint 제약을 추가 검사한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 운영 관점의 의미
이 설계는 MinIO, PostgreSQL, Keycloak 같은 핵심 의존성과 Langfuse 같은 선택 기능을 서로 다른 실패 도메인으로 관리하기 쉽게 만든다. 또한 integration 테스트를 운영 환경과 분리된 환경 식별자와 secret 세트로 관리하도록 유도한다. 최신 문서는 `DOCMESH_LOG_LEVEL`이 `CommonConfig` 필드가 아니라 `configure_logging()` 전용 환경변수라는 점도 분리해 설명한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

예제 문서는 이 선택적 로딩 모델이 실제로 어떻게 쓰이는지도 보강한다. 예를 들어 PostgreSQL만 필요한 최소 예제, SQLite/Langfuse만 필요한 부분 기능 예제, NATS만 필요한 비동기 예제가 모두 `services={...}` 기반으로 분기된다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 서비스 설계 시사점
문서 CRUD 서비스와 SDK를 함께 배포할 때, 설정 로딩과 검증은 단순 부트스트랩 코드가 아니라 서비스 계약의 일부다. `diagnose_services(plan=...)`는 client 생성 전 partial/invalid 설정을 한 번에 집계하고 secret 원문 없이 JSON-safe 결과를 제공하므로 CI/CD와 deployment preflight에 적합하다. 필요한 서비스, 대안 그룹, startup check 정책은 [[runtime-planning-and-environment-diagnosis]]의 typed plan으로 명시해야 한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[postgres-configuration]]
- [[minio-configuration]]
- [[keycloak-auth-service]]
- [[sdk-consumption-patterns]]
- [[service-runtime-assembly]]
- [[runtime-planning-and-environment-diagnosis]]
