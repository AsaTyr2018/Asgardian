# Contributing

Thanks for your interest in improving Asgardian.

## Before opening a pull request

1. Keep changes focused and reviewable.
2. Do not commit credentials, private keys, tokens, generated media, local
   diagnostics, or environment-specific infrastructure details.
3. Keep `docs/` local unless maintainers explicitly request documentation to be
   published.
4. Run relevant checks before submitting.

## Development checks

```bash
ruff check src tests migrations
pytest -q
npm run test:web
npm run build:web
```

## Commit style

Use concise, descriptive commit messages:

```text
fix: preserve portrait image aspect ratio in viewer
feat: add saved asset delete flow
docs: clarify deployment configuration
```

## Licensing of contributions

By contributing, you agree that your contribution is provided under the same
license terms as the project: PolyForm Noncommercial License 1.0.0, unless a
separate written agreement says otherwise.

Do not submit code or assets you do not have the right to contribute.
