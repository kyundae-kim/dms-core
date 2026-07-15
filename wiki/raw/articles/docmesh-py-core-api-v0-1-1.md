---
source_url: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.2.0/docs/api.md
ingested: 2026-07-15
sha256: 8f9acd3ca907f75823201ba4cdcc17eb53ef52bfd9a93204ab8a6c072a7933e4
---

1|# docmesh-py-core API Reference
2|
3|이 문서는 현재 소스코드(`docmesh_py_core/__init__.py`, 각 모듈 구현)를 기준으로 정리한 공개 API 레퍼런스입니다.
4|
5|- 사용 흐름은 [README](../README.md)
6|- 환경변수/설정 규칙은 [config.md](./config.md)
7|- 실제 통합 예시는 [examples.md](./examples.md)
8|
9|## 1. Public imports
10|
11|패키지 루트에서 바로 import 가능한 공개 API는 다음과 같습니다.
12|
13|```python
14|from docmesh_py_core import (
15|    AccessTokenResult,
16|    AuthenticatedUser,
17|    CommonConfig,
18|    ConfigError,
19|    ConfigIssue,
20|    HealthCheckError,
21|    HealthCheckResult,
22|    KeycloakAuthService,
23|    KeycloakConfig,
24|    KeycloakDiscoveryConfig,
25|    KeycloakProvisioner,
26|    KeycloakTokenAuthenticationError,
27|    KeycloakTokenConfigurationError,
28|    KeycloakTokenError,
29|    KeycloakTokenTemporaryError,
30|    LangfuseConfig,
31|    MinioConfig,
32|    MinioRuntimeDefaults,
33|    MilvusConfig,
34|    MilvusRuntimeDefaults,
35|    NatsConnectionBuilder,
36|    NatsConfig,
37|    OllamaConfig,
38|    OllamaRuntimeDefaults,
39|    PostgresConfig,
40|    ProvisioningResult,
41|    ServiceBundle,
42|    ServiceCloseError,
43|    ServiceCloseFailure,
44|    ServiceClientError,
45|    ServiceClientProtocol,
46|    ServiceClientWrapper,
47|    ServiceClientWrapperError,
48|    ServiceConfigs,
49|    ServiceRuntime,
50|    ServiceHealthStatus,
51|    SqliteConfig,
52|    TokenValidationError,
53|    assemble_services,
54|    assemble_service_runtime,
55|    async_check_all_services,
56|    async_close_service_clients,
57|    build_service_log_event,
58|    check_all_services,
59|    close_service_clients,
60|    configure_logging,
61|    create_keycloak_client,
62|    create_langfuse_client,
63|    create_milvus_client,
64|    create_minio_client,
65|    create_nats_client,
66|    create_ollama_client,
67|    create_postgres_client,
68|    create_sqlite_client,
69|    load_available_service_configs,
70|    load_service_configs,
71|    require_minio_bucket,
72|    mask_sensitive_value,
73|    retry_call,
74|    validate_service_requirements,
75|    validate_runtime_security,
76|)
77|```
78|
79|> 위 목록은 `docmesh_py_core/__init__.py`의 `__all__` 기준입니다.
80|
81|### 공개 결과 및 오류 데이터 구조
82|
83|#### `AccessTokenResult`
84|
85|- `access_token`: `str`; 토큰 원문이므로 로그에 기록하지 않습니다.
86|- `token_type`: `str`
87|- `expires_in`: `int`
88|- `refresh_token`: `str | None`; 토큰 원문이므로 로그에 기록하지 않습니다.
89|- `scope`: `str | None`
90|
91|#### `AuthenticatedUser`
92|
93|- 사용자 식별 필드: `sub`, `preferred_username`, `email`, `given_name`, `family_name`, `name`
94|- 권한 필드: `realm_roles: list[str]`, `client_roles: dict[str, list[str]]`
95|- 검증된 전체 JWT payload: `claims: dict[str, Any]`
96|
97|#### `ProvisioningResult`
98|
99|- `created`, `updated`, `unchanged`, `planned`: 리소스 식별자 목록
100|- `failed`: `(리소스 식별자, 마스킹된 오류)` tuple 목록
101|- `dry_run`: dry-run 실행 여부
102|
103|#### `ConfigIssue`
104|
105|- `service`, `env_key`, `reason`, `error_type`, `remediation`
106|- `ConfigError.issues`와 호환 별칭인 `ConfigError.errors`에서 확인할 수 있습니다.
107|
108|#### `ServiceCloseFailure`
109|
110|- `client`: 종료에 실패한 클라이언트 또는 wrapper
111|- `error`: 원래 종료 예외
112|- 여러 실패는 `ServiceCloseError.failures`에 tuple로 보존됩니다.
113|
114|#### Runtime defaults
115|
116|`ServiceClientWrapper.runtime_defaults`에는 SDK 생성자에 직접 전달되지 않은 typed 기본값이 저장될 수 있습니다.
117|
118|- `MinioRuntimeDefaults`: `bucket`, `request_timeout_seconds`, `max_retries`
119|- `MilvusRuntimeDefaults`: `collection`, `connect_timeout_seconds`, `max_retries`, `secure`
120|- `OllamaRuntimeDefaults`: `generation_model`, `embedding_model`, `max_retries`
121|
122|## 2. 권장 사용 흐름
123|
124|이 라이브러리는 **assembly-first, direct-api-when-needed** 정책을 따릅니다.
125|
126|| 상황 | 우선 API | direct API가 필요한 경우 |
127|| --- | --- | --- |
128|| 동기 서비스 lifecycle 조립 | `assemble_services()` | 특정 SDK factory hook 또는 client lifecycle을 직접 제어할 때 |
129|| NATS 또는 async lifecycle 조립 | `assemble_service_runtime()` | NATS builder/SDK 연결을 직접 제어할 때 |
130|| Keycloak 토큰/JWT 기능만 사용 | `KeycloakAuthService(KeycloakConfig())` | 해당 direct API가 기본 경로 |
131|| CLI, 배치, 단일 서비스 테스트 | 서비스별 `*Config()` + `create_*_client()` | 해당 direct API가 기본 경로 |
132|
133|일반 애플리케이션은 아래 순서로 assembly API를 사용합니다.
134|
135|1. 환경변수 또는 명시적 mapping 준비
136|2. 동기 서비스는 `assemble_services()`, NATS/async 서비스는 `await assemble_service_runtime()` 호출
137|3. `required`, `one_of`, `check_on_startup`으로 구성·startup 정책 선언
138|4. `ServiceBundle` 또는 `ServiceRuntime`의 context manager로 lifecycle 관리
139|
140|주의:
141|
142|- `nats`만 예외적으로 `NatsConnectionBuilder`를 반환하며, 실제 네트워크 연결은 `await connect()` / `await ping()` / `await check()`에서 일어납니다.
143|- `langfuse`는 `LANGFUSE_ENABLED=false`면 `create_langfuse_client()`가 `None`을 반환할 수 있습니다.
144|- `CommonConfig.env`는 자유 문자열이며 enum 검증을 하지 않습니다. 운영 판정은 `DOCMESH_SECURITY_MODE`가 있으면 그 값을 우선하고, 없으면 `DOCMESH_PRODUCTION_ALIASES`(기본값 `prod,production`)와 환경 이름을 비교합니다.
145|
146|## 3. Service config API
147|
148|### Direct API용 config entrypoint
149|
150|서비스별 config class 직접 생성은 direct-api-when-needed 경로입니다. 일반 애플리케이션 lifecycle 조립에는 먼저 [assembly API](#5-공통-wrapper--helper-api)의 `assemble_services()` 또는 `assemble_service_runtime()`을 고려하세요.
151|
152|- 공통: `CommonConfig()`
153|- Keycloak discovery 전용: `KeycloakDiscoveryConfig()`
154|- Keycloak 전체: `KeycloakConfig()`
155|- PostgreSQL: `PostgresConfig()`
156|- SQLite: `SqliteConfig()`
157|- MinIO: `MinioConfig()`
158|- Milvus: `MilvusConfig()`
159|- Ollama: `OllamaConfig()`
160|- Langfuse: `LangfuseConfig()`
161|- NATS: `NatsConfig()`
162|
163|규칙:
164|
165|- 서비스별 `*Config()` 직접 생성은 pydantic `ValidationError`를 그대로 발생시킵니다.
166|- `load_service_configs()`는 선택된 서비스만 읽고, 검증 실패를 `ConfigError`로 다시 감싸서 반환합니다.
167|- `LANGFUSE_ENVIRONMENT`가 비어 있으면 `CommonConfig().env` 값을 상속합니다.
168|
169|예시:
170|
171|```python
172|from docmesh_py_core import CommonConfig, KeycloakAuthService, KeycloakConfig
173|
174|common = CommonConfig()
175|keycloak = KeycloakConfig()
176|
177|auth = KeycloakAuthService(keycloak)
178|
179|assert isinstance(common.env, str)
180|assert keycloak.client_id
181|```
182|
183|### 3.2 `load_service_configs(env=None, *, services=None) -> ServiceConfigs`
184|
185|설정을 읽고 검증합니다. `env`를 생략하면 현재 프로세스 환경변수를 읽고,
186|`Mapping[str, str]`을 전달하면 해당 mapping만 사용하며 `os.environ`과 병합하거나
187|수정하지 않습니다.
188|
189|주요 동작:
190|
191|- `services=None`이면 지원 서비스 전체(`keycloak`, `postgres`, `sqlite`, `minio`, `milvus`, `ollama`, `langfuse`, `nats`)를 검증합니다.
192|- `services={...}`를 주면 지정한 서비스만 검증하고, 나머지 필드는 `None`으로 둡니다.
193|- 지원하지 않는 서비스 이름이 들어오면 `ConfigError`가 발생합니다.
194|- 선택된 서비스에서 필수 env가 없거나 타입/범위 검증에 실패하면 `ConfigError`가 발생합니다.
195|- 마지막에 `validate_runtime_security()`를 호출해 production 계열 보안 제약을 확인합니다.
196|
197|### 3.3 `load_available_service_configs(env, *, services=None) -> ServiceConfigs`
198|
199|명시한 후보 서비스 중 관련 prefix가 존재하는 서비스만 로딩합니다.
200|
201|- 관련 키가 전혀 없는 서비스는 결과에서 `None`입니다.
202|- 관련 키가 하나라도 있지만 설정이 불완전하면 `ConfigError`가 발생합니다.
203|- 단순 prefix 존재를 유효한 설정으로 간주하지 않고 실제 config validation을 수행합니다.
204|
205|PostgreSQL과 SQLite 같은 대안 서비스 후보를 전역 backend selector 없이 탐색할 때 사용할 수 있습니다.
206|
207|예시:
208|
209|```python
210|from docmesh_py_core import load_available_service_configs
211|
212|settings = load_available_service_configs(
213|    {"SQLITE_PATH": ":memory:"},
214|    services={"postgres", "sqlite"},
215|)
216|
217|assert settings.postgres is None
218|assert settings.sqlite is not None
219|```
220|
221|### 3.4 서비스 조합 및 MinIO bucket 검증
222|
223|- `validate_service_requirements(configs, required=..., one_of=...)`는 필수 서비스와 대안 서비스 그룹을 검증하고 현재 구성된 서비스 이름을 반환합니다.
224|- `require_minio_bucket(config)`은 제품이 bucket을 필수로 사용할 때 opt-in으로 검증하고 bucket 이름을 반환합니다.
225|- 두 helper의 실패는 구조화된 `ConfigError.issues`로 제공됩니다.
226|
227|### 3.5 `ServiceConfigs`
228|
229|서비스 설정 묶음 dataclass입니다.
230|
231|필드:
232|
233|- `common: CommonConfig`
234|- `keycloak: KeycloakConfig | None`
235|- `postgres: PostgresConfig | None`
236|- `sqlite: SqliteConfig | None`
237|- `minio: MinioConfig | None`
238|- `milvus: MilvusConfig | None`
239|- `ollama: OllamaConfig | None`
240|- `langfuse: LangfuseConfig | None`
241|- `nats: NatsConfig | None`
242|
243|추가 속성:
244|
245|- `docmesh_env -> str`: `common.env`를 그대로 반환하는 convenience property
246|
247|각 optional 필드에는 `require_keycloak()`, `require_postgres()`, `require_sqlite()`, `require_minio()`, `require_milvus()`, `require_ollama()`, `require_langfuse()`, `require_nats()`가 대응합니다. 로딩된 config는 non-optional 타입으로 반환하고, 로딩되지 않은 서비스는 구조화된 `ConfigError`를 발생시킵니다.
248|
249|## 4. Client creation API
250|
251|서비스별 `create_*_client()` 함수는 direct-api-when-needed 경로입니다. 일반 애플리케이션 lifecycle 조립에는 `assemble_services()` 또는 `assemble_service_runtime()`을 우선 사용합니다.
252|
253|모든 factory는 테스트와 특수 실행 환경을 위해 keyword-only `client_factory` hook을 제공합니다. NATS는 `connect_factory`, SQLite는 추가로 `configure_engine`을 지원합니다.
254|
255|### Factory 확장 hook
256|
257|- `client_factory`: 기본 SDK 생성자를 대체합니다. 기본 생성자와 같은 인자를 받고 호환 client를 반환해야 합니다.
258|- `connect_factory`: NATS 연결 함수를 대체합니다. `NatsConnectionBuilder.connect_kwargs`를 받아 client 또는 awaitable client를 반환해야 합니다.
259|- `configure_engine`: `(engine, SqliteConfig)`를 받아 SQLite pragma/listener 구성을 대체합니다.
260|- `engine_options`: PostgreSQL/SQLite의 SQLAlchemy 옵션을 확장합니다. `connect_args`는 기본값과 중첩 병합됩니다.
261|- `factory_overrides`: `assemble_service_runtime()`에서 서비스 이름별 `(config) -> client` factory를 대체합니다.
262|
263|이 hook들은 mock 기반 단위 테스트나 명시적인 실행 환경 대체에 적합합니다. 반환 객체는 해당 서비스의 healthcheck와 lifecycle 계약을 충족해야 합니다.
264|
265|### `create_keycloak_client(config: KeycloakConfig, *, client_factory=None) -> ServiceClientWrapper`
266|
267|- 내부적으로 `KeycloakAuthService(config)`를 생성합니다.
268|- `check()` / `ping()`는 `fetch_access_token()`을 호출합니다.
269|
270|### `create_postgres_client(config: PostgresConfig, *, engine_options=None, client_factory=None) -> ServiceClientWrapper[Engine]`
271|
272|- SQLAlchemy engine을 생성합니다.
273|- `config.dsn`이 있으면 그 값을 사용하고, 없으면 host/db/user/password 조합으로 URL을 만듭니다.
274|- `check()` / `ping()`는 `SELECT 1`을 실행합니다.
275|- `close()`는 내부 `dispose()`를 호출합니다.
276|- `engine_options`는 SQLAlchemy `create_engine()` 옵션을 확장하며, 중첩된 `connect_args`는 기본 연결 옵션과 병합됩니다.
277|
278|### `create_sqlite_client(config: SqliteConfig, *, engine_options=None, client_factory=None, configure_engine=None) -> ServiceClientWrapper[Engine]`
279|
280|- SQLAlchemy engine을 생성합니다.
281|- `config.path == ":memory:"`를 지원합니다.
282|- `readonly`, `enable_wal`, `busy_timeout_ms`를 반영합니다.
283|- `check()` / `ping()`는 `SELECT 1`을 실행합니다.
284|- `close()`는 내부 `dispose()`를 호출합니다.
285|- `engine_options`와 `connect_args`를 추가하거나 기본값 위에 덮어쓸 수 있습니다.
286|
287|### `create_minio_client(config: MinioConfig, *, client_factory=None) -> ServiceClientWrapper`
288|
289|- `Minio(...)` 클라이언트를 즉시 생성합니다.
290|- `secure` 값은 `cert_check`에도 그대로 반영됩니다.
291|- `check()` / `ping()`는 `list_buckets()`를 호출합니다.
292|
293|### `create_milvus_client(config: MilvusConfig, *, client_factory=None) -> ServiceClientWrapper`
294|
295|- `MilvusClient(...)`를 생성합니다.
296|- `check()` / `ping()`는 `list_collections()`를 호출합니다.
297|
298|### `create_ollama_client(config: OllamaConfig, *, client_factory=None) -> ServiceClientWrapper`
299|
300|- `ollama.Client(...)`를 생성합니다.
301|- `check()` / `ping()`는 `ps()`를 호출합니다.
302|
303|### `create_langfuse_client(config: LangfuseConfig, *, client_factory=None) -> ServiceClientWrapper | None`
304|
305|- `config.enabled`가 `False`면 `None`을 반환합니다.
306|- 활성화 시 `Langfuse(...)`를 생성합니다.
307|- `check()` / `ping()`는 `auth_check()`를 호출합니다.
308|- `close()`는 `flush()`를 호출합니다.
309|
310|### `create_nats_client(config: NatsConfig, *, connect_factory=None) -> NatsConnectionBuilder`
311|
312|- 즉시 연결하지 않습니다.
313|- 실제 네트워크 연결은 `await builder.connect()` / `await builder.ping()` / `await builder.check()`에서 일어납니다.
314|- `ping()` / `check()`는 임시 연결 후 `flush()`를 수행하고, 끝나면 연결을 정리합니다.
315|
316|예시:
317|
318|```python
319|from docmesh_py_core import create_postgres_client, load_service_configs
320|
321|settings = load_service_configs(services={"postgres"})
322|postgres = create_postgres_client(settings.require_postgres())
323|
324|postgres.check()
325|postgres.close()
326|```
327|
328|## 5. 공통 wrapper / helper API
329|
330|### `ServiceClientWrapper`
331|
332|서비스 클라이언트를 표준 인터페이스로 감싸는 `ServiceClientWrapper[T]` 제네릭 wrapper입니다.
333|underlying `client`의 타입을 보존합니다.
334|
335|주요 메서드:
336|
337|- `check()` / `ping()`
338|- `close()`
339|- `unwrap() -> T`
340|- `__getattr__()` 위임
341|
342|동작 규칙:
343|
344|- healthcheck 호출 중 예외가 발생하면 `ServiceClientWrapperError`로 변환합니다.
345|- 오류 메시지는 `mask_sensitive_value()`를 거쳐 민감정보를 숨깁니다.
346|- `close_fn`이 있으면 그 함수를 우선 호출하고, 없으면 내부 client의 `close()`를 찾습니다.
347|- SDK 생성자에 직접 전달할 수 없는 기본 resource/retry 값은 서비스별 typed `runtime_defaults`로 보존됩니다.
348|
349|### `close_service_clients(clients: Iterable[Any]) -> None`
350|
351|여러 wrapper/client에 대해 `close()`를 순회 호출합니다. `None` 값은 무시합니다.
352|
353|### `async_close_service_clients(clients) -> None`
354|
355|동기·비동기 `close()` 반환을 모두 수용합니다. 한 client의 종료 실패와 관계없이 나머지 client를 계속 정리하며, 실패가 있으면 전체 `ServiceCloseFailure`를 담은 `ServiceCloseError`를 발생시킵니다.
356|
357|### `assemble_services(...) -> ServiceBundle`
358|
359|mapping 기반 설정 로딩, available 서비스 탐지, required/one-of 검증, 클라이언트 생성과 선택적 startup healthcheck를 한 번에 수행합니다.
360|
361|- `services`: 탐색할 서비스 후보
362|- `required`: 반드시 구성되어야 하는 서비스
363|- `one_of`: 각 그룹에서 하나 이상 필요한 대안 서비스 조합
364|- `engine_options`: `postgres`/`sqlite`별 SQLAlchemy 옵션
365|- `check_on_startup`: 생성 직후 healthcheck 실행 여부
366|- `parallel_healthchecks`: startup healthcheck 병렬 실행 여부
367|
368|`ServiceBundle`은 `configs`, `clients`, `checks`, `selected_services`를 제공하며 `check()`, `close()`와 context manager를 지원합니다. startup healthcheck가 실패하면 이미 생성된 클라이언트를 닫은 뒤 예외를 다시 발생시킵니다.
369|
370|NATS는 비동기 lifecycle이므로 동기 `ServiceBundle` 조립 대상에서 제외되며 `create_nats_client()`로 별도 생성해야 합니다.
371|
372|### `assemble_service_runtime(...) -> ServiceRuntime`
373|
374|NATS를 포함해 동기·비동기 서비스를 함께 조립하는 비동기 runtime API입니다. `await assemble_service_runtime(...)`으로 생성하며 `async with`를 지원합니다.
375|
376|- sync/async health check를 한 API에서 실행
377|- 개별 health check timeout과 전체 timeout 지원
378|- 생성 또는 startup health check 실패 시 생성 완료 client rollback
379|- 종료 실패와 관계없이 모든 client에 best-effort cleanup 수행
380|- `factory_overrides`로 명시적인 서비스별 factory 대체 지원
381|- `runtime.require(name)`으로 생성된 client 조회
382|
383|### `async_check_all_services(...)`
384|
385|동기 함수와 awaitable health check를 모두 실행합니다. `parallel`, `timeout_seconds`, `overall_timeout_seconds`를 지원하며 required 실패 시 예외의 `result`와 `failures`에서 전체 상태를 확인할 수 있습니다.
386|
387|### 주요 예외 및 cleanup 계약
388|
389|| API | 주요 실패 | cleanup 계약 |
390|| --- | --- | --- |
391|| `load_service_configs()` | `ConfigError` | 클라이언트를 생성하지 않음 |
392|| `ServiceClientWrapper.check()` | `ServiceClientWrapperError` | 자동 종료하지 않음 |
393|| `check_all_services()` / `async_check_all_services()` | required 실패 시 `HealthCheckError` | 호출자가 lifecycle을 관리 |
394|| `assemble_services()` | 설정/생성/startup healthcheck 예외 | startup healthcheck 실패 시 생성한 client를 닫고 원래 예외를 다시 발생 |
395|| `assemble_service_runtime()` | 설정/생성/startup healthcheck 예외 | 이미 생성한 client를 best-effort로 닫고 원래 예외를 다시 발생 |
396|| `async_close_service_clients()` | 종료 실패 시 `ServiceCloseError` | 나머지 client 종료를 계속 시도하고 전체 실패를 보존 |
397|
398|동기 `close_service_clients()`는 첫 종료 예외를 그대로 전파하므로 이후 항목까지 정리해야 한다면 `async_close_service_clients()`를 사용합니다.
399|
400|### `check_all_services(service_checks, *, required_services=None, timer=time.perf_counter, parallel=False)`
401|
402|서비스 헬스체크 함수를 모아 실행합니다.
403|
404|반환값:
405|
406|- `HealthCheckResult(ok: bool, services: list[ServiceHealthStatus])`
407|
408|각 항목:
409|
410|- `ServiceHealthStatus(service, ok, latency_ms, required=False, error=None, error_type=None)`
411|- `HealthCheckResult.to_dict()`와 `ServiceHealthStatus.to_dict()`는 JSON-friendly dict를 반환합니다.
412|
413|규칙:
414|
415|- `parallel=False`면 입력 순서대로 순차 실행합니다.
416|- `parallel=True`면 `ThreadPoolExecutor`로 병렬 실행하지만 반환 순서는 입력 순서를 유지합니다.
417|- required 서비스가 실패하면 `HealthCheckError`를 발생시킵니다.
418|- `HealthCheckError.status`는 첫 번째 required 서비스 실패 상태를 제공합니다.
419|- `HealthCheckError.failures`는 실패한 required 서비스 전체를 제공합니다.
420|- `HealthCheckError.result`는 optional 서비스를 포함한 전체 healthcheck 결과를 제공합니다.
421|- 오류 문자열은 마스킹됩니다.
422|
423|### `mask_sensitive_value(value: str | None) -> str | None`
424|
425|민감정보를 로그 친화적으로 마스킹합니다.
426|
427|주요 동작:
428|
429|- URL/DSN이면 사용자정보와 민감 query parameter를 마스킹합니다.
430|- raw token/secret/password 계열 문자열도 `***` 또는 `key=***` 형태로 변환합니다.
431|- 민감 키워드가 없는 일반 진단 문자열은 보존합니다.
432|
433|### `retry_call(operation, *args, retry_on=..., max_attempts=..., base_delay_seconds=0.5, sleep=time.sleep, **kwargs)`
434|
435|동기 함수 재시도 helper입니다.
436|
437|- `max_attempts`는 1 이상이어야 합니다.
438|- 실패 간격은 지수 백오프(`0.5`, `1.0`, `2.0`, ...)입니다.
439|- 재시도 대상 예외만 다시 시도하고, 마지막 시도에서도 실패하면 원래 예외를 그대로 올립니다.
440|
441|### `build_service_log_event(...) -> dict[str, Any]`
442|
443|서비스 이벤트를 구조화된 dict로 생성합니다.
444|
445|기본 키:
446|
447|- `service`
448|- `operation`
449|- `outcome`
450|- optional: `host`, `latency_ms`, `retry_count`, `error`
451|
452|`error`와 민감한 `extra` 필드는 마스킹됩니다.
453|
454|### `configure_logging(*, level=None, log_path=None, force=False, env=None, env_key="DOCMESH_LOG_LEVEL") -> logging.Logger`
455|
456|루트 로거를 설정합니다.
457|
458|동작:
459|
460|- `level`이 주어지면 그 값을 우선 사용합니다.
461|- 아니면 `DOCMESH_LOG_LEVEL` 환경변수를 읽습니다.
462|- 값이 없거나 빈 문자열이면 `INFO`를 사용합니다.
463|- 잘못된 로그 레벨이면 `ValueError`를 발생시킵니다.
464|- `log_path`가 있으면 부모 디렉터리를 생성한 뒤 파일 핸들러를 추가합니다.
465|
466|## 6. Keycloak API
467|
468|### `KeycloakAuthService(config: KeycloakConfig, ...)`
469|
470|Keycloak 토큰 획득과 JWT 검증을 담당합니다.
471|
472|주요 속성/메서드:
473|
474|- `issuer`
475|- `token_endpoint`
476|- `jwks_endpoint`
477|- `fetch_access_token(...) -> AccessTokenResult`
478|- `extract_user_info(token: str) -> AuthenticatedUser`
479|
480|### `fetch_access_token(*, scope=None, username=None, password=None) -> AccessTokenResult`
481|
482|- 기본 grant type은 `client_credentials`입니다.
483|- password grant는 함수 인자를 우선 사용하고, 생략된 값은 `config.token_username`, `config.token_password`에서 가져옵니다.
484|- 두 입력 경로에도 username/password가 모두 갖춰지지 않으면 `KeycloakTokenConfigurationError`가 발생합니다.
485|- 일시적 장애(`KeycloakTokenTemporaryError`)는 `config.max_retries + 1`번까지 재시도합니다.
486|- 재시도 이벤트는 `build_service_log_event()` 형식으로 로깅됩니다.
487|
488|### `extract_user_info(token: str) -> AuthenticatedUser`
489|
490|- `Bearer <jwt>` 형식과 raw JWT 문자열을 모두 받습니다.
491|- `HS256`과 `RS256` 검증 경로를 지원합니다.
492|- `audience`가 설정되면 audience 검증을 수행하고, 없으면 audience 검증을 끕니다.
493|- RS256에서는 JWKS 캐시(`jwks_cache_ttl_seconds`)를 사용하고, 필요 시 refresh합니다.
494|- 반환 객체에는 `sub`, `preferred_username`, `email`, `given_name`, `family_name`, `name`, `realm_roles`, `client_roles`, `claims`가 포함됩니다.
495|
496|### `KeycloakProvisioner(config: KeycloakConfig, *, admin_client)`
497|
498|Realm / Client / Role 프로비저닝 orchestration을 담당합니다.
499|
500|- `config.provisioning_dry_run=True`면 실제 변경 없이 `planned`만 채웁니다.
501|