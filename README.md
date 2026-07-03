# Document Management Service

사용자 문서를 Object Storage(MinIO)에 저장/조회/삭제하고 문서 연관 metadata를 PostgreSQL 또는 SQLite에 저장/관리하는 Python SDK입니다.

`dms`는 독립 실행형 API 서버가 아니라 다른 프로젝트에서 import 해서 사용하는 라이브러리입니다.

## Installation

### uv로 GitHub에서 직접 설치

프로젝트에 dependency로 추가:

```bash
uv add "git+https://github.com/kyundae-kim/dms-core.git"
```

특정 ref/tag/branch를 지정해서 추가:

```bash
uv add "git+https://github.com/kyundae-kim/dms-core.git@main"
uv add "git+https://github.com/kyundae-kim/dms-core.git@v0.1.0"
uv add "git+https://github.com/kyundae-kim/dms-core.git@<commit-sha>"
```

임포트 예시:

```python
from dms.sdk import UploadDocumentRequest, create_sdk
```

## SDK quick start

환경 기반 factory를 사용하면 `docmesh-py-core`의 최신 서비스 설정/클라이언트 생성 API를 통해 SDK를 조립할 수 있습니다.

```python
import logging
from os import environ

from dms.sdk import UploadDocumentRequest, create_sdk

sdk = create_sdk(environ, logger=logging.getLogger("dms.sdk"))
try:
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"hello world",
            filename="hello.txt",
            content_type="text/plain",
            metadata={"team": "platform"},
            created_by="tester",
        )
    )

    metadata = sdk.get_document_metadata(result.document_id)
    content = sdk.get_document_content(result.document_id)
    content_stream = sdk.get_document_content_stream(result.document_id, chunk_size=65536)
    health = sdk.check_health()

    print(result.storage_key)
    print(metadata.status)
    print(content.size)
    print(sum(len(chunk) for chunk in content_stream.iter_chunks()))
    print(health.ok)
    content_stream.close()
finally:
    sdk.close()
```

하위 호환을 위해 `create_sdk_from_environment(environ)`도 계속 사용할 수 있습니다.

## Public API summary

`dms.sdk`에서 다음 핵심 타입과 진입점을 사용할 수 있습니다.

- `create_sdk(env, logger=None)`
- `create_sdk_from_environment(env, logger=None)`
- `DocumentManagementSDK`
- `DefaultDocumentManagementSDK`
- `UploadDocumentRequest`
- `UploadDocumentResult`
- `DocumentMetadata`
- `DocumentContent`
- `DocumentContentStream`
- `DeleteDocumentResult`
- `HealthStatus`
- `ServiceHealth`
- `AccessTokenResult`
- `AuthenticatedUser`
- `DmsError` 및 하위 예외 타입

## Authentication helpers

선택적으로 `DMS_AUTH_ENABLED=true`를 함께 주면 Keycloak 기반 인증 helper도 활성화됩니다.

```python
user = sdk.get_authenticated_user("Bearer <jwt>")
token = sdk.fetch_access_token(scope="documents:write")
```

주의:
- auth helper는 기본 비활성입니다.
- auth service가 조립되지 않은 SDK 인스턴스에서 `fetch_access_token()` 또는 `get_authenticated_user()`를 호출하면 `ConfigurationError`가 발생합니다.
- 빈 token으로 `get_authenticated_user()`를 호출하면 `ValidationError`가 발생합니다.

## Configuration

### PostgreSQL + MinIO

필수 환경변수 예시:

```bash
export DOCMESH_ENV=local
export DOCMESH_HEALTHCHECK_ENABLED=true
export POSTGRES_DSN=postgresql+psycopg://user:password@localhost:5432/dms
export MINIO_ENDPOINT=localhost:9000
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin
export MINIO_BUCKET=documents
```

### SQLite + MinIO

로컬 개발/단일 프로세스 테스트에서는 PostgreSQL 대신 SQLite metadata store를 사용할 수 있습니다.

```bash
export DOCMESH_ENV=local
export DOCMESH_HEALTHCHECK_ENABLED=true
export SQLITE_PATH=/tmp/dms-metadata.db
export MINIO_ENDPOINT=localhost:9000
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin
export MINIO_BUCKET=documents
```

