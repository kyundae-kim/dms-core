---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.1/docs/config.md
ingested: 2026-06-15
sha256: 6445da8c4d83fb59911a34cb1b10a3b4a8ef6d6279959246dadff5af89433174
---

# docmesh-py-core 설정 가이드

## 개요

이 문서는 `docs/prd.md`를 바탕으로 `docmesh-py-core`의 환경변수 규칙과
서비스별 설정 항목을 정리한다.

핵심 목표는 다음과 같다.

- 외부 서비스 연결 정보를 환경변수로 일관되게 관리
- 필수값, 기본값, 조건부 필수값을 명확히 정의
- 민감정보를 안전하게 주입하고 로그에 노출하지 않도록 운영
- 환경별 코드 변경 없이 설정만으로 동작하도록 지원

---

## 공통 원칙

### 기본 규칙

- 모든 설정은 환경변수에서 읽는다.
- 코드에 URL, 계정, 비밀번호, 토큰, secret key를 하드코딩하지 않는다.
- 애플리케이션 시작 시 설정을 1회 로드하고 검증한다.
- 공백 문자열은 값이 없는 것으로 간주한다.
- boolean 값은 대소문자와 관계없이 `true` / `false`로 해석한다.
- 숫자형 값은 허용 범위를 검증한다.
- 민감정보는 Secret Manager, CI secret, 배포 플랫폼 secret 주입 기능을 사용한다.

### 환경별 운영 규칙

- 로컬/개발/스테이징/운영은 코드가 아니라 환경변수로 구분한다.
- 운영 환경에서는 TLS와 인증서 검증을 기본값으로 유지한다.
- SSL 검증 비활성화는 개발/테스트에서만 허용하는 정책을 권장한다.
- Langfuse 같은 선택 기능은 비활성화 가능해야 하며 핵심 서비스 장애와 분리한다.
- integration 테스트는 운영 설정과 분리된 별도 테스트용 환경변수 세트를 사용한다.

---

## 공통 환경변수

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `DOCMESH_ENV` | 아니요 | `development` | 실행 환경 식별자 |
| `DOCMESH_HEALTHCHECK_ENABLED` | 아니요 | `true` | health check 활성화 여부 |

참고:

- 공통 timeout/retry/pool 설정은 제공하지 않는다.
- timeout/retry는 반드시 서비스별 환경변수로 관리한다.

### integration 테스트용 공통 권장값

- `DOCMESH_ENV=integration` 또는 팀에서 합의한 별도 값 사용
- `DOCMESH_HEALTHCHECK_ENABLED=true` 유지 권장
- integration 테스트 전용 `.env.integration` 또는 CI secret 세트를 별도로 관리
- 운영용 host, database, realm, bucket, credential을 재사용하지 않는다.

---

## Keycloak 설정

### 기본 인증

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KEYCLOAK_URL` | 예 | 없음 | Keycloak 기본 URL |
| `KEYCLOAK_REALM` | 예 | 없음 | 인증 Realm |
| `KEYCLOAK_CLIENT_ID` | 예 | 없음 | OIDC Client ID |
| `KEYCLOAK_CLIENT_SECRET` | 조건부 | 없음 | Confidential Client 사용 시 Secret |
| `KEYCLOAK_VERIFY_SSL` | 아니요 | `true` | TLS 인증서 검증 여부 |
| `KEYCLOAK_AUDIENCE` | 아니요 | 없음 | JWT 검증 대상 Audience |
| `KEYCLOAK_REQUEST_TIMEOUT_SECONDS` | 아니요 | `10` | OIDC/JWKS 요청 제한 시간 |
| `KEYCLOAK_MAX_RETRIES` | 아니요 | `3` | 일시적 HTTP 오류 최대 재시도 횟수 |

### 토큰 획득

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KEYCLOAK_TOKEN_GRANT_TYPE` | 아니요 | `client_credentials` | 토큰 획득 grant type |
| `KEYCLOAK_TOKEN_SCOPE` | 아니요 | 없음 | 토큰 요청 시 전달할 scope |
| `KEYCLOAK_TOKEN_USERNAME` | 조건부 | 없음 | password grant 사용 시 사용자명 |
| `KEYCLOAK_TOKEN_PASSWORD` | 조건부 | 없음 | password grant 사용 시 비밀번호 |

