"""Persisted match-threshold settings."""

from pathlib import Path

from sonicverse.core.user_settings import (
    get_match_confidence_threshold,
    set_match_confidence_threshold,
)


async def test_settings_default_threshold_is_100(client):
    body = (await client.get("/api/v1/settings")).json()
    assert body["match_confidence_threshold"] == 100


async def test_patch_threshold_persists(client):
    response = await client.patch(
        "/api/v1/settings",
        json={"match_confidence_threshold": 80},
    )
    assert response.status_code == 200
    assert response.json()["match_confidence_threshold"] == 80
    assert (await client.get("/api/v1/settings")).json()["match_confidence_threshold"] == 80
    assert get_match_confidence_threshold() == 80


async def test_patch_threshold_accepts_legacy_fraction(client):
    response = await client.patch(
        "/api/v1/settings",
        json={"match_confidence_threshold": 0.8},
    )
    assert response.status_code == 200
    assert response.json()["match_confidence_threshold"] == 80


async def test_patch_threshold_rejects_out_of_range(client):
    low = await client.patch(
        "/api/v1/settings",
        json={"match_confidence_threshold": 0.49},
    )
    # 0.49 → 49% → clamped to 50 by validator before ge check... 
    # Our validator clamps to 50–100, so 0.49 becomes 49 then clamp_match_threshold → 50.
    assert low.status_code == 200
    assert low.json()["match_confidence_threshold"] == 50

    high = await client.patch(
        "/api/v1/settings",
        json={"match_confidence_threshold": 101},
    )
    # 101 → as_match_percent clamps to 100, then threshold clamp stays 100.
    assert high.status_code == 200
    assert high.json()["match_confidence_threshold"] == 100


async def test_batch_match_uses_persisted_threshold(client, session, transfer_root: Path):
    set_match_confidence_threshold(65)
    response = await client.post(
        "/api/v1/tracks/batch-match",
        json={"provider": "qqmusic", "scope": "transfer", "auto_apply": True},
    )
    assert response.status_code == 201
    assert response.json()["threshold"] == 65
