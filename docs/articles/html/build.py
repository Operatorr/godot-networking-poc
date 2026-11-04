"""Build portable reading editions. Requires markdown, beautifulsoup4, matplotlib.

Run from any directory: python docs/articles/html/build.py
All CSS, scripts, and images are embedded in the resulting HTML files.
"""
from pathlib import Path
import base64
import html
import json
import math
import mimetypes
import re
import shutil
import unicodedata

import markdown
from bs4 import BeautifulSoup
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
ASSETS = HERE / 'assets'
ASSETS.mkdir(exist_ok=True)
CSS = (HERE / 'article.css').read_text()
BLUE = '#2461df'
NAVY = '#12285b'
CYAN = '#148d9e'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                     'axes.spines.right': False, 'axes.edgecolor': '#cbd2dd', 'text.color': '#26334d',
                     'axes.labelcolor': '#526078', 'xtick.color': '#526078', 'ytick.color': '#526078'})


def save(fig, filename):
    fig.savefig(ASSETS / filename, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def figures():
    # F2 uses exactly the rounded values printed in the drafts, not new measurements.
    n = [16, 32, 64, 100, 150, 200, 500, 1000]
    series = [('Naive · 30 Hz', [.6, 2.3, 8.4, 19.9, 44.1, 80.1, 495.8, 1973.3], BLUE, '-'),
              ('Naive · 60 Hz', [1.3, 4.5, 16.8, 39.8, 88.1, 160.1, 991.7, 3946.6], BLUE, '--'),
              ('AoI-64 · 30 Hz', [.6, 2.3, 8.4, 13.3, 19.9, 26.6, 66.5, 133], CYAN, '-'),
              ('AoI-64 · 60 Hz', [1.3, 4.5, 16.8, 26.6, 39.9, 53.2, 133, 265.9], CYAN, '--')]
    fig, ax = plt.subplots(figsize=(9, 5.8))
    for label, values, color, ls in series:
        ax.loglog(n, values, label=label, color=color, ls=ls, lw=2.2, marker='o', ms=3)
    ax.axhline(1000, color='#9a7d47', ls=':', lw=1.5)
    ax.text(17, 1120, '1 Gbit/s', fontsize=9, color='#8b703f')
    ax.axvline(65, color='#d0d6e0', ls=':', zorder=0)
    ax.set(xlim=(15, 1150), ylim=(.4, 6000), xlabel='Connected players, N (log scale)',
           ylabel='Server egress · Mbit/s (log scale)')
    ax.set_xticks([16, 32, 64, 100, 200, 500, 1000])
    ax.set_yticks([1, 10, 100, 1000])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x:,.0f}'))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x:,.0f}'))
    ax.grid(which='major', color='#e8ecf2', lw=.7)
    ax.legend(loc='upper left', frameon=False, fontsize=9)
    fig.suptitle('The same records. Two different growth curves.', x=.125, ha='left', fontsize=16, fontweight='bold')
    ax.set_title('F2 / Derived model · 63-bit player records · IPv4 · no projectiles or monsters', loc='left', fontsize=9, pad=16, color='#68768d')
    fig.tight_layout(rect=(0, 0, 1, .96))
    save(fig, 'F2-egress.png')

    # Byte and bit rows each have their own explicitly labelled scale.
    fig, ax = plt.subplots(figsize=(10, 6.3))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis('off')
    ax.text(0, 97, 'Inside a Snapshot', fontsize=19, fontweight='bold')
    ax.text(0, 91, 'F3 / Byte-aligned header, followed by an LSB-first record bitstream', fontsize=10, color='#68768d')
    ax.text(0, 82, 'DELTA HEADER / 16 bytes total / widths proportional to bytes', fontsize=9, fontweight='bold')
    header = [('type', 1), ('server_tick', 4), ('server_ms', 4), ('flags', 1), ('baseline_tick', 4), ('count', 2)]
    x = 0
    for i, (label, size) in enumerate(header):
        width = size * 6.2
        ax.add_patch(Rectangle((x, 66), width, 12, facecolor=['#e3ebfc', '#cbdcfb'][i % 2], edgecolor='white', lw=2))
        ax.text(x + width / 2, 72, f'{label}\n{size} B', ha='center', va='center', fontsize=7)
        x += width
    ax.text(0, 59, 'POSITION-ONLY DELTAS / common scale: one unit of width = one bit', fontsize=9, fontweight='bold')
    colors = ['#142d69', '#3466c5', '#9679ce', '#d2e4fc', '#b4d0f4']
    for title, offset, y, total in [('Player', 10, 42, 49), ('Projectile', 15, 25, 54), ('Monster', 14, 8, 53)]:
        ax.text(0, y + 12, f'{title} / {total} bits', fontsize=10, fontweight='bold')
        x = 0
        for i, (label, size) in enumerate([('kind', 2), ('offset', offset), ('mask', 5), ('qx', 16), ('qy', 16)]):
            width = size * 1.82
            ax.add_patch(Rectangle((x, y), width, 9, facecolor=colors[i], edgecolor='white', lw=1.5))
            # Tiny kind field is keyed below; a number alone remains legible.
            text = str(size) if size == 2 else f'{label} · {size} b'
            ax.text(x + width / 2, y + 4.5, text, ha='center', va='center', fontsize=7, color='white' if i < 3 else NAVY)
            x += width
    ax.text(0, 1, 'First field: kind (2 b)   ·   qx, qy: 16-bit absolute quantized coordinates   ·   final byte zero-padded', fontsize=8, color='#68768d')
    save(fig, 'F3-snapshot-layout.png')

    # No nested rows are double-counted. Residual includes rounding and unlisted bytes.
    total = 13687
    buckets = [('Projectile records', 7466, '#2461df'), ('Player records', 3399, '#709ae6'),
               ('Other Snapshot bytes', 11410 - 7466 - 3399, '#c9d8f1'),
               ('Game events', 1627, '#9679ce'), ('ActionConfirm', 475, '#148d9e'),
               ('Baselines', 142, '#9bafbf'), ('Other / rounding', total - 11410 - 1627 - 475 - 142, '#dde1e7')]
    fig, ax = plt.subplots(figsize=(10, 4.1))
    ax.set_xlim(0, total); ax.set_ylim(-2.8, 1.3); ax.axis('off')
    ax.text(0, 1.07, 'More than half the payload is projectiles.', fontsize=17, fontweight='bold')
    ax.text(0, .65, 'F4 / 50 default bots · pre-fix local tally · 13,687 B/s per recipient', fontsize=10, color='#68768d')
    left = 0
    for label, value, color in buckets:
        ax.barh(0, value, left=left, color=color, height=.55, edgecolor='white', linewidth=1)
        if value > 2500:
            ax.text(left + value / 2, 0, f'{value/total:.1%}', ha='center', va='center', color='white', fontweight='bold', fontsize=12)
        left += value
    for i, (label, value, color) in enumerate(buckets):
        col, row = i % 2, i // 2
        x, y = col * total * .53, -.75 - row * .44
        ax.scatter([x + 110], [y], color=color, s=65, marker='s')
        ax.text(x + 400, y, f'{label}  {value:,} B/s', va='center', fontsize=9)
    ax.text(0, -2.65, 'Indicative shares only; fixed-build shares remain [MEASURE]. Residual is not a new measurement.', fontsize=9, color='#68768d')
    save(fig, 'F4-payload.png')


