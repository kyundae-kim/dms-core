---
title: Configuration loading and validation
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [sdk, configuration, integration, security]
sources: [raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-sdk-v0-1-1.md]
confidence: medium
---

# Configuration loading and validation

`docmesh-py-core`의 설정 모델은 모든 외부 서비스 연결 정보를 환경변수로만 읽고, 애플리케이션 시작 시 1회 로드 및 검증하는 원칙을 따른다. 이는 서비스 코드와 배포 환경을 분리하고, 문서 저장 서비스와 SDK 배포 시 환경별 차이를 설정만으로 흡수하려는 설계다. SDK 사용 가이드는 이 설정 로드를 전체 lifecycle의 첫 단계로 고정한다.

## 핵심 원칙
- URL, 계정, 비밀번호, 토큰, secret key를 코드에 하드코딩하지 않는다.
- 공백 문자열은 미입력으로 간주한다.
- boolean과 숫자형 값은 파싱뿐 아니라 의미 있는 검증 규칙까지 가진다.
- timeout/retry/pool은 공통값 대신 서비스별 환경변수로 분리한다.

## 운영 관점의 의미
이 설계는 MinIO, PostgreSQL, Keycloak 같은 핵심 의존성과 Langfuse 같은 선택 기능을 서로 다른 실패 도메인으로 관리하기 쉽게 만든다. 또한 integration 테스트를 운영 환경과 분리된 `.env.integration` 또는 CI secret 세트로 관리하도록 유도한다.

## 서비스 설계 시사점
문서 CRUD 서비스와 SDK를 함께 배포할 때, 설정 로딩과 검증은 단순 부트스트랩 코드가 아니라 서비스 계약의 일부다. 잘못된 설정을 요청 처리 중 늦게 발견하기보다, 시작 시 명확한 `ConfigError`로 중단시키는 쪽이 운영 안정성에 유리하다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[postgres-configuration]]
- [[minio-configuration]]
- [[keycloak-auth-service]]
- [[sdk-consumption-patterns]]
