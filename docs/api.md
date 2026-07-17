# 공개 API 계약

이 문서는 SDK의 공개 계약을 설명합니다. 파일명/메타데이터 일반 검색은 제공하지 않습니다.

## 등록과 멱등성

`UploadDocumentRequest`와 `UploadDocumentStreamRequest`는 `idempotency_key`와 `idempotency_scope`를 지원합니다. 멱등성 키를 사용한다면 테넌트·사용자 등 재시도 충돌 경계를 `idempotency_scope`에 명시하십시오. 이전 호출과의 호환을 위해 범위를 생략하면 `created_by`, 그마저 없으면 `anonymous`를 사용하지만 `DeprecationWarning`이 발생합니다. 스트림 멱등 등록에는 SHA-256 `checksum`이 필수입니다.

## 목록

- `list_documents(offset=0, limit=100, status=None) -> list[DocumentMetadata]`: 기존 오프셋 API입니다.
- `list_documents_page(cursor=None, limit=100, status=None) -> DocumentPage`: 커서 API입니다.
- `DocumentPage.items`: 현재 페이지 문서 정보
- `DocumentPage.next_cursor`: 다음 페이지가 있을 때만 제공되는 불투명 문자열
- `DocumentPage.has_more`: 다음 페이지 존재 여부

정렬은 `created_at DESC, document_id DESC`로 고정됩니다. 커서는 이 복합 키와 상태 필터를 보존하는 불투명 페이지 상태이며, 인증·인가 또는 보안 토큰이 아닙니다. 호출자는 커서를 해석하거나 변경하지 말고, 다음 호출에 같은 `status`와 함께 그대로 전달해야 합니다. 페이지 `limit`은 1~1000이며, 너무 길거나 잘못되었거나 다른 상태 필터에 사용된 커서는 `ValidationError`입니다.

## 삭제

- `soft_delete_document(document_id)`: 본문을 제거하고 메타데이터를 `DELETED`로 보존합니다.
- `hard_delete_document(document_id)`: 본문과 메타데이터를 제거합니다.
- `delete_document(document_id, hard_delete=False)`: 호환성을 위해 유지되는 기존 API입니다.

세 메서드 모두 `DeleteDocumentResult`를 반환합니다. 삭제의 부분 실패 상태 및 예외 계약은 기존과 같습니다.

## 자원 관리

SDK는 컨텍스트 관리자를 지원합니다. `with` 블록 종료 시 `close()`가 호출됩니다. `DocumentContentStream`도 컨텍스트 관리자로 사용해 스트림을 닫아야 합니다.

컨텍스트 관리자가 기본 사용 흐름입니다. SDK와 내려받기 스트림 모두 `with`로 감싸십시오. `DocumentMetadata.storage_key`는 저장소 어댑터 및 복구를 위한 **내부 필드**입니다. 외부 URL이나 영구 공개 식별자로 노출·저장·조합하지 마십시오.

## 등록 방식 결정표

| 입력 | 메서드 | 크기/체크섬 계약 |
| --- | --- | --- |
| 메모리 바이트 | `upload_document` | SDK가 계산 |
| 크기를 아는 스트림 | `upload_document_stream` | 선언 크기를 엄격 검증; 멱등 등록은 checksum 필수 |
| 크기를 모르는 스트림 | `upload_document_unknown_size_stream` | 필수 양수 `max_size`까지 임시 spool에 먼저 복사하여 크기와 SHA-256 계산 후 엄격 스트림 메서드에 위임 |

미지 크기 요청은 `UploadDocumentUnknownSizeStreamRequest`를 사용합니다. `max_size`는 SDK의 구성된 `max_file_size` 이하여야 하며 읽기 전에 검증됩니다. 메모리 spool 임계값과 최대 chunk 크기는 요청의 `max_size`와 독립적으로 보수적으로 제한됩니다. `max_size` 초과 시 저장소 등록 전에 `ValidationError`이며 임시 spool은 성공과 실패 모두에서 닫힙니다. 입력 스트림의 소유권은 호출자에게 있어 SDK가 닫지 않습니다.

