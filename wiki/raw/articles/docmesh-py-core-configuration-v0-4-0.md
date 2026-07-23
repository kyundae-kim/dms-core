---
source_url: https://github.com/kyundae-kim/docmesh-py-core/wiki/Configuration-v0.5.0
ingested: 2026-07-21
sha256: f7249e3a27ba51ca4520bbc34e9dda9f25c642ea7d3c03b8bd6e2a5adaca33a4
---
# 서비스 연결 및 SDK 확장 설정

`docmesh-py-core`의 서비스 설정은 프로세스 환경변수에서 직접 로드된다. 설정 객체나 factory에 mapping, 개별 연결 값 또는 임의 SDK kwargs를 전달할 수 없다.

전체 공개 동작은 [API 레퍼런스](./api.md), copy-adapt 흐름은 [사용 예제](./examples.md)를 참고한다.

## 사용 원칙

1. 애플리케이션이 사용할 서비스만 `load_service_configs(services={...})`로 선택한다.
2. 각 환경변수는 서비스별 `BaseSettings` 모델에서 typed 값으로 파싱·검증된다.
3. 검증이 끝난 설정만 `create_*_client(config)` factory가 SDK 생성자에 전달한다.
4. 지원하지 않는 SDK 옵션은 임의 kwargs로 우회하지 않고 설정 모델과 이 문서에 명시적으로 추가한다.
5. production에서는 TLS 전송 및 인증서 검증을 비활성화할 수 없다.

전체 환경변수 예시는 [`.env.example`](../.env.example)을 참고한다.

## 파싱과 선택 규칙

- 문자열 앞뒤 공백은 제거하며, 공백만 있는 값은 미설정으로 처리한다.
- `bool`, 숫자, CSV 목록은 Pydantic settings가 typed 값으로 파싱한다.
- CSV 목록은 쉼표로 구분한다. 대상은 production alias, Keycloak URI/role 목록, NATS server 목록이다.
- `load_service_configs(services={...})`는 명시한 서비스만 검증한다. `services=None`은 8개 전체를 의미한다.
- `load_available_service_configs()`는 인식 가능한 환경변수가 존재하는 후보만 로드하지만, 일부 필수값만 있는 partial 설정은 오류다.
- 설정 클래스는 `SqliteConfig()`처럼 인자 없이 생성한다. 생성자에 mapping이나 개별 값을 넘기면 `TypeError`다.
- startup healthcheck는 환경변수가 아니라 `RuntimePlan.healthcheck`로 제어한다.

## 전체 환경변수 레퍼런스

`필수`는 해당 서비스를 선택했을 때 필요하다는 뜻이다. `선택` 값이 미설정이면 표의 기본값을 사용한다. `조건부` 규칙은 같은 서비스의 다른 설정에 따라 적용된다.

### 공통

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `DOCMESH_ENV` | `str` | 선택 | `development` | `env` |
| `DOCMESH_SECURITY_MODE` | `development \| production` | 선택 | 미설정 | `security_mode` |
| `DOCMESH_PRODUCTION_ALIASES` | CSV `list[str]` | 선택 | `prod,production` | `production_aliases` |
| `DOCMESH_LOG_LEVEL` | logging level | 선택 | `INFO` | `configure_logging()` 전용 |

`DOCMESH_SECURITY_MODE`가 있으면 `DOCMESH_ENV` alias 판정보다 우선한다. `DOCMESH_LOG_LEVEL`은 `CommonConfig` 필드가 아니며 `configure_logging()`이 직접 읽는다. 함수의 `level` 인자가 환경변수보다 우선한다.

