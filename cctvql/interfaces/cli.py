"""
cctvQL CLI Interface
---------------------
Interactive terminal chat for querying your CCTV system in plain English.

Usage:
    cctvql chat --config config/config.yaml
    cctvql chat --adapter frigate --host http://192.168.1.100:5000 --llm ollama
"""

from __future__ import annotations

import asyncio
import logging
import sys

from cctvql.adapters.base import AdapterRegistry
from cctvql.core.nlp_engine import NLPEngine
from cctvql.core.query_router import QueryRouter
from cctvql.llm.base import LLMRegistry

logger = logging.getLogger(__name__)

BANNER = """
╔══════════════════════════════════════════════════╗
║          cctvQL — Conversational CCTV            ║
║   Ask your cameras anything in plain English.    ║
║   Type 'exit' or Ctrl+C to quit.                 ║
║   Type 'reset' to clear conversation history.   ║
╚══════════════════════════════════════════════════╝
"""

HELP_TEXT = """
Example queries:
  • "Show me all cameras"
  • "Any motion on the front door camera today?"
  • "Was there a person detected in the backyard last night?"
  • "Show me clips from the parking lot between 2am and 4am"
  • "Get a snapshot from Camera 1"
  • "How much storage is left?"
"""


class CLIChat:
    """
    Interactive REPL for cctvQL.

    Args:
        adapter_name: Name of the active adapter (e.g. 'frigate', 'onvif')
        llm_name:     Name of the active LLM backend (e.g. 'ollama', 'openai')
        verbose:      Show debug info like detected intent
    """

    def __init__(
        self,
        adapter_name: str | None = None,
        llm_name: str | None = None,
        verbose: bool = False,
    ) -> None:
        self.adapter_name = adapter_name
        self.llm_name = llm_name
        self.verbose = verbose
        self._nlp: NLPEngine | None = None
        self._router: QueryRouter | None = None

    async def setup(self) -> bool:
        """Initialize adapter and LLM. Returns False if setup fails."""
        # Resolve adapter
        if self.adapter_name:
            try:
                AdapterRegistry.set_active(self.adapter_name)
            except ValueError as e:
                print(f"[error] {e}")
                print(f"Available adapters: {AdapterRegistry.available()}")
                return False

        # Resolve LLM
        if self.llm_name:
            try:
                LLMRegistry.set_active(self.llm_name)
            except ValueError as e:
                print(f"[error] {e}")
                print(f"Available LLMs: {LLMRegistry.available()}")
                return False

        adapter = AdapterRegistry.get_active()
        llm = LLMRegistry.get_active()

        print(f"[cctvQL] Connecting to {adapter.name}...")
        connected = await adapter.connect()
        if not connected:
            print("[error] Could not connect to CCTV system. Check your config.")
            return False

        llm_ok = await llm.health_check()
        if not llm_ok:
            print(f"[warning] LLM backend '{llm.name}' may not be available.")

        self._nlp = NLPEngine(llm)
        self._router = QueryRouter(adapter, llm)

        print(f"[cctvQL] Connected  adapter={adapter.name}  llm={llm.name}")
        return True

    async def run(self) -> None:
        """Start the interactive REPL."""
        ok = await self.setup()
        if not ok:
            sys.exit(1)

        print(BANNER)
        print(HELP_TEXT)

        while True:
            try:
                query = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[cctvQL] Goodbye!")
                break

            if not query:
                continue

            if query.lower() in {"exit", "quit", "q"}:
                print("[cctvQL] Goodbye!")
                break

            if query.lower() == "reset":
                self._nlp.reset()
                print("[cctvQL] Conversation history cleared.")
                continue

            if query.lower() in {"help", "?"}:
                print(HELP_TEXT)
                continue

            await self._process(query)

    async def _process(self, query: str) -> None:
        print("cctvQL > ", end="", flush=True)
        try:
            ctx = await self._nlp.parse(query)

            if self.verbose:
                print(f"\n[intent: {ctx.intent}]", end=" ")
                if ctx.extra.get("explanation"):
                    print(f"[{ctx.extra['explanation']}]", end=" ")
                print()

            response = await self._router.route(ctx)
            print(response)
        except Exception as exc:
            logger.debug("Error processing query", exc_info=exc)
            print(f"[error] {exc}")

        print()


def run_cli(
    adapter_name: str | None = None,
    llm_name: str | None = None,
    verbose: bool = False,
) -> None:
    """Entry point for CLI. Called from __main__ or CLI script."""
    chat = CLIChat(
        adapter_name=adapter_name,
        llm_name=llm_name,
        verbose=verbose,
    )
    asyncio.run(chat.run())
