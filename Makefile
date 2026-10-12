.PHONY: install env dev backend frontend test seed build web clean

install:
	cd backend && python3 -m venv venv && . venv/bin/activate && pip install -q -r requirements.txt
	cd frontend && npm install

# backend/.env with a freshly generated encryption key, if there is not one
# already. Never overwrites an existing file: that key decrypts every stored
# provider token, and replacing it would orphan all of them.
env:
	@if [ -f backend/.env ]; then echo "backend/.env already exists; leaving it alone."; else \
		cp .env.example backend/.env && \
		key=$$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())') && \
		sed -i.bak "s|^FINANCE_MASTER_KEY=.*|FINANCE_MASTER_KEY=$$key|" backend/.env && \
		rm -f backend/.env.bak && echo "Created backend/.env with a fresh encryption key."; fi

# Ports can be overridden per checkout in local.mk (untracked), so a second
# copy of the project can run alongside the first:
#     BACKEND_PORT = 8002
#     FRONTEND_PORT = 5175
-include local.mk
BACKEND_PORT ?= 8001
FRONTEND_PORT ?= 5174
export BACKEND_PORT FRONTEND_PORT

# --reload watches .py files only, so an edited .env would otherwise need a
# manual restart — and the symptom is a provider that stays "not set up" with
# correct credentials sitting right there in the file.
RELOAD = --reload --reload-include .env

dev:
	@trap 'kill 0' SIGINT; \
	(cd backend && . venv/bin/activate && uvicorn main:app $(RELOAD) --port $(BACKEND_PORT)) & \
	(cd frontend && npm run dev) & \
	wait

backend:
	cd backend && . venv/bin/activate && uvicorn main:app $(RELOAD) --port $(BACKEND_PORT)

frontend:
	cd frontend && npm run dev

test:
	cd backend && . venv/bin/activate && python -m pytest tests/ -q

seed:
	cd backend && . venv/bin/activate && python -c "from services import seed; seed.reseed()"

build:
	cd frontend && npm run build

clean:
	rm -f backend/finance.db backend/finance.db-shm backend/finance.db-wal

# The web build GitHub Pages serves: the whole app, Python backend included,
# running in the browser. Output in frontend/dist-web; serve that folder to try it.
web:
	python3 backend/scripts/build_browser_bundle.py
	cd frontend && VITE_BROWSER_APP=1 npx vite build --outDir dist-web