규칙:

- 기본 grant는 `client_credentials`이다.
- `KEYCLOAK_TOKEN_GRANT_TYPE=password`이면 `KEYCLOAK_TOKEN_USERNAME`, `KEYCLOAK_TOKEN_PASSWORD`가 필요하다.
- password grant는 제한된 내부/레거시 용도로만 사용을 권장한다.
- public client가 아니면 `KEYCLOAK_CLIENT_SECRET`이 필요할 수 있다.

### 프로비저닝

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KEYCLOAK_PROVISIONING_ENABLED` | 아니요 | `false` | 프로비저닝 활성화 여부 |
| `KEYCLOAK_PROVISIONING_DRY_RUN` | 아니요 | `false` | 변경 없이 실행 계획만 출력 |
| `KEYCLOAK_ADMIN_REALM` | 조건부 | `master` | Admin API 인증 Realm |
| `KEYCLOAK_ADMIN_CLIENT_ID` | 조건부 | `admin-cli` | Admin API 인증 Client ID |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | 조건부 | 없음 | Service Account 인증용 secret |
| `KEYCLOAK_ADMIN_USERNAME` | 조건부 | 없음 | 관리자 사용자명 인증 시 사용자명 |
| `KEYCLOAK_ADMIN_PASSWORD` | 조건부 | 없음 | 관리자 사용자명 인증 시 비밀번호 |
| `KEYCLOAK_REALM_ENABLED` | 아니요 | `true` | 대상 Realm 활성화 여부 |
| `KEYCLOAK_REALM_DISPLAY_NAME` | 아니요 | 없음 | 대상 Realm 표시 이름 |
| `KEYCLOAK_CLIENT_PUBLIC` | 아니요 | `false` | 생성할 client의 public 여부 |
| `KEYCLOAK_CLIENT_REDIRECT_URIS` | 아니요 | 없음 | 쉼표 구분 redirect URI 목록 |
| `KEYCLOAK_CLIENT_WEB_ORIGINS` | 아니요 | 없음 | 쉼표 구분 web origin 목록 |
| `KEYCLOAK_REALM_ROLES` | 아니요 | 없음 | 쉼표 구분 realm role 목록 |
| `KEYCLOAK_CLIENT_ROLES` | 아니요 | 없음 | 쉼표 구분 client role 목록 |

규칙:

- `KEYCLOAK_PROVISIONING_ENABLED=true`이면 Admin API 인증정보가 필요하다.
- 인증 방식은 아래 둘 중 하나만 사용한다.
  1. service account (`KEYCLOAK_ADMIN_CLIENT_ID` + `KEYCLOAK_ADMIN_CLIENT_SECRET`)
  2. 관리자 사용자명/비밀번호 (`KEYCLOAK_ADMIN_USERNAME` + `KEYCLOAK_ADMIN_PASSWORD`)
- 프로비저닝 대상 realm/client는 각각 `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`를 사용한다.
- 선언에서 제거된 리소스는 자동 삭제하지 않는다.

---

## PostgreSQL 설정

`POSTGRES_DSN`이 있으면 개별 연결 항목보다 우선한다.

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `POSTGRES_DSN` | 조건부 | 없음 | PostgreSQL 연결 URI |
| `POSTGRES_HOST` | 조건부 | 없음 | 데이터베이스 호스트 |
| `POSTGRES_PORT` | 아니요 | `5432` | 데이터베이스 포트 |
| `POSTGRES_DB` | 조건부 | 없음 | 데이터베이스 이름 |
| `POSTGRES_USER` | 조건부 | 없음 | 사용자명 |
| `POSTGRES_PASSWORD` | 조건부 | 없음 | 비밀번호 |
| `POSTGRES_SSLMODE` | 아니요 | `prefer` | PostgreSQL SSL 모드 |
| `POSTGRES_CONNECT_TIMEOUT_SECONDS` | 아니요 | `10` | 연결 제한 시간 |
| `POSTGRES_POOL_SIZE` | 아니요 | `5` | 기본 풀 크기 |
| `POSTGRES_MAX_OVERFLOW` | 아니요 | `10` | 추가 허용 연결 수 |

규칙:

- DSN을 쓰지 않으면 host/db/user/password 조합이 필요하다.
- 연결 문자열 원문은 로그/예외에 그대로 남기지 않는다.
- health check 기본 방식은 `SELECT 1`이다.

---

## SQLite 설정

SQLite는 로컬 개발, 단위 테스트, 경량 통합 테스트에서 PostgreSQL 대체 저장소로
사용할 수 있다.

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `SQLITE_PATH` | 조건부 | 없음 | SQLite 데이터베이스 파일 경로 또는 `:memory:` |
| `SQLITE_READONLY` | 아니요 | `false` | 읽기 전용 모드 사용 여부 |
| `SQLITE_ENABLE_WAL` | 아니요 | `false` | WAL 모드 활성화 여부 |
| `SQLITE_BUSY_TIMEOUT_MS` | 아니요 | `5000` | 잠금 대기 시간(ms) |

규칙:

- SQLite를 사용하지 않으면 위 환경변수는 비워둘 수 있다.
- `SQLITE_PATH=:memory:`는 프로세스 내 메모리 DB를 의미한다.
- 상대 경로는 애플리케이션 작업 디렉터리를 기준으로 해석한다.
- 파일 기반 SQLite는 상위 디렉터리가 존재해야 하며, 없으면 명확한 설정 오류를 반환한다.
- health check는 파일 접근 가능 여부 확인과 `SELECT 1` 실행으로 구성한다.
- 파일 경로는 로그/예외에 그대로 남기기보다 필요 시 축약 또는 마스킹한다.

---

## MinIO 설정

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MINIO_ENDPOINT` | 예 | 없음 | `host:port` 형식 endpoint |
| `MINIO_ACCESS_KEY` | 예 | 없음 | access key |
| `MINIO_SECRET_KEY` | 예 | 없음 | secret key |
| `MINIO_SECURE` | 아니요 | `true` | HTTPS 사용 여부 |
| `MINIO_REGION` | 아니요 | 없음 | region |
| `MINIO_BUCKET` | 아니요 | 없음 | 기본 bucket |
| `MINIO_REQUEST_TIMEOUT_SECONDS` | 아니요 | `30` | 요청 제한 시간 |
| `MINIO_MAX_RETRIES` | 아니요 | `3` | 일시적 요청 오류 최대 재시도 횟수 |

