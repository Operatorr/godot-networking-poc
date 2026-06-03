# Review Rules — Project Standards

Copy this file to a target repository as `REVIEW.md` and customize it for that project.

The `code-review` skill treats a repository's root `REVIEW.md` as the highest-priority source of review rules.

## Core Principles

- **Clarity and maintainability first** — Code should be easy for the whole team to understand and modify.
- **Fail fast and explicitly** — Prefer early validation, clear errors, and defensive programming.
- **Consistency over cleverness** — Follow existing patterns unless there is a strong reason not to.
- **Test what matters** — New logic and changes to critical paths should include meaningful tests.

## Mandatory Rules

Violations of these rules should usually block merge.

### 1. Null / Undefined Safety

- Never access properties or call methods on a value that can be `null` or `undefined` without an explicit guard.
- Check the result of any function that can return `null` or `undefined` immediately after the call.
- Use optional chaining and nullish coalescing where appropriate, but prefer explicit checks for critical logic.

### 2. Error Handling

- Handle errors explicitly. Do not let unhandled promises or exceptions crash the process.
- Prefer project-specific error types where they exist.
- Log errors with enough context to diagnose them, but never log sensitive data such as passwords, tokens, PII, or secrets.

### 3. Security

- Validate and sanitize user input before using it in database queries, templates, or system commands.
- Use parameterized queries or ORM methods. Never build SQL or shell commands via unsafe string concatenation.
- Authentication and authorization checks must happen before business logic executes.
- Secrets must come from environment variables or a secrets manager. Never hardcode them.

### 4. Input Validation & APIs

- Public API endpoints and public functions should validate input using shared validation schemas where available.
- New public interfaces should include clear documentation when that is the project standard.
- Response formats should follow the project's standard envelope when applicable.

### 5. Testing Requirements

- New features, bug fixes, and changes to critical logic should include tests.
- Cover the happy path plus at least one important error or edge case.
- Use existing test utilities and patterns.
- Prefer integration tests for changes involving external services or the database.

### 6. Performance & Scalability

- Avoid N+1 database queries.
- Use batch loading, joins, or caching where appropriate.
- Review new endpoints and background jobs for database or external-service impact.

## Strongly Preferred Rules

Flag these when the touched code clearly violates them and the fix is local:

- Prefer early returns over deeply nested conditionals.
- Use `const` by default. Use `let` only for reassignment.
- Replace magic numbers and strings with named constants.
- Extract duplicated logic into shared utilities or helper functions.
- Keep functions focused and reasonably sized.
- Use descriptive names. Avoid cryptic abbreviations except for well-known ones like `id`, `url`, and `ctx`.

## Language & Framework Specific

Customize these sections for each project.

### TypeScript / JavaScript

- Enable and respect strict null checks.
- Avoid `any` unless absolutely necessary and documented.
- Prefer composition over deep class inheritance.

### Python

- Follow the project's Black and Ruff configuration.
- Use type hints on public functions and important internal functions.
- Prefer Pydantic models for data validation and settings when appropriate.

### Go

- Follow `golangci-lint` rules where configured.
- Use `errors.Is` and `errors.As` for error handling.
- Keep functions small and focused.

## What Not to Flag

Do not flag these unless this file explicitly adds a rule for them:

- Minor formatting already handled by linters
- Personal coding style differences
- Large refactors unless the PR itself is a refactor
- Comments on self-explanatory code
- Performance micro-optimizations without evidence of a bottleneck

## How to Customize

1. Edit this file for the target repository.
2. Be specific and concrete. Vague rules lead to inconsistent reviews.
3. Add project-specific sections such as "Payment Service Rules" or "Frontend Component Rules".
4. Periodically review accepted and dismissed comments, then update this file with what you learn.
