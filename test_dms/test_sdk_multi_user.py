from __future__ import annotations

from io import BytesIO

import pytest

import dms
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


def _sdk() -> dms.DefaultDocumentManagementSDK:
    return dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )


def _request(document_id: str, *, user_id: str | None = None) -> dms.UploadDocumentRequest:
    return dms.UploadDocumentRequest(
        document_id=document_id,
        content=document_id.encode(),
        filename=f"{document_id}.txt",
        content_type="text/plain",
        user_id=user_id,
    )


def test_user_scoped_facades_isolate_upload_list_read_and_delete() -> None:
    sdk = _sdk()
    alice = sdk.scoped(dms.DmsOperationContext(user_id="alice"))
    bob = sdk.scoped(dms.DmsOperationContext(user_id="bob"))

    alice_result = alice.upload_document(_request("alice-doc"))
    bob_result = bob.upload_document(_request("bob-doc"))

    assert alice_result.metadata.user_id == "alice"
    assert bob_result.metadata.user_id == "bob"
    assert [item.document_id for item in alice.list_documents().items] == ["alice-doc"]
    assert [item.document_id for item in bob.list_documents().items] == ["bob-doc"]

    with pytest.raises(dms.AccessDeniedError):
        bob.get_document_metadata(alice_result.document_id)
    with pytest.raises(dms.AccessDeniedError):
        bob.get_document_content(alice_result.document_id)
    with pytest.raises(dms.AccessDeniedError):
        bob.delete_document(alice_result.document_id)

    assert alice.get_document_content(alice_result.document_id).content == b"alice-doc"
    assert alice.delete_document(alice_result.document_id).deleted is True


def test_user_scope_rejects_cross_user_upload_and_binds_cursor() -> None:
    sdk = _sdk()
    alice = sdk.scoped(dms.DmsOperationContext(user_id="alice"))
    bob = sdk.scoped(dms.DmsOperationContext(user_id="bob"))
    alice.upload_document(_request("alice-1"))
    alice.upload_document(_request("alice-2"))

    with pytest.raises(dms.ValidationError):
        alice.upload_document(_request("spoofed", user_id="bob"))

    first = alice.list_documents(limit=1)
    assert first.next_cursor is not None
    with pytest.raises(dms.ValidationError):
        bob.list_documents(cursor=first.next_cursor, limit=1)


def test_user_scoped_reset_removes_only_the_users_data() -> None:
    sdk = _sdk()
    alice = sdk.scoped(dms.DmsOperationContext(user_id="alice"))
    bob = sdk.scoped(dms.DmsOperationContext(user_id="bob"))
    alice.upload_document(_request("alice-doc"))
    bob.upload_document(_request("bob-doc"))

    result = alice.clear_all_data()

    assert result.metadata_deleted == 1
    assert result.objects_deleted == 1
    assert [item.document_id for item in bob.list_documents().items] == ["bob-doc"]
    assert sdk.list_documents().items == []


def test_user_id_is_available_to_access_policy_and_public_serialization() -> None:
    seen: list[str | None] = []

    class UserPolicy:
        def allows(self, *, operation, context, metadata):
            del operation
            if metadata is None:
                return context is not None
            seen.append(metadata.user_id)
            return context is not None and metadata.user_id == context.user_id

    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        access_policy=UserPolicy(),
    )
    uploaded = sdk.upload_document(_request("policy-doc", user_id="alice"))

    assert uploaded.metadata.to_public_dict()["user_id"] == "alice"
    assert sdk.get_document_metadata(
        uploaded.document_id,
        access_context=dms.AccessContext(user_id="alice"),
    ).user_id == "alice"
    assert seen == ["alice"]


@pytest.mark.asyncio
async def test_async_scoped_facade_preserves_user_isolation() -> None:
    sync_sdk = _sdk()
    sdk = dms.AsyncDocumentManagementSDK(sync_sdk)
    alice = sdk.scoped(dms.DmsOperationContext(user_id="alice"))
    bob = sdk.scoped(dms.DmsOperationContext(user_id="bob"))

    uploaded = await alice.upload_document(_request("async-alice"))
    assert [item.document_id async for item in alice.iter_documents()] == ["async-alice"]
    with pytest.raises(dms.AccessDeniedError):
        await bob.get_document_content(uploaded.document_id)

    sink = BytesIO()
    with pytest.raises(dms.AccessDeniedError):
        await bob.copy_document_to(uploaded.document_id, sink)
