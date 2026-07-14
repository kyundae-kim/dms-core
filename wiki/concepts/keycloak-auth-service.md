---
title: KeycloakAuthService
created: 2026-06-15
updated: 2026-07-15
type: concept
tags: [auth, service, security, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# KeycloakAuthService

`KeycloakAuthService`는 Keycloak 기반 access token 발급과 JWT 검증을 담당하는 인증 통합 계층이다. 최신 API 문서에서는 `KeycloakConfig`를 받아 동작하며, 문서 서비스에서 사용자 인증/권한 판별을 SDK 레벨에서 보조한다. 토큰 발급 실패와 검증 실패는 여전히 구분된 예외 체계로 노출된다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

설정 문서 기준으로는 `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`가 기본 축이며, `client_credentials`가 기본 grant다. v0.2.0 API 문서에서 password grant는 함수 인자를 우선 사용하되, 생략한 `username`/`password`는 `KeycloakConfig.token_username`과 `token_password`에서 보완한다. 두 입력 경로를 합쳐도 자격증명이 완전하지 않으면 `KeycloakTokenConfigurationError`가 발생한다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 핵심 API
- `fetch_access_token(scope=None) -> AccessTokenResult`
- `extract_user_info(token) -> AuthenticatedUser`

최신 구현 노트:
- `extract_user_info()`는 `Bearer <jwt>` 형식과 raw JWT 문자열을 모두 받는다.
- `HS256`/`RS256` 검증 경로를 모두 지원하며, RS256은 JWKS 캐시 TTL을 사용한다.
- `audience` 설정이 없으면 audience 검증을 비활성화한다.
- 운영 환경에서는 `KEYCLOAK_VERIFY_SSL=false`를 허용하지 않으며, `KEYCLOAK_JWKS_CACHE_TTL_SECONDS` 기본값은 300초다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 예외 모델
토큰 요청 과정에서는 `KeycloakTokenConfigurationError`, `KeycloakTokenAuthenticationError`, `KeycloakTokenTemporaryError`, `KeycloakTokenError`가 대표 예외다. JWT 해석/검증 실패는 `TokenValidationError`로 보고된다. 일시적 장애는 `config.max_retries + 1`회까지 재시도되며, 재시도 이벤트는 구조화 로그로 남는다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 서비스 설계 관점
문서 업로드/조회/삭제 서비스가 외부 Keycloak에 의존한다면, 토큰 발급과 사용자 정보 추출 규약은 API 게이트웨이 또는 애플리케이션 미들웨어 설계에 직접 연결된다. 특히 헬스체크가 `fetch_access_token()`을 사용하므로 인증 서버 상태는 서비스 준비 상태 판단에도 영향을 준다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[service-factory-registry]]
- [[configuration-loading-and-validation]]