### Keycloak

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `KEYCLOAK_URL` | `str` | 필수 | 없음 | `url` |
| `KEYCLOAK_REALM` | `str` | 필수 | 없음 | `realm` |
| `KEYCLOAK_CLIENT_ID` | `str` | 필수 | 없음 | `client_id` |
| `KEYCLOAK_CLIENT_SECRET` | `str` | 조건부: `KEYCLOAK_CLIENT_PUBLIC=false` | 미설정 | `client_secret` |
| `KEYCLOAK_VERIFY_SSL` | `bool` | 선택 | `true` | `verify_ssl` |
| `KEYCLOAK_AUDIENCE` | `str` | 선택 | 미설정 | `audience` |
| `KEYCLOAK_TOKEN_GRANT_TYPE` | `password \| client_credentials` | 선택 | `password` | `token_grant_type` |
| `KEYCLOAK_TOKEN_SCOPE` | `str` | 선택 | 미설정 | `token_scope` |
| `KEYCLOAK_TOKEN_USERNAME` | `str` | 조건부: password grant 호출 시 | 미설정 | `token_username` |
| `KEYCLOAK_TOKEN_PASSWORD` | `str` | 조건부: password grant 호출 시 | 미설정 | `token_password` |
| `KEYCLOAK_REQUEST_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `10` | `request_timeout_seconds` |
| `KEYCLOAK_MAX_RETRIES` | `int >= 0` | 선택 | `3` | `max_retries` |
| `KEYCLOAK_JWKS_CACHE_TTL_SECONDS` | `int >= 0` | 선택 | `300` | `jwks_cache_ttl_seconds` |
| `KEYCLOAK_PROVISIONING_ENABLED` | `bool` | 선택 | `false` | `provisioning_enabled` |
| `KEYCLOAK_PROVISIONING_DRY_RUN` | `bool` | 선택 | `false` | `provisioning_dry_run` |
| `KEYCLOAK_ADMIN_REALM` | `str` | 선택 | `master` | `admin_realm` |
| `KEYCLOAK_ADMIN_CLIENT_ID` | `str` | 선택 | `admin-cli` | `admin_client_id` |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | `str` | 조건부: provisioning service-account mode | 미설정 | `admin_client_secret` |
| `KEYCLOAK_ADMIN_USERNAME` | `str` | 조건부: provisioning user mode | 미설정 | `admin_username` |
| `KEYCLOAK_ADMIN_PASSWORD` | `str` | 조건부: provisioning user mode | 미설정 | `admin_password` |
| `KEYCLOAK_REALM_ENABLED` | `bool` | 선택 | `true` | `realm_enabled` |
| `KEYCLOAK_REALM_DISPLAY_NAME` | `str` | 선택 | 미설정 | `realm_display_name` |
| `KEYCLOAK_CLIENT_PUBLIC` | `bool` | 선택 | `false` | `client_public` |
| `KEYCLOAK_CLIENT_REDIRECT_URIS` | CSV `list[str]` | 선택 | 빈 목록 | `client_redirect_uris` |
| `KEYCLOAK_CLIENT_WEB_ORIGINS` | CSV `list[str]` | 선택 | 빈 목록 | `client_web_origins` |
| `KEYCLOAK_REALM_ROLES` | CSV `list[str]` | 선택 | 빈 목록 | `realm_roles` |
| `KEYCLOAK_CLIENT_ROLES` | CSV `list[str]` | 선택 | 빈 목록 | `client_roles` |

provisioning을 활성화하면 admin client secret 방식과 admin username/password 방식 중 **정확히 하나**만 구성해야 한다. password grant 자격증명은 설정 로딩 시점이 아니라 실제 token 호출 시 필요하며, `fetch_access_token(username=..., password=...)` 호출 인자가 설정값보다 우선한다.

### PostgreSQL

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `POSTGRES_HOST` | `str` | 필수 | 없음 | `host` |
| `POSTGRES_PORT` | `int >= 1` | 선택 | `5432` | `port` |
| `POSTGRES_DB` | `str` | 필수 | 없음 | `db` |
| `POSTGRES_USER` | `str` | 필수 | 없음 | `user` |
| `POSTGRES_PASSWORD` | `str` | 필수 | 없음 | `password` |
| `POSTGRES_SSLMODE` | `str` | 선택 | `prefer` | `sslmode` |
| `POSTGRES_CONNECT_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `10` | `connect_timeout_seconds` |
| `POSTGRES_POOL_SIZE` | `int >= 1` | 선택 | `5` | `pool_size` |
| `POSTGRES_MAX_OVERFLOW` | `int >= 0` | 선택 | `10` | `max_overflow` |
| `POSTGRES_POOL_PRE_PING` | `bool` | 선택 | `false` | `pool_pre_ping` |
| `POSTGRES_POOL_RECYCLE_SECONDS` | `int >= -1` | 선택 | `-1` | `pool_recycle_seconds` |
| `POSTGRES_ECHO` | `bool` | 선택 | `false` | `echo` |
| `POSTGRES_APPLICATION_NAME` | `str` | 선택 | 미설정 | `application_name` |

