"""
Tests for the bootstrap module (cctvql._bootstrap).
"""
from __future__ import annotations

import logging

import pytest
import yaml

from cctvql._bootstrap import (
    _create_adapter,
    _create_llm,
    _setup_logging,
    bootstrap,
)
from cctvql.adapters.base import AdapterRegistry
from cctvql.llm.base import LLMRegistry

# ---------------------------------------------------------------------------
# Ensure clean registries for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registries():
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None
    yield
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None


# ---------------------------------------------------------------------------
# bootstrap()
# ---------------------------------------------------------------------------

def test_bootstrap_defaults(tmp_path):
    """When no config file exists, bootstrap should register defaults."""
    fake_path = str(tmp_path / "nonexistent.yaml")
    bootstrap(config_path=fake_path)

    assert "ollama" in LLMRegistry.available()
    assert "frigate" in AdapterRegistry.available()


def test_bootstrap_with_config(tmp_path):
    """Create a temp YAML config and verify bootstrap loads it."""
    config = {
        "logging": {"level": "DEBUG"},
        "llm": {
            "active": "ollama",
            "backends": {
                "ollama": {
                    "provider": "ollama",
                    "host": "http://localhost:11434",
                    "model": "llama3",
                },
            },
        },
        "adapters": {
            "active": "frigate",
            "systems": {
                "frigate": {
                    "type": "frigate",
                    "host": "http://localhost:5000",
                },
            },
        },
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    bootstrap(config_path=str(config_file))

    assert "ollama" in LLMRegistry.available()
    assert "frigate" in AdapterRegistry.available()


# ---------------------------------------------------------------------------
# _setup_logging
# ---------------------------------------------------------------------------

def test_setup_logging():
    _setup_logging({"level": "WARNING"})
    root_logger = logging.getLogger()
    assert root_logger.level == logging.WARNING

    # Reset
    _setup_logging({"level": "INFO"})


# ---------------------------------------------------------------------------
# _create_llm
# ---------------------------------------------------------------------------

def test_create_llm_ollama():
    backend = _create_llm("ollama", {"host": "http://localhost:11434", "model": "llama3"})
    assert backend.name == "ollama"
    assert backend.model == "llama3"


def test_create_llm_openai():
    backend = _create_llm("openai", {"api_key": "sk-test", "model": "gpt-4o-mini"})
    assert backend.name == "openai"
    assert backend.model == "gpt-4o-mini"
    assert backend.api_key == "sk-test"


def test_create_llm_anthropic():
    backend = _create_llm("anthropic", {"api_key": "ant-test", "model": "claude-haiku-4-5-20251001"})  # noqa: E501
    assert backend.name == "anthropic"
    assert backend.model == "claude-haiku-4-5-20251001"
    assert backend.api_key == "ant-test"


# ---------------------------------------------------------------------------
# _create_adapter
# ---------------------------------------------------------------------------

def test_create_adapter_frigate():
    adapter = _create_adapter("frigate", {"host": "http://192.168.1.100:5000"})
    assert adapter.name == "frigate"
    assert adapter.host == "http://192.168.1.100:5000"


def test_create_adapter_onvif():
    adapter = _create_adapter("onvif", {
        "host": "192.168.1.200",
        "port": 80,
        "username": "admin",
        "password": "pass123",
    })
    assert adapter.name == "onvif"


def test_create_adapter_demo():
    """Verify that _create_adapter supports the 'demo' type."""
    adapter = _create_adapter("demo", {})
    assert adapter.name == "demo"


def test_create_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown adapter type"):
        _create_adapter("totally_fake_adapter", {})