규칙:

- endpoint는 `host:port` 형태를 권장한다.
- health check는 bucket 존재 확인 또는 서버 응답 확인 방식으로 구현할 수 있다.
- secret key는 로그/예외/디버그 출력에 포함하지 않는다.

---

## Milvus 설정

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MILVUS_URI` | 예 | 없음 | Milvus 서버 URI |
| `MILVUS_TOKEN` | 조건부 | 없음 | 인증 토큰 |
| `MILVUS_DB_NAME` | 아니요 | `default` | 데이터베이스 이름 |
| `MILVUS_COLLECTION` | 아니요 | 없음 | 기본 collection |
| `MILVUS_SECURE` | 아니요 | `false` | TLS 사용 여부 |
| `MILVUS_CONNECT_TIMEOUT_SECONDS` | 아니요 | `10` | 연결 제한 시간 |
| `MILVUS_REQUEST_TIMEOUT_SECONDS` | 아니요 | `30` | 요청 제한 시간 |
| `MILVUS_MAX_RETRIES` | 아니요 | `3` | 일시적 연결/요청 오류 최대 재시도 횟수 |

규칙:

- health check는 서버 연결 확인 또는 collection 조회로 구현한다.
- token 사용 시 예외 메시지에 원문이 노출되지 않도록 한다.

---

## Ollama 설정

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `OLLAMA_HOST` | 예 | 없음 | Ollama API 기본 URL |
| `OLLAMA_GENERATION_MODEL` | 아니요 | 없음 | 기본 생성 모델 |
| `OLLAMA_EMBEDDING_MODEL` | 아니요 | 없음 | 기본 임베딩 모델 |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | 아니요 | `120` | 요청 제한 시간 |
| `OLLAMA_MAX_RETRIES` | 아니요 | `2` | 일시적 HTTP 오류 최대 재시도 횟수 |

규칙:

- health check는 버전 조회, 프로세스 조회, 모델 목록 조회 중 하나로 구현 가능하다.
- 모델명은 선택값이며 패키지 수준에서 모델 다운로드를 강제하지 않는다.

---

## Langfuse 설정

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `LANGFUSE_HOST` | 예 | 없음 | Langfuse API 기본 URL |
| `LANGFUSE_PUBLIC_KEY` | 예 | 없음 | public key |
| `LANGFUSE_SECRET_KEY` | 예 | 없음 | secret key |
| `LANGFUSE_ENABLED` | 아니요 | `true` | tracing 활성화 여부 |
| `LANGFUSE_RELEASE` | 아니요 | 없음 | 릴리스 식별자 |
| `LANGFUSE_ENVIRONMENT` | 아니요 | `DOCMESH_ENV` 값 | Langfuse 환경 식별자 |
| `LANGFUSE_REQUEST_TIMEOUT_SECONDS` | 아니요 | `10` | API 요청 제한 시간 |
| `LANGFUSE_MAX_RETRIES` | 아니요 | `3` | 일시적 전송 오류 최대 재시도 횟수 |

규칙:

- `LANGFUSE_ENABLED=false`이면 나머지 Langfuse 값은 선택 처리 가능하다.
- Langfuse 장애가 핵심 애플리케이션 기능을 중단시키지 않도록 선택적 비활성화를 지원한다.
- health check는 인증 API 요청 또는 클라이언트 검증 방식으로 수행한다.

---

## NATS 설정

| 환경변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `NATS_SERVERS` | 예 | 없음 | 쉼표 구분 NATS 서버 URL 목록 |
| `NATS_USER` | 조건부 | 없음 | 사용자명 인증 시 사용자명 |
| `NATS_PASSWORD` | 조건부 | 없음 | 사용자명 인증 시 비밀번호 |
| `NATS_TOKEN` | 조건부 | 없음 | 토큰 인증 시 토큰 |
| `NATS_CREDS_FILE` | 조건부 | 없음 | credentials 파일 경로 |
| `NATS_NAME` | 아니요 | `docmesh-py-core` | 클라이언트 연결 이름 |
| `NATS_CONNECT_TIMEOUT_SECONDS` | 아니요 | `10` | 연결 제한 시간 |
| `NATS_MAX_RECONNECT_ATTEMPTS` | 아니요 | `10` | 최대 재연결 횟수 |

규칙:

- 인증 방식은 아래 중 하나만 선택한다.
  - user/password
  - token
  - creds file
- `NATS_SERVERS`는 쉼표 구분 목록으로 파싱한다.
- health check는 connect 후 ping/pong 또는 flush 확인으로 수행한다.
- 비동기 SDK 특성에 맞게 이벤트 루프를 임의 생성/종료하지 않는다.

---

## 보안 운영 규칙

- `.env` 파일을 쓸 수는 있지만 실제 비밀정보가 포함된 파일은 git에 포함하지 않는다.
- 예외 메시지에는 비밀번호, secret, token, 전체 DSN/URI를 그대로 포함하지 않는다.
- DSN/URI 출력이 필요하면 사용자명/비밀번호/token/query 민감값을 마스킹한다.
- Access Token, Refresh Token, ID Token 원문은 로그/트레이싱에 기록하지 않는다.
- Keycloak 관리자 계정은 최소 권한 원칙을 따른다.
- 가능하면 관리자 사용자명/비밀번호보다 service account 방식을 우선 사용한다.

---

## 예시 `.env`

아래 예시는 `.env.example`과 동일한 문서용 예시이며 실제 secret 값은 넣지 않는다.

integration 테스트에서는 별도 `.env.integration` 또는 CI secret 세트를 사용하고,
테스트 대상 서비스도 운영 자원과 분리한다.

```env
DOCMESH_ENV=development
DOCMESH_HEALTHCHECK_ENABLED=true