## 업로드 작업 조회

`get_upload_operation(scope=..., idempotency_key=...) -> UploadOperationResult`는 정확한 범위와 키로 `PENDING`, `SUCCEEDED`, `FAILED` 상태, 문서 ID 및 시각을 반환합니다. fingerprint는 공개하지 않습니다. 작업 저장소가 필요하며, 정확한 조합이 없으면 결과의 `None`이 아니라 `UploadOperationNotFoundError`입니다. 빈 범위/키는 `ValidationError`입니다.

## 오류별 호출자 조치

| 오류 | 권장 조치 |
| --- | --- |
| `ValidationError` | 요청을 수정하고 새로 호출 |
| `IdempotencyInProgressError` | 같은 범위/키로 지연 후 상태 조회 또는 재시도 |
| `IdempotencyConflictError` | 같은 키를 다른 요청에 재사용하지 말고 새 키 사용 |
| `UploadOperationNotFoundError` | 범위와 키를 확인; 아직 요청하지 않은 작업으로 처리 |
| `DocumentNotFoundError` | 문서 ID 확인 또는 이미 삭제된 것으로 처리 |
| `StorageError` / `MetadataStoreError` | 백오프로 재시도하고 상태 점검 |
| `ConsistencyError` | 재시도 전에 점검·복구 API로 불일치 확인 |

## 상태 및 일괄 복구 요약

`DocumentStatus.UPLOADED`는 역직렬화 호환만을 위한 폐기 예정(legacy) 값이며 SDK의 정상 등록 흐름에서는 생성되지 않습니다. 정상 등록은 `AVAILABLE`을 생성합니다. `BatchReconciliationResult`는 안정적인 `scanned`, `eligible`, `applied`, `skipped`, `failed` 요약 속성을 제공합니다. `eligible`은 항목 오류가 없는 수, `skipped`는 eligible 중 적용되지 않은 수(예: dry-run)입니다.

## 공개 메타데이터와 스키마 검증

`public_metadata(value) -> PublicDocumentMetadata`는 `DocumentMetadata` 또는 `UploadDocumentResult`를 직접 받아 `storage_key`가 없는 독립 복사본을 만듭니다. 기존 모델과 반환 계약은 변경되지 않습니다.

`StructuredMetadataValidator(parser=..., schema_version=..., projector=..., policy=...)`는 외부 의존성 없는 `metadata_validator` 어댑터입니다. 버전 필드(기본 `schema_version`)를 먼저 확인하며 실패는 `MetadataSchemaValidationError.issues`의 `MetadataValidationIssue(path, code, message)`로 제공합니다. parser/projector 결과는 항상 구성 가능한 `DefaultMetadataPolicy`(기본값)를 통과하므로 JSON 직렬화, 깊이, 크기 및 중첩 blocked-key 제한을 우회할 수 없습니다. 기존 mapping-to-dict validator도 그대로 지원합니다. SDK는 Pydantic을 import하거나 선택 의존하지 않습니다.

## 복구 계획과 감사

dry-run 결과의 `to_plan()`은 원래 배치의 `status`와 `action`을 포함하고 불변 tuple 항목을 갖는 `ReconciliationPlan`을 내보냅니다. 항목 action은 plan action과 같아야 합니다. 실제 적용 결과에서는 계획을 내보낼 수 없습니다. `execute_reconciliation_plan(plan, actor=...)`은 저장된 점검 결과를 신뢰하지 않고 각 항목 직전에 다시 점검·검증하며, 오래되거나 예기치 않게 실패한 항목은 구조화된 항목별 오류로 반환하고 나머지 항목을 계속 처리합니다. 각 `reconcile_document(..., actor=...)` 시도에는 실행 시각과 선택적 실행 주체를 포함한 `RecoveryAuditEvent`가 발생합니다. `recovery_audit_hook`은 두 factory에 전달할 수 있으며 **best-effort**입니다. hook 예외는 로그만 남고 복구 성공/실패를 가리지 않습니다.
