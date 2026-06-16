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
- public import contract: `DocumentManagementSDK`, request/result 타입은 export되지만 `dms.sdk`에서 `DocumentMetadata`는 export되지 않아 문서 초안과 일치하지 않는다 (`docs/SDK_INTERFACE.md`, `dms/sdk/__init__.py`).
- 팩토리 naming contract: 문서 초안은 `create_sdk(env)`를 제안하지만 구현은 의존성 주입용 `create_sdk(...)`와 환경 기반 `create_sdk_from_environment(env)`로 나뉘어 있다 (`docs/SDK_INTERFACE.md`, `dms/sdk/factory.py`).
- 오류 분류: 핵심 예외 계층은 존재하지만 인증/권한 오류, 구조화된 부분 실패 정보는 아직 없다 (`dms/sdk/errors.py`).
- 메타데이터 모델: 최소 필드 대부분은 구현됐지만 상태 전이 규칙과 checksum/created_by 활용 범위는 제한적이다 (`dms/domain/models.py`).

## 미구현 또는 명확한 갭
- 인증/권한부여 경로: Keycloak/JWT/bearer token 관련 구현이 없다 (`dms/` 코드 검색 기준).
- 구조화 로깅/운영 추적: 업로드/삭제 실패 원인 추적용 logging 코드가 없다 (`dms/` 코드 검색 기준).
- 스트리밍 다운로드: `get_document_content()`는 바이트를 통째로 반환하며 스트리밍 인터페이스가 없다 (`dms/sdk/implementation.py`).
- 삭제 상태 전이: `deleting`/`failed` 상태는 enum에만 있고 실제 흐름에서 사용되지 않는다 (`dms/domain/models.py`, `dms/sdk/implementation.py`).
- 문서화된 public import 예시의 완전한 부합: `from dms.sdk import DocumentMetadata`는 현재 성립하지 않는다 (`dms/sdk/__init__.py`).
- 배포 관점의 직접 의존성 명시: `pyproject.toml`에는 `docmesh-py-core`만 선언돼 있지만 코드가 `sqlalchemy`와 `minio`를 직접 import한다 (`pyproject.toml`, `dms/infrastructure/...`).

## 우선순위가 높은 다음 작업
1. `dms.sdk` export와 팩토리 naming을 문서 계약에 맞추거나 문서를 구현에 맞게 정렬.
2. 인증/권한부여를 초기 버전 범위에 둘지 명확히 결정하고, 범위라면 Keycloak 연동 추가.
3. 실패 원인 추적용 구조화 logging/diagnostics 추가.
4. 스트리밍 다운로드 또는 현재 비스트리밍 정책 명문화.
5. 직접 runtime dependency 선언을 정리해 배포 계약을 안정화.

## 관련 페이지
- [[sdk-public-interface]]
- [[document-lifecycle-and-consistency]]
- [[sdk-factory-assembly]]
- [[sdk-exception-model]]
