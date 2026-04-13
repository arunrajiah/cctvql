"""
cctvQL Bootstrap
-----------------
Loads config.yaml and wires up adapters + LLM backends into their registries.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from cctvql.adapters.base import AdapterRegistry
from cctvql.llm.base import LLMRegistry

logger = logging.getLogger(__name__)


def bootstrap(config_path: str = "config/config.yaml") -> None:
    """
    Read config file and register all configured adapters and LLM backends.
    Sets the active adapter and LLM as specified in config.
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning("Config file not found: %s — using defaults", config_path)
        _bootstrap_defaults()
        return

    with open(path) as f:
        config: dict[str, Any] = yaml.safe_load(f) or {}

    _setup_logging(config.get("logging", {}))
    _setup_llms(config.get("llm", {}))
    _setup_adapters(config.get("adapters", {}))


def _bootstrap_defaults() -> None:
    """Register default Ollama + Frigate for zero-config startup."""
    from cctvql.adapters.frigate import FrigateAdapter
    from cctvql.llm.ollama_backend import OllamaBackend

    llm = OllamaBackend()
    LLMRegistry.register(llm)
    LLMRegistry.set_active("ollama")

    adapter = FrigateAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("frigate")


def _setup_llms(llm_config: dict) -> None:
    active = llm_config.get("active", "ollama")

    backends = llm_config.get("backends", {})
    if not backends:
        # Sensible defaults if no backends configured
        backends = {"ollama": {"provider": "ollama"}}

    for name, cfg in backends.items():
        provider = cfg.get("provider", name)
        try:
            backend = _create_llm(provider, cfg)
            LLMRegistry.register(backend)
            logger.debug("Registered LLM backend: %s", backend.name)
        except Exception as exc:
            logger.warning("Could not register LLM '%s': %s", name, exc)

    if LLMRegistry.available():
        try:
            LLMRegistry.set_active(active)
        except ValueError:
            first = LLMRegistry.available()[0]
            logger.warning("Active LLM '%s' not found, falling back to '%s'", active, first)
            LLMRegistry.set_active(first)


def _create_llm(provider: str, cfg: dict):
    if provider == "ollama":
        from cctvql.llm.ollama_backend import OllamaBackend

        return OllamaBackend(
            host=cfg.get("host", "http://localhost:11434"),
            model=cfg.get("model", "llama3"),
        )
    elif provider == "openai":
        from cctvql.llm.openai_backend import OpenAIBackend

        return OpenAIBackend(
            api_key=cfg.get("api_key") or os.environ.get("OPENAI_API_KEY"),
            model=cfg.get("model", "gpt-4o-mini"),
            base_url=cfg.get("base_url"),
        )
    elif provider == "anthropic":
        from cctvql.llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(
            api_key=cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"),
            model=cfg.get("model", "claude-haiku-4-5-20251001"),
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def _setup_adapters(adapters_config: dict) -> None:
    active = adapters_config.get("active", "frigate")
    systems = adapters_config.get("systems", {})

    if not systems:
        systems = {"frigate": {"type": "frigate"}}

    for name, cfg in systems.items():
        adapter_type = cfg.get("type", name)
        try:
            adapter = _create_adapter(adapter_type, cfg)
            AdapterRegistry.register(adapter)
            logger.debug("Registered adapter: %s", adapter.name)
        except Exception as exc:
            logger.warning("Could not register adapter '%s': %s", name, exc)

    if AdapterRegistry.available():
        try:
            AdapterRegistry.set_active(active)
        except ValueError:
            first = AdapterRegistry.available()[0]
            logger.warning("Active adapter '%s' not found, falling back to '%s'", active, first)
            AdapterRegistry.set_active(first)


def _create_adapter(adapter_type: str, cfg: dict):
    if adapter_type == "frigate":
        from cctvql.adapters.frigate import FrigateAdapter

        return FrigateAdapter(
            host=cfg.get("host", "http://localhost:5000"),
            mqtt_host=cfg.get("mqtt_host"),
            mqtt_port=cfg.get("mqtt_port", 1883),
        )
    elif adapter_type == "onvif":
        from cctvql.adapters.onvif import ONVIFAdapter

        return ONVIFAdapter(
            host=cfg.get("host", "192.168.1.100"),
            port=cfg.get("port", 80),
            username=cfg.get("username", "admin"),
            password=cfg.get("password", ""),
        )
    elif adapter_type == "demo":
        from cctvql.adapters.demo import DemoAdapter

        return DemoAdapter()
    else:
        raise ValueError(f"Unknown adapter type: {adapter_type}")


def _setup_logging(log_config: dict) -> None:
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
