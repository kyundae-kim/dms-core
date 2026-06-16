# Document Management Service

사용자 문서를 Object Storage(MinIO)에 저장/조회/삭제 하고 문서 연관 metadata를 RDB(Postgres) 또는 SQLite에 저장/관리하는 SDK입니다.

## SDK quick start

환경 기반 factory를 사용하면 `docmesh-py-core` 설정 로더를 통해 SDK를 조립할 수 있습니다.

```python
from os import environ

from dms.sdk import UploadDocumentRequest, create_sdk_from_environment

sdk = create_sdk_from_environment(environ)
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
    health = sdk.check_health()

    print(result.storage_key)
    print(metadata.status)
    print(content.size)
    print(health.ok)
finally:
    sdk.close()
```

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

### SQLite local path + MinIO

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
- `POSTGRES_*` 설정이 있으면 PostgreSQL 우선 사용
- PostgreSQL 설정이 없고 `SQLITE_PATH`가 있으면 SQLite fallback 사용
- startup 시 metadata backend와 MinIO health check를 통과해야 SDK 생성 성공

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

## Metadata schema/index notes

현재 metadata store는 다음 조회 경로를 고려해 인덱스를 생성합니다.
- primary key: `document_id`
- secondary indexes: `storage_key`, `status`, `created_at`

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

`uv run pytest test_dms/test_integration_adapters.py -q`

기존 환경변수를 그대로 재사용하며, 별도의 `DMS_TEST_*` 변수는 사용하지 않습니다.
환경변수가 없으면 integration test는 skip 됩니다.