현재 factory 동작:
- `load_service_configs()`로 필요한 서비스 설정만 검증
- `POSTGRES_*` 설정이 있으면 PostgreSQL 우선 사용
- PostgreSQL 설정이 없고 `SQLITE_PATH`가 있으면 SQLite fallback 사용
- `create_minio_client()`로 MinIO wrapper를 만들고 `MINIO_BUCKET`을 object store에 연결
- `DMS_AUTH_ENABLED`가 truthy이면 `create_keycloak_client()`로 Keycloak helper 조립 시도
- `DOCMESH_HEALTHCHECK_ENABLED=true`이면 startup 시 metadata backend와 MinIO를 health check
- `sdk.close()` 시 내부적으로 `close_service_clients()`를 통해 생성한 service wrapper들을 정리

## Storage policy

- MinIO bucket은 `MINIO_BUCKET` 단일 버킷을 사용합니다.
- object key는 `documents/{document_id}/{sanitized_filename}` 형식입니다.
- 파일명 정규화 규칙:
  - 앞뒤 공백 제거
  - `/`, `\` → `-`
  - `..` → `.`
  - 정규화 결과가 `.` 또는 빈 문자열이면 업로드 거부
- 충돌 기준은 `document_id`입니다.
  - 같은 `document_id` 재사용은 `DuplicateDocumentError`
  - 같은 filename은 다른 `document_id`에서 허용

예시:
- 입력 filename: ` ../nested\quarterly/report..pdf `
- 저장 key: `documents/<document_id>/.-nested-quarterly-report.pdf`

## Metadata schema/index notes

현재 metadata store는 다음 조회 경로를 고려해 인덱스를 생성합니다.
- primary key: `document_id`
- secondary indexes: `storage_key`, `status`, `created_at`

문서 metadata 필드:
- `document_id`
- `original_filename`
- `content_type`
- `file_size`
- `storage_key`
- `status`
- `created_at`
- `updated_at`
- `checksum`
- `deleted_at`
- `created_by`
- `extra_metadata`

상태(status) semantics:
- upload 성공 시 `available`
- delete 시작 시 `deleting`
- object 삭제 실패 시 `failed`
- soft delete 완료 시 `deleted`
- hard delete 완료 시 metadata row 제거

## Download modes

다운로드는 두 가지 모드를 제공합니다.
- `get_document_content(document_id)`: 전체 바이트를 한 번에 반환
- `get_document_content_stream(document_id, chunk_size=65536)`: 큰 파일용 chunked stream 반환 (`close()` 필요)

추가 규칙:
- `chunk_size <= 0`이면 `ValidationError`
- metadata는 있지만 object가 없으면 `ConsistencyError`

## Error model

주요 public 예외:
- `ConfigurationError`
- `ValidationError`
- `AuthenticationError`
- `DocumentNotFoundError`
- `DuplicateDocumentError`
- `StorageError`
- `MetadataStoreError`
- `ConsistencyError`
- `HealthCheckFailedError`

대표 동작:
- metadata 없음 → `DocumentNotFoundError`
- object storage 접근 실패 → `StorageError`
- metadata backend 실패 → `MetadataStoreError`
- metadata와 object storage 불일치 → `ConsistencyError`
- startup health check 실패 → `HealthCheckFailedError`

## Logging

SDK는 표준 Python logger를 받아 operation 단위의 structured diagnostic log를 남길 수 있습니다.

각 record에는 다음과 같은 extra field가 포함될 수 있습니다.
- `dms_event`
- `dms_document_id`
- `dms_storage_key`
- `dms_duration_ms`
- `dms_error_type`

raw token이나 document content 자체는 로그에 남기지 않습니다.

## Integration tests

실제 PostgreSQL + MinIO integration test는 외부에 이미 준비된 서비스를 사용합니다.
테스트가 docker compose를 생성하거나 실행하지 않습니다.

필수 환경변수:
- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

실행:

```bash
uv run pytest test_dms/test_integration_adapters.py -q
```

기존 환경변수를 그대로 재사용하며, 별도의 `DMS_TEST_*` 변수는 사용하지 않습니다.
환경변수가 없으면 integration test는 skip 됩니다.

## Scope note

현재 문서 기준으로 다음 항목은 아직 SDK 범위에 포함되지 않습니다.
- presigned URL 발급
- 문서 검색/필터링
- 비동기 SDK
- NATS/Langfuse 연계 API
- 자체 권한 정책 관리 API
