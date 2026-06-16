# SDK Public Interface Draft

## 목적

이 문서는 `dms` 프로젝트가 다른 Python 프로젝트에서 import 해서 사용할 수 있는 SDK로 배포될 때의 public interface 초안을 정의한다.

본 초안은 현재 `SRS.md`와 `docmesh-py-core` 기반 설계 원칙을 반영한다.

## 설계 원칙

- SDK 소비자는 MinIO/PostgreSQL 초기화 세부사항을 직접 다루지 않아야 한다.
- SDK public API는 문서 업로드/조회/삭제/헬스체크라는 핵심 유스케이스 중심으로 노출한다.
- 설정 로드와 외부 서비스 초기화는 `docmesh-py-core` lifecycle 패턴을 따른다.
- 예외는 비즈니스 의미를 가진 타입으로 구분한다.
- 메타데이터 조회와 원문 조회를 분리해 필요한 비용만 지불하도록 한다.

## 권장 import 형태

```python
from dms.sdk import (
    DocumentManagementSDK,
    UploadDocumentRequest,
    UploadDocumentResult,
    DocumentMetadata,
    DocumentContent,
    DeleteDocumentResult,
    HealthStatus,
)
```

## 핵심 인터페이스

### `DocumentManagementSDK`

```python
class DocumentManagementSDK(Protocol):
    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult: ...
    def get_document_metadata(self, document_id: str) -> DocumentMetadata: ...
    def get_document_content(self, document_id: str) -> DocumentContent: ...
    def delete_document(self, document_id: str, *, hard_delete: bool = False) -> DeleteDocumentResult: ...
    def check_health(self) -> HealthStatus: ...
    def close(self) -> None: ...
```

### 책임

- `upload_document(...)`
  - 파일과 메타데이터를 받아 MinIO + metadata store에 반영
- `get_document_metadata(...)`
  - 문서 메타데이터만 조회
- `get_document_content(...)`
  - 원문 바이트/스트림 정보 조회
- `delete_document(...)`
  - soft/hard delete 정책에 따라 삭제 처리
- `check_health()`
  - PostgreSQL/MinIO 등 핵심 의존성 상태 확인
- `close()`
  - registry/client/resource 종료

## 요청/응답 모델

### `UploadDocumentRequest`

필수 필드
- `content: bytes`
- `filename: str`
- `content_type: str`

선택 필드
- `document_id: str | None`
- `metadata: Mapping[str, Any]`
- `created_by: str | None`
- `checksum: str | None`

### `UploadDocumentResult`

- `document_id: str`
- `metadata: DocumentMetadata`
- `storage_key: str`
- `created: bool`

### `DocumentMetadata`

- `document_id`
- `original_filename`
- `content_type`
- `file_size`
- `storage_key`
- `checksum`
- `status`
- `created_at`
- `updated_at`
- `deleted_at`
- `created_by`
- `extra_metadata`

### `DocumentContent`

- `document_id`
- `content: bytes`
- `content_type`
- `filename`
- `size`
- `checksum`

### `DeleteDocumentResult`

- `document_id`
- `deleted`
- `hard_deleted`
- `status`

### `HealthStatus`

- `ok`
- `services`
- `checked_at`

## 예외 모델 초안

```python
DmsError
├── ConfigurationError
├── ValidationError
├── DocumentNotFoundError
├── DuplicateDocumentError
├── StorageError
├── MetadataStoreError
├── ConsistencyError
└── HealthCheckFailedError
```

## 팩토리 진입점 초안

```python
from os import environ
from dms.sdk import create_sdk

sdk = create_sdk(environ)
try:
    result = sdk.upload_document(...)
finally:
    sdk.close()
```

### `create_sdk(env)` 책임

- `docmesh-py-core.load_settings(env)` 호출
- `ServiceFactoryRegistry(settings)` 생성
- metadata store / object store 구현체 조립
- startup 시 필수 의존성 health check 수행
- `DocumentManagementSDK` 구현체 반환

## 스토리지 키 및 버킷 정책

초기 버전의 업로드 경로는 고정 규칙을 따른다.

- 버킷 선택: `MINIO_BUCKET` 환경변수로 주입된 단일 버킷 사용
- object key prefix: 항상 `documents/`
- object key 형식: `documents/{document_id}/{sanitized_filename}`
- `sanitized_filename` 규칙:
  - 앞뒤 공백 제거
  - `/`, `\`는 `-`로 치환
  - `..`는 `.`로 축약
  - 정규화 결과가 `.` 또는 빈 문자열이면 업로드 거부

예시:
- 입력 filename: ` ../nested\quarterly/report..pdf `
- 저장 key: `documents/<document_id>/.-nested-quarterly-report.pdf`

## 충돌 정책

- 문서 식별자 충돌 기준은 `document_id`다.
- 동일한 `document_id`로 재업로드하면 `DuplicateDocumentError`를 반환한다.
- 동일한 원본 파일명은 서로 다른 `document_id`에서 허용된다.
- 따라서 파일명 자체는 전역 유일성을 요구하지 않으며, 저장 경로의 유일성은 `document_id` 디렉터리로 확보한다.

## 삭제/보상 정책

- 업로드 중 object 저장 성공 후 metadata 저장 실패 시 object를 즉시 삭제해 orphan을 남기지 않는다.
- soft delete는 object를 삭제한 뒤 metadata status를 `deleted`로 전환한다.
- hard delete는 object를 삭제한 뒤 metadata row를 제거한다.
- object 삭제와 metadata 후속 처리 사이에서 실패가 발생하면 `ConsistencyError`를 반환한다.

## 비동기 확장 방향

초기 버전은 동기 SDK를 우선한다. 향후 필요 시 아래를 별도 노출할 수 있다.

- `AsyncDocumentManagementSDK`
- NATS 기반 비동기 후처리 훅
- presigned URL 발급 유틸리티

## 패키지 구조 제안

- `dms/sdk/`
  - public interface
  - request/response models
  - factory
  - facade/client
- `dms/domain/`
  - metadata entity
  - storage ports
  - business policies
- `dms/infrastructure/`
  - postgres metadata store
  - sqlite metadata store
  - minio object store

## 현재 저장소 반영 상태

이 문서와 함께 다음 초안 코드가 추가된다.

- `dms/sdk/client.py`
- `dms/sdk/types.py`
- `dms/domain/models.py`
- `dms/domain/interfaces.py`
