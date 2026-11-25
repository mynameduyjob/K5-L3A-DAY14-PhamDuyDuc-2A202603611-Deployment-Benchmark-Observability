"""API Key authentication (tiêu chí 6)."""
import secrets

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency kiểm tra header X-API-Key; thiếu hoặc sai -> HTTP 401."""
    if (
        not api_key
        or not settings.agent_api_key
        or not secrets.compare_digest(api_key, settings.agent_api_key)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key",
        )
    return api_key
