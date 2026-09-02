from __future__ import annotations

import inspect as inspect_module
from dataclasses import replace
from io import BytesIO

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import create_async_engine

import dms
from dms.domain.interfaces import MetadataConflictError
from dms.infrastructure.metadata.async_sqlite import AsyncSqliteMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from test_dms.sdk_test_support import (
    CursorMemoryStore,
    RecordingOperationStore,
    StreamMemoryObjectStore,
    metadata,
)

PERSONAL_ALICE = dms.DocumentPartition.personal("alice")
PERSONAL_BOB = dms.DocumentPartition.personal("bob")
GROUP_ALPHA = dms.DocumentPartition.group("alpha")


class KeyAuthoritativeObjectStore(StreamMemoryObjectStore):
    """Match MinIO semantics where the storage key, not document_id, is authoritative."""

    def object_exists(self, document_id: str, storage_key: str) -> bool:
        return any(key == storage_key for _, key in self._items)

    def delete_object(self, document_id: str, storage_key: str) -> None:
        for key in tuple(self._items):
            if key[1] == storage_key:
                del self._items[key]
                return
        raise LookupError(storage_key)


class ExplodingPath:
    def __fspath__(self) -> str:
        raise AssertionError("invalid partition must be validated before file access")


def _request(
    document_id: str,
    *,
    idempotency_key: str | None = None,
    idempotency_scope: str | None = None,
) -> dms.UploadDocumentRequest:
    return dms.UploadDocumentRequest(
        document_id=document_id,
        content=document_id.encode(),
        filename=f"{document_id}.txt",
        content_type="text/plain",
        idempotency_key=idempotency_key,
        idempotency_scope=idempotency_scope,
    )


def _sdk(*, operation_store=None) -> dms.DefaultDocumentManagementSDK:
    return dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_store=operation_store,
    )


def test_public_contract_exposes_only_personal_and_group_partitions() -> None:
    assert list(dms.PartitionKind) == [
        dms.PartitionKind.PERSONAL,
        dms.PartitionKind.GROUP,
    ]
    assert dms.DocumentPartition.personal("person").to_dict() == {
        "kind": "personal",
        "partition_id": "person",
    }
    assert dms.DocumentPartition.group("group").to_dict() == {
        "kind": "group",
        "partition_id": "group",
    }
    assert {
        "AccessContext",
        "AccessDeniedError",
        "DocumentAccessPolicy",
    }.isdisjoint(vars(dms))


