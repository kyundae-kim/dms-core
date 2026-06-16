---
title: DMS SDK
created: 2026-06-15
updated: 2026-06-16
type: entity
tags: [sdk, document, metadata, storage, client-library]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# DMS SDK

`dms` 프로젝트는 MinIO에 원문을 저장하고 PostgreSQL에 문서 메타데이터를 저장하는 문서 관리 기능을 Python SDK 형태로 제공하는 패키지다. SRS가 제품 형태를 규정하고, SDK interface 초안이 `DocumentManagementSDK`, 요청/응답 모델, 예외 계층, `create_sdk(env)` 조립, storage key/삭제 보상 정책까지 계약 수준에서 구체화한다.^[raw/articles/dms-sdk-interface-2026-06-15.md]

## 핵심 역할
- 문서 업로드, 조회, 삭제를 SDK 인터페이스로 노출한다.
- 원문 저장과 메타데이터 저장 책임을 분리한다.
- `docmesh-py-core`를 기반으로 설정 로드, 서비스 초기화, health check 규약을 재사용한다.
- SQLite를 로컬/테스트용 대체 저장소로 허용하면서 운영 기본 경로는 PostgreSQL + MinIO로 둔다.

## 설계 시사점
- public contract는 HTTP endpoint보다 함수/클래스 중심으로 정의되어야 한다.
- 소비 프로젝트는 `load_settings()` → registry 생성 → check → close 흐름을 공유해야 한다.
- 문서 lifecycle, 메타데이터 스키마, storage key 규칙, 삭제 일관성 정책이 SDK 인터페이스와 함께 진화해야 한다.

## 관련 페이지
- [[docmesh-py-core]]
- [[sdk-consumption-patterns]]
- [[document-metadata-model]]
- [[document-lifecycle-and-consistency]]
- [[sdk-public-interface]]
- [[sdk-factory-assembly]]
