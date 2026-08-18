"""Shared test fixtures."""
import pytest


@pytest.fixture
def mock_udp_responses(monkeypatch):
    """Inject pre-canned UDP responses into AnidbUdpClient.

    Patch _send_raw so each call pops the next bytes off the queue.
    Usage::

        mock_udp_responses.extend([b"200 sess LOGIN ACCEPTED\\n", ...])
    """
    responses: list[bytes] = []

    async def fake_send_raw(self, command: str) -> bytes:  # noqa: ARG001
        if not responses:
            raise RuntimeError("No more fake UDP responses queued")
        return responses.pop(0)

    from anibridge.providers.anidb import udp_client as mod
    monkeypatch.setattr(mod.AnidbUdpClient, "_send_raw", fake_send_raw)
    return responses
