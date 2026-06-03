# Code Review Reference

Supporting templates, examples, and guidelines for the light `code-review` skill.

Use this reference for high-signal reviews only. The normal output is 0-3 material findings; exhaustive low-severity and nitpick coverage belongs in `deep-review`.

## Full Handoff Prompt Template

Use this structure for every issue:

````markdown
**Handoff Prompt:**
```
In the file `RELATIVE_PATH`, around lines START-END:

[What to change and why, referencing the specific problem.]

[Exact implementation steps, including null checks, error handling, or edge cases.]

[How the surrounding code should look after the change. Reference similar patterns elsewhere in the codebase if relevant.]

After making the change:
- Verify the fix by [specific test command or manual check]
- Ensure no other call sites are broken
- Run the project's linter/checks for the file

Only modify the necessary lines. Do not reformat unrelated code.
```
````

## Good Handoff Prompt Example

```markdown
In the file `src/services/AttendeeService.ts`, around lines 55-78:

After calling `AttendeeService.getAttendeeByAttendeeId(eventId, attendeeIdCode)`, immediately check whether the returned value is null or undefined. If it is, return a 404 response with JSON body `{ error: "Attendee not found" }` instead of continuing execution.

Only access `attendee.id`, `attendee.name`, `attendee.email`, or `attendee.company` after the null check passes.

If `getAttendeeActivitiesDetailed` expects the internal `attendee.id` rather than `attendeeIdCode`, call it with `attendee.id` after the check.

Follow the same error response pattern used in `EventController.getEventById`.

After the change, add a unit test case for the "attendee not found" scenario.
```

## Severity Guidelines

| Severity | When to Use | Example Issues |
| --- | --- | --- |
| Critical | Immediate data loss, security breach, production crash, auth bypass | SQL injection, missing auth on sensitive endpoint, crash in startup path |
| High | Logic bug that breaks a core feature, missing critical error handling, major performance regression | Wrong calculation in pricing engine, payment race condition, N+1 query on hot path |
| Medium | Maintainability issue likely to cause future bugs, missing tests for a concrete regression risk, minor behavior issue | Duplicate validation logic, magic values that affect behavior, missing edge-case test |
| Low | Normally omitted; use only when an explicit project rule makes the issue merge-blocking | Required generated file is missing from a project that requires it |

Rule of thumb: if you would not block a real merge for it, do not mark it Medium or higher.
Do not include Low/Nit findings just to fill space.

## Sample Review Output

````markdown
## High Issue: Missing null check on attendee lookup can cause runtime error

**File:** `src/controllers/EventController.ts:62-75`
**Category:** Bug

**Problem:**
`getAttendeeByAttendeeId` can return null when the attendee does not exist. The code immediately accesses `attendee.id` without checking, causing a potential 500 instead of a proper 404.

**Impact:**
Users will see generic server errors instead of clear "not found" messages, and the system will mask a predictable edge case as an unexpected failure.

**Suggested Fix:**
```diff
 const attendee = await AttendeeService.getAttendeeByAttendeeId(eventId, attendeeIdCode);
+if (!attendee) {
+  return { status: 404, body: JSON.stringify({ error: "Attendee not found" }) };
+}
 const activities = await AttendeeService.getAttendeeActivitiesDetailed(eventId, attendeeIdCode);
```

**Handoff Prompt:**
```
In the file `src/controllers/EventController.ts`, around lines 62-75:

After the line `const attendee = await AttendeeService.getAttendeeByAttendeeId(eventId, attendeeIdCode);`, add an immediate null/undefined check. If attendee is falsy, return a 404 response with JSON body `{ error: "Attendee not found" }`.

Only proceed to call `getAttendeeActivitiesDetailed` and access attendee properties after the check passes.

Use the same error response format as `getEventById`.

Add a corresponding test case for the "attendee not found" path.
```

### PR Summary
This PR adds attendee activity tracking to the event endpoint. The core direction is sound and follows existing patterns, but one High issue should be fixed before merge.