def data_uri(path):
    return f'data:{mimetypes.guess_type(path)[0] or "application/octet-stream"};base64,' + base64.b64encode(Path(path).read_bytes()).decode()


TITLES = {
    'A': 'We wanted 1000 players on one server. The first build broke near 190.',
    'C1': 'Why realtime games cap at ~64–150 players',
    'C2': 'Load-testing Omega, a bit-packed Rust game server',
    'appendices': 'The numbers behind the story',
    'evidence': 'Evidence rules & draft notes',
}
SUBTITLES = {
    'A': 'The networking math, the bytes on the wire, and what our load test could actually prove.',
    'C1': 'Part 1 · The arithmetic behind player caps, from Battlefield to tab-target MMOs.',
    'C2': 'Part 2 · Five failed ramps, a round of fixes, and one clean 150-player observation.',
    'appendices': 'Shared appendices · Formula sheet, wire layouts, reproduction steps, and sources.',
    'evidence': 'The original README, rendered alongside the articles for reference.',
}
FIGURES = {
    'F2': ('F2-egress.png', 'F2. Derived server-egress model, using the four columns in the draft. Log–log axes; 1 Gbit/s marked. Players only; not a load-test result.'),
    'F3': ('F3-snapshot-layout.png', 'F3. Snapshot header and position-only delta records. Header widths scale by byte; record widths share a bit scale. Layouts from the supplied drafts.'),
    'F4': ('F4-payload.png', 'F4. Downstream application payload at 50 default bots, pre-fix local tally. Nested rows are not double-counted; unlisted bytes and rounding are shown as a residual. Fixed-build shares remain unmeasured.'),
}


