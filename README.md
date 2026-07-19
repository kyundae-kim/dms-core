# Document Management Service

사용자 문서를 MinIO에 저장하고 문서 메타데이터를 PostgreSQL 또는 SQLite에 저장/관리하는 Python SDK입니다.

`dms`는 독립 실행형 API 서버가 아니라 다른 프로젝트에서 import 해서 사용하는 라이브러리입니다.

## Installation

```bash
uv add "git+https://github.com/kyundae-kim/dms-core.git"
```

특정 ref/tag/branch를 지정해서 추가:

```bash
uv add "git+https://github.com/kyundae-kim/dms-core.git@main"
uv add "git+https://github.com/kyundae-kim/dms-core.git@v0.4.0"
uv add "git+https://github.com/kyundae-kim/dms-core.git@<commit-sha>"
```

## Quick start

가장 일반적인 시작 방식은 환경 기반 조립입니다.

```python
import logging
from os import environ

from dms import UploadDocumentRequest, create_sdk_from_environment

sdk = create_sdk_from_environment(environ, logger=logging.getLogger("dms.sdk"))
try:
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"hello world",
            filename="hello.txt",
            content_type="text/plain",
        )
    )

    metadata = sdk.get_document_metadata(result.document_id)
    content = sdk.get_document_content(result.document_id)

    print(result.storage_key)
    print(metadata.status)
    print(content.size)
finally:
    sdk.close()
```

명시적 의존성 주입이 필요하면 `create_sdk_from_components(...)`를 사용할 수 있습니다.

### docmesh-py-core v0.4 연동 방식

- DMS는 동기 SDK이므로 내부 서비스 조립에 `docmesh-py-core`의 동기 `ServiceBundle` lifecycle을 사용합니다.
- 서비스 선택과 사전 진단은 typed runtime plan에서 파생되며 PostgreSQL 또는 SQLite와 MinIO만 선택합니다.
- `docmesh-py-core` 설정 모델은 프로세스 환경변수만 읽습니다. DMS는 기존 `env` mapping API 호환을 위해 core 진단·조립 호출 동안 관련 환경변수만 잠시 적용하고 호출 후 원래 상태를 복구합니다.
- 환경 기반 SDK를 생성하는 동안 다른 thread나 라이브러리가 `DOCMESH_*`, `POSTGRES_*`, `SQLITE_*`, `MINIO_*` 값을 직접 변경하지 않아야 합니다.

## Public API overview

주요 공개 진입점:
- `create_sdk_from_environment(env, logger=None)`
- `create_sdk_from_components(...)`
- `DefaultDocumentManagementSDK`
- `UploadDocumentRequest`
- `UploadDocumentResult`
- `DocumentMetadata`
- `DocumentStatus`
- `DocumentContent`
- `DocumentContentStream`
- `DocumentPage`
- `DeleteDocumentResult`
- `HealthStatus`
- `ServiceHealth`
- `DmsError` 및 하위 예외 타입

전체 공개 계약은 package root의 내보내기 목록과 테스트를 기준으로 관리합니다.

## Minimum configuration overview

환경 기반 조립 기준:
- PostgreSQL 사용 시: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`
- SQLite 사용 시: `SQLITE_PATH`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`

주의:
- 현재 실행 환경의 `docmesh-py-core` 설정 검증 범위에 따라 `.env.example`의 추가 값이 함께 필요할 수 있습니다.
- PostgreSQL과 SQLite 설정을 자동 선택으로 함께 제공하면 PostgreSQL이 선택되고 경고가 발생합니다. `DMS_CONFIGURATION_STRICT=true`로 이 모호한 구성을 거부하거나 `DMS_METADATA_BACKEND`로 저장소를 명시하십시오.
- py-core v0.4.0 설정 규칙은 `wiki/entities/docmesh-py-core.md`와 연결된 configuration 문서를 참고하세요.

## Document guide

- 제품 요구사항: `docs/prd.md`
- 소프트웨어 요구사항: `docs/srs.md`
- docmesh-py-core v0.4.0 지식 문서: `wiki/entities/docmesh-py-core.md`

## Integration tests

실제 PostgreSQL + MinIO integration test는 외부에 이미 준비된 서비스를 재사용합니다.
테스트가 Docker Compose를 생성하거나 실행하지 않습니다.

```bash
uv run pytest test_dms -q
```

## Out of scope

현재 범위 밖 항목:
- 인증 helper
- presigned URL 발급
- 문서 검색/필터링
- 비동기 SDK
- 메시지 브로커 연계 API
- 자체 권한 정책 관리 API
