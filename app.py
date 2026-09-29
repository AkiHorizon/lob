# app.py
import streamlit as st
import requests
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile
import os

HORIZON = "https://horizon.stellar.org"   # oder https://horizon-testnet.stellar.org

def get_created_accounts(address: str, limit: int = 200):
    """Holt alle create_account-Operationen einer Adresse (mit Paginierung)."""
    created = []
    cursor = None
    while True:
        url = f"{HORIZON}/accounts/{address}/operations"
        params = {
            "limit": limit,
            "order": "asc",          # älteste zuerst
            "include_failed": "false"
        }
        if cursor:
            params["cursor"] = cursor

        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            st.warning(f"Fehler bei {address}: {e}")
            break

        records = data.get("_embedded", {}).get("records", [])
        if not records:
            break

        for op in records:
            if op.get("type") == "create_account":
                # funder = Quelle, account = neu erstellte Adresse
                created.append({
                    "funder": op.get("funder") or op.get("source_account"),
                    "account": op.get("account"),
                    "starting_balance": op.get("starting_balance"),
                    "created_at": op.get("created_at"),
                    "id": op.get("id")
                })

        # Nächste Seite
        next_link = data.get("_links", {}).get("next", {}).get("href")
        if not next_link or len(records) < limit:
            break
        # Cursor aus dem letzten paging_token
        cursor = records[-1].get("paging_token")

    return created

def build_graph(root: str, depth: int = 2):
    """Baut den Graphen rekursiv bis zur gewünschten Tiefe."""
    G = nx.DiGraph()
    G.add_node(root, label=root[:6] + "…" + root[-4:], title=root, level=0)

    visited = set([root])
    queue = [(root, 0)]   # (adresse, aktuelle_tiefe)

    while queue:
        current, level = queue.pop(0)
        if level >= depth:
            continue

        created = get_created_accounts(current)
        for item in created:
            child = item["account"]
            if not child:
                continue
            G.add_node(child,
                       label=child[:6] + "…" + child[-4:],
                       title=f"{child}\nBalance: {item['starting_balance']} XLM\n{item['created_at']}",
                       level=level + 1)
            G.add_edge(current, child,
                       title=f"aktiviert am {item['created_at']}\n{item['starting_balance']} XLM")
            if child not in visited:
                visited.add(child)
                queue.append((child, level + 1))

    return G

def show_graph(G):
    """Interaktiver Graph mit pyvis."""
    net = Network(height="700px", width="100%", directed=True, notebook=False)
    net.from_nx(G)

    # Farben nach Ebene
    for node in net.nodes:
        level = G.nodes[node["id"]].get("level", 0)
        if level == 0:
            node["color"] = "#e63946"      # Root rot
            node["size"] = 30
        elif level == 1:
            node["color"] = "#457b9d"
            node["size"] = 22
        else:
            node["color"] = "#a8dadc"
            node["size"] = 16

    net.set_options("""
    {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -80,
          "centralGravity": 0.01,
          "springLength": 120,
          "springConstant": 0.08
        },
        "minVelocity": 0.75,
        "solver": "forceAtlas2Based"
      }
    }
    """)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
        net.save_graph(tmp.name)
        html = open(tmp.name, "r", encoding="utf-8").read()
        os.unlink(tmp.name)
    components.html(html, height=720, scrolling=True)

# ---------- Streamlit UI ----------
st.set_page_config(page_title="Stellar Wallet Activation Graph", layout="wide")
st.title("Stellar Wallet Activation Graph")
st.markdown("Gib eine öffentliche Adresse ein → das Programm sucht aktivierte Wallets (create_account) und visualisiert sie als Netzwerk.")

address = st.text_input("Öffentliche Adresse (G…)", placeholder="GAOW…HHZG")
depth = st.slider("Tiefe (Ebenen)", 1, 3, 2)
run = st.button("Graph bauen", type="primary")

if run and address:
    if not address.startswith("G") or len(address) != 56:
        st.error("Ungültige Stellar-Adresse")
    else:
        with st.spinner("Hole Daten von Horizon… (kann bei vielen Wallets etwas dauern)"):
            G = build_graph(address.strip(), depth=depth)
        st.success(f"Graph fertig: {G.number_of_nodes()} Wallets, {G.number_of_edges()} Verbindungen")
        show_graph(G)

        # Optional: Liste anzeigen
        with st.expander("Gefundene Verbindungen (Tabelle)"):
            edges = []
            for u, v, data in G.edges(data=True):
                edges.append({"Von": u, "Nach": v, "Info": data.get("title", "")})
            st.dataframe(edges, use_container_width=True)
