---
title: Storage backend selection
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [storage, postgres, database, configuration]
sources: [raw/articles/docmesh-py-core-sdk-v0-1-1.md, raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/dms-srs-2026-06-15.md]
confidence: medium
---

# Storage backend selection

`docmesh-py-core`는 별도의 backend selector 플래그보다, 실제로 주입된 환경변수 존재 여부를 기준으로 저장소를 선택하는 패턴을 권장한다. 대표적으로 운영 환경에서는 PostgreSQL, 로컬/테스트에서는 SQLite를 사용하는 구성이 자연스러운 소비 패턴으로 제시된다.

## 선택 규칙
- `POSTGRES_*` 설정이 제공되면 PostgreSQL 경로를 사용한다.
- `SQLITE_*` 설정이 제공되면 SQLite 경로를 사용한다.
- `SQLITE_PATH=:memory:`는 테스트/로컬 실행에 유용한 메모리 DB 패턴이다.

## 설계 장점
- 별도 스위치 없이 실제 사용 의도를 설정 자체로 표현할 수 있다.
- 로컬/테스트/운영 저장소 구성을 코드 수정 없이 바꿀 수 있다.
- 소비 프로젝트가 조건 분기를 하더라도 `settings.sqlite is not None` 같은 명시적 규칙으로 단순화된다.

## 문서 서비스 관점의 의미
문서 metadata 저장소가 개발 단계에서는 SQLite, 운영에서는 PostgreSQL일 수 있으므로, 이 패턴은 서비스와 SDK 배포를 같은 코드베이스에서 유지하는 데 유리하다. 특히 로컬에서 빠르게 CRUD 흐름을 검증하고 운영에서는 풀 기반 PostgreSQL로 전환하는 경로를 깔끔하게 만든다.

DMS SRS는 PostgreSQL + MinIO를 기본 목표 경로로 두되, SQLite를 로컬/테스트용 대체 저장소로 허용하는 제품 요구사항을 명시한다.^[raw/articles/dms-srs-2026-06-15.md]

## 관련 페이지
- [[configuration-loading-and-validation]]
- [[postgres-configuration]]
- [[docmesh-py-core]]
- [[sdk-consumption-patterns]]
- [[dms-sdk]]
- [[document-metadata-model]]