KEYCLOAK_URL=https://keycloak.example.com
KEYCLOAK_REALM=docmesh
KEYCLOAK_CLIENT_ID=docmesh-backend
KEYCLOAK_CLIENT_SECRET=
KEYCLOAK_VERIFY_SSL=true
KEYCLOAK_AUDIENCE=
KEYCLOAK_TOKEN_GRANT_TYPE=client_credentials
KEYCLOAK_TOKEN_SCOPE=
KEYCLOAK_TOKEN_USERNAME=
KEYCLOAK_TOKEN_PASSWORD=
KEYCLOAK_REQUEST_TIMEOUT_SECONDS=10
KEYCLOAK_MAX_RETRIES=3
KEYCLOAK_PROVISIONING_ENABLED=false
KEYCLOAK_PROVISIONING_DRY_RUN=false
KEYCLOAK_ADMIN_REALM=master
KEYCLOAK_ADMIN_CLIENT_ID=admin-cli
KEYCLOAK_ADMIN_CLIENT_SECRET=
KEYCLOAK_ADMIN_USERNAME=
KEYCLOAK_ADMIN_PASSWORD=
KEYCLOAK_REALM_ENABLED=true
KEYCLOAK_REALM_DISPLAY_NAME=
KEYCLOAK_CLIENT_PUBLIC=false
KEYCLOAK_CLIENT_REDIRECT_URIS=
KEYCLOAK_CLIENT_WEB_ORIGINS=
KEYCLOAK_REALM_ROLES=
KEYCLOAK_CLIENT_ROLES=