@pytest.mark.parametrize("partition_id", ["", "   "])
def test_partition_rejects_invalid_identifiers(partition_id: object) -> None:
    with pytest.raises(ValueError, match="partition_id"):
        dms.DocumentPartition(
            kind=dms.PartitionKind.PERSONAL,
            partition_id=partition_id,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("partition_id", [None, 1])
def test_partition_rejects_non_string_identifiers(partition_id: object) -> None:
    with pytest.raises(TypeError, match="partition_id"):
        dms.DocumentPartition(
            kind=dms.PartitionKind.PERSONAL,
            partition_id=partition_id,  # type: ignore[arg-type]
        )


def test_personal_and_group_partitions_isolate_core_document_operations() -> None:
    sdk = _sdk()
    personal = sdk.upload_document(_request("personal-doc"), partition=PERSONAL_ALICE)
    group = sdk.upload_document(_request("group-doc"), partition=GROUP_ALPHA)

    assert personal.metadata.partition == PERSONAL_ALICE
    assert group.metadata.partition == GROUP_ALPHA
    assert personal.metadata.to_public_dict()["partition"] == PERSONAL_ALICE.to_dict()
    assert [
        item.document_id for item in sdk.list_documents(partition=PERSONAL_ALICE).items
    ] == ["personal-doc"]
    assert [
        item.document_id for item in sdk.list_documents(partition=GROUP_ALPHA).items
    ] == ["group-doc"]

    for operation in (
        lambda: sdk.get_document_metadata("personal-doc", partition=GROUP_ALPHA),
        lambda: sdk.get_document_content("personal-doc", partition=GROUP_ALPHA),
        lambda: sdk.delete_document("personal-doc", partition=GROUP_ALPHA),
    ):
        with pytest.raises(dms.DocumentNotFoundError):
            operation()

    assert (
        sdk.get_document_content("personal-doc", partition=PERSONAL_ALICE).content
        == b"personal-doc"
    )


def test_wrong_partition_recovery_hides_document_as_not_found() -> None:
    sdk = _sdk()
    sdk.upload_document(_request("personal-recovery"), partition=PERSONAL_ALICE)

    inspection = sdk.inspect_document(
        "personal-recovery",
        partition=GROUP_ALPHA,
    )
    assert inspection.metadata_exists is False
    assert inspection.issue is dms.RecoveryIssue.METADATA_MISSING

    with pytest.raises(dms.DocumentNotFoundError):
        sdk.reconcile_document(
            "personal-recovery",
            dms.RecoveryAction.MARK_FAILED,
            partition=GROUP_ALPHA,
        )


def test_document_id_remains_globally_unique_across_partitions() -> None:
    sdk = _sdk()
    sdk.upload_document(_request("global-id"), partition=PERSONAL_ALICE)

    with pytest.raises(dms.DuplicateDocumentError):
        sdk.upload_document(_request("global-id"), partition=GROUP_ALPHA)


def test_partition_is_required_and_bound_to_cursor() -> None:
    sdk = _sdk()
    sdk.upload_document(_request("one"), partition=PERSONAL_ALICE)
    sdk.upload_document(_request("two"), partition=PERSONAL_ALICE)

    with pytest.raises(TypeError, match="partition"):
        sdk.list_documents()  # type: ignore[call-arg]

    first = sdk.list_documents(partition=PERSONAL_ALICE, limit=1)
    assert first.next_cursor is not None
    with pytest.raises(dms.ValidationError, match="partition"):
        sdk.list_documents(
            partition=PERSONAL_BOB,
            cursor=first.next_cursor,
            limit=1,
        )


def test_partition_only_operations_reject_invalid_partition_values() -> None:
    operations = RecordingOperationStore()
    sdk = _sdk(operation_store=operations)
    sdk_without_operations = _sdk()
    sdk.upload_document(
        _request(
            "invalid-partition-target",
            idempotency_key="operation-key",
            idempotency_scope="operation-scope",
        ),
        partition=PERSONAL_ALICE,
    )

    calls = (
        lambda: sdk.get_document_metadata(
            "invalid-partition-target",
            partition=None,  # type: ignore[arg-type]
        ),
        lambda: sdk.list_documents(partition=None),  # type: ignore[arg-type]
        lambda: sdk.inspect_document(
            "invalid-partition-target",
            partition=None,  # type: ignore[arg-type]
        ),
        lambda: sdk.list_recovery_candidates(
            status=dms.DocumentStatus.FAILED,
            partition=None,  # type: ignore[arg-type]
        ),
        lambda: sdk.get_upload_operation(
            scope="operation-scope",
            idempotency_key="operation-key",
            partition=None,  # type: ignore[arg-type]
        ),
        lambda: sdk.upload_file(
            ExplodingPath(),  # type: ignore[arg-type]
            partition=None,  # type: ignore[arg-type]
        ),
    )
    for call in calls:
        with pytest.raises(dms.ValidationError, match="partition"):
            call()
    with pytest.raises(dms.ValidationError, match="partition"):
        sdk_without_operations.get_upload_operation(
            scope="operation-scope",
            idempotency_key="operation-key",
            partition=None,  # type: ignore[arg-type]
        )


def test_all_normal_public_operations_require_keyword_only_partition() -> None:
    methods = {
        "upload_document",
        "upload_file",
        "upload_document_stream",
        "get_upload_operation",
        "get_internal_document_metadata",
        "get_document_metadata",
        "list_documents",
        "list_documents_page",
        "iter_documents",
        "get_document_content",
        "get_document_content_stream",
        "copy_document_to",
        "delete_document",
        "soft_delete_document",
        "hard_delete_document",
        "inspect_document",
        "list_recovery_candidates",
        "iter_recovery_candidates",
        "reconcile_document",
        "execute_reconciliation_plan",
        "reconcile_documents",
        "clear_partition_data",
        "initialize_partition_for_data_load",
    }
    for sdk_type in (
        dms.DefaultDocumentManagementSDK,
        dms.AsyncDocumentManagementSDK,
    ):
        for method_name in methods:
            parameter = inspect_module.signature(
                getattr(sdk_type, method_name)
            ).parameters["partition"]
            assert parameter.kind is inspect_module.Parameter.KEYWORD_ONLY
            assert parameter.default is inspect_module.Parameter.empty

        for global_method in ("clear_all_data", "initialize_for_data_load"):
            assert (
                "partition"
                not in inspect_module.signature(
                    getattr(sdk_type, global_method)
                ).parameters
            )


def test_storage_and_idempotency_namespaces_include_partition_kind() -> None:
    operations = RecordingOperationStore()
    sdk = _sdk(operation_store=operations)
    group_with_same_id = dms.DocumentPartition.group(PERSONAL_ALICE.partition_id)

    for partition in (PERSONAL_ALICE, group_with_same_id):
        sdk.upload_document(
            _request(
                f"{partition.kind.value}-doc",
                idempotency_key="same-key",
                idempotency_scope="same-scope",
            ),
            partition=partition,
        )
        operation = sdk.get_upload_operation(
            scope="same-scope",
            idempotency_key="same-key",
            partition=partition,
        )
        assert operation.scope == "same-scope"

    personal_key = sdk.get_internal_document_metadata(
        "personal-doc", partition=PERSONAL_ALICE
    ).storage_key
    group_key = sdk.get_internal_document_metadata(
        "group-doc", partition=group_with_same_id
    ).storage_key
    assert personal_key.startswith("documents/partitions/personal/")
    assert group_key.startswith("documents/partitions/group/")
    assert operations.scopes[0].startswith("partition:personal:")
    assert operations.scopes[1].startswith("partition:group:")
    assert operations.scopes[0] != operations.scopes[1]


def test_reconciliation_plan_is_bound_to_its_origin_partition() -> None:
    sdk = _sdk()
    uploaded = sdk.upload_document(_request("failed-doc"), partition=PERSONAL_ALICE)
    internal = sdk.get_internal_document_metadata(
        uploaded.document_id,
        partition=PERSONAL_ALICE,
    )
    sdk._metadata_store.update_metadata(
        replace(internal, status=dms.DocumentStatus.FAILED)
    )
    sdk._object_store.delete_object(uploaded.document_id, internal.storage_key)

    plan = sdk.reconcile_documents(
        status=dms.DocumentStatus.FAILED,
        action=dms.RecoveryAction.MARK_FAILED,
        dry_run=True,
        partition=PERSONAL_ALICE,
    ).to_plan()

    assert plan.partition == PERSONAL_ALICE
    with pytest.raises(dms.ValidationError, match="partition"):
        sdk.execute_reconciliation_plan(plan, partition=GROUP_ALPHA)


def test_orphan_recovery_rejects_another_document_key_in_same_partition() -> None:
    objects = KeyAuthoritativeObjectStore()
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=objects,
    )
    uploaded = sdk.upload_document(_request("live-document"), partition=PERSONAL_ALICE)
    internal = sdk.get_internal_document_metadata(
        uploaded.document_id,
        partition=PERSONAL_ALICE,
    )

    with pytest.raises(dms.ValidationError, match="document"):
        sdk.reconcile_document(
            "missing-document",
            dms.RecoveryAction.PURGE_ORPHAN_OBJECT,
            storage_key=internal.storage_key,
            partition=PERSONAL_ALICE,
        )

    assert (
        sdk.get_document_content(
            uploaded.document_id,
            partition=PERSONAL_ALICE,
        ).content
        == b"live-document"
    )


