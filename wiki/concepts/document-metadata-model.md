---
title: Document metadata model
created: 2026-06-15
updated: 2026-06-16
type: concept
tags: [document, metadata, schema, database, sdk]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# Document metadata model

DMS SRS는 문서 원문과 별개로 관리되는 최소 메타데이터 모델을 정의한다. SDK interface 초안은 이를 `DocumentMetadata` 반환 모델로 연결하며, `storage_key`, `deleted_at`, `created_by`, `extra_metadata`까지 포함한 Python 타입으로 노출하는 방향을 제시한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 왜 중요한가
- 원문 저장소와 메타데이터 저장소의 책임을 분리할 수 있다.
- 다운로드 없이도 문서 목록/상태/추적 정보를 다룰 수 있다.
- SQLite와 PostgreSQL 사이에서 같은 도메인 모델을 유지할 수 있다.

## 상태 모델
- `uploaded`
- `available`
- `deleting`
- `deleted`
- `failed`

## 필드 시사점
- `storage_key`는 `documents/{document_id}/{sanitized_filename}` 규칙을 따르므로 object 위치와 문서 식별자를 함께 추적한다.
- `deleted_at`는 soft delete/hard delete 경로 차이를 설명하는 핵심 timestamp다.
- `created_by`와 `extra_metadata`는 감사/확장 요구를 흡수하되, 핵심 도메인 필드와 분리돼야 한다.
- `checksum`은 content 검증과 중복 분석에 쓸 수 있지만, 현재 충돌 기준은 파일명이 아니라 `document_id`다.

## 설계 시사점
- metadata schema는 SDK public interface와 함께 버전 관리되어야 한다.
- `document_id` 유니크 제약과 `storage_key` 규칙이 함께 정의되어야 저장 경로 충돌을 방지할 수 있다.
- soft delete 여부에 따라 `deleted_at`와 status semantics가 달라질 수 있다.
- SDK request/response 모델과 저장소 스키마가 필드 수준에서 어긋나지 않아야 한다.

## 관련 페이지
- [[dms-sdk]]
- [[storage-backend-selection]]
- [[postgres-configuration]]
- [[sdk-public-interface]]
- [[sdk-factory-assembly]]
- [[document-lifecycle-and-consistency]]
