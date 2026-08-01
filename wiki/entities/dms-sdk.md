---
title: DMS SDK
created: 2026-06-15
updated: 2026-07-19
type: entity
tags: [sdk, document, metadata, storage, client-library]
sources: [raw/articles/dms-srs-2026-06-15.md, raw/articles/dms-sdk-interface-2026-06-15.md]
confidence: medium
---

# DMS SDK

`dms` 프로젝트는 MinIO에 원문을 저장하고 PostgreSQL 또는 SQLite에 문서 메타데이터를 저장하는 문서 관리 기능을 Python SDK 형태로 제공하는 패키지다. 현재 공개 API와 예제는 [`docs/api.md`](../../docs/api.md), [`docs/config.md`](../../docs/config.md), [`docs/examples.md`](../../docs/examples.md)에 source/test 추적성과 함께 정리되어 있다. PRD/SRS는 제품·소프트웨어 요구사항의 역할을 유지하고, API reference가 실제 export와 method contract를 담당한다.

## 핵심 역할
- 문서 업로드, 조회, 삭제를 SDK 인터페이스로 노출한다.
- 전체 바이트 조회와 chunked stream 조회를 모두 SDK 계약에 포함한다.
- 원문 저장과 메타데이터 저장 책임을 분리한다.
- 호스트가 생성한 client 또는 저장소 component를 주입받고, SDK가 소유할 자원만 명시적으로 종료한다.
- client dialect 검증, 선택적 startup/runtime health check, rollback cleanup을 조립 계약으로 제공한다.
- SQLite를 로컬/테스트용 대체 저장소로 허용하면서 운영 기본 경로는 PostgreSQL + MinIO로 둔다.
- 환경변수에서 client를 자동 생성하는 factory와 인증 helper는 공개 범위에 포함하지 않는다.

## 설계 시사점
- public contract는 HTTP endpoint보다 함수/클래스 중심으로 정의되어야 한다.
- 소비 프로젝트는 자체 설정 계층에서 client를 만든 뒤 explicit dependency injection factory를 호출하고, `check_health()`/`close()` 수명주기를 관리해야 한다.
- 문서 lifecycle, 메타데이터 스키마, storage key 규칙, 삭제 일관성 정책이 SDK 인터페이스와 함께 진화해야 한다.
- SRS/README/API reference/example은 각각의 문서 역할을 지키면서 현재 코드/테스트 기준으로 함께 갱신되어야 한다.

## 관련 페이지
- [[docmesh-py-core]]
- [[sdk-consumption-patterns]]
- [[document-metadata-model]]
- [[document-lifecycle-and-consistency]]
- [[sdk-public-interface]]
- [[sdk-factory-assembly]]
- `docs/api.md` — 전체 공개 export, method, 오류 및 추적성 매트릭스
- `docs/config.md` — component/client 조립과 ownership 정책
- `docs/examples.md` — 동기·비동기 소비 예제
