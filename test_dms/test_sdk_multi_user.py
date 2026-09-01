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


def _context(user_id: str) -> dms.AccessContext:
    return dms.AccessContext(user_id=user_id)


def test_user_access_context_isolates_upload_list_read_and_delete() -> None:
    sdk = _sdk()
    alice = _context("alice")
    bob = _context("bob")

    alice_result = sdk.upload_document(_request("alice-doc"), access_context=alice)
    bob_result = sdk.upload_document(_request("bob-doc"), access_context=bob)

    assert alice_result.metadata.user_id == "alice"
    assert bob_result.metadata.user_id == "bob"
    assert [item.document_id for item in sdk.list_documents(access_context=alice).items] == ["alice-doc"]
    assert [item.document_id for item in sdk.list_documents(access_context=bob).items] == ["bob-doc"]

    with pytest.raises(dms.AccessDeniedError):
        sdk.get_document_metadata(alice_result.document_id, access_context=bob)
    with pytest.raises(dms.AccessDeniedError):
        sdk.get_document_content(alice_result.document_id, access_context=bob)
    with pytest.raises(dms.AccessDeniedError):
        sdk.delete_document(alice_result.document_id, access_context=bob)

    assert sdk.get_document_content(alice_result.document_id, access_context=alice).content == b"alice-doc"
    assert sdk.delete_document(alice_result.document_id, access_context=alice).deleted is True


def test_user_access_context_rejects_cross_user_upload_and_binds_cursor() -> None:
    sdk = _sdk()
    alice = _context("alice")
    bob = _context("bob")
    sdk.upload_document(_request("alice-1"), access_context=alice)
    sdk.upload_document(_request("alice-2"), access_context=alice)

    with pytest.raises(dms.ValidationError):
        sdk.upload_document(_request("spoofed", user_id="bob"), access_context=alice)

    first = sdk.list_documents(limit=1, access_context=alice)
    assert first.next_cursor is not None
    with pytest.raises(dms.ValidationError):
        sdk.list_documents(cursor=first.next_cursor, limit=1, access_context=bob)


def test_user_access_context_reset_removes_only_the_users_data() -> None:
    sdk = _sdk()
    alice = _context("alice")
    bob = _context("bob")
    sdk.upload_document(_request("alice-doc"), access_context=alice)
    sdk.upload_document(_request("bob-doc"), access_context=bob)

    result = sdk.clear_all_data(access_context=alice)

    assert result.metadata_deleted == 1
    assert result.objects_deleted == 1
    assert [item.document_id for item in sdk.list_documents(access_context=bob).items] == ["bob-doc"]
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
async def test_async_access_context_preserves_user_isolation() -> None:
    sync_sdk = _sdk()
    sdk = dms.AsyncDocumentManagementSDK(sync_sdk)
    alice = _context("alice")
    bob = _context("bob")

    uploaded = await sdk.upload_document(_request("async-alice"), access_context=alice)
    assert [item.document_id async for item in sdk.iter_documents(access_context=alice)] == ["async-alice"]
    with pytest.raises(dms.AccessDeniedError):
        await sdk.get_document_content(uploaded.document_id, access_context=bob)

    sink = BytesIO()
    with pytest.raises(dms.AccessDeniedError):
        await sdk.copy_document_to(uploaded.document_id, sink, access_context=bob)
