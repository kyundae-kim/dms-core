---
title: Requirements vs implementation 2026-06-16
created: 2026-06-16
updated: 2026-07-15
type: query
tags: [sdk, document, testing, reliability]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# Requirements vs implementation 2026-06-16

이 문서는 `docs/SRS.md`와 `docs/SDK_INTERFACE.md`를 현재 코드베이스와 대조한 최신 갭 분석이다. 제품 형태는 독립 서비스가 아니라 import 가능한 Python SDK이며, 판단 기준은 [[sdk-public-interface]], [[sdk-factory-assembly]], [[document-lifecycle-and-consistency]], [[sdk-exception-model]]이다. 2026-06-18 기준 SRS 자체가 미래 요구사항 초안에서 현재 구현 계약 문서로 갱신되었으므로, 이 query는 “문서가 코드를 따라잡았는가”까지 함께 추적한다.

## 실행으로 확인한 현재 상태
- 테스트 실행: `uv run pytest -q`
- 결과: `43 passed, 1 warning in 1.04s`
- 따라서 현재 SDK의 핵심 업로드/조회/삭제/health/auth helper 경로는 최소한 테스트 기준으로는 동작이 검증됐다.

## 요구사항 대비 상태 매트릭스

### 구현됨
- FR-1 설정 로드/검증: `create_sdk_from_environment()`가 `load_settings(env)`를 호출하고 MinIO/metadata 설정 누락 시 즉시 실패한다 (`dms/sdk/factory.py:68-109`).
- FR-2 서비스 초기화/종료: `ServiceFactoryRegistry(settings)`를 사용해 필요한 클라이언트를 조립하고 `registry.close_all`을 종료 콜백으로 등록한다 (`dms/sdk/factory.py:96-142`).
- FR-3 문서 업로드: object 저장 후 metadata 저장, 중복 document_id 차단, 결과로 document_id/storage_key/metadata 반환이 구현돼 있다 (`dms/sdk/implementation.py:125-210`).
- FR-4 문서 조회: metadata 조회, 전체 바이트 조회, chunked stream 조회가 모두 존재하고 object-metadata 불일치 시 `ConsistencyError`를 반환한다 (`dms/sdk/implementation.py:212-309`).
- FR-5 삭제 정책 선택: soft/hard delete 선택이 가능하고 metadata 후속 처리 실패를 `ConsistencyError`로 표면화한다 (`dms/sdk/implementation.py:311-387`).
- FR-6 메타데이터 모델: `document_id`, 파일명, content type, file size, storage key, checksum, status, created/updated/deleted timestamps, created_by, 확장 metadata가 구현돼 있다 (`dms/domain/models.py:17-30`).
- FR-7 헬스체크: 서비스별 check 결과를 집계하는 `check_health()`가 존재하고 startup 시 required health check도 수행한다 (`dms/sdk/factory.py:128-142`, `dms/sdk/implementation.py:389-423`).
- FR-8 저장소 선택: PostgreSQL 우선, 없으면 SQLite fallback 조립이 구현돼 있다 (`dms/sdk/factory.py:98-109`).
- FR-9 인증: `DMS_AUTH_ENABLED=true`일 때 Keycloak helper를 조립하고, 비활성 상태에서는 `ConfigurationError`를 반환한다 (`dms/sdk/factory.py:114-127`, `dms/sdk/implementation.py:72-123`).
- 외부 인터페이스/quick-start 정렬: `dms.sdk` namespace export와 `create_sdk(env)` public entrypoint가 문서와 일치한다 (`dms/sdk/__init__.py:1-53`, `README.md:5-56`, `docs/SDK_INTERFACE.md:17-183`).

### 부분 구현
- FR-10 오류 분류: 설정/인증/스토리지/메타데이터/일관성/헬스체크 예외 타입은 나뉘어 있다. 다만 requirement의 `dependency unavailable` 전용 타입은 별도 모델이 아니라 `HealthCheckFailedError`나 backend 예외 메시지에 흡수된다 (`dms/sdk/errors.py:4-41`).
- NFR-2 대용량 다운로드: stream API와 adapter 지원은 구현됐지만 async 변형이나 presigned URL은 아직 없다. 이는 현재 SRS의 필수 항목은 아니고 향후 확장에 가깝다 (`dms/sdk/types.py:39-65`, `dms/infrastructure/storage/minio.py:63-85`).

### 아직 남은 갭
1. 민감정보 비노출 요구는 코드 의도는 보이지만 회귀 테스트가 부족하다.
   - structured log extra에는 token/content를 넣지 않는다 (`dms/sdk/implementation.py:442-459`).
   - 반면 여러 경로에서 `str(exc)`를 그대로 오류 메시지/health 결과에 사용한다 (`dms/sdk/factory.py:87`, `dms/sdk/factory.py:133`, `dms/sdk/implementation.py:84`, `dms/sdk/implementation.py:92`, `dms/sdk/implementation.py:116`, `dms/sdk/implementation.py:403`).
   - 현재 테스트는 log field 존재를 검증하지만 secret redaction 자체는 검증하지 않는다 (`test_dms/test_sdk_behavior.py:521-563`).

