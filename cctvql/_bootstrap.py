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
    _setup_notifications(config.get("notifications", {}))


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
    elif adapter_type == "hikvision":
        from cctvql.adapters.hikvision import HikvisionAdapter

        return HikvisionAdapter(
            host=cfg.get("host", "192.168.1.100"),
            username=cfg.get("username", "admin"),
            password=cfg.get("password", ""),
            channel_count=cfg.get("channel_count"),
        )
    elif adapter_type == "dahua":
        from cctvql.adapters.dahua import DahuaAdapter

        return DahuaAdapter(
            host=cfg.get("host", "192.168.1.100"),
            port=cfg.get("port", 80),
            username=cfg.get("username", "admin"),
            password=cfg.get("password", ""),
            channel_count=cfg.get("channel_count", 4),
        )
    elif adapter_type == "synology":
        from cctvql.adapters.synology import SynologyAdapter

        return SynologyAdapter(
            host=cfg.get("host", "http://192.168.1.10:5000"),
            username=cfg.get("username", "admin"),
            password=cfg.get("password", ""),
            session=cfg.get("session", "SurveillanceStation"),
            ssl_verify=cfg.get("ssl_verify", True),
        )
    elif adapter_type == "milestone":
        from cctvql.adapters.milestone import MilestoneAdapter

        return MilestoneAdapter(
            host=cfg.get("host", "https://vms.example.com"),
            username=cfg.get("username", "admin"),
            password=cfg.get("password", ""),
            client_id=cfg.get("client_id", "GrantValidatorClient"),
            grant_type=cfg.get("grant_type", "password"),
            ssl_verify=cfg.get("ssl_verify", True),
        )
    elif adapter_type == "scrypted":
        from cctvql.adapters.scrypted import ScryptedAdapter

        return ScryptedAdapter(
            host=cfg.get("host", "https://scrypted.local:10443"),
            api_token=cfg.get("api_token", ""),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            ssl_verify=cfg.get("ssl_verify", True),
        )
    else:
        raise ValueError(f"Unknown adapter type: {adapter_type}")


def _setup_notifications(notif_config: dict) -> None:
    """Register notification channels from config."""
    if not notif_config:
        return

    from cctvql.notifications.registry import NotifierRegistry

    # Webhook
    for wh in notif_config.get("webhooks", []):
        url = wh.get("url")
        if url:
            from cctvql.notifications.webhook import WebhookNotifier

            NotifierRegistry.register(WebhookNotifier(url=url))
            logger.debug("Registered webhook notifier: %s", url)

    # Telegram
    tg = notif_config.get("telegram", {})
    if tg.get("bot_token") and tg.get("chat_id"):
        from cctvql.notifications.telegram import TelegramNotifier

        NotifierRegistry.register(
            TelegramNotifier(bot_token=tg["bot_token"], chat_id=str(tg["chat_id"]))
        )
        logger.debug("Registered Telegram notifier")

    # Slack
    sl = notif_config.get("slack", {})
    if sl.get("webhook_url"):
        from cctvql.notifications.slack import SlackNotifier

        NotifierRegistry.register(SlackNotifier(webhook_url=sl["webhook_url"]))
        logger.debug("Registered Slack notifier")

    # ntfy
    nt = notif_config.get("ntfy", {})
    if nt.get("topic"):
        from cctvql.notifications.ntfy import NtfyNotifier

        NotifierRegistry.register(
            NtfyNotifier(
                topic=nt["topic"],
                server=nt.get("server", "https://ntfy.sh"),
            )
        )
        logger.debug("Registered ntfy notifier: %s", nt["topic"])

    # Email
    em = notif_config.get("email", {})
    if em.get("smtp_host") and em.get("from_addr") and em.get("to_addrs"):
        from cctvql.notifications.email_notifier import EmailNotifier

        NotifierRegistry.register(
            EmailNotifier(
                smtp_host=em["smtp_host"],
                smtp_port=int(em.get("smtp_port", 587)),
                username=em.get("username", ""),
                password=em.get("password", ""),
                from_addr=em["from_addr"],
                to_addrs=em["to_addrs"] if isinstance(em["to_addrs"], list) else [em["to_addrs"]],
                use_tls=bool(em.get("use_tls", True)),
            )
        )
        logger.debug("Registered email notifier → %s", em["to_addrs"])

    registered = len(NotifierRegistry.all())
    if registered:
        logger.info("Notifications: %d channel(s) registered", registered)


def _setup_logging(log_config: dict) -> None:
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
