---
title: Configuration loading and validation
created: 2026-06-15
updated: 2026-07-03
type: concept
tags: [sdk, configuration, integration, security]
sources: [raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-examples-v0-1-4.md]
confidence: medium
---

# Configuration loading and validation

`docmesh-py-core`의 설정 모델은 모든 외부 서비스 연결 정보를 환경변수로만 읽고, 애플리케이션 시작 시 1회 로드 및 검증하는 원칙을 따른다. 최신 설정 문서는 서비스별 config class 직접 생성과 `load_service_configs(services={...})` 기반 선택적 검증을 공개 계약으로 강조한다. 이는 서비스 코드와 배포 환경을 분리하고, 문서 저장 서비스와 SDK 배포 시 환경별 차이를 설정만으로 흡수하려는 설계다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 핵심 원칙
- URL, 계정, 비밀번호, 토큰, secret key를 코드에 하드코딩하지 않는다.
- 공백 문자열은 미입력으로 간주한다.
- boolean과 숫자형 값은 파싱뿐 아니라 의미 있는 검증 규칙까지 가진다.
- timeout/retry/pool은 공통값 대신 서비스별 환경변수로 분리한다.
- `load_service_configs()` 경로의 검증 오류는 `ConfigError`로 래핑된다.
- production/prod 환경에서는 `validate_runtime_security()`가 Keycloak/MinIO/Milvus 보안 제약을 추가 검사한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 운영 관점의 의미
이 설계는 MinIO, PostgreSQL, Keycloak 같은 핵심 의존성과 Langfuse 같은 선택 기능을 서로 다른 실패 도메인으로 관리하기 쉽게 만든다. 또한 integration 테스트를 운영 환경과 분리된 환경 식별자와 secret 세트로 관리하도록 유도한다. 최신 문서는 `DOCMESH_LOG_LEVEL`이 `CommonConfig` 필드가 아니라 `configure_logging()` 전용 환경변수라는 점도 분리해 설명한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

예제 문서는 이 선택적 로딩 모델이 실제로 어떻게 쓰이는지도 보강한다. 예를 들어 PostgreSQL만 필요한 최소 예제, SQLite/Langfuse만 필요한 부분 기능 예제, NATS만 필요한 비동기 예제가 모두 `services={...}` 기반으로 분기된다.^[raw/articles/docmesh-py-core-examples-v0-1-4.md]

## 서비스 설계 시사점
문서 CRUD 서비스와 SDK를 함께 배포할 때, 설정 로딩과 검증은 단순 부트스트랩 코드가 아니라 서비스 계약의 일부다. 잘못된 설정을 요청 처리 중 늦게 발견하기보다, 시작 시 명확한 `ConfigError`로 중단시키는 쪽이 운영 안정성에 유리하다. 특히 최신 공개 계약은 전체 aggregate 설정을 항상 읽는 방식보다, 필요한 서비스만 선택적으로 검증하는 패턴을 우선시하므로 소비 프로젝트도 의존 서비스 집합을 더 명시적으로 표현해야 한다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[postgres-configuration]]
- [[minio-configuration]]
- [[keycloak-auth-service]]
- [[sdk-consumption-patterns]]
