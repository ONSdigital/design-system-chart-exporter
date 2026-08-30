from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.models import RenderedChart, StoredObject
from app.storage.memory import MemoryObject


@pytest.mark.parametrize(
    ("instance", "field"),
    [
        (
            RenderedChart(
                id=uuid4(), key="charts/x.png", size_bytes=1, width=1, height=1, created_at=datetime.now(UTC)
            ),
            "key",
        ),
        (StoredObject(bucket="b", key="charts/x.png", size_bytes=1, content_type="image/png"), "key"),
        (MemoryObject(data=b"x", content_type="image/png"), "data"),
    ],
)
def test_domain_models_are_frozen_and_slotted(instance, field):
    """Value objects: immutable (frozen) and typo-proof (slots, no __dict__)."""
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, "other")

    assert not hasattr(instance, "__dict__")
