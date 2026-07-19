---
source_url: https://github.com/kyundae-kim/docmesh-py-core/wiki/Configuration-v0.4.0
ingested: 2026-07-19
sha256: c471ad729b3816172141206ccad1899e90887110a026de6257ab5718f6c0136f
---
# docmesh-py-core Configuration Guide

> 기준: **v0.4.0**. API의 반환값·오류·lifecycle은 [API Reference](./api.md)를, 실제 조립 순서는 [Examples](./examples.md)를 참조한다.

## 1. 설정 계약

1. 모든 `*Config`는 **프로세스 환경변수만** 읽는다. `KeycloakConfig(url=...)`처럼 생성자 인자로 주입하면 `TypeError`다.
2. 빈 문자열은 미설정으로 처리한다. boolean·숫자는 Pydantic 기본 coercion으로 파싱하고 범위 제약을 검증한다.
3. `load_service_configs()`는 선택한 서비스의 완전한 설정을 요구한다. `load_available_service_configs()`는 접두 변수가 전혀 없는 서비스만 건너뛰며 부분 설정은 거부한다.
4. service 목록은 대소문자와 무관하게 `keycloak`, `postgres`, `sqlite`, `minio`, `milvus`, `ollama`, `langfuse`, `nats`를 사용한다.
5. `DOCMESH_ENV`가 `prod`/`production`이거나 `DOCMESH_SECURITY_MODE=production`이면 production 보안 검증이 적용된다.

```bash
# 애플리케이션을 시작하는 쉘 또는 deployment secret injection 경로에서 설정한다.
export DOCMESH_ENV=development
export SQLITE_PATH=:memory:
```

## 2. 공통 환경변수

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `DOCMESH_ENV` | `development` | 실행 환경 이름. `LangfuseConfig.environment`의 기본값이기도 하다. |
| `DOCMESH_SECURITY_MODE` | 없음 | `development` 또는 `production`을 강제한다. |
| `DOCMESH_PRODUCTION_ALIASES` | `prod,production` | `DOCMESH_ENV`를 production으로 판단할 별칭 CSV다. |
| `DOCMESH_LOG_LEVEL` | `INFO` | `configure_logging()`이 level 인자를 받지 않을 때 사용할 logging level이다. |

## 3. 서비스별 환경변수 레퍼런스

표기: **필수**는 해당 서비스를 완전하게 로드할 때 필요하고, **조건부**는 조건을 만족할 때 필요하다. `🔒`는 secret으로 `SERVICE_CATALOG` 및 진단 출력에서 원문을 노출하지 않아야 하는 값이다.

### Keycloak — `KeycloakConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `KEYCLOAK_URL` | 필수 | Keycloak base URL |
| `KEYCLOAK_REALM` | 필수 | realm 이름 |
| `KEYCLOAK_CLIENT_ID` | 필수 | OIDC client ID |
| `KEYCLOAK_CLIENT_SECRET` | 조건부 🔒 | `KEYCLOAK_CLIENT_PUBLIC=false`일 때 필수 |
| `KEYCLOAK_VERIFY_SSL` | `true` | production에서 반드시 `true` |
| `KEYCLOAK_AUDIENCE` | 없음 | JWT audience 검증 값 |
| `KEYCLOAK_TOKEN_GRANT_TYPE` | `password` | `password` 또는 `client_credentials` |
| `KEYCLOAK_TOKEN_SCOPE` | 없음 | 기본 OIDC scope |
| `KEYCLOAK_TOKEN_USERNAME` | 없음 | password grant 기본 사용자 |
| `KEYCLOAK_TOKEN_PASSWORD` | 없음 🔒 | password grant 기본 비밀번호 |
| `KEYCLOAK_REQUEST_TIMEOUT_SECONDS` | `10` | 1 이상 |
| `KEYCLOAK_MAX_RETRIES` | `3` | 0 이상 |
| `KEYCLOAK_JWKS_CACHE_TTL_SECONDS` | `300` | 0 이상; `0`은 cache 만료를 강제하지 않는다 |
| `KEYCLOAK_PROVISIONING_ENABLED` | `false` | provisioning admin auth 검증을 켠다 |
| `KEYCLOAK_PROVISIONING_DRY_RUN` | `false` | 원격 변경 없이 계획만 반환 |
| `KEYCLOAK_ADMIN_REALM` | `master` | provisioning admin realm |
| `KEYCLOAK_ADMIN_CLIENT_ID` | `admin-cli` | provisioning admin client |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | 없음 🔒 | admin service-account 인증 |
| `KEYCLOAK_ADMIN_USERNAME` | 없음 | admin password 인증 사용자 |
| `KEYCLOAK_ADMIN_PASSWORD` | 없음 🔒 | admin password 인증 비밀번호 |
| `KEYCLOAK_REALM_ENABLED` | `true` | provisioned realm enabled 상태 |
| `KEYCLOAK_REALM_DISPLAY_NAME` | 없음 | realm 표시 이름 |
| `KEYCLOAK_CLIENT_PUBLIC` | `false` | public client면 client secret 불필요 |
| `KEYCLOAK_CLIENT_REDIRECT_URIS` | 빈 목록 | 쉼표 구분 URI 목록 |
| `KEYCLOAK_CLIENT_WEB_ORIGINS` | 빈 목록 | 쉼표 구분 origin 목록 |
| `KEYCLOAK_REALM_ROLES` | 빈 목록 | 쉼표 구분 realm role 목록 |
| `KEYCLOAK_CLIENT_ROLES` | 빈 목록 | 쉼표 구분 client role 목록 |

