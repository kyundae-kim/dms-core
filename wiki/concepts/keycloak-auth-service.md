---
title: KeycloakAuthService
created: 2026-06-15
updated: 2026-07-19
type: concept
tags: [auth, service, security, integration]
sources: [raw/articles/docmesh-py-core-api-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-api-reference-v0-4-0.md, raw/articles/docmesh-py-core-configuration-v0-4-0.md]
confidence: medium
---

# KeycloakAuthService

`KeycloakAuthService`는 Keycloak 기반 access token 발급과 JWT 검증을 담당하는 인증 통합 계층이다. v0.4.0 공개 API에서는 `KeycloakConfig`를 받아 동작하며, 문서 서비스에서 사용자 인증/권한 판별을 SDK 레벨에서 보조한다. 토큰 발급 실패와 검증 실패는 구분된 예외 체계로 노출되며, 선언형 초기화에는 별도 `KeycloakProvisioner`가 제공된다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]

설정 문서 기준으로는 `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`가 기본 축이다. password grant가 기본이며, `client_credentials`도 명시적으로 선택할 수 있다. v0.4.0에서 provisioning을 켜면 admin client secret 방식 또는 admin username/password 방식 중 정확히 하나만 설정해야 한다.^[raw/articles/docmesh-py-core-api-reference-v0-4-0.md]^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 핵심 API
- `fetch_access_token(scope=None) -> AccessTokenResult`
- `extract_user_info(token) -> AuthenticatedUser`

최신 구현 노트:
- `extract_user_info()`는 `Bearer <jwt>` 형식과 raw JWT 문자열을 모두 받는다.
- 기본 허용 알고리즘은 `HS256`이며, RS256 검증은 `allowed_algorithms`로 명시적으로 허용해야 한다. RS256은 JWKS 캐시 TTL을 사용한다. 기본 password grant는 설정 로딩만으로 username/password를 강제하지 않지만, Keycloak을 startup healthcheck 대상으로 조립할 때는 두 credential이 모두 필요하다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]
- `audience` 설정이 없으면 audience 검증을 비활성화한다.
- 운영 환경에서는 `KEYCLOAK_VERIFY_SSL=false`를 허용하지 않으며, `KEYCLOAK_JWKS_CACHE_TTL_SECONDS` 기본값은 300초다. production 설정 진단은 secret placeholder와 endpoint placeholder도 거부한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 예외 모델
토큰 요청 과정에서는 `KeycloakTokenConfigurationError`, `KeycloakTokenAuthenticationError`, `KeycloakTokenTemporaryError`, `KeycloakTokenError`가 대표 예외다. JWT 해석/검증 실패는 `TokenValidationError`로 보고된다. 일시적 장애는 `config.max_retries + 1`회까지 재시도되며, 재시도 이벤트는 구조화 로그로 남는다.^[raw/articles/docmesh-py-core-api-v0-1-1.md]

## 서비스 설계 관점
문서 업로드/조회/삭제 서비스가 외부 Keycloak에 의존한다면, 토큰 발급과 사용자 정보 추출 규약은 API 게이트웨이 또는 애플리케이션 미들웨어 설계에 직접 연결된다. 특히 헬스체크가 `fetch_access_token()`을 사용하므로 인증 서버 상태는 서비스 준비 상태 판단에도 영향을 준다.

## 관련 페이지
- [[docmesh-py-core]]
- [[service-health-checking]]
- [[service-factory-registry]]
- [[configuration-loading-and-validation]]
- [[public-api-contract]]
