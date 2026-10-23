"""Entry point: uvicorn app.main:app"""

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_env == "dev",
        log_level=settings.log_level.lower(),
    )
