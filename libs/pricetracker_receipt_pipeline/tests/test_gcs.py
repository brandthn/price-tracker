"""Découpage des URI gs://."""

from __future__ import annotations

import pytest

from pricetracker_receipt_pipeline.worker.gcs import split_gs_uri


def test_split_gs_uri():
    assert split_gs_uri("gs://bucket/a/b/c.jpg") == ("bucket", "a/b/c.jpg")


@pytest.mark.parametrize(
    "uri",
    ["https://bucket/obj", "gs://bucket", "gs://bucket/", "gs:///obj"],
)
def test_split_gs_uri_rejects_malformed(uri: str):
    with pytest.raises(ValueError):
        split_gs_uri(uri)