### Recommendations
- [ ] Fix the null-check issue
- [ ] Add coverage for the not-found path

### Statistics
- Files changed: 4
- Issues found: 1 (Critical: 0, High: 1, Medium: 0, Low: 0)
- Checks run: `npm test -- AttendeeService`
````

## GitHub PR Comment Template

Use this one-comment format when posting a review to a GitHub PR. Keep the summary and statistics visible, and wrap every material finding in its own collapsible section.

````markdown
# Code Review

[Short overall assessment. State whether the PR looks mergeable, has blocking issues, or needs specific follow-up.]

### Statistics
- Files changed: X
- Issues found: Y (Critical: A, High: B, Medium: C, Low: D)
- Checks run: [commands or "not run"]

### Findings

<details>
<summary>[Severity] path/to/file.ext:line - short issue title</summary>

**Category:** Bug | Security | Logic | Reliability | Maintainability | Testing | Performance | Style

**Problem:**
[Clear 1-2 sentence explanation of what is wrong and why it matters.]

**Impact:**
[Specific consequence if this is not fixed.]

**Suggested Fix:**
```diff
[Exact unified diff, or a precise before/after code block if a diff is not practical.]
```

**Handoff Prompt:**
```text
In the file `path/to/file.ext`, around lines X-Y:

[Detailed, self-contained instruction explaining the exact change needed, why it is required, edge cases to consider, and how to verify it.]

Only modify the necessary lines. Keep unrelated code unchanged.
```

</details>
````

If there are no findings, omit the `### Findings` section and say clearly that no blocking issues were found.

## GitHub CLI Commands

Check whether posting is available:

```bash
command -v gh
gh auth status
```

Resolve PR metadata and diff:

```bash
gh pr view <url-or-number> --json title,body,author,baseRefName,headRefName,files,commits,url
gh pr diff <url-or-number>
```

Post as a single PR comment:

```bash
tmp_review="$(mktemp -t code-review.XXXXXX.md)"
# Write the final GitHub comment markdown to "$tmp_review" before posting.
gh pr comment <url-or-number> --body-file "$tmp_review"
```

Terminal fallback when `gh` is missing or unauthenticated:

```bash
tmp_review="$(mktemp -t code-review.XXXXXX.md)"
# Write the final GitHub comment markdown to "$tmp_review" before fallback handling.
if ! command -v gh >/dev/null 2>&1; then
  printf 'GitHub posting skipped: gh is not installed.\n\n'
  cat "$tmp_review"
elif ! gh auth status 2>/tmp/code-review-gh-auth.err; then
  printf 'GitHub posting skipped: gh auth status failed.\n'
  cat /tmp/code-review-gh-auth.err
  printf '\n\n'
  cat "$tmp_review"
fi
```

Terminal fallback when posting fails:

```bash
tmp_review="$(mktemp -t code-review.XXXXXX.md)"
# Write the final GitHub comment markdown to "$tmp_review" before posting.
gh pr comment <url-or-number> --body-file "$tmp_review" 2>/tmp/code-review-gh-post.err || {
  printf 'GitHub posting failed.\n'
  cat /tmp/code-review-gh-post.err
  printf '\n\n'
  cat "$tmp_review"
}
```

Create line-specific comments with the API:

```bash
gh api repos/OWNER/REPO/pulls/123/reviews \
  -f event=COMMENT \
  -f body="Overall review summary here" \
  -f comments='[{"path":"src/file.ts","line":42,"body":"Specific comment here"}]'
```

## Pitfalls to Avoid

- Do not flag every formatting issue unless `REVIEW.md` explicitly requires it.
- Do not suggest massive refactors unless the PR itself is a refactor.
- Do not provide vague feedback like "this could be better".
- Do not include stale PR numbers, dates, or environment-specific details in reusable templates.
- If the PR is good, say what is good. Positive signal builds trust.
