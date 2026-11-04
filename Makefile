UV ?= uv

.PHONY: help
help: ## Show make targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z\/_-]+:.*?## / {sub("\\\\n",sprintf("\n%22c"," "), $$2);printf " \033[36m%-20s\033[0m  %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: client/install
client/install: ## Install the CLI package from this checkout
	@$(UV) tool install --force --reinstall ./client

.PHONY: dev/setup
dev/setup: ## Install the CLI in editable mode for development
	@$(UV) tool install --force --reinstall --editable ./client

.PHONY: server/sync
server/sync: ## Upload server/ with ss and its private .sisy.json configuration
	@test -f server/.sisy.json || { echo "Missing server/.sisy.json; copy server/.sisy.example.json and configure it." >&2; exit 1; }
	@command -v ss >/dev/null || { echo "The ss sync script was not found in PATH." >&2; exit 1; }
	@cd server && ss -u

