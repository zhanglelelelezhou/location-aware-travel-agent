from __future__ import annotations

import argparse
import asyncio
import json

from mcp import Client


async def probe(url: str) -> None:
    async with Client(url) as client:
        result = await client.list_tools()
        print(
            json.dumps(
                {
                    "protocol_version": client.protocol_version,
                    "tools": sorted(tool.name for tool in result.tools),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe a travel-tools MCP endpoint.")
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8001/mcp")
    args = parser.parse_args()
    asyncio.run(probe(args.url))


if __name__ == "__main__":
    main()
