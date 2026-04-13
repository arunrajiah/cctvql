"""
cctvQL entry point.
Run as: python -m cctvql  or  cctvql  (after pip install)
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cctvql",
        description="cctvQL — Conversational query layer for CCTV systems",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ---- chat subcommand ----
    chat_parser = subparsers.add_parser("chat", help="Start interactive CLI chat")
    chat_parser.add_argument("--config", default="config/config.yaml", help="Path to config file")
    chat_parser.add_argument("--adapter", help="Adapter name (frigate, onvif, ...)")
    chat_parser.add_argument("--llm", help="LLM backend name (ollama, openai, anthropic)")
    chat_parser.add_argument("--verbose", "-v", action="store_true", help="Show intent debug info")

    # ---- serve subcommand ----
    serve_parser = subparsers.add_parser("serve", help="Start REST API server")
    serve_parser.add_argument("--config", default="config/config.yaml")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")

    args = parser.parse_args()

    if args.command == "chat":
        from cctvql._bootstrap import bootstrap
        bootstrap(args.config)
        from cctvql.interfaces.cli import run_cli
        run_cli(
            adapter_name=args.adapter,
            llm_name=args.llm,
            verbose=args.verbose,
        )

    elif args.command == "serve":
        from cctvql._bootstrap import bootstrap
        bootstrap(args.config)
        import uvicorn
        uvicorn.run(
            "cctvql.interfaces.rest_api:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
