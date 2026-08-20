"""Run the production MAGI API with a PostgreSQL-compatible event loop."""

from __future__ import annotations

import asyncio
import selectors
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "magi.api.production:create_production_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        loop="none" if sys.platform == "win32" else "auto",
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(
            server.serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
        return
    uvicorn.run(
        "magi.api.production:create_production_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