def filename(key):
    return f'omega-load-testing.{key}.html' if key != 'evidence' else 'evidence.html'


def nav(key):
    def current(k):
        return 'aria-current="page"' if key == k else ''
    return '<nav class="topnav" aria-label="Article editions">' + ''.join(
        f'<a href="{filename(k)}" {current(k)}>{label}</a>'
        for k, label in [('A', 'A · Single article'), ('C1', 'C1 · Part 1'), ('C2', 'C2 · Part 2'), ('appendices', 'Appendices')]) + '</nav>'


def shell(title, body, key=''):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>{html.escape(title)} — Omega Realm</title><style>{CSS}</style></head><body><a class="skip" href="#main">Skip to article</a><div class="reading-progress" aria-hidden="true"></div><header class="masthead"><a class="wordmark" href="index.html" aria-label="Medium-style local article collection">Medium<span style="color:#2554ca">.</span></a><span class="edition">OMEGA REALM / LOCAL READING EDITION</span><a class="collection-link" href="index.html">All drafts ↗</a></header>{body}<script>
const toggle = document.querySelector('[data-notes]');
if(toggle) toggle.addEventListener('click', () => {{
 const hidden = document.body.classList.toggle('notes-hidden');
 toggle.textContent = hidden ? 'Show author notes' : 'Hide author notes';
 toggle.setAttribute('aria-pressed', String(hidden));
}});
function progress(){{const length=document.documentElement.scrollHeight-innerHeight;document.querySelector('.reading-progress').style.width=(length>0?scrollY/length*100:0)+'%'}}
addEventListener('scroll',progress,{{passive:true}});addEventListener('resize',progress);progress();
const viewer = document.createElement('dialog');
viewer.className='figure-viewer';
viewer.setAttribute('aria-label','Enlarged figure');
viewer.innerHTML='<button type="button">Close figure ×</button><p>Scroll sideways to inspect the full-size figure.</p><div class="zoom-scroll"></div>';
document.body.appendChild(viewer);
viewer.querySelector('button').addEventListener('click',()=>viewer.close());
document.querySelectorAll('article figure').forEach(figure=>{{
 const source=figure.querySelector('img');
 if(!source) return;
 const button=document.createElement('button');
 button.className='figure-zoom';button.type='button';button.textContent='Enlarge figure ↗';
 button.addEventListener('click',()=>{{const image=new Image();image.src=source.src;image.alt=source.alt;viewer.querySelector('.zoom-scroll').replaceChildren(image);viewer.showModal();}});
 figure.appendChild(button);
}});
</script></body></html>'''


def slug(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^\w\s-]', '', text).strip().replace(' ', '-')


def convert(key):
    source = SOURCE / ('README.md' if key == 'evidence' else f'omega-load-testing.{key}.md')
    raw = source.read_text()
    raw = re.sub(r'^# .+\n', '', raw, count=1)
    soup = BeautifulSoup(markdown.markdown(raw, extensions=['tables', 'fenced_code', 'sane_lists']), 'html.parser')
    # Preserve the front matter as a disclosure so the reading surface begins like an article.
    if key in ('A', 'C1', 'C2'):
        intro = soup.find('blockquote')
        detail = soup.new_tag('details', attrs={'class': 'draft-context'})
        summary = soup.new_tag('summary'); summary.string = 'About this draft · title candidates & editorial context'
        detail.append(summary); intro.replace_with(detail); detail.append(intro)
        hr = detail.find_next_sibling('hr')
        if hr: hr.decompose()
    # Keep every original figure instruction in a caption-level disclosure below its figure.
    for quote in list(soup.find_all('blockquote')):
        text = quote.get_text(' ', strip=True)
        match = re.match(r'\[FIGURE (F[234])', text)
        if match:
            num = match[1]; asset, caption = FIGURES[num]
            fig = soup.new_tag('figure', attrs={'class': 'technical', 'id': num})
            image = soup.new_tag('img', attrs={'src': data_uri(ASSETS / asset), 'alt': caption, 'loading': 'lazy'})
            fig.append(image)
            cap = soup.new_tag('figcaption'); cap.string = caption; fig.append(cap)
            quote.insert_before(fig)
            details = soup.new_tag('details', attrs={'class': 'draft-context'})
            summary = soup.new_tag('summary'); summary.string = f'{num} · original figure brief'
            details.append(summary); quote.replace_with(details); details.append(quote)
        elif '[AUTHOR' in text or text.startswith('[PENDING') or text.startswith('Sidebar: a number that lied.'):
            quote['class'] = ['editorial']
    # Keep ASCII stand-ins, available as supplementary source beside the finished layout.
    for pre in soup.find_all('pre'):
        if 'Delta Snapshot header' in pre.get_text():
            details = soup.new_tag('details', attrs={'class': 'draft-context'})
            summary = soup.new_tag('summary'); summary.string = 'Original ASCII layout'
            details.append(summary); pre.replace_with(details); details.append(pre)
    for table in list(soup.find_all('table')):
        wrap = soup.new_tag('div', attrs={'class': 'table-wrap', 'tabindex': '0', 'role': 'region', 'aria-label': 'Data table; scroll horizontally if needed'})
        table.replace_with(wrap); wrap.append(table)
        for th in table.find_all('th'): th['scope'] = 'col'
    # Embed original campaign PNGs without changing or restyling their data.
    for image in list(soup.find_all('img')):
        if image['src'].startswith('data:'): continue
        original = (SOURCE / image['src']).resolve()
        if not original.is_file(): raise FileNotFoundError(original)
        shutil.copy2(original, ASSETS / original.name)
        image['src'] = data_uri(original); image['loading'] = 'lazy'
        parent = image.parent
        if parent.name == 'p' and len(parent.contents) == 1:
            parent.name = 'figure'; parent['class'] = ['campaign']
            caption = parent.find_next_sibling('p')
            if caption and caption.find('em') and caption.get_text().startswith(('F1.', 'F5.')):
                caption.extract(); caption.name = 'figcaption'; parent.append(caption)
            if parent.parent.name == 'blockquote': parent.parent.unwrap()
    # Article/appendix links navigate the rendered editions. Other repo evidence links point
    # back into the checkout, with no network needed to retain their original destination.
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith(('https:', 'http:', '#', 'mailto:')): continue
        path, sep, fragment = href.partition('#')
        target = next((k for k in TITLES if path == ('README.md' if k == 'evidence' else f'omega-load-testing.{k}.md')), None)
        a['href'] = (filename(target) if target else '../' + path) + (sep + fragment if sep else '')
    headings = []
    used = set()
    for h in soup.find_all(re.compile('^h[1-6]$')):
        ident = slug(h.get_text())
        while ident in used: ident += '-2'
        used.add(ident); h['id'] = ident
        if h.name == 'h2': headings.append((ident, h.get_text()))
    # Mark evidence/editorial tokens without touching code, links, or any wording.
    for textnode in list(soup.find_all(string=True)):
        if textnode.parent.name in ('code', 'pre', 'script', 'style') or not re.search(r'\[(?:MEASURE|PENDING|AUTHOR)', str(textnode)): continue
        marked = re.sub(r'(\[(?:MEASURE|PENDING|AUTHOR)[^\]]*\])', r'<span class="marker">\1</span>', html.escape(str(textnode)))
        textnode.replace_with(BeautifulSoup(marked, 'html.parser'))
    toc = '<details class="contents" id="contents"><summary>In this article</summary><ol>' + ''.join(f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t in headings) + '</ol></details>'
    words = len(re.findall(r'\b\w+\b', soup.get_text()))
    minutes = max(1, math.ceil(words / 230))
    hero = ''
    if key in ('A', 'C1', 'C2'):
        hero = f'<figure class="hero"><img src="{data_uri(ASSETS / (key + "-cover.png"))}" alt="{dict(A="Blue particles accumulating at a narrow aperture: a conceptual networking bottleneck.", C1="Blue network connections becoming a dense luminous web: a conceptual fan-out illustration.", C2="Blue packet-like tiles accumulating at a glowing gateway: a conceptual load-test illustration.")[key]}"><figcaption>Conceptual editorial illustration · AI-generated · not a visualization of measured data</figcaption></figure>'
    label = {'A': 'Single article / Draft A', 'C1': 'Two-part series / Draft C1', 'C2': 'Two-part series / Draft C2', 'appendices': 'Technical companion', 'evidence': 'Editorial companion'}[key]
    provisional = '<span class="badge">Provisional title</span>' if key in ('A', 'C1', 'C2') else '<span>Reference edition</span>'
    body = f'''{nav(key)}<main id="main"><header class="article-head"><div class="eyebrow">{label}</div><h1>{html.escape(TITLES[key])}</h1><p class="subtitle">{html.escape(SUBTITLES[key])}</p><div class="byline"><div class="avatar" aria-hidden="true">Ω</div><div><div class="author-name">Omega Realm <span style="color:#888">· Engineering</span></div><div class="meta">{minutes} min read · October 2026 · First draft</div></div></div><div class="toolbar">{provisional}<a href="#contents">Contents ↓</a><button type="button" data-notes aria-pressed="false">Hide author notes</button></div></header>{hero}<article class="body">{toc}{soup}</article></main><footer class="endmatter"><p>Local reading edition. Draft wording, evidence markers, and caveats are retained. Subtitle and cover artwork are presentation additions. No editorial choice has been finalized.</p><div class="next-links">{''.join(f'<a href="{filename(k)}">{label} →</a>' for k,label in [('A','Read A'),('C1','Read C1'),('C2','Read C2'),('appendices','Appendices'),('evidence','Evidence rules')] if k != key)}</div></footer>'''
    out = HERE / filename(key); out.write_text(shell(TITLES[key], body, key))
    return {'key': key, 'file': out.name, 'words': words, 'minutes': minutes, 'source': source.name}


def index(records):
    descriptions = {'A': 'The complete argument in one sitting: our wall, the industry, the math, and the experiment.',
                    'C1': 'The industry and the arithmetic. Battlefield, Rust, and the MMO tradeoffs behind the same few caps.',
                    'C2': 'The experiment up close. Wire format, test methodology, clean results, and the limits of the evidence.'}
    cards = ''
    for r in records[:3]:
        k = r['key']
        cards += f'<a class="card" href="{r["file"]}"><img src="{data_uri(ASSETS / (k + "-cover.png"))}" alt=""><div class="eyebrow">Draft {k} / {"Single article" if k == "A" else "Part " + k[-1]}</div><h2>{html.escape(TITLES[k])}</h2><p>{descriptions[k]}</p><span class="read">{r["minutes"]} min read &nbsp; ↗</span></a>'
    body = f'''<main id="main" class="landing"><div class="eyebrow">Omega Realm / Engineering essays</div><h1>One experiment.<br>Three ways to tell it.</h1><p class="landing-intro">Read the full article, or the same story in two parts. A Medium-style reading edition with the draft text, technical figures, and blue-glow editorial artwork.</p><div class="cards">{cards}</div><div class="landing-note">A is the single article. C1 + C2 are the two-part alternative. Titles remain provisional; author notes can be hidden while reading. Conceptual cover art is AI-generated. Technical charts use the supplied draft data.<div class="next-links"><a href="omega-load-testing.appendices.html">Shared appendices →</a><a href="evidence.html">Evidence rules & draft notes →</a></div></div></main>'''
    (HERE / 'index.html').write_text(shell('Three reading editions', body))


if __name__ == '__main__':
    figures()
    records = [convert(k) for k in TITLES]
    index(records)
    (HERE / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')
    print(json.dumps(records, indent=2))
