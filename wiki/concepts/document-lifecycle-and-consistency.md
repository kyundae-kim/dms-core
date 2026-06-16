---
title: Document lifecycle and consistency
created: 2026-06-15
updated: 2026-06-16
type: concept
tags: [document, lifecycle, consistency, storage, reliability]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# Document lifecycle and consistency

DMS SRS는 업로드와 삭제를 단순 CRUD 호출이 아니라 원문 저장소와 메타데이터 저장소 사이의 일관성 문제로 정의한다. 최신 SDK interface 초안은 이 추상 요구를 더 구체화해, object 저장 성공 후 metadata 저장 실패 시 즉시 object를 삭제하고, soft delete/hard delete 모두 object 삭제 뒤 metadata 후속 처리를 수행하도록 명시한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 업로드 일관성
- object 저장 성공 후 metadata 저장 실패 시 즉시 orphan cleanup을 수행해야 한다.
- metadata 반영 전에는 완료로 간주하면 안 된다.
- 보상 삭제까지 실패하면 호출자는 `ConsistencyError`를 받아 후속 복구 절차를 시작할 수 있어야 한다.

## 삭제 일관성
- delete 시작 시 metadata status를 먼저 `deleting`으로 전환해 부분 실패를 후속 조회에서 감지할 수 있어야 한다.
- soft delete는 object를 삭제한 뒤 metadata status를 `deleted`로 전환한다.
- hard delete는 object를 삭제한 뒤 metadata row를 제거한다.
- object 삭제 자체가 실패하면 metadata status를 `failed`로 남기고 호출자에게 `StorageError`를 반환할 수 있다.
- object 삭제와 metadata 후속 처리 사이에서 실패가 발생하면 `ConsistencyError`를 반환하고 metadata는 `deleting` 상태로 남아 운영 복구/재시도 신호 역할을 한다.

## 충돌/경로 정책과의 연결
- 충돌 기준은 파일명이 아니라 `document_id`다.
- 동일 파일명은 다른 `document_id` 아래에서 공존할 수 있으므로, storage key는 `document_id` 디렉터리 경계를 전제로 한다.
- 파일명 정규화 규칙은 경로 traversal 성격의 입력을 object key 수준에서 약화시키는 첫 방어선이다.

## 설계 시사점
- 일관성 정책은 [[sdk-exception-model]]과 직접 연결된다.
- health check는 현재 상태만 보여 주지만, consistency policy는 실패 후 어떻게 회복할지까지 다뤄야 한다.
- object key 규칙과 metadata schema는 lifecycle policy를 전제로 설계되어야 한다.

## 관련 페이지
- [[dms-sdk]]
- [[document-metadata-model]]
- [[service-health-checking]]
- [[sdk-public-interface]]
- [[sdk-exception-model]]
- [[minio-configuration]]