legacy DSN 환경변수는 지원하지 않는다. URL은 필드에서 안전하게 조립하며 factory에 추가 engine kwargs를 넘길 수 없다.

### SQLite

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `SQLITE_PATH` | `str` | 필수 | 없음 | `path` |
| `SQLITE_READONLY` | `bool` | 선택 | `false` | `readonly` |
| `SQLITE_ENABLE_WAL` | `bool` | 선택 | `false` | `enable_wal` |
| `SQLITE_BUSY_TIMEOUT_MS` | `int >= 0` | 선택 | `5000` | `busy_timeout_ms` |
| `SQLITE_CHECK_SAME_THREAD` | `bool` | 선택 | `false` | `check_same_thread` |
| `SQLITE_ECHO` | `bool` | 선택 | `false` | `echo` |

`SQLITE_PATH=:memory:`를 지원한다. 상대 경로는 현재 작업 디렉터리 기준이며 라이브러리는 상위 디렉터리를 만들지 않는다.

### MinIO

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `MINIO_ENDPOINT` | `str` | 필수 | 없음 | `endpoint` |
| `MINIO_ACCESS_KEY` | `str` | 필수 | 없음 | `access_key` |
| `MINIO_SECRET_KEY` | `str` | 필수 | 없음 | `secret_key` |
| `MINIO_SECURE` | `bool` | 선택 | `true` | `secure` |
| `MINIO_CERT_CHECK` | `bool` | 선택 | `true` | `cert_check` |
| `MINIO_REGION` | `str` | 선택 | 미설정 | `region` |
| `MINIO_BUCKET` | `str` | 선택 | 미설정 | `bucket` |
| `MINIO_REQUEST_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `30` | `request_timeout_seconds` |
| `MINIO_MAX_RETRIES` | `int >= 0` | 선택 | `3` | `max_retries` |

bucket은 공통 연결에는 선택값이다. bucket이 필수인 애플리케이션은 `require_minio_bucket()`을 호출한다.

### Milvus

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `MILVUS_URI` | `str` | 필수 | 없음 | `uri` |
| `MILVUS_TOKEN` | `str` | 선택 | 미설정 | `token` |
| `MILVUS_DB_NAME` | `str` | 선택 | `default` | `db_name` |
| `MILVUS_COLLECTION` | `str` | 선택 | 미설정 | `collection` |
| `MILVUS_SECURE` | `bool` | 선택 | `false` | `secure` |
| `MILVUS_CONNECT_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `10` | `connect_timeout_seconds` |
| `MILVUS_REQUEST_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `30` | `request_timeout_seconds` |
| `MILVUS_MAX_RETRIES` | `int >= 0` | 선택 | `3` | `max_retries` |

### Ollama

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `OLLAMA_HOST` | `str` | 필수 | 없음 | `host` |
| `OLLAMA_VERIFY_SSL` | `bool` | 선택 | `true` | `verify_ssl` |
| `OLLAMA_FOLLOW_REDIRECTS` | `bool` | 선택 | `true` | `follow_redirects` |
| `OLLAMA_GENERATION_MODEL` | `str` | 선택 | 미설정 | `generation_model` |
| `OLLAMA_EMBEDDING_MODEL` | `str` | 선택 | 미설정 | `embedding_model` |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `120` | `request_timeout_seconds` |
| `OLLAMA_MAX_RETRIES` | `int >= 0` | 선택 | `2` | `max_retries` |

### Langfuse

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `LANGFUSE_ENABLED` | `bool` | 선택 | `true` | `enabled` |
| `LANGFUSE_HOST` | `str` | 조건부: `LANGFUSE_ENABLED=true` | 미설정 | `host` |
| `LANGFUSE_PUBLIC_KEY` | `str` | 조건부: `LANGFUSE_ENABLED=true` | 미설정 | `public_key` |
| `LANGFUSE_SECRET_KEY` | `str` | 조건부: `LANGFUSE_ENABLED=true` | 미설정 | `secret_key` |
| `LANGFUSE_RELEASE` | `str` | 선택 | 미설정 | `release` |
| `LANGFUSE_ENVIRONMENT` | `str` | 선택 | `DOCMESH_ENV` 값 | `environment` |
| `LANGFUSE_REQUEST_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `10` | `request_timeout_seconds` |
| `LANGFUSE_MAX_RETRIES` | `int >= 0` | 선택 | `3` | `max_retries` |
| `LANGFUSE_DEBUG` | `bool` | 선택 | `false` | `debug` |
| `LANGFUSE_TRACING_ENABLED` | `bool` | 선택 | `true` | `tracing_enabled` |
| `LANGFUSE_FLUSH_AT` | `int >= 1` | 선택 | SDK 기본값 | `flush_at` |
| `LANGFUSE_FLUSH_INTERVAL_SECONDS` | `float > 0` | 선택 | SDK 기본값 | `flush_interval_seconds` |
| `LANGFUSE_SAMPLE_RATE` | `float 0..1` | 선택 | SDK 기본값 | `sample_rate` |