POSTGRES_DSN=
POSTGRES_HOST=postgres.example.com
POSTGRES_PORT=5432
POSTGRES_DB=docmesh
POSTGRES_USER=docmesh
POSTGRES_PASSWORD=
POSTGRES_SSLMODE=prefer
POSTGRES_CONNECT_TIMEOUT_SECONDS=10
POSTGRES_POOL_SIZE=5
POSTGRES_MAX_OVERFLOW=10

MINIO_ENDPOINT=minio.example.com:9000
MINIO_ACCESS_KEY=minio-access-key
MINIO_SECRET_KEY=
MINIO_SECURE=true
MINIO_REGION=
MINIO_BUCKET=
MINIO_REQUEST_TIMEOUT_SECONDS=30
MINIO_MAX_RETRIES=3

MILVUS_URI=http://milvus.example.com:19530
MILVUS_TOKEN=
MILVUS_DB_NAME=default
MILVUS_COLLECTION=
MILVUS_SECURE=false
MILVUS_CONNECT_TIMEOUT_SECONDS=10
MILVUS_REQUEST_TIMEOUT_SECONDS=30
MILVUS_MAX_RETRIES=3

OLLAMA_HOST=http://ollama.example.com:11434
OLLAMA_GENERATION_MODEL=
OLLAMA_EMBEDDING_MODEL=
OLLAMA_REQUEST_TIMEOUT_SECONDS=120
OLLAMA_MAX_RETRIES=2

LANGFUSE_HOST=https://langfuse.example.com
LANGFUSE_PUBLIC_KEY=pk-live-placeholder
LANGFUSE_SECRET_KEY=
LANGFUSE_ENABLED=true
LANGFUSE_RELEASE=
LANGFUSE_ENVIRONMENT=
LANGFUSE_REQUEST_TIMEOUT_SECONDS=10
LANGFUSE_MAX_RETRIES=3

NATS_SERVERS=nats://n1.example.com:4222,nats://n2.example.com:4222
NATS_USER=
NATS_PASSWORD=
NATS_TOKEN=
NATS_CREDS_FILE=
NATS_NAME=docmesh-py-core
NATS_CONNECT_TIMEOUT_SECONDS=10
NATS_MAX_RECONNECT_ATTEMPTS=10
```

---

## 검증 체크리스트

설정 추가/변경 시 아래를 함께 확인한다.

- [ ] 필수 여부가 문서와 코드에서 일치하는가
- [ ] 기본값이 문서와 코드에서 일치하는가
- [ ] 조건부 필수 규칙이 문서와 코드에서 일치하는가
- [ ] 민감정보 항목이 마스킹 정책 대상에 포함되는가
- [ ] `.env.example`와 본 문서가 동기화되어 있는가
- [ ] integration 테스트용 설정이 운영 설정과 분리되어 있는가
- [ ] 테스트가 새 설정 항목을 검증하는가

---

## 문서 유지 원칙

다음 변경 시 이 문서를 함께 갱신한다.

- 신규 외부 서비스 추가
- 설정 필드 이름 변경
- 기본값 변경
- timeout/retry/security 정책 변경
- Keycloak provisioning/token/JWT 계약 변경