def test_clear_partition_data_preserves_other_partitions() -> None:
    sdk = _sdk()
    sdk.upload_document(_request("personal-doc"), partition=PERSONAL_ALICE)
    sdk.upload_document(_request("group-doc"), partition=GROUP_ALPHA)

    result = sdk.clear_partition_data(partition=PERSONAL_ALICE)

    assert result.metadata_deleted == 1
    assert result.objects_deleted == 1
    assert sdk.list_documents(partition=PERSONAL_ALICE).items == []
    assert [
        item.document_id for item in sdk.list_documents(partition=GROUP_ALPHA).items
    ] == ["group-doc"]


def test_partition_reset_rejects_none_without_clearing_all_data() -> None:
    sdk = _sdk()
    sdk.upload_document(_request("personal-kept"), partition=PERSONAL_ALICE)
    sdk.upload_document(_request("group-kept"), partition=GROUP_ALPHA)

    with pytest.raises(dms.ValidationError, match="partition"):
        sdk.clear_partition_data(partition=None)  # type: ignore[arg-type]
    with pytest.raises(dms.ValidationError, match="partition"):
        sdk.initialize_partition_for_data_load(partition=None)  # type: ignore[arg-type]

    assert (
        sdk.get_document_metadata("personal-kept", partition=PERSONAL_ALICE).document_id
        == "personal-kept"
    )
    assert (
        sdk.get_document_metadata("group-kept", partition=GROUP_ALPHA).document_id
        == "group-kept"
    )