`KEYCLOAK_PROVISIONING_ENABLED=true`이면 `KEYCLOAK_ADMIN_CLIENT_SECRET` **또는** `KEYCLOAK_ADMIN_USERNAME` + `KEYCLOAK_ADMIN_PASSWORD` 중 정확히 하나의 인증 방식만 설정한다.

### PostgreSQL — `PostgresConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `POSTGRES_HOST` | 필수 | hostname |
| `POSTGRES_PORT` | `5432` | 1 이상 |
| `POSTGRES_DB` | 필수 | database 이름 |
| `POSTGRES_USER` | 필수 | 사용자 |
| `POSTGRES_PASSWORD` | 필수 🔒 | 비밀번호 |
| `POSTGRES_SSLMODE` | `prefer` | psycopg SSL mode |
| `POSTGRES_CONNECT_TIMEOUT_SECONDS` | `10` | 1 이상 |
| `POSTGRES_POOL_SIZE` | `5` | 1 이상 |
| `POSTGRES_MAX_OVERFLOW` | `10` | 0 이상 |

`POSTGRES_DSN`은 지원하지 않는다. host/db/user/password를 분리해 사용한다.

### SQLite — `SqliteConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `SQLITE_PATH` | 필수 | 파일 경로 또는 `:memory:` |
| `SQLITE_READONLY` | `false` | true면 SQLite URI read-only mode |
| `SQLITE_ENABLE_WAL` | `false` | 연결마다 `PRAGMA journal_mode=WAL` 적용 |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000` | 0 이상; busy timeout milliseconds |

상대 경로는 현재 작업 디렉터리 기준이다. 라이브러리는 상위 디렉터리를 만들지 않는다.

### MinIO — `MinioConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `MINIO_ENDPOINT` | 필수 | `host:port` endpoint |
| `MINIO_ACCESS_KEY` | 필수 🔒 | access key |
| `MINIO_SECRET_KEY` | 필수 🔒 | secret key |
| `MINIO_SECURE` | `true` | production에서 반드시 `true` |
| `MINIO_REGION` | 없음 | region |
| `MINIO_BUCKET` | 없음 | application이 `require_minio_bucket()`로 요구할 선택 bucket |
| `MINIO_REQUEST_TIMEOUT_SECONDS` | `30` | 1 이상 |
| `MINIO_MAX_RETRIES` | `3` | 0 이상 |

### Milvus — `MilvusConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `MILVUS_URI` | 필수 | Milvus URI |
| `MILVUS_TOKEN` | 없음 🔒 | 인증 token |
| `MILVUS_DB_NAME` | `default` | database 이름 |
| `MILVUS_COLLECTION` | 없음 | application 기본 collection |
| `MILVUS_SECURE` | `false` | production에서 반드시 `true` |
| `MILVUS_CONNECT_TIMEOUT_SECONDS` | `10` | 1 이상 |
| `MILVUS_REQUEST_TIMEOUT_SECONDS` | `30` | 1 이상 |
| `MILVUS_MAX_RETRIES` | `3` | 0 이상 |

### Ollama — `OllamaConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `OLLAMA_HOST` | 필수 | Ollama server URL |
| `OLLAMA_GENERATION_MODEL` | 없음 | generation 기본 모델 |
| `OLLAMA_EMBEDDING_MODEL` | 없음 | embedding 기본 모델 |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | `120` | 1 이상 |
| `OLLAMA_MAX_RETRIES` | `2` | 0 이상 |

