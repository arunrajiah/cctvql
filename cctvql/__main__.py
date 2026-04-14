"""
cctvQL entry point.
Run as: python -m cctvql  or  cctvql  (after pip install)
"""

from __future__ import annotations

import argparse
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

    # ---- discover subcommand ----
    discover_parser = subparsers.add_parser(
        "discover", help="Discover ONVIF cameras on the local network"
    )
    discover_parser.add_argument(
        "--timeout", type=float, default=3.0, help="Probe timeout in seconds (default: 3.0)"
    )
    discover_parser.add_argument(
        "--interface", default="", help="Local interface IP to bind to (default: all)"
    )
    discover_parser.add_argument(
        "--yaml", action="store_true", help="Output as config.yaml adapter snippet"
    )

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

    elif args.command == "discover":
        import asyncio

        from cctvql.adapters.onvif_discovery import discover_onvif_devices

        print(f"Scanning for ONVIF cameras (timeout={args.timeout}s) …\n")
        devices = asyncio.run(
            discover_onvif_devices(timeout=args.timeout, interface=args.interface)
        )

        if not devices:
            print("No ONVIF devices found.")
            print("Make sure your cameras are on the same subnet and support WS-Discovery.")
            sys.exit(0)

        print(f"Found {len(devices)} device(s):\n")
        for i, d in enumerate(devices, 1):
            print(f"  [{i}] {d.name}")
            print(f"      Address : {d.address}")
            print(f"      Host    : {d.host}  Port: {d.port}")
            if d.hardware:
                print(f"      Hardware: {d.hardware}")
            print()

        if args.yaml:
            print("─── config.yaml adapter snippet ───")
            print("adapters:")
            print("  active: onvif")
            print("  systems:")
            for d in devices:
                safe_name = (d.name or "onvif").lower().replace(" ", "_")
                print(f"    {safe_name}:")
                print("      type: onvif")
                print(f"      host: {d.host}")
                print(f"      port: {d.port}")
                print("      username: admin")
                print('      password: ""')
            print("───────────────────────────────────")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