`LANGFUSE_ENABLED=false`이면 host와 key가 없어도 설정은 유효하고 factory는 `None`을 반환한다.

### NATS

| 환경변수 | 타입 | 요구 여부 | 기본값 | 설정 필드 |
| --- | --- | --- | --- | --- |
| `NATS_SERVERS` | CSV `list[str]` | 필수 | 없음 | `servers` |
| `NATS_USER` | `str` | 조건부: user/password auth | 미설정 | `user` |
| `NATS_PASSWORD` | `str` | 조건부: user/password auth | 미설정 | `password` |
| `NATS_TOKEN` | `str` | 조건부: token auth | 미설정 | `token` |
| `NATS_CREDS_FILE` | `str` | 조건부: credentials-file auth | 미설정 | `creds_file` |
| `NATS_NAME` | `str` | 선택 | `docmesh-py-core` | `name` |
| `NATS_CONNECT_TIMEOUT_SECONDS` | `int >= 1` | 선택 | `10` | `connect_timeout_seconds` |
| `NATS_MAX_RECONNECT_ATTEMPTS` | `int >= 0` | 선택 | `10` | `max_reconnect_attempts` |
| `NATS_RECONNECT_TIME_WAIT_SECONDS` | `float > 0` | 선택 | `2.0` | `reconnect_time_wait_seconds` |
| `NATS_PING_INTERVAL_SECONDS` | `int >= 1` | 선택 | `120` | `ping_interval_seconds` |
| `NATS_MAX_OUTSTANDING_PINGS` | `int >= 1` | 선택 | `2` | `max_outstanding_pings` |
| `NATS_NO_ECHO` | `bool` | 선택 | `false` | `no_echo` |

인증은 user/password, token, credentials file 중 최대 하나만 선택한다. user와 password는 함께 설정해야 한다.

## Production 보안 제약

`CommonConfig.is_production`이 참이면 다음 값은 모두 `true`여야 하며, 위반 시 client 생성 전에 `ConfigError`가 발생한다.

- `KEYCLOAK_VERIFY_SSL`
- `MINIO_SECURE`
- `MINIO_CERT_CHECK`
- `MILVUS_SECURE`
- `OLLAMA_VERIFY_SSL`

production 진단은 secret의 `replace-me`/`changeme`류 값과 endpoint의 `example.com`/localhost류 placeholder도 보고한다.

## SDK 적용 상세