### Langfuse — `LangfuseConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `LANGFUSE_ENABLED` | `true` | false면 factory는 `None`을 반환 |
| `LANGFUSE_HOST` | 조건부 | enabled일 때 필수 |
| `LANGFUSE_PUBLIC_KEY` | 조건부 🔒 | enabled일 때 필수 |
| `LANGFUSE_SECRET_KEY` | 조건부 🔒 | enabled일 때 필수 |
| `LANGFUSE_RELEASE` | 없음 | release metadata |
| `LANGFUSE_ENVIRONMENT` | `DOCMESH_ENV` | trace environment |
| `LANGFUSE_REQUEST_TIMEOUT_SECONDS` | `10` | 1 이상 |
| `LANGFUSE_MAX_RETRIES` | `3` | 0 이상 |

### NATS — `NatsConfig`

| 키 | 필수/기본값 | 설명 |
| --- | --- | --- |
| `NATS_SERVERS` | 필수 | 쉼표 구분 NATS URL 목록 |
| `NATS_USER` | 없음 | user/password 인증의 사용자 |
| `NATS_PASSWORD` | 없음 🔒 | user/password 인증의 비밀번호; user와 함께 설정 |
| `NATS_TOKEN` | 없음 🔒 | token 인증. 다른 인증 방식과 동시 사용 불가 |
| `NATS_CREDS_FILE` | 없음 🔒 | credentials-file 인증. 다른 인증 방식과 동시 사용 불가 |
| `NATS_NAME` | `docmesh-py-core` | connection name |
| `NATS_CONNECT_TIMEOUT_SECONDS` | `10` | 1 이상 |
| `NATS_MAX_RECONNECT_ATTEMPTS` | `10` | 0 이상 |

인증 방식은 없음, `NATS_USER`+`NATS_PASSWORD`, `NATS_TOKEN`, `NATS_CREDS_FILE` 중 하나여야 한다. user/password의 한쪽만 설정하는 것은 오류다.

## 4. Production 보안과 진단

다음은 `CommonConfig.is_production`이 true일 때 `diagnose_services()`와 `load_service_configs()`에서 확인한다.

- `KEYCLOAK_VERIFY_SSL=false`, `MINIO_SECURE=false`, `MILVUS_SECURE=false`를 거부한다.
- 선택된 서비스의 password/secret/token/access key placeholder(`replace-me`, `changeme`, `change-me`, `placeholder`)를 거부한다.
- 선택된 서비스 endpoint의 `example.com`, `localhost`, `127.0.0.1` placeholder를 거부한다.
- 진단은 secret 원문 대신 `ConfigIssue`의 환경변수 키와 remediation만 반환한다.

```python
from docmesh_py_core import Service, RuntimePlan, diagnose_services

plan = RuntimePlan(services=(Service.MINIO.required(),))
diagnosis = diagnose_services(plan=plan)
if not diagnosis.ok:
    raise RuntimeError(diagnosis.to_dict())
```

## 5. 구성 API 추적성

| Configuration Guide 주제 | 공개 API | API Reference |
| --- | --- | --- |
| 공통 보안 모드 | `CommonConfig`, `validate_runtime_security` | [설정·진단](./api.md#3-설정과-진단) |
| 서비스 설정 모델 | `KeycloakDiscoveryConfig`, `KeycloakConfig`, `PostgresConfig`, `SqliteConfig`, `MinioConfig`, `MilvusConfig`, `OllamaConfig`, `LangfuseConfig`, `NatsConfig` | [설정·진단](./api.md#3-설정과-진단) |
| 선택 로딩 | `ServiceConfigs`, `load_service_configs`, `load_available_service_configs` | [설정·진단](./api.md#3-설정과-진단) |
| 사전 진단 | `diagnose_services`, `ConfigIssue`, `ServiceConfigurationDiagnosis`, `EnvironmentDiagnosis`, `ConfigError` | [설정·진단](./api.md#3-설정과-진단) |
| requirement 정책 | `require_minio_bucket`, `validate_service_requirements`, `SERVICE_CATALOG`, `ServiceDescriptor`, `EnvironmentRequirement` | [카탈로그](./api.md#5-서비스-카탈로그) |

## 6. 배포 점검 목록

1. application `RuntimePlan`에서 선택한 서비스만 배포 secret/환경변수로 제공한다.
2. `diagnose_services(plan=...)`를 네트워크 연결 전에 실행해 `diagnosis.ok`를 확인한다.
3. production에서는 TLS 및 placeholder 검증 오류를 해결한 뒤 `assemble_service_runtime()`을 호출한다.
4. 환경변수 값, access token, URI의 secret component를 로그나 오류 메시지에 직접 기록하지 않는다.