@pytest.mark.asyncio
async def test_async_facade_preserves_partition_contract() -> None:
    sdk = dms.AsyncDocumentManagementSDK(_sdk())
    uploaded = await sdk.upload_document(
        _request("async-personal"),
        partition=PERSONAL_ALICE,
    )

    assert [
        item.document_id async for item in sdk.iter_documents(partition=PERSONAL_ALICE)
    ] == ["async-personal"]
    with pytest.raises(dms.DocumentNotFoundError):
        await sdk.copy_document_to(
            uploaded.document_id,
            BytesIO(),
            partition=GROUP_ALPHA,
        )


def test_sqlalchemy_schema_uses_required_partition_columns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    SqliteMetadataStore(engine)

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("document_metadata")
    }
    assert columns["partition_type"]["nullable"] is False
    assert columns["partition_id"]["nullable"] is False
    assert "user_id" not in columns
    checks = inspect(engine).get_check_constraints("document_metadata")
    partition_check = " ".join(check["sqltext"] for check in checks).lower()
    assert "partition_type" in partition_check
    assert "personal" in partition_check
    assert "group" in partition_check


def test_sql_metadata_update_cannot_move_a_document_between_partitions() -> None:
    store = SqliteMetadataStore(create_engine("sqlite+pysqlite:///:memory:"))
    item = metadata("immutable-partition", partition=PERSONAL_ALICE)
    store.save_metadata(item)

    with pytest.raises(LookupError):
        store.update_metadata(replace(item, partition=GROUP_ALPHA))

    assert (
        store.get_metadata(
            item.document_id,
            partition=PERSONAL_ALICE,
        ).partition
        == PERSONAL_ALICE
    )
    with pytest.raises(LookupError):
        store.get_metadata(item.document_id, partition=GROUP_ALPHA)


def test_sync_sql_duplicate_maps_to_metadata_conflict() -> None:
    store = SqliteMetadataStore(create_engine("sqlite+pysqlite:///:memory:"))
    item = metadata("duplicate", partition=PERSONAL_ALICE)
    store.save_metadata(item)

    with pytest.raises(MetadataConflictError):
        store.save_metadata(item)


@pytest.mark.asyncio
async def test_async_sql_metadata_update_cannot_move_a_document_between_partitions() -> (
    None
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = AsyncSqliteMetadataStore(engine)
    try:
        await store.initialize()
        item = metadata("async-immutable-partition", partition=PERSONAL_ALICE)
        await store.save_metadata(item)

        with pytest.raises(LookupError):
            await store.update_metadata(replace(item, partition=GROUP_ALPHA))

        assert (
            await store.get_metadata(item.document_id, partition=PERSONAL_ALICE)
        ).partition == PERSONAL_ALICE
        with pytest.raises(LookupError):
            await store.get_metadata(item.document_id, partition=GROUP_ALPHA)
    finally:
        await engine.dispose()