## 2026-06-16 추가 반영 사항
- 삭제 시작 시 metadata status를 `deleting`으로 영속화하고, object 삭제 실패 시 `failed`를 남기도록 보강됐다 (`dms/sdk/implementation.py`, `test_dms/test_sdk_behavior.py`).
- soft delete metadata 후속 처리 실패와 hard delete row 제거 실패가 발생하면 metadata는 `deleting` 상태로 남아 운영 복구 신호를 제공한다 (`dms/sdk/implementation.py`, `test_dms/test_sdk_behavior.py`).

## 2026-06-18 문서 정렬 상태
- `docs/SRS.md`는 현재 코드/테스트 기준의 SDK 요구사항 문서로 재작성되었고, runtime health check, explicit dependency injection 경로, metadata 최소 필드, partial-failure semantics까지 현재형으로 반영했다.
- `README.md`도 같은 기준으로 정렬되어 GitHub `uv add` 설치 경로와 public API 요약을 포함한다.
- `docs/SDK_INTERFACE.md`도 실제 export와 시그니처 기준으로 갱신되어 `AccessTokenResult`, `AuthenticatedUser`, `DocumentContentStream`, `ServiceHealth`, `DefaultDocumentManagementSDK`, `create_sdk_from_environment`까지 현재 public surface를 반영한다.
- 따라서 이전 query에서 남아 있던 “SRS/README의 미래형 설명과 구현 사이의 문서 drift”는 해소됐다.

## 요구사항과 무관하거나 우선순위가 낮은 항목
- role/scope 기반 권한부여 enforcement는 아직 없다. 다만 이는 SRS 16장의 향후 확장 범위에 더 가깝고, 현재 FR-9의 최소 기준은 optional auth helper 제공이므로 즉시 blocker는 아니다.
- presigned URL, async SDK, 버전 관리, 감사 로그도 현재는 확장 요구사항 영역이다.

## 다음 작업 우선순위
1. secret redaction 회귀 테스트를 추가해 DSN/token/secret이 예외 메시지와 로그에 노출되지 않음을 고정.
2. wiki의 `SCHEMA.md` 도메인 설명이 아직 “서비스와 SDK를 함께 배포” 관점을 강하게 남기고 있으므로, 현재 제품 중심이 SDK임을 더 분명히 다듬을지 검토.

## 2026-07-15 docmesh-py-core v0.2.0 재점검
- 현재 `dms/sdk/factory.py`는 v0.2.0에 존재하는 `load_service_configs`, `create_*_client`, `check_all_services`, `close_service_clients`를 사용하므로 제거된 registry API에 대한 필수 마이그레이션은 이미 반영돼 있다.
- v0.2.0의 `load_service_configs(env, services=...)`에 환경 매핑을 직접 전달하도록 변경했고, 프로세스 전역 `os.environ`을 교체하던 compatibility overlay는 제거했다. 이에 따라 동시 SDK 생성 시 환경 오염 위험을 없앴다 (`dms/sdk/factory.py`).
- v0.2.0의 `assemble_services()`로 설정 로딩, 요구 서비스 검증, client 생성, startup check와 rollback cleanup을 위임했다. DMS factory는 PostgreSQL 우선/SQLite fallback 선택 정책과 public 예외 매핑, adapter 조립만 담당한다. upstream assembly 이후 DMS adapter 조립이 실패하는 경우에도 `ServiceBundle.close()`를 호출한다.
- factory의 upstream 연동 회귀 테스트는 env 직접 전달, PostgreSQL/SQLite 선택, 정상 종료 시 close 위임, startup health failure 시 rollback cleanup, core 설정/health 오류의 DMS 공개 예외 변환을 고정한다 (`test_dms/test_sdk_behavior.py`, `test_dms/test_infrastructure_adapters.py`).
- startup health check 실패 시 이미 생성된 metadata/MinIO client를 `close_service_clients()`로 정리하며, cleanup 자체가 실패하면 원래 startup 예외를 유지하고 보충 note를 추가한다 (`dms/sdk/factory.py`).
- 실행 확인: `uv run pytest -q` 결과 `37 passed in 1.08s`.

## 2026-07-15 runtime dependency 계약 정렬
- DMS metadata adapter가 직접 import하는 SQLAlchemy를 `pyproject.toml`의 runtime dependency에 `sqlalchemy>=2.0`으로 명시했다.
- `uv.lock`을 갱신했고 SQLAlchemy 2.0.51이 DMS의 직접 의존성으로 해석되는 것을 `uv tree --depth 1`로 확인했다.
- 실행 확인: `uv run pytest -q` 결과 `37 passed in 1.04s`.

## 2026-07-15 ServiceBundle 기반 factory 조립
- 환경 기반 factory가 개별 loader/client/check/close helper를 수동 호출하는 대신 `assemble_services()`와 `ServiceBundle`을 사용하도록 전환됐다.
- PostgreSQL 설정이 있으면 PostgreSQL+MinIO를 필수로, SQLite 설정만 있으면 SQLite+MinIO를 필수로 요청한다. metadata 설정이 없으면 PostgreSQL/SQLite `one_of` 요구사항으로 설정 오류를 표면화한다.
- startup health check와 실패 rollback은 py-core assembly에 위임하고, 정상 종료는 SDK의 `close()`가 `ServiceBundle.close()`를 호출한다.
- 실행 확인: `uv run pytest -q` 결과 `38 passed in 1.30s`.

## 관련 페이지
- [[sdk-public-interface]]
- [[sdk-factory-assembly]]
- [[document-lifecycle-and-consistency]]
- [[sdk-exception-model]]