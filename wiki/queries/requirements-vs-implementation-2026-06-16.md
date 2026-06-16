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

이 문서는 `docs/SRS.md`와 `docs/SDK_INTERFACE.md`를 현재 코드베이스와 대조한 최신 갭 분석이다. 제품 형태는 독립 서비스가 아니라 import 가능한 Python SDK이며, 판단 기준은 [[sdk-public-interface]], [[sdk-factory-assembly]], [[document-lifecycle-and-consistency]], [[sdk-exception-model]]이다.

## 실행으로 확인한 현재 상태
- 테스트 실행: `uv run pytest -q`
- 결과: `40 passed, 1 warning in 1.04s`
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
1. 부분 실패를 metadata 상태로 남기지 않는다.
   - `DocumentStatus`에는 `DELETING`/`FAILED`가 정의돼 있지만 실제 업로드/삭제 흐름에서는 사용되지 않는다 (`dms/domain/models.py:9-14`).
   - 삭제 경로는 object 삭제 후 metadata 갱신이 실패하면 `ConsistencyError`를 던지지만, metadata 쪽에 재시도 가능 상태를 남기지 않는다 (`dms/sdk/implementation.py:319-387`).
   - 따라서 FR-5.3, FR-10.3, 11.2의 "부분 실패 감지 가능 상태" 요구는 예외 표면화까지만 충족되고 상태 영속화는 미흡하다.
2. 런타임 dependency 선언이 코드 사용 범위와 완전히 맞지 않는다.
   - `pyproject.toml`의 runtime dependency는 `docmesh-py-core`만 선언한다 (`pyproject.toml:7-9`).
   - 그러나 런타임 metadata store 구현은 `sqlalchemy`를 직접 import한다 (`dms/infrastructure/metadata/postgres.py:7-8`, `dms/infrastructure/metadata/sqlite.py:3`).
   - 현재 테스트 환경에서는 설치돼 있어 통과하지만, 배포 계약 측면에서는 명시가 더 안전하다.
3. 민감정보 비노출 요구는 코드 의도는 보이지만 회귀 테스트가 부족하다.
   - structured log extra에는 token/content를 넣지 않는다 (`dms/sdk/implementation.py:442-459`).
   - 반면 여러 경로에서 `str(exc)`를 그대로 오류 메시지/health 결과에 사용한다 (`dms/sdk/factory.py:87`, `dms/sdk/factory.py:133`, `dms/sdk/implementation.py:84`, `dms/sdk/implementation.py:92`, `dms/sdk/implementation.py:116`, `dms/sdk/implementation.py:403`).
   - 현재 테스트는 log field 존재를 검증하지만 secret redaction 자체는 검증하지 않는다 (`test_dms/test_sdk_behavior.py:521-563`).

## 요구사항과 무관하거나 우선순위가 낮은 항목
- role/scope 기반 권한부여 enforcement는 아직 없다. 다만 이는 SRS 16장의 향후 확장 범위에 더 가깝고, 현재 FR-9의 최소 기준은 optional auth helper 제공이므로 즉시 blocker는 아니다.
- presigned URL, async SDK, 버전 관리, 감사 로그도 현재는 확장 요구사항 영역이다.

## 다음 작업 우선순위
1. 삭제/업로드 부분 실패 시 metadata에 `failed` 또는 중간 상태를 남기도록 일관성 정책을 보강.
2. `pyproject.toml`에 직접 사용하는 runtime dependency(`sqlalchemy`)를 명시해 패키지 계약을 안정화.
3. secret redaction 회귀 테스트를 추가해 DSN/token/secret이 예외 메시지와 로그에 노출되지 않음을 고정.

## 관련 페이지
- [[sdk-public-interface]]
- [[sdk-factory-assembly]]
- [[document-lifecycle-and-consistency]]
- [[sdk-exception-model]]