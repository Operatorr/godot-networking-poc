# HTML reading editions

Open `index.html` in a browser, or open one of the articles directly:

- `omega-load-testing.A.html` — the complete single article.
- `omega-load-testing.C1.html` — Part 1.
- `omega-load-testing.C2.html` — Part 2.
- `omega-load-testing.appendices.html` — shared appendices.
- `evidence.html` — the original article README rendered as a companion.

Every HTML file embeds its CSS, JavaScript, and images and opens offline without a server.
Keep the files together to switch between editions. Other repository evidence links retain
their original destinations in the checkout; external source links need internet access.

The Markdown drafts are unchanged. Provisional titles are displayed without their bracketed
prefix, with an explicit provisional-title label. Their complete original front matter,
title candidates, ASCII layouts, and figure briefs remain in expandable disclosures.
Author notes can be hidden; evidence caveats and unresolved claims remain in the article.
Presentation subtitles and the byline label "Omega Realm · Engineering" are additions.

Three AI-generated conceptual covers follow the supplied cobalt/cyan glow reference.
They are labelled as conceptual illustrations, not measured evidence. The built-in image
generation tool produced them; the exact prompts are in `assets/prompts.md`.

Reusable PNG assets are in `assets/`:

- `A-cover.png`, `C1-cover.png`, `C2-cover.png` — generated editorial covers.
- `F2-egress.png` — the draft's four egress columns on log–log axes.
- `F3-snapshot-layout.png` — proportional header and position-only record layouts.
- `F4-payload.png` — the original pre-fix local tally, with nested rows counted once.
- The two existing campaign PNGs, copied without alteration.

Technical figures are drawn deterministically with Matplotlib. F2 and F4 retain their
derived-model / pre-fix labels; no fixed-build measurements are added. The very small
residual in F4 is the printed total minus the listed top-level categories, not a new tally.
Use "Enlarge figure" to inspect small labels on a phone.

To rebuild after changing the Markdown drafts (Python 3.10+):

```sh
python3 -m venv /tmp/omega-articles-venv
/tmp/omega-articles-venv/bin/pip install -r docs/articles/html/requirements.txt
/tmp/omega-articles-venv/bin/python docs/articles/html/build.py
```

Rebuilding retains the generated cover PNGs and regenerates the figures and reading editions.
