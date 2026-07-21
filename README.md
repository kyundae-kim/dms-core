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
uv add "git+https://github.com/kyundae-kim/dms-core.git@v0.5.0"
uv add "git+https://github.com/kyundae-kim/dms-core.git@<commit-sha>"
```

## Quick start

가장 일반적인 시작 방식은 환경 기반 조립입니다.

```python
import logging

from dms import UploadDocumentRequest, create_sdk_from_environment

sdk = create_sdk_from_environment(logger=logging.getLogger("dms.sdk"))
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

    print(result.metadata.original_filename)
    print(metadata.status)
    print(content.size)
finally:
    sdk.close()
```

명시적 의존성 주입이 필요하면 `create_sdk_from_components(...)`를 사용할 수 있습니다.

호스트 애플리케이션이 이미 SQLAlchemy `Engine`과 MinIO client의 lifecycle을 관리한다면 client 기반 조립을 사용할 수 있습니다.

```python
from dms import create_sdk_from_clients

sdk = create_sdk_from_clients(
    engine=engine,
    minio_client=minio_client,
    bucket_name="documents",
)
try:
    health = sdk.check_health()
finally:
    sdk.close()
```

주입된 client는 기본적으로 호출자 소유이며 `sdk.close()`가 종료하지 않습니다. SDK 종료 시 함께 실행할 정리 작업이 필요한 경우에만 `close_callbacks`에 명시적으로 전달합니다. client를 생성하는 callable을 받는 별도 API는 제공하지 않으며, 호출자가 client를 생성한 뒤 이 팩토리에 전달합니다.

이미 `docmesh-py-core`에서 검증된 서비스 설정 묶음을 보유한 애플리케이션은 환경을 다시 읽지 않는 설정 기반 조립을 사용할 수 있습니다.

```python
from docmesh_py_core import load_service_configs

from dms import create_sdk_from_service_configs

configs = load_service_configs(services={"sqlite", "minio"})
sdk = create_sdk_from_service_configs(configs, check_on_startup=True)
try:
    health = sdk.check_health()
finally:
    sdk.close()