### PostgreSQL SQLAlchemy 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `POSTGRES_POOL_SIZE` | int, 1 이상 | `5` | `create_engine(pool_size=...)` |
| `POSTGRES_MAX_OVERFLOW` | int, 0 이상 | `10` | `create_engine(max_overflow=...)` |
| `POSTGRES_POOL_PRE_PING` | bool | `false` | `create_engine(pool_pre_ping=...)` |
| `POSTGRES_POOL_RECYCLE_SECONDS` | int, -1 이상 | `-1` | `create_engine(pool_recycle=...)` |
| `POSTGRES_ECHO` | bool | `false` | `create_engine(echo=...)` |
| `POSTGRES_APPLICATION_NAME` | string | 미설정 | PostgreSQL `connect_args.application_name` |

`POSTGRES_CONNECT_TIMEOUT_SECONDS`와 `POSTGRES_SSLMODE`도 `connect_args`에 적용된다.

### SQLite SQLAlchemy 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `SQLITE_CHECK_SAME_THREAD` | bool | `false` | `connect_args.check_same_thread` |
| `SQLITE_ECHO` | bool | `false` | `create_engine(echo=...)` |
| `SQLITE_BUSY_TIMEOUT_MS` | int, 0 이상 | `5000` | 연결 timeout 및 `PRAGMA busy_timeout` |

### MinIO 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `MINIO_SECURE` | bool | `true` | `Minio(secure=...)` |
| `MINIO_CERT_CHECK` | bool | `true` | `Minio(cert_check=...)` |
| `MINIO_REGION` | string | 미설정 | `Minio(region=...)` |

production에서는 `MINIO_SECURE`와 `MINIO_CERT_CHECK`가 모두 `true`여야 한다.

### Milvus 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `MILVUS_DB_NAME` | string | `default` | `MilvusClient(db_name=...)` |
| `MILVUS_REQUEST_TIMEOUT_SECONDS` | int, 1 이상 | `30` | `MilvusClient(timeout=...)` |
| `MILVUS_SECURE` | bool | `false` | `MilvusClient(secure=...)` |

production에서는 `MILVUS_SECURE=true`가 필요하다.

### Ollama HTTP 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | int, 1 이상 | `120` | `Client(timeout=...)` |
| `OLLAMA_VERIFY_SSL` | bool | `true` | `Client(verify=...)` |
| `OLLAMA_FOLLOW_REDIRECTS` | bool | `true` | `Client(follow_redirects=...)` |

production에서는 `OLLAMA_VERIFY_SSL=true`가 필요하다.

### Langfuse 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `LANGFUSE_DEBUG` | bool | `false` | `Langfuse(debug=...)` |
| `LANGFUSE_TRACING_ENABLED` | bool | `true` | `Langfuse(tracing_enabled=...)` |
| `LANGFUSE_FLUSH_AT` | int, 1 이상 | SDK 기본값 | `Langfuse(flush_at=...)` |
| `LANGFUSE_FLUSH_INTERVAL_SECONDS` | float, 0 초과 | SDK 기본값 | `Langfuse(flush_interval=...)` |
| `LANGFUSE_SAMPLE_RATE` | float, 0~1 | SDK 기본값 | `Langfuse(sample_rate=...)` |

### NATS 옵션

| 환경변수 | 타입 | 기본값 | SDK 적용 위치 |
| --- | --- | --- | --- |
| `NATS_CONNECT_TIMEOUT_SECONDS` | int, 1 이상 | `10` | `nats.connect(connect_timeout=...)` |
| `NATS_MAX_RECONNECT_ATTEMPTS` | int, 0 이상 | `10` | `nats.connect(max_reconnect_attempts=...)` |
| `NATS_RECONNECT_TIME_WAIT_SECONDS` | float, 0 초과 | `2.0` | `nats.connect(reconnect_time_wait=...)` |
| `NATS_PING_INTERVAL_SECONDS` | int, 1 이상 | `120` | `nats.connect(ping_interval=...)` |
| `NATS_MAX_OUTSTANDING_PINGS` | int, 1 이상 | `2` | `nats.connect(max_outstanding_pings=...)` |
| `NATS_NO_ECHO` | bool | `false` | `nats.connect(no_echo=...)` |

NATS factory는 연결을 즉시 열지 않고, 위 설정을 보존한 `NatsConnectionBuilder`를 반환한다.
