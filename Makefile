PYTHON    = /opt/anaconda3/bin/python3
BACKEND   = backend
FRONTEND  = frontend
PLIST     = com.taf-accuracy.scheduler.plist
PLIST_DST = $(HOME)/Library/LaunchAgents/$(PLIST)

# ── Development ──────────────────────────────────────────────────────────────

.PHONY: dev
dev:           ## Start backend + frontend dev servers (two separate terminals needed)
	@echo "Run each in its own terminal:"
	@echo "  make backend"
	@echo "  make frontend"

.PHONY: backend
backend:       ## Start FastAPI backend on :8000 (auto-reload)
	cd $(BACKEND) && $(PYTHON) -m uvicorn main:app --reload --port 8000

.PHONY: frontend
frontend:      ## Start Vite dev server on :5173
	cd $(FRONTEND) && npm run dev

.PHONY: build
build:         ## Production build of the React frontend
	cd $(FRONTEND) && npm run build

# ── Ingest ───────────────────────────────────────────────────────────────────

.PHONY: ingest
ingest:        ## Run one ingest cycle for all US TAF airports
	cd $(BACKEND) && $(PYTHON) ingest.py --all --workers 3 --hours 30

.PHONY: ingest-test
ingest-test:   ## Quick test ingest for 5 major airports
	cd $(BACKEND) && $(PYTHON) ingest.py --airports KORD KJFK KLAX KBOS KATL

.PHONY: scheduler-once
scheduler-once: ## Run the scheduler for exactly one cycle (dry-run / test)
	cd $(BACKEND) && $(PYTHON) scheduler.py --once --verbose

# ── Scheduler service (launchd) ───────────────────────────────────────────────

.PHONY: service-install
service-install: ## Install + start the hourly scheduler as a launchd service
	mkdir -p logs
	cp $(PLIST) $(PLIST_DST)
	launchctl load $(PLIST_DST)
	@echo "Scheduler installed. Check status with: make service-status"

.PHONY: service-start
service-start: ## Start the scheduler service (must be installed first)
	launchctl start com.taf-accuracy.scheduler

.PHONY: service-stop
service-stop:  ## Stop the scheduler service (does not uninstall)
	launchctl stop com.taf-accuracy.scheduler

.PHONY: service-uninstall
service-uninstall: ## Stop + remove the scheduler service
	-launchctl unload $(PLIST_DST)
	-rm -f $(PLIST_DST)
	@echo "Scheduler removed."

.PHONY: service-status
service-status: ## Show launchd service status
	launchctl list | grep taf || echo "(not loaded)"

.PHONY: logs
logs:          ## Tail the scheduler log
	tail -f logs/scheduler.log

.PHONY: logs-all
logs-all:      ## Tail all logs
	tail -f logs/scheduler.log logs/scheduler-stdout.log logs/scheduler-stderr.log

# ── Database ─────────────────────────────────────────────────────────────────

.PHONY: db-stats
db-stats:      ## Print row counts for all tables
	sqlite3 data/taf_accuracy.db \
	  "SELECT 'airports'||(SELECT count(*) FROM airports), \
	          'tafs'||(SELECT count(*) FROM tafs), \
	          'taf_periods'||(SELECT count(*) FROM taf_periods), \
	          'metars'||(SELECT count(*) FROM metars), \
	          'forecast_scores'||(SELECT count(*) FROM forecast_scores);" \
	| tr ',' '\n'

.PHONY: db-reset
db-reset:      ## ⚠ Delete the database and start fresh
	@read -p "Delete data/taf_accuracy.db? [y/N] " ans; [ "$$ans" = "y" ] && rm -f data/taf_accuracy.db || true

.PHONY: help
help:          ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
