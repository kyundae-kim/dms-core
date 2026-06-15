---
title: KeycloakAuthService
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [auth, service, security, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# KeycloakAuthService

`KeycloakAuthService`는 Keycloak 기반 access token 발급과 JWT 검증을 담당하는 인증 통합 계층이다. 문서 서비스에서 사용자 인증/권한 판별을 SDK 레벨에서 보조하며, 토큰 발급 실패와 검증 실패를 구분된 예외 체계로 노출한다.

설정 문서 기준으로는 `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`가 기본 축이며, `client_credentials`가 기본 grant다. `password` grant는 제한적 내부/레거시 용도에만 권장되고, 프로비저닝을 활성화하면 별도의 Admin API 인증정보가 필요하다.

## 핵심 API
- `fetch_access_token(scope=None) -> AccessTokenResult`
- `extract_user_info(token) -> AuthenticatedUser`

## 예외 모델
토큰 요청 과정에서는 `KeycloakTokenConfigurationError`, `KeycloakTokenAuthenticationError`, `KeycloakTokenTemporaryError`, `KeycloakTokenError`가 대표 예외다. JWT 해석/검증 실패는 `TokenValidationError`로 보고된다.

## 서비스 설계 관점
문서 업로드/조회/삭제 서비스가 외부 Keycloak에 의존한다면, 토큰 발급과 사용자 정보 추출 규약은 API 게이트웨이 또는 애플리케이션 미들웨어 설계에 직접 연결된다. 특히 헬스체크가 `fetch_access_token()`을 사용하므로 인증 서버 상태는 서비스 준비 상태 판단에도 영향을 준다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[service-factory-registry]]
- [[configuration-loading-and-validation]]
