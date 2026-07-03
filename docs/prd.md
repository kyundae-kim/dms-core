# Product Requirements Document (PRD)

## 1. 문서 목적

본 문서는 `docs/SRS.md`에 정의된 소프트웨어 요구사항을 제품 관점으로 재구성한 제품 요구사항 문서다.
목표는 구현 세부사항을 반복하는 것이 아니라, `dms`가 어떤 문제를 해결하는 제품인지, 누구를 위한 것인지,
어떤 사용자 가치와 운영 기준을 만족해야 하는지를 명확히 하는 데 있다.

이 문서는 다음에 답한다.
- 왜 이 SDK가 필요한가
- 누가 어떤 상황에서 사용하는가
- MVP에서 반드시 제공해야 하는 사용자 가치가 무엇인가
- 성공한 제품으로 보기 위한 품질 기준은 무엇인가

## 2. 제품 개요

`dms`는 다른 Python 애플리케이션이 문서 저장 기능을 빠르게 내장할 수 있도록 돕는 문서 관리 SDK다.
이 제품은 독립 실행형 웹 서비스가 아니라 import 해서 사용하는 라이브러리이며,
문서 본문은 MinIO에 저장하고 문서 metadata는 PostgreSQL 또는 SQLite에 저장한다.

제품이 해결하는 핵심 문제:
- 애플리케이션마다 문서 업로드/조회/삭제 로직을 중복 구현해야 하는 문제
- 문서 content 저장소와 metadata 저장소 간 일관성 처리 부담
- 환경별 저장소 설정, health check, 인증 helper 조립을 각 프로젝트가 직접 처리해야 하는 문제

## 3. 제품 비전

애플리케이션 개발자가 최소한의 코드와 명확한 계약만으로,
운영 가능한 문서 저장 기능을 안전하게 자신의 서비스 안에 포함할 수 있게 한다.

## 4. 목표

### 4.1 비즈니스/제품 목표
- Python 기반 내부 서비스들이 공통 문서 관리 기능을 재사용 가능한 SDK 형태로 도입할 수 있게 한다.
- 문서 저장 기능의 구현 편차를 줄이고 운영 안정성을 높인다.
- 문서 lifecycle(upload, read, delete, health, optional auth)을 표준화한다.

### 4.2 사용자 목표
- 개발자는 환경 설정만으로 SDK를 쉽게 조립할 수 있어야 한다.
- 개발자는 문서 업로드/조회/삭제를 예측 가능한 예외 모델과 타입 안정성으로 호출할 수 있어야 한다.
- 운영자는 startup 시점에 storage/backend readiness를 빠르게 확인할 수 있어야 한다.

## 5. 대상 사용자

### 5.1 1차 사용자
- Python 백엔드 개발자
- 플랫폼/SDK 통합 개발자
- 내부 서비스 운영자

### 5.2 사용 맥락
- 사내 서비스에서 첨부파일, 결과물, 리포트, 증빙 문서를 저장해야 하는 경우
- 문서 본문 저장과 metadata 관리를 분리해야 하는 경우
- PostgreSQL 기반 운영 환경과 SQLite 기반 로컬/테스트 환경을 함께 지원해야 하는 경우

## 6. 핵심 사용자 시나리오

### 시나리오 1. 서비스에 문서 업로드 기능 추가
개발자는 `dms.sdk`를 import 하고 환경 기반 factory로 SDK를 생성한 뒤,
`upload_document()`를 호출해 문서를 저장한다.
업로드가 끝나면 document ID, storage key, metadata를 즉시 받을 수 있어야 한다.

### 시나리오 2. 저장된 문서의 metadata와 본문 조회
개발자는 `document_id`만으로 metadata, 전체 content, 또는 stream content를 조회할 수 있어야 한다.
대용량 파일은 전체 메모리 로드 없이 stream 방식으로 처리할 수 있어야 한다.

### 시나리오 3. 문서 삭제와 운영 복구 신호 확인
개발자는 soft delete 또는 hard delete를 선택할 수 있어야 한다.
삭제 도중 object storage 또는 metadata 후속 처리 실패가 발생하면,
SDK는 예외를 반환할 뿐 아니라 복구에 필요한 상태 신호를 metadata에 남겨야 한다.

