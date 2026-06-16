---
title: Requirements vs implementation 2026-06-16
created: 2026-06-16
updated: 2026-06-16
type: query
tags: [sdk, document, testing, reliability]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# Requirements vs implementation 2026-06-16

이 비교는 SRS와 SDK interface 초안을 현재 저장소 구현과 대조해, 무엇이 이미 충족되었고 무엇이 아직 부족한지 정리한 결과다. 해석 기준은 repo 문서와 위키의 [[sdk-public-interface]], [[document-lifecycle-and-consistency]] 페이지다.

## 이미 구현된 항목
- SDK 중심 제품 형태: 패키지 메타데이터와 README가 import 가능한 Python SDK 방향을 명시한다 (`pyproject.toml`, `README.md`).
- 핵심 인터페이스: `DocumentManagementSDK` 프로토콜과 upload/get/delete/check/close 진입점이 구현돼 있다 (`dms/sdk/client.py`, `dms/sdk/implementation.py`).
- 업로드/조회/삭제 핵심 흐름: MinIO 저장, 메타데이터 저장, soft/hard delete, health check가 동작한다 (`dms/sdk/implementation.py`).
- 저장소 선택: 환경 기반으로 PostgreSQL 우선, SQLite fallback 경로가 구현돼 있다 (`dms/sdk/factory.py`).
- startup health check: 환경 기반 팩토리에서 필수 서비스 check를 수행한다 (`dms/sdk/factory.py`).
- 테스트 검증: 단위/어댑터/실서비스 연동 테스트가 존재하고 현재 통과한다 (`test_dms/`).

## 부분 구현 항목
- 오류 분류: 핵심 예외 계층은 존재하고 인증 오류도 분리됐지만, 더 세밀한 부분 실패 taxonomy는 아직 제한적이다 (`dms/sdk/errors.py`).
- 메타데이터 모델: 최소 필드 대부분은 구현됐지만 상태 전이 규칙과 checksum/created_by 활용 범위는 제한적이다 (`dms/domain/models.py`).

## 2026-06-16 반영 사항
- `dms.sdk` namespace가 `DocumentMetadata`를 직접 export하도록 정렬됐다 (`dms/sdk/__init__.py`).
- public quick-start는 `create_sdk(env)`를 기본 진입점으로 사용하도록 정렬됐고, `create_sdk_from_environment(env)`는 하위 호환 alias로 유지된다 (`README.md`, `docs/SDK_INTERFACE.md`, `dms/sdk/factory.py`).
- 테스트도 새 public 진입점과 export 계약을 검증하도록 보강됐다 (`test_dms/test_infrastructure_adapters.py`, `test_dms/test_sdk_behavior.py`).
- optional auth helper가 추가되어 `DMS_AUTH_ENABLED=true`일 때 Keycloak 기반 `fetch_access_token(...)` / `get_authenticated_user(...)`를 사용할 수 있다 (`dms/sdk/client.py`, `dms/sdk/implementation.py`, `dms/sdk/factory.py`).
- 인증 실패를 구분하기 위한 `AuthenticationError`가 SDK 예외 계층에 추가됐다 (`dms/sdk/errors.py`).
- 선택적 `logger` 인자를 통해 upload/get/delete/auth/health/close 경계에 structured diagnostic logging이 추가됐다 (`dms/sdk/factory.py`, `dms/sdk/implementation.py`).
- structured log record에는 `dms_event`, `dms_document_id`, `dms_storage_key`, `dms_duration_ms`, `dms_error_type` 같은 extra field가 담긴다 (`dms/sdk/implementation.py`).
- `get_document_content_stream(document_id, *, chunk_size=65536)`가 추가되어 큰 파일 다운로드를 chunked stream으로 처리할 수 있다 (`dms/sdk/client.py`, `dms/sdk/types.py`, `dms/sdk/implementation.py`).
- MinIO adapter도 stream download 경로를 제공하고 관련 테스트가 추가됐다 (`dms/infrastructure/storage/minio.py`, `test_dms/test_infrastructure_adapters.py`, `test_dms/test_sdk_behavior.py`).

## 미구현 또는 명확한 갭
- 권한부여 정책 자체: 토큰 검증 helper는 추가됐지만 문서별 role/scope enforcement 정책은 아직 없다.
- 삭제 상태 전이: `deleting`/`failed` 상태는 enum에만 있고 실제 흐름에서 사용되지 않는다 (`dms/domain/models.py`, `dms/sdk/implementation.py`).
- 배포 관점의 직접 의존성 명시: `pyproject.toml`에는 `docmesh-py-core`만 선언돼 있지만 코드가 `sqlalchemy`와 `minio`를 직접 import한다 (`pyproject.toml`, `dms/infrastructure/...`).

## 우선순위가 높은 다음 작업
1. 문서별 role/scope 기반 권한부여 정책을 SDK 범위에 포함할지 결정.
2. 직접 runtime dependency 선언을 정리해 배포 계약을 안정화.
3. 필요하면 현재 structured logging field를 metrics/tracing 체계와 연결.
4. stream download에 presigned URL 또는 async variant가 필요한지 결정.

## 관련 페이지
- [[sdk-public-interface]]
- [[document-lifecycle-and-consistency]]
- [[sdk-factory-assembly]]
- [[sdk-exception-model]]
