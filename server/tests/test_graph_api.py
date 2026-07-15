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


def test_pagina_graph_servida(client):
    res = client.get("/graph")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