### 시나리오 4. 환경별 조립과 readiness 확인
운영자 또는 애플리케이션 bootstrap 코드는 환경변수 기반으로 SDK를 조립하고,
필요 시 startup health check를 통해 metadata backend, MinIO, optional auth 의존성 상태를 검증할 수 있어야 한다.

### 시나리오 5. 인증이 필요한 통합 환경
인증이 활성화된 서비스는 optional Keycloak helper를 통해 access token 발급 또는 사용자 인증 정보를 조회할 수 있어야 한다.
인증이 비활성인 환경에서는 기능 부재가 명확한 예외로 표현되어야 한다.

## 7. 제품 범위

### 7.1 MVP 포함 범위
- 문서 업로드
- 문서 metadata 조회
- 문서 본문 전체 조회
- 문서 본문 스트리밍 조회
- soft delete / hard delete
- MinIO 기반 object storage
- PostgreSQL 또는 SQLite 기반 metadata store
- 환경 기반 SDK factory
- 런타임 및 startup health check
- 선택적 Keycloak auth helper
- 구조화된 오류 모델과 로깅

### 7.2 현재 범위 제외
- presigned URL 발급
- 문서 검색/필터링
- 문서 버전 관리
- 비동기 후처리
- 감사 로그 저장
- 멀티테넌시
- 자체 권한 모델 구현

## 8. 제품 원칙

1. SDK-first
   - 제품은 서버가 아니라 import 가능한 Python SDK로 제공되어야 한다.

2. Operationally safe by default
   - 설정 오류, 의존성 미준비, storage inconsistency를 조기에 드러내야 한다.

3. Predictable contract
   - public API, 반환 타입, 예외 타입이 문서와 일치해야 한다.

4. Environment-flexible
   - 운영 환경에서는 PostgreSQL + MinIO, 로컬/테스트에서는 SQLite + MinIO 조합을 허용해야 한다.

5. Recoverable lifecycle
   - 삭제/저장 중 부분 실패가 발생해도 운영자가 상태를 관찰하고 복구할 수 있어야 한다.

## 9. 기능 요구사항

### PR-1. 쉬운 조립
- 개발자는 환경 기반 factory 또는 명시적 dependency injection 방식으로 SDK를 생성할 수 있어야 한다.
- MinIO와 metadata backend가 올바르게 설정되지 않으면 SDK 생성은 즉시 실패해야 한다.
- PostgreSQL 설정이 있으면 우선 사용하고, 없으면 SQLite fallback을 사용할 수 있어야 한다.

### PR-2. 문서 업로드 경험
- 개발자는 content, filename, content_type 중심의 단순한 요청 객체로 문서를 업로드할 수 있어야 한다.
- caller가 `document_id`를 생략하면 SDK가 식별자를 생성해야 한다.
- 업로드 성공 시 호출자는 이후 조회/삭제에 필요한 document ID와 저장 결과를 받아야 한다.
- 중복 `document_id`는 명확히 거부되어야 한다.

### PR-3. 신뢰 가능한 조회 경험
- 개발자는 같은 `document_id`를 기준으로 metadata와 content를 일관되게 조회할 수 있어야 한다.
- 작은 파일은 전체 바이트 조회, 큰 파일은 stream 조회를 선택할 수 있어야 한다.
- metadata는 존재하지만 object가 없는 비정상 상태는 일반 not-found가 아니라 일관성 오류로 구분되어야 한다.

### PR-4. 운영 가능한 삭제 경험
- soft delete와 hard delete를 명시적으로 선택할 수 있어야 한다.
- 삭제 시작과 실패 상태가 metadata에 반영되어 운영자가 후속 조치를 판단할 수 있어야 한다.
- object 삭제 후 metadata 후속 처리 실패는 호출자에게 명확히 전달되어야 한다.

### PR-5. 상태 확인 가능성
- SDK는 health check API를 제공해야 한다.
- startup health check가 활성화된 경우 생성 시점에 핵심 의존성 상태를 검증해야 한다.
- health 결과는 전체 성공 여부와 서비스별 상태를 함께 제공해야 한다.

