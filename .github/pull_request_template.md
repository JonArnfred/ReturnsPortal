## What and why

<!-- What this changes and why. Link the issue it addresses. -->

## Checklist

- [ ] No account numbers, amounts, holdings or credentials in code, fixtures, screenshots or this description
- [ ] Accounting changes: `documentation/VISION.md` updated, engine integration tests run
- [ ] API changes: `cd frontend && npm run api:generate` run and the generated files committed
- [ ] Checks pass:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
TEST_DATABASE_URL=postgresql://... uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build && npm run test:ssr
```
