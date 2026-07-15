# Knowledge Graph Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin-only screen at `/graph` that visualizes the tenant's knowledge base as an interactive graph (tags + documents), backed by a new `GET /api/admin/graph` endpoint.

**Architecture:** One new read-only endpoint in the existing KB router (`server/app/routers/documents.py`, prefix `/api/admin`, guarded by `require_admin`, always scoped to `admin.organization_id`). One new static vanilla page `server/static/graph.html` rendered with a vendored Cytoscape.js (no CDN at runtime for JS). Spec: `docs/superpowers/specs/2026-07-15-knowledge-graph-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2 (backend), pytest + TestClient (tests), vanilla HTML/JS + Cytoscape.js 3.30.4 vendored (frontend).

## Global Constraints

- UI copy in pt-BR; code identifiers and commit messages in English (conventional commits). Inline comments/docstrings follow the repo's existing pt-BR style.
- All commands use `py` (Windows). **Never `cd` persistently into subfolders** — use a subshell: `(cd server && py -m pytest tests)`.
- Every new route needs tests in `server/tests`, **including a tenant-isolation case** (`.claude/rules/server.md`).
- No chunk text in the graph payload — metadata only (token/payload economy).
- Colors/typography come from the palette already used in `server/static/admin.html` (`--bg-dark #2A1B14`, `--accent #C86F52`, `--accent-solid #B25B3E`, cream ink `#F6EFE4`; olive `#4A4F3A` family for secondary data). No cold/neon colors.
- Tag `path` separator is `/` (see `normalize_path` in `server/app/kb/classify.py:42`).
- User-facing copy: apply skill `tom-teia` when writing; run agent `revisor-de-marca` before the final commit that touches copy.
- Downloading the Cytoscape file is an external download — confirm with the user before fetching (Task 2, Step 1).

---

### Task 1: `GET /api/admin/graph` endpoint (TDD)

**Files:**
- Modify: `server/app/routers/documents.py` (new route at end of file; add `datetime` import)
- Test: `server/tests/test_graph_api.py` (create)

**Interfaces:**
- Consumes: existing models `Tag`, `Document`, `DocumentTag` (`server/app/models.py`), `require_admin` (`server/app/deps.py`), fixtures `seed`, `client`, `db` and helpers `login`, `auth_headers` (`server/tests/conftest.py`).
- Produces: `GET /api/admin/graph` → `{"nodes": [...], "edges": [...], "generated_at": "<iso>Z"}` where
  - tag node: `{"id": "tag:<pk>", "kind": "tag", "label": "<last path segment>", "path": "<full path>", "status": "approved|pending|rejected"}`
  - doc node: `{"id": "doc:<pk>", "kind": "doc", "label": "<filename>", "status": "<doc status>", "chunk_count": <int>}`
  - edge: `{"source": "<node id>", "target": "<node id>", "kind": "hierarchy" | "doc_tag"}`; hierarchy edges point parent → child; doc_tag edges point doc → tag.
  - Task 2's frontend consumes exactly this shape.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_graph_api.py`:

```python
"""Rota do knowledge graph: shape do payload, isolamento e autorização."""

from app.models import Document, DocumentTag, Tag

from .conftest import auth_headers, login


def _seed_kb(db, org_id):
    """Taxonomia mínima: rh -> rh/beneficios (com doc), juridico pendente."""
    t_rh = Tag(organization_id=org_id, path="rh", status="approved", source="admin")
    t_ben = Tag(organization_id=org_id, path="rh/beneficios", status="approved",
                source="ia")
    t_pend = Tag(organization_id=org_id, path="juridico", status="pending",
                 source="ia")
    db.add_all([t_rh, t_ben, t_pend])
    doc = Document(organization_id=org_id, filename="ferias.md", ext=".md",
                   content_hash="h1", stored_path="uploads/ferias.md",
                   status="indexed", chunk_count=3)
    db.add(doc)
    db.flush()
    db.add(DocumentTag(document_id=doc.id, tag_id=t_ben.id))
    db.commit()
    return doc, t_rh, t_ben, t_pend


def test_shape_do_grafo(client, db, seed):
    doc, t_rh, t_ben, t_pend = _seed_kb(db, seed["ong"].id)
    token = login(client, "gestora@raizes.org.br", "senha-gestora-123")
    res = client.get("/api/admin/graph", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()

    ids = {n["id"] for n in body["nodes"]}
    assert ids == {f"tag:{t_rh.id}", f"tag:{t_ben.id}", f"tag:{t_pend.id}",
                   f"doc:{doc.id}"}

    ben = next(n for n in body["nodes"] if n["id"] == f"tag:{t_ben.id}")
    assert ben == {"id": f"tag:{t_ben.id}", "kind": "tag", "label": "beneficios",
                   "path": "rh/beneficios", "status": "approved"}
    d = next(n for n in body["nodes"] if n["id"] == f"doc:{doc.id}")
    assert d == {"id": f"doc:{doc.id}", "kind": "doc", "label": "ferias.md",
                 "status": "indexed", "chunk_count": 3}

    edges = {(e["source"], e["target"], e["kind"]) for e in body["edges"]}
    assert edges == {
        (f"tag:{t_rh.id}", f"tag:{t_ben.id}", "hierarchy"),
        (f"doc:{doc.id}", f"tag:{t_ben.id}", "doc_tag"),
    }
    assert body["generated_at"].endswith("Z")


def test_isolamento_entre_tenants(client, db, seed):
    """Admin de outra org não recebe nenhum nó/aresta da ONG."""
    _seed_kb(db, seed["ong"].id)
    teia_token = login(client, "admin@teia.org.br", "senha-admin-123")
    body = client.get("/api/admin/graph",
                      headers=auth_headers(teia_token)).json()
    assert body["nodes"] == []
    assert body["edges"] == []


def test_member_recebe_403(client, seed):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    res = client.get("/api/admin/graph", headers=auth_headers(token))
    assert res.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `(cd server && py -m pytest tests/test_graph_api.py -v)`
Expected: all 3 FAIL — the route doesn't exist yet, so every request returns 404 (including the member case, which expects 403).

- [ ] **Step 3: Implement the route**

In `server/app/routers/documents.py`, add to the imports block (top of file):

```python
from datetime import datetime
```

Append at the end of the file:

```python
# ---------------------------------------------------------------------- grafo
@router.get("/graph")
def knowledge_graph(admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    """Nós (tags e documentos) e arestas (hierarquia e doc↔tag) da org do
    admin. Só metadados — nenhum texto de chunk sai por aqui."""
    org_id = admin.organization_id
    tags = db.scalars(
        select(Tag).where(Tag.organization_id == org_id).order_by(Tag.path)
    ).all()
    docs = db.scalars(
        select(Document).where(Document.organization_id == org_id)
        .order_by(Document.filename)
    ).all()
    links = db.execute(
        select(DocumentTag.document_id, DocumentTag.tag_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(Tag.organization_id == org_id)
    ).all()

    nodes = [
        {"id": f"tag:{t.id}", "kind": "tag",
         "label": t.path.rsplit("/", 1)[-1], "path": t.path,
         "status": t.status}
        for t in tags
    ] + [
        {"id": f"doc:{d.id}", "kind": "doc", "label": d.filename,
         "status": d.status, "chunk_count": d.chunk_count}
        for d in docs
    ]

    tag_by_path = {t.path: t for t in tags}
    edges = []
    for t in tags:
        if "/" in t.path:
            parent = tag_by_path.get(t.path.rsplit("/", 1)[0])
            if parent is not None:
                edges.append({"source": f"tag:{parent.id}",
                              "target": f"tag:{t.id}", "kind": "hierarchy"})
    doc_ids = {d.id for d in docs}
    for document_id, tag_id in links:
        if document_id in doc_ids:
            edges.append({"source": f"doc:{document_id}",
                          "target": f"tag:{tag_id}", "kind": "doc_tag"})

    return {"nodes": nodes, "edges": edges,
            "generated_at": datetime.utcnow().isoformat() + "Z"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `(cd server && py -m pytest tests/test_graph_api.py -v)`
Expected: 3 PASS

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `(cd server && py -m pytest tests)`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/routers/documents.py server/tests/test_graph_api.py
git commit -m "feat(server): add knowledge graph endpoint"
```

---

### Task 2: Vendored Cytoscape, `/graph` route and the graph page

**Files:**
- Create: `server/static/vendor/cytoscape.min.js` (downloaded, pinned 3.30.4)
- Create: `server/static/graph.html`
- Modify: `server/app/main.py` (route `/graph`, next to the existing `/admin` route at `server/app/main.py:138`)
- Test: `server/tests/test_graph_api.py` (one more test)

**Interfaces:**
- Consumes: `GET /api/admin/graph` payload from Task 1 (exact shape in Task 1's Produces block); auth pattern from `server/static/admin.html` (`tryRefresh` via `POST /api/auth/refresh` cookie + `Bearer` header); global `cytoscape()` from the vendored script.
- Produces: page served at `/graph`; `admin.html` links to it in Task 3.

- [ ] **Step 1: Vendor Cytoscape.js (ask the user first — external download)**

Confirm with the user, then download `https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js` (~360 KB, MIT license) to `server/static/vendor/cytoscape.min.js`:

```bash
mkdir -p server/static/vendor
curl -L -o server/static/vendor/cytoscape.min.js https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js
```

Sanity check: file starts with a minified banner mentioning `cytoscape` and is >300 KB.

- [ ] **Step 2: Write the failing route test**

Append to `server/tests/test_graph_api.py`:

```python
def test_pagina_graph_servida(client):
    res = client.get("/graph")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
```

Run: `(cd server && py -m pytest tests/test_graph_api.py::test_pagina_graph_servida -v)`
Expected: FAIL (404 — StaticFiles only matches `/graph.html`, not `/graph`)

- [ ] **Step 3: Add the `/graph` route in `server/app/main.py`**

Right after the `/admin` route (`server/app/main.py:138-143`):

```python
@app.get("/graph", include_in_schema=False)
def graph_page():
    # Casca do grafo da base de conhecimento; os dados vêm de
    # /api/admin/graph, que exige papel admin no servidor.
    return FileResponse(STATIC_DIR / "graph.html")
```

- [ ] **Step 4: Create `server/static/graph.html`**

Full page (copy in pt-BR, palette identical to `admin.html`):

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Te[IA] — Grafo da base</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,wght@0,500;0,600;1,500&family=IBM+Plex+Mono:wght@500&family=Inter:wght@400;500&display=swap');

  :root {
    --bg-dark: #2A1B14;
    --accent: #C86F52;
    --accent-solid: #B25B3E;
    --olive: #8A8F72;
    --ink: #F6EFE4;
    --ink-2: rgba(246, 239, 228, 0.65);
    --ink-3: rgba(246, 239, 228, 0.4);
    --line: rgba(246, 239, 228, 0.12);
    --card: rgba(246, 239, 228, 0.05);
  }

  * { box-sizing: border-box; }

  html, body {
    margin: 0; height: 100%;
    background: var(--bg-dark); color: var(--ink);
    font-family: 'Inter', system-ui, sans-serif; font-size: 14px;
  }

  .wrap { display: flex; flex-direction: column; height: 100vh; max-width: 1280px; margin: 0 auto; padding: 0 20px; }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 0 12px; border-bottom: 1px solid var(--line);
  }
  .logo { font-family: 'Source Serif 4', serif; font-size: 22px; font-weight: 600; display: flex; align-items: center; gap: 2px; }
  .logo .chip { background: var(--accent); color: var(--ink); padding: 2px 6px; border-radius: 4px; font-size: 15px; }
  .logo .page { font-family: 'Inter', sans-serif; font-size: 13px; color: var(--ink-3); margin-left: 10px; }
  .mono { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; }
  .header-right { display: flex; align-items: center; gap: 16px; }
  .header-right a { color: var(--ink-3); text-decoration: none; }
  .header-right a:hover { color: var(--accent); }

  .toolbar { display: flex; align-items: center; gap: 12px; padding: 12px 0; }
  .toolbar input {
    background: var(--card); border: 1px solid var(--line); border-radius: 6px;
    color: var(--ink); padding: 8px 10px; width: 260px; font: inherit;
  }
  .toolbar button {
    background: var(--accent-solid); border: 0; border-radius: 6px;
    color: var(--ink); padding: 8px 14px; font: inherit; cursor: pointer;
  }
  .toolbar button:hover { background: var(--accent); }
  .legend { margin-left: auto; display: flex; gap: 14px; color: var(--ink-2); font-size: 12px; }
  .legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }

  .flash { color: var(--accent); font-size: 13px; min-height: 18px; }

  .main { flex: 1; display: flex; gap: 16px; min-height: 0; padding-bottom: 20px; }
  #cy { flex: 1; min-width: 0; background: var(--card); border-radius: 8px; }

  aside {
    width: 280px; background: var(--card); border-top: 2px solid var(--accent);
    border-radius: 8px; padding: 16px; overflow-y: auto;
  }
  aside h3 { font-family: 'Source Serif 4', serif; font-weight: 600; font-size: 16px; margin: 0 0 4px; word-break: break-all; }
  aside h4 { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-3); margin: 16px 0 4px; }
  aside .meta { color: var(--ink-2); font-size: 12px; margin: 4px 0; }
  aside ul { list-style: none; padding: 0; margin: 4px 0; }
  aside li { padding: 5px 0; border-bottom: 1px solid var(--line); color: var(--ink-2); font-size: 13px; cursor: pointer; word-break: break-all; }
  aside li:hover { color: var(--accent); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">Te<span class="chip">IA</span><span class="page">grafo da base de conhecimento</span></div>
    <div class="header-right mono"><a href="/admin">painel</a><a href="/">chat</a></div>
  </header>

  <div class="toolbar">
    <input id="search" type="search" placeholder="Buscar tag ou documento..." />
    <button id="refresh">Atualizar</button>
    <div class="legend">
      <span><span class="dot" style="background: var(--accent)"></span>tag</span>
      <span><span class="dot" style="background: var(--accent); opacity: .4"></span>tag aguardando aprovação</span>
      <span><span class="dot" style="background: var(--olive)"></span>documento</span>
    </div>
  </div>
  <div class="flash" id="flash"></div>

  <div class="main">
    <div id="cy"></div>
    <aside id="panel"><p class="meta">Clique num nó para ver os detalhes.</p></aside>
  </div>
</div>

<script src="/vendor/cytoscape.min.js"></script>
<script>
  let token = null;

  async function tryRefresh() {
    try {
      const res = await fetch('/api/auth/refresh', { method: 'POST' });
      if (!res.ok) return false;
      token = (await res.json()).access_token;
      return true;
    } catch { return false; }
  }

  async function api(path, opts = {}, retry = true) {
    opts.headers = Object.assign({}, opts.headers,
      token ? { 'Authorization': 'Bearer ' + token } : {});
    const res = await fetch(path, opts);
    if (res.status === 401 && retry && await tryRefresh()) return api(path, opts, false);
    return res;
  }

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let cy = null;
  let graph = { nodes: [], edges: [] };

  const nodeById = (id) => graph.nodes.find((n) => n.id === id);

  function styleSheet() {
    return [
      { selector: 'node', style: {
          label: 'data(label)', 'font-size': 9, color: '#F6EFE4',
          'text-valign': 'bottom', 'text-margin-y': 4,
          'background-color': '#C86F52', width: 18, height: 18 } },
      { selector: 'node[kind = "doc"]', style: {
          shape: 'round-rectangle', 'background-color': '#8A8F72',
          width: 22, height: 14 } },
      { selector: 'node[kind = "tag"][status = "pending"]', style: {
          'background-opacity': 0.35, 'border-width': 2,
          'border-style': 'dashed', 'border-color': '#C86F52' } },
      { selector: 'node[kind = "doc"][status = "error"]', style: {
          'border-width': 2, 'border-color': '#B25B3E' } },
      { selector: 'edge', style: {
          width: 1, 'line-color': 'rgba(246, 239, 228, 0.25)',
          'curve-style': 'haystack' } },
      { selector: 'edge[kind = "hierarchy"]', style: {
          width: 2, 'line-color': 'rgba(200, 111, 82, 0.6)' } },
      { selector: '.highlight', style: {
          'border-width': 3, 'border-style': 'solid',
          'border-color': '#F6EFE4' } },
    ];
  }

  function renderGraph() {
    if (cy) cy.destroy();
    const elements = [
      ...graph.nodes.map((n) => ({ data: { ...n } })),
      ...graph.edges.map((e, i) => ({ data: { id: 'e' + i, ...e } })),
    ];
    cy = cytoscape({
      container: $('cy'), elements, style: styleSheet(),
      layout: { name: 'cose', animate: false }, wheelSensitivity: 0.2,
    });
    cy.on('tap', 'node', (ev) => showDetails(ev.target.data()));
  }

  function focusNode(id) {
    const node = cy.getElementById(id);
    if (!node.length) return;
    cy.elements().removeClass('highlight');
    node.addClass('highlight');
    cy.animate({ center: { eles: node }, zoom: 1.4, duration: 300 });
    showDetails(node.data());
  }

  function showDetails(d) {
    const item = (id, label) => '<li data-id="' + esc(id) + '">' + esc(label) + '</li>';
    let html;
    if (d.kind === 'tag') {
      const children = graph.edges
        .filter((e) => e.kind === 'hierarchy' && e.source === d.id)
        .map((e) => nodeById(e.target)).filter(Boolean);
      const docs = graph.edges
        .filter((e) => e.kind === 'doc_tag' && e.target === d.id)
        .map((e) => nodeById(e.source)).filter(Boolean);
      html = '<h3>' + esc(d.path) + '</h3>'
        + '<p class="meta">tag · ' + (d.status === 'pending' ? 'aguardando aprovação' : 'aprovada') + '</p>'
        + '<h4>Sub-tags (' + children.length + ')</h4><ul>'
        + children.map((c) => item(c.id, c.path)).join('') + '</ul>'
        + '<h4>Documentos (' + docs.length + ')</h4><ul>'
        + docs.map((doc) => item(doc.id, doc.label)).join('') + '</ul>';
    } else {
      const tags = graph.edges
        .filter((e) => e.kind === 'doc_tag' && e.source === d.id)
        .map((e) => nodeById(e.target)).filter(Boolean);
      html = '<h3>' + esc(d.label) + '</h3>'
        + '<p class="meta">documento · ' + esc(d.status) + ' · ' + d.chunk_count + ' trecho(s)</p>'
        + (d.status === 'error'
            ? '<p class="meta">Este documento falhou no processamento — os detalhes estão no painel.</p>' : '')
        + '<h4>Tags (' + tags.length + ')</h4><ul>'
        + tags.map((t) => item(t.id, t.path)).join('') + '</ul>';
    }
    const panel = $('panel');
    panel.innerHTML = html;
    panel.querySelectorAll('li[data-id]').forEach((li) =>
      li.addEventListener('click', () => focusNode(li.dataset.id)));
  }

  async function loadGraph() {
    const res = await api('/api/admin/graph');
    if (res.status === 401 || res.status === 403) { window.location.href = '/'; return; }
    if (!res.ok) { $('flash').textContent = 'Não foi possível carregar o grafo. Tente atualizar.'; return; }
    graph = await res.json();
    $('flash').textContent = graph.nodes.length
      ? '' : 'A base ainda não tem documentos nem tags — o grafo aparece conforme a equipe alimenta a base.';
    renderGraph();
  }

  $('refresh').addEventListener('click', loadGraph);

  $('search').addEventListener('input', (ev) => {
    if (!cy) return;
    const term = ev.target.value.trim().toLowerCase();
    cy.elements().removeClass('highlight');
    if (!term) return;
    const hits = cy.nodes().filter((n) => {
      const d = n.data();
      return (d.label || '').toLowerCase().includes(term)
        || (d.path || '').toLowerCase().includes(term);
    });
    hits.addClass('highlight');
    if (hits.length) cy.animate({ fit: { eles: hits, padding: 80 }, duration: 300 });
  });

  (async () => {
    if (!(await tryRefresh())) { window.location.href = '/'; return; }
    await loadGraph();
  })();
</script>
</body>
</html>
```

- [ ] **Step 5: Run the tests**

Run: `(cd server && py -m pytest tests/test_graph_api.py -v)`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add server/static/vendor/cytoscape.min.js server/static/graph.html server/app/main.py server/tests/test_graph_api.py
git commit -m "feat(server): add admin knowledge graph screen with vendored cytoscape"
```

---

### Task 3: Entry link, brand review and end-to-end verification

**Files:**
- Modify: `server/static/admin.html` (link in `.header-right`, around line 69 of the CSS / the header markup near the top of `<body>`)

**Interfaces:**
- Consumes: `/graph` page from Task 2.
- Produces: final, verified feature; no new interfaces.

- [ ] **Step 1: Add the entry link in `admin.html`**

Locate the `<div class="header-right mono">` element in the `<body>` of `server/static/admin.html` and add, as its first child:

```html
<a href="/graph">grafo da base</a>
```

(match the existing anchors' style — they are plain `<a>` elements styled by `.header-right a`).

- [ ] **Step 2: Brand review of user-facing copy**

Run the `revisor-de-marca` agent over `server/static/graph.html` and the `admin.html` diff; apply any tone/vocabulary fixes it reports. Copy was written with skill `tom-teia` in mind — verify, don't assume.

- [ ] **Step 3: Principles review**

Run skill `revisao-principios` on the delivery (read-only screen, admin-gated, no AI decision loop — expected to pass; the graph does not edit taxonomy, so the human-approval pattern is untouched).

- [ ] **Step 4: Full test suite**

Run: `(cd server && py -m pytest tests)`
Expected: all PASS

- [ ] **Step 5: Verify in the browser**

Start the server via `.claude/launch.json` preview (never Bash). Seed demo data if needed: `(cd server && py -m app.seed --demo)`. Then:
1. Log in as an admin, open `/admin`, click "grafo da base".
2. Confirm the graph renders; click a tag node → side panel shows sub-tags/documents; click a doc node → panel shows tags and chunk count.
3. Type in the search box → matching nodes highlight.
4. Upload a new document in `/admin`, wait for indexing, click "Atualizar" on `/graph` → new node appears.
5. Log in as a member in a private window → opening `/graph` redirects to `/` (API 403).
Take a screenshot as proof.

- [ ] **Step 6: Commit**

```bash
git add server/static/admin.html server/static/graph.html
git commit -m "feat(server): link knowledge graph from admin panel"
```
