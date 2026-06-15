---
title: Document lifecycle and consistency
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [document, lifecycle, consistency, storage, reliability]
sources: [raw/articles/dms-srs-2026-06-15.md]
confidence: medium
---

# Document lifecycle and consistency

DMS SRS는 업로드와 삭제를 단순 CRUD 호출이 아니라 원문 저장소와 메타데이터 저장소 사이의 일관성 문제로 정의한다. 업로드 시에는 MinIO 저장 성공 후 PostgreSQL 저장 실패를 어떻게 보상할지 결정해야 하고, 삭제 시에는 파일과 메타데이터 중 무엇을 먼저 처리할지 정책이 필요하다.

## 업로드 일관성
- object 저장 성공 후 metadata 저장 실패 시 orphan cleanup 또는 보상 트랜잭션 전략이 필요하다.
- metadata 반영 전에는 완료로 간주하면 안 된다.

## 삭제 일관성
- soft delete와 hard delete를 구분해야 한다.
- 부분 실패 시 재시도 가능한 상태 모델이 필요하다.
- 복구 절차를 운영 문서와 코드에 함께 남겨야 한다.

## 설계 시사점
- 일관성 정책은 SDK 예외 모델과 직접 연결된다.
- health check는 현재 상태만 보여 주지만, consistency policy는 실패 후 어떻게 회복할지까지 다뤄야 한다.
- object key 규칙과 metadata schema는 lifecycle policy를 전제로 설계되어야 한다.

## 관련 페이지
- [[dms-sdk]]
- [[document-metadata-model]]
- [[service-health-checking]]
- [[sdk-public-interface]]
