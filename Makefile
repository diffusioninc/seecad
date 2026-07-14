UV ?= uv
PNPM ?= pnpm
DOCKER ?= docker
OPENSCAD_IMAGE ?= seecad-openscad:local

.PHONY: bootstrap worker demo serve mcp web test integration lint format typecheck web-check check clean

bootstrap:
	$(UV) sync --frozen --all-extras --dev
	$(PNPM) --dir web install --frozen-lockfile

worker:
	$(DOCKER) build -f docker/openscad.Dockerfile -t $(OPENSCAD_IMAGE) .

demo: worker
	$(UV) run seecad demo --output .seecad/demo

serve:
	$(UV) run uvicorn seecad.api:app --reload --host 127.0.0.1 --port 8000

mcp:
	$(UV) run seecad mcp

web:
	$(PNPM) --dir web dev

test:
	$(UV) run pytest -m 'not integration'

integration: worker
	SEECAD_OPENSCAD_IMAGE=$(OPENSCAD_IMAGE) $(UV) run pytest -m integration

lint:
	$(UV) run ruff check src tests scripts
	$(UV) run ruff format --check src tests scripts

format:
	$(UV) run ruff check --fix src tests scripts
	$(UV) run ruff format src tests scripts
	$(PNPM) --dir web format

typecheck:
	$(UV) run mypy src scripts

web-check:
	$(PNPM) --dir web lint
	$(PNPM) --dir web typecheck
	$(PNPM) --dir web test --run
	$(PNPM) --dir web build

check: lint typecheck test web-check

clean:
	rm -rf .seecad .pytest_cache .mypy_cache .ruff_cache htmlcov web/dist
