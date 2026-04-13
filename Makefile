.PHONY: help install dev test lint type-check format coverage clean docker docker-up docker-down demo docs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install cctvQL
	pip install -e .

dev: ## Install with all development dependencies
	pip install -e ".[dev,mqtt,onvif,all]"
	pre-commit install

test: ## Run tests
	pytest tests/ -v --tb=short

lint: ## Run linter (ruff)
	ruff check cctvql/ tests/

format: ## Auto-format code
	ruff check --fix cctvql/ tests/
	ruff format cctvql/ tests/

type-check: ## Run type checker (mypy)
	mypy cctvql/

coverage: ## Run tests with coverage report
	pytest tests/ -v --cov=cctvql --cov-report=term-missing --cov-report=html

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker: ## Build Docker image
	docker build -t cctvql .

docker-up: ## Start Docker Compose stack
	docker compose up -d

docker-down: ## Stop Docker Compose stack
	docker compose down

demo: ## Run interactive demo with mock adapter
	cctvql chat --adapter demo --llm ollama
