from __future__ import annotations

from io import BytesIO

import pytest

import dms
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore

PERSONAL = dms.DocumentPartition.personal("person-a")
GROUP = dms.DocumentPartition.group("group-a")


def _sdk() -> dms.DefaultDocumentManagementSDK:
    return dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )


def _request(document_id: str) -> dms.UploadDocumentRequest:
    return dms.UploadDocumentRequest(
        document_id=document_id,
        content=document_id.encode(),
        filename=f"{document_id}.txt",
        content_type="text/plain",
    )


def test_personal_and_group_partitions_route_documents_independently() -> None:
    sdk = _sdk()
    personal = sdk.upload_document(_request("personal"), partition=PERSONAL)
    group = sdk.upload_document(_request("group"), partition=GROUP)

    assert personal.metadata.partition == PERSONAL
    assert group.metadata.partition == GROUP
    assert [
        item.document_id for item in sdk.list_documents(partition=PERSONAL).items
    ] == ["personal"]
    assert [item.document_id for item in sdk.list_documents(partition=GROUP).items] == [
        "group"
    ]

    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_document_content(personal.document_id, partition=GROUP)
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.delete_document(personal.document_id, partition=GROUP)


def test_partition_reset_removes_only_the_selected_partition() -> None:
    sdk = _sdk()
    sdk.upload_document(_request("personal"), partition=PERSONAL)
    sdk.upload_document(_request("group"), partition=GROUP)

    result = sdk.clear_partition_data(partition=PERSONAL)

    assert result.metadata_deleted == 1
    assert result.objects_deleted == 1
    assert sdk.list_documents(partition=PERSONAL).items == []
    assert [item.document_id for item in sdk.list_documents(partition=GROUP).items] == [
        "group"
    ]


@pytest.mark.asyncio
async def test_async_partition_routing_matches_sync() -> None:
    sdk = dms.AsyncDocumentManagementSDK(_sdk())
    uploaded = await sdk.upload_document(_request("async-personal"), partition=PERSONAL)

    assert [
        item.document_id async for item in sdk.iter_documents(partition=PERSONAL)
    ] == [uploaded.document_id]
    with pytest.raises(dms.DocumentNotFoundError):
        await sdk.copy_document_to(uploaded.document_id, BytesIO(), partition=GROUP)
