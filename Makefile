.PHONY: install run migrate test lint format up down logs

install:
	pip install -r requirements-dev.txt

run:
	uvicorn integrahub.main:create_app --factory --reload --app-dir src

migrate:
	alembic upgrade head

test:
	pytest --cov

lint:
	ruff check .

format:
	ruff format .

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api