### PR-6. 선택적 인증 지원
- 인증이 필요한 제품 환경에서는 access token 발급 및 사용자 인증 정보 조회 helper를 사용할 수 있어야 한다.
- 인증이 비활성인 환경에서는 관련 메서드가 조용히 실패하지 않고 설정 오류를 명확히 반환해야 한다.

### PR-7. 개발자 친화적 계약
- public namespace는 `dms.sdk`로 일관되게 제공되어야 한다.
- 주요 요청/응답/오류 타입은 재사용 가능한 public contract로 노출되어야 한다.
- README와 interface 문서는 실제 import/호출 방식과 일치해야 한다.

## 10. 비기능 요구사항

### NFR-1. 안정성
- 문서 저장과 metadata 저장 간 부분 실패를 orphan 또는 침묵 오류로 남기지 않아야 한다.
- rollback 실패 시에는 운영 복구가 필요한 상태임을 오류와 metadata 상태로 드러내야 한다.

### NFR-2. 가시성
- SDK는 logger를 받아 operation 단위 진단 정보를 남길 수 있어야 한다.
- 로그에는 `dms_` prefix 기반 추가 필드를 사용할 수 있어야 한다.
- raw token, document content 등 민감정보는 로그에 직접 남기지 않아야 한다.

### NFR-3. 테스트 가능성
- 단위 테스트에서는 fake store 기반으로 기능을 검증할 수 있어야 한다.
- adapter 테스트와 integration 테스트를 통해 저장소 round-trip을 검증할 수 있어야 한다.
- integration 테스트는 별도 compose 의존 없이 기존 환경을 재사용하거나 skip 되어야 한다.

### NFR-4. 호환성
- Python 3.11 이상에서 동작해야 한다.
- `docmesh-py-core` 기반 설정 조립과 호환되어야 한다.

## 11. 성공 지표

### 정성 지표
- 개발자가 별도 서비스 구현 없이 SDK import만으로 문서 기능을 통합할 수 있다고 느낀다.
- 운영자가 startup 실패와 storage inconsistency를 빠르게 파악할 수 있다.
- 문서와 실제 API 간 불일치가 줄어든다.

### 정량/검증 지표
- 핵심 lifecycle(upload, metadata read, content read, stream read, delete, health, auth helper)가 자동 테스트로 검증된다.
- PostgreSQL/SQLite/MinIO adapter round-trip이 테스트로 검증된다.
- 필수 환경변수가 없는 integration 테스트는 실패 대신 skip 된다.

## 12. 출시 승인 기준

다음을 만족하면 현재 제품 요구사항을 충족한 것으로 본다.
1. 환경 기반 SDK 생성이 설정 로드, backend 선택, startup health check를 수행한다.
2. SDK가 MinIO와 metadata store를 사용해 업로드/조회/삭제를 수행한다.
3. soft delete/hard delete와 부분 실패 상태 semantics가 테스트로 검증된다.
4. 전체 다운로드와 스트리밍 다운로드가 모두 동작한다.
5. auth helper 활성/비활성 경로가 모두 검증된다.
6. README 및 SDK interface 문서가 실제 public API와 일치한다.

## 13. 향후 확장 후보

- presigned URL 기반 외부 다운로드/업로드 지원
- metadata 검색 및 필터링
- 문서 버전 관리
- 비동기 이벤트/후처리 연동
- 감사 로그 및 규제 대응 기능
- 멀티테넌시와 권한 모델 확장

## 14. SRS 추적성

본 PRD는 다음 SRS 범위를 제품 요구사항으로 재해석한다.
- 초기화/설정/health check: FR-1 ~ FR-4
- 문서 lifecycle: FR-5 ~ FR-11
- 데이터/스토리지 계약: FR-12 ~ FR-18
- 오류/로깅/테스트 가능성: 12장 ~ 14장

즉, SRS가 “어떻게 동작해야 하는가”를 정의한다면,
본 PRD는 “왜 필요한가, 누구에게 어떤 가치로 제공되는가, 어떤 수준이면 제품으로 성공인가”를 정의한다.
