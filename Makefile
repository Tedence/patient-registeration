.PHONY: backend frontend run test

backend:
	cd backend && ../venv/bin/uvicorn main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

run:
	$(MAKE) backend & $(MAKE) frontend

test:
	cd .. && python -m pytest register_app/tests/ -v