```

설정 묶음 기반 조립은 PostgreSQL과 SQLite 중 정확히 하나를 요구하며 MinIO와 버킷 설정을 필수로 사용합니다. 호출 시 프로세스 환경을 읽거나 변경하지 않고, 묶음에 포함된 다른 서비스 설정은 조립 대상에서 제외합니다. 시작 상태 확인은 기본적으로 비활성화되며 `check_on_startup=True`로 활성화할 수 있습니다. 반면 환경 기반 자동 선택은 두 문서 정보 저장소가 모두 설정되면 PostgreSQL을 우선 선택합니다.

### docmesh-py-core v0.5 연동 방식

- 환경 기반 팩토리는 typed `RuntimePlan`을 그대로 `assemble_service_runtime()`에 전달하며, 설정 로드·client 생성·시작 상태 확인·실패 rollback을 core runtime에 위임합니다.
- DMS의 공개 문서 작업 API는 동기 계약을 유지합니다. 서비스별 상태 확인은 core handle을 직접 재사용하고, 비동기 runtime 종료는 동기 lifecycle 경계에서 안전하게 실행합니다. 이미 event loop가 실행 중인 호스트에서는 종료를 별도 실행 thread에 위임합니다.
- 서비스 선택과 사전 진단은 동일한 typed runtime plan에서 파생되며 PostgreSQL 또는 SQLite와 MinIO만 선택합니다.
- `create_sdk_from_environment()`는 호출 시점의 프로세스 환경변수를 읽으며 별도의 환경 mapping을 받지 않습니다. 필요한 설정은 SDK를 생성하기 전에 준비해야 합니다.
- `create_sdk_from_service_configs(configs)`는 이미 로드된 설정만 사용하며 프로세스 환경변수를 읽거나 변경하지 않습니다.
- 설정 묶음 기반 조립은 공통 실행 보안 정책과 MinIO 연결 보안 조건을 검증합니다. 조건에 맞지 않는 설정은 SDK 조립 전에 설정 오류로 확인됩니다.
- `diagnose_environment(env)`는 연결 없이 별도 mapping을 점검하는 사전 진단 API로 유지됩니다.
- 환경 기반 SDK를 생성하는 동안 다른 thread나 라이브러리가 `DMS_*`, `DOCMESH_*`, `POSTGRES_*`, `SQLITE_*`, `MINIO_*` 값을 직접 변경하지 않아야 합니다.
- 환경 선택, 진단 및 실제 조립은 하나의 typed runtime plan 결정에서 파생됩니다. 진단용 환경 overlay는 core 호환 경계에만 격리되며 runtime factory에는 사용하지 않습니다.
- 설정 검증, core 오류 변환, service runtime 변환, 문서 작업 및 상태 확인·종료는 내부 책임 경계로 분리하되 package root의 공개 API는 유지합니다.

## Public API overview

주요 공개 진입점:
- `create_sdk_from_environment(logger=None)`
- `create_sdk_from_service_configs(configs, check_on_startup=False, ...)`
- `create_sdk_from_clients(engine=..., minio_client=..., bucket_name=..., ...)`
- `create_sdk_from_components(...)`
- `DefaultDocumentManagementSDK`
- `UploadDocumentRequest`
- `UploadDocumentResult`
- `PublicDocumentMetadata`
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
- `POSTGRES_DSN`은 지원하지 않습니다. PostgreSQL은 개별 `POSTGRES_*` 필드로 설정해야 하며, 진단 결과의 `unsupported_keys`에서 금지된 legacy 키를 확인할 수 있습니다.
- 현재 실행 환경의 `docmesh-py-core` 설정 검증 범위에 따라 `.env.example`의 추가 값이 함께 필요할 수 있습니다.
- `DOCMESH_ENV`, 선택적 보안 정책 값 및 `MINIO_SECURE`는 실행 환경의 보안 조건과 함께 검증됩니다. 환경별 보안 정책에 맞는 값을 `.env.example`을 기준으로 설정하십시오.
- PostgreSQL과 SQLite 설정을 자동 선택으로 함께 제공하면 PostgreSQL이 선택되고 경고가 발생합니다. `DMS_CONFIGURATION_STRICT=true`로 이 모호한 구성을 거부하거나 `DMS_METADATA_BACKEND`로 저장소를 명시하십시오.
- py-core v0.5.0 설정 규칙은 `wiki/entities/docmesh-py-core.md`와 연결된 configuration 문서를 참고하세요.

`diagnose_environment()`는 연결 없이 구조화된 진단 결과를 반환하고,
`format_environment_diagnosis()`는 같은 결과를 secret-safe 운영자용 문자열로 변환합니다.
설정 예외는 진단 결과를 `diagnosis` 속성으로 보존합니다.

## 공개 문서 정보와 삭제 조회

- 업로드, 일반 문서 정보 조회, 목록 및 커서 페이지는 내부 저장 위치가 없는 `PublicDocumentMetadata`를 반환합니다.
- 저장 위치가 필요한 복구·관리 작업만 `get_internal_document_metadata()`를 명시적으로 사용해야 합니다.
- 논리 삭제된 문서의 정보는 상태 확인을 위해 조회할 수 있지만, 본문 및 본문 스트림 조회는 `DocumentDeletedError`를 발생시킵니다.
- `DocumentDeletedError`는 `code`, `retryable`, `document_id`를 제공하며, 시작 상태 확인 실패는 서비스와 원인을 구조화해 제공합니다.

### v0.4 공개 반환값 이전 안내

- 기존 `result.storage_key` 사용 코드는 관리 작업에 한해 `sdk.get_internal_document_metadata(result.document_id).storage_key`로 이전해야 합니다.
- 기존 일반 조회와 목록에서 `storage_key`를 읽던 코드는 공개 반환값에서 해당 필드를 제거해야 합니다.
- 내부 저장 위치를 외부 응답이나 업무 메타데이터로 전달하지 말고, 명시적 관리·복구 경로 안에서만 사용해야 합니다.

## Document guide

- 제품 요구사항: `docs/prd.md`
- 소프트웨어 요구사항: `docs/srs.md`
- docmesh-py-core v0.5.0 지식 문서: `wiki/entities/docmesh-py-core.md`

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
