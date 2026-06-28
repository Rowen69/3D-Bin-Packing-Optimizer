import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import random
import time
import gurobipy as gp
from gurobipy import GRB
import pymongo
import uuid
from datetime import datetime
from fpdf import FPDF
import io

st.set_page_config(page_title="3D Bin Packing", layout="wide")

# =========================
# CONFIG & SESSION STATE
# =========================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

if 'all_results' not in st.session_state:
    st.session_state['all_results'] = None

if 'current_page' not in st.session_state:
    st.session_state['current_page'] = "Dashboard Optimasi"

# =========================
# DATASET INTERNAL
# =========================
dataset_dict = [
    {"name": "Waterproof PAR 1810W", "length": 46, "width": 46, "height": 32, "weight": 18, "quantity": 1, "fragile": False},
    {"name": "Display Board",        "length": 46, "width": 46, "height": 10, "weight": 8,  "quantity": 1, "fragile": True},
    {"name": "Fan Unit",             "length": 22, "width": 49, "height": 32, "weight": 12, "quantity": 1, "fragile": False},
    {"name": "Mainboard PAR 1810W",  "length": 40, "width": 30, "height": 8,  "weight": 5,  "quantity": 1, "fragile": True},
    {"name": "Inner Wire Set",       "length": 30, "width": 20, "height": 10, "weight": 3,  "quantity": 1, "fragile": False},
    {"name": "LED Bulb A",           "length": 30, "width": 30, "height": 40, "weight": 5,  "quantity": 40, "fragile": True},
    {"name": "LED Panel",            "length": 100, "width": 60, "height": 10, "weight": 8,  "quantity": 40, "fragile": True},
    {"name": "Metal Frame",          "length": 120, "width": 50, "height": 50, "weight": 20, "quantity": 14, "fragile": False},
    {"name": "Cable Box",            "length": 40, "width": 40, "height": 40, "weight": 10, "quantity": 8,  "fragile": False},
    {"name": "Glass Cover",          "length": 80, "width": 80, "height": 5,  "weight": 6,  "quantity": 10, "fragile": True},
    {"name": "Driver Unit",          "length": 50, "width": 40, "height": 30, "weight": 12, "quantity": 10, "fragile": False},
    {"name": "Long Strobe",          "length": 106, "width": 28, "height": 33, "weight": 16, "quantity": 7,  "fragile": False},
    {"name": "Wallwasher 1810W",     "length": 106, "width": 28, "height": 33, "weight": 16, "quantity": 3,  "fragile": False},
    {"name": "Strobo Waterproof",    "length": 51, "width": 34, "height": 29, "weight": 20, "quantity": 6,  "fragile": False},
    {"name": "Strobe 8 Segment",     "length": 51, "width": 34, "height": 29, "weight": 20, "quantity": 7,  "fragile": False},
    {"name": "Fresnell 200W",        "length": 46, "width": 46, "height": 21, "weight": 15, "quantity": 5,  "fragile": False}
]

def load_dataset(uploaded_file):
    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith("xlsx") else pd.read_csv(uploaded_file)
    df.columns = [c.lower().strip() for c in df.columns]
    return df

def load_default_dataset():
    return pd.DataFrame(dataset_dict)

def expand_items(df):
    items = []
    for _, row in df.iterrows():
        quantity = int(row['quantity']) if pd.notnull(row['quantity']) else 0
        for i in range(quantity):
            items.append({
                'id': f"{row['name']}_{i}",
                'name': row['name'],
                'l': float(row['length']),
                'w': float(row['width']),
                'h': float(row['height']),
                'weight': float(row['weight']),
                'volume': float(row['length']) * float(row['width']) * float(row['height']),
                'fragile': any(k in str(row['name']).lower() for k in ['glass','led','screen']) or bool(row.get('fragile', False))
            })
    return items

# =========================
# FUNGSI DATABASE (MONGODB)
# =========================
def get_mongo_db():
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    return client["db_binpacking"]

def save_all_to_mongodb(results_dict, container, all_items):
    try:
        db = get_mongo_db()
        collection = db["history_optimasi"]
        
        batch_id = f"BATCH_{uuid.uuid4().hex[:8].upper()}"
        
        doc = {
            "batch_id": batch_id,
            "waktu_simpan": datetime.now(),
            "kontainer": container,
            "total_request_item": len(all_items),
            "metode": {}
        }
        
        for method, data in results_dict.items():
            if data['result'] is not None:
                doc["metode"][method] = {
                    "waktu_komputasi": data['time'],
                    "placed_items": data['result']
                }
                
        collection.insert_one(doc)
        return True, "Berhasil! Seluruh hasil optimasi tersimpan ke MongoDB."
    except Exception as e:
        return False, f"Gagal menyimpan ke MongoDB: {str(e)}"

def get_all_history():
    try:
        db = get_mongo_db()
        return list(db["history_optimasi"].find().sort("waktu_simpan", -1))
    except:
        return []

# =========================
# CORE PACKER DECODER (FA-FFD & GA)
# =========================
def pack_items(items_order, container):
    placed = []
    total_weight = 0

    for item in items_order:
        if total_weight + item['weight'] > container['max_kg']: continue

        # Dibulatkan agar terhindar dari error desimal Python
        x_pts = sorted(list(set([0] + [round(p['x'] + p['l'], 2) for p in placed if round(p['x'] + p['l'], 2) < container['L']])))
        y_pts = sorted(list(set([0] + [round(p['y'] + p['w'], 2) for p in placed if round(p['y'] + p['w'], 2) < container['W']])))
        z_pts = sorted(list(set([0] + [round(p['z'] + p['h'], 2) for p in placed if round(p['z'] + p['h'], 2) < container['H']])))

        placed_this_item = False
        
        for z in z_pts:
            if z + item['h'] > container['H']: continue
            for y in y_pts:
                if y + item['w'] > container['W']: continue
                for x in x_pts:
                    if x + item['l'] > container['L']: continue

                    overlap = False
                    for p in placed:
                        # Cek Overlap
                        if not (round(x + item['l'], 2) <= p['x'] or round(p['x'] + p['l'], 2) <= x or
                                round(y + item['w'], 2) <= p['y'] or round(p['y'] + p['w'], 2) <= y or
                                round(z + item['h'], 2) <= p['z'] or round(p['z'] + p['h'], 2) <= z):
                            overlap = True
                            break
                            
                    if not overlap:
                        fragile_violation = False
                        for p in placed:
                            irisan_XY = not (round(x + item['l'], 2) <= p['x'] or round(p['x'] + p['l'], 2) <= x or
                                             round(y + item['w'], 2) <= p['y'] or round(p['y'] + p['w'], 2) <= y)
                                             
                            if irisan_XY:
                                # Cek 1: Jika barang LAMA (p) fragile, dan barang BARU (item) ditaruh di atasnya
                                if p['fragile']:
                                    if z >= round(p['z'] + p['h'], 2): 
                                        # PELANGGARAN MUTLAK: Tidak boleh ada barang apa pun di atas fragile
                                        fragile_violation = True
                                        break
                                        
                                # Cek 2: Jika barang BARU (item) fragile, dan barang LAMA (p) ada di atasnya
                                if item['fragile']:
                                    if p['z'] >= round(z + item['h'], 2): 
                                        # PELANGGARAN MUTLAK: Fragile tidak boleh diselipkan di bawah barang apa pun
                                        fragile_violation = True
                                        break
                        
                        if not fragile_violation:
                            placed.append({**item, 'x': x, 'y': y, 'z': z})
                            total_weight += item['weight']
                            placed_this_item = True
                            break
                if placed_this_item: break
            if placed_this_item: break

    # Post-processing gravitasi (menarik semua box agar jatuh menumpuk dengan rapat)
    placed.sort(key=lambda b: b['z'])
    for i in range(len(placed)):
        box = placed[i]
        max_z_below = 0
        for j in range(i):
            other = placed[j]
            if (round(box['x'], 2) < round(other['x'] + other['l'], 2) and round(box['x'] + box['l'], 2) > other['x']) and \
               (round(box['y'], 2) < round(other['y'] + other['w'], 2) and round(box['y'] + box['w'], 2) > other['y']):
                if round(other['z'] + other['h'], 2) > max_z_below: 
                    max_z_below = round(other['z'] + other['h'], 2)
        box['z'] = max_z_below

    return placed

def fa_ffd(items, container):
    items_sorted = sorted(items, key=lambda x: (x['fragile'], -x['volume']))
    return pack_items(items_sorted, container)

def genetic_algorithm(items, container):
    items_sorted_faffd = sorted(items, key=lambda x: (x['fragile'], -x['volume']))
    population = [items_sorted_faffd]
    for _ in range(9): population.append(random.sample(items, len(items)))

    def fitness(chrom): return sum(i['volume'] for i in pack_items(chrom, container))

    for _ in range(10):
        population = sorted(population, key=fitness, reverse=True)
        new_pop = population[:2]
        while len(new_pop) < 10:
            p1, p2 = random.sample(population[:5], 2)
            cut = random.randint(1, len(items)-1)
            child = p1[:cut] + [i for i in p2 if i not in p1[:cut]]
            if random.random() < 0.1:
                idx1, idx2 = random.sample(range(len(child)), 2)
                child[idx1], child[idx2] = child[idx2], child[idx1]
            new_pop.append(child)
        population = new_pop
    return pack_items(population[0], container)

# =========================
# MILP OPTIMIZATION (GUROBI)
# =========================
def run_milp_optimization(items, container, time_limit):
    n = len(items)
    L_cont, W_cont, H_cont, W_max = container['L'], container['W'], container['H'], container['max_kg']
    M = max(L_cont, W_cont, H_cont) * 2 
    
    model = gp.Model("3DBPP_MILP")
    model.setParam('TimeLimit', time_limit)
    model.setParam('OutputFlag', 1)

    model.setParam('Threads', 2) 
    model.setParam('NodefileStart', 0.5) 

    x = model.addVars(n, vtype=GRB.CONTINUOUS, lb=0, name="x")
    y = model.addVars(n, vtype=GRB.CONTINUOUS, lb=0, name="y")
    z = model.addVars(n, vtype=GRB.CONTINUOUS, lb=0, name="z")
    u = model.addVars(n, vtype=GRB.BINARY, name="u")

    d_x, d_nx = model.addVars(n, n, vtype=GRB.BINARY), model.addVars(n, n, vtype=GRB.BINARY)
    d_y, d_ny = model.addVars(n, n, vtype=GRB.BINARY), model.addVars(n, n, vtype=GRB.BINARY)
    d_z, d_nz = model.addVars(n, n, vtype=GRB.BINARY), model.addVars(n, n, vtype=GRB.BINARY)

    penalty = gp.quicksum(0.1 * x[i] + 0.1 * y[i] + 0.5 * z[i] for i in range(n))
    model.setObjective(gp.quicksum(items[i]['volume'] * u[i] for i in range(n)) - penalty, GRB.MAXIMIZE) 

    for i in range(n):
        model.addConstr(x[i] + items[i]['l'] * u[i] <= L_cont * u[i])
        model.addConstr(y[i] + items[i]['w'] * u[i] <= W_cont * u[i])
        model.addConstr(z[i] + items[i]['h'] * u[i] <= H_cont * u[i])

    model.addConstr(gp.quicksum(items[i]['weight'] * u[i] for i in range(n)) <= W_max)

    for i in range(n):
        for j in range(i + 1, n):
            model.addConstr(x[i] + items[i]['l'] <= x[j] + M * (1 - d_x[i,j]))
            model.addConstr(x[j] + items[j]['l'] <= x[i] + M * (1 - d_nx[i,j]))
            model.addConstr(y[i] + items[i]['w'] <= y[j] + M * (1 - d_y[i,j]))
            model.addConstr(y[j] + items[j]['w'] <= y[i] + M * (1 - d_ny[i,j]))
            model.addConstr(z[i] + items[i]['h'] <= z[j] + M * (1 - d_z[i,j]))
            model.addConstr(z[j] + items[j]['h'] <= z[i] + M * (1 - d_nz[i,j]))
            model.addConstr(d_x[i,j] + d_nx[i,j] + d_y[i,j] + d_ny[i,j] + d_z[i,j] + d_nz[i,j] >= u[i] + u[j] - 1)

            # 4. Fragile (REVISI MUTLAK: Fragile tidak boleh ditimpa apapun)
            if items[i]['fragile']:
                model.addConstr(d_z[i,j] == 0)

            if items[j]['fragile']:
                model.addConstr(d_nz[i,j] == 0)

    model.optimize()

    placed_boxes = []
    if model.SolCount > 0:
        raw_boxes = []
        for i in range(n):
            if u[i].X > 0.5:
                box = items[i].copy()
                box['x'], box['y'], box['z'] = round(x[i].X, 2), round(y[i].X, 2), round(z[i].X, 2)
                raw_boxes.append(box)
        raw_boxes.sort(key=lambda b: b['z'])
        for i in range(len(raw_boxes)):
            box = raw_boxes[i]
            max_z_below = 0
            for j in range(i):
                other = raw_boxes[j]
                if (round(box['x'], 2) < round(other['x'] + other['l'], 2) and round(box['x'] + box['l'], 2) > other['x']) and \
                   (round(box['y'], 2) < round(other['y'] + other['w'], 2) and round(box['y'] + box['w'], 2) > other['y']):
                    if round(other['z'] + other['h'], 2) > max_z_below: 
                        max_z_below = round(other['z'] + other['h'], 2)
            box['z'] = max_z_below
            placed_boxes.append(box)
    return placed_boxes

# =========================
# VISUALISASI PLOTLY
# =========================
def create_box_with_edges(x, y, z, l, w, h, color, name, show_legend):
    traces = []
    
    i_correct = [0, 0,  4, 4,  0, 0,  3, 3,  0, 0,  1, 1]
    j_correct = [1, 2,  5, 6,  1, 5,  2, 6,  3, 7,  2, 6]
    k_correct = [2, 3,  6, 7,  5, 4,  6, 7,  7, 4,  6, 5]

    traces.append(go.Mesh3d(
        x=[x, x+l, x+l, x, x, x+l, x+l, x], 
        y=[y, y, y+w, y+w, y, y, y+w, y+w], 
        z=[z, z, z, z, z+h, z+h, z+h, z+h],
        i=i_correct, j=j_correct, k=k_correct,
        opacity=0.85, color=color, name=name, legendgroup=name, showlegend=show_legend,
        flatshading=True, hoverinfo="name+text", text=f"{name}<br>Ukuran: {l}x{w}x{h}<br>X:{x:.1f}, Y:{y:.1f}, Z:{z:.1f}"
    ))
    
    xe = [x, x+l, x+l, x, x, None, x, x+l, x+l, x, x, None, x, x, None, x+l, x+l, None, x+l, x+l, None, x, x, None]
    ye = [y, y, y+w, y+w, y, None, y, y, y+w, y+w, y, None, y, y, None, y, y, None, y+w, y+w, None, y+w, y+w, None]
    ze = [z, z, z, z, z, None, z+h, z+h, z+h, z+h, z+h, None, z, z+h, None, z, z+h, None, z, z+h, None, z, z+h, None]
    traces.append(go.Scatter3d(x=xe, y=ye, z=ze, mode='lines', line=dict(color='black', width=3), hoverinfo='skip', showlegend=False, legendgroup=name))
    return traces

def draw_container(container):
    L, W, H = container['L'], container['W'], container['H']
    lines = []
    edges = [[(0,0,0),(L,0,0)], [(0,W,0),(L,W,0)], [(0,0,H),(L,0,H)], [(0,W,H),(L,W,H)], [(0,0,0),(0,W,0)], [(L,0,0),(L,W,0)], [(0,0,H),(0,W,H)], [(L,0,H),(L,W,H)], [(0,0,0),(0,0,H)], [(L,0,0),(L,0,H)], [(0,W,0),(0,W,H)], [(L,W,0),(L,W,H)]]
    for e in edges:
        x, y, z = zip(*e)
        lines.append(go.Scatter3d(x=x, y=y, z=z, mode='lines', line=dict(color='#2ca02c', width=5), showlegend=False, hoverinfo='skip'))
    return lines

def visualize(items, container, method_name):
    fig = go.Figure()
    for line in draw_container(container): fig.add_trace(line)

    palette = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52']
    color_map = {}
    added_to_legend = set()

    for item in items:
        if item['name'] not in color_map: color_map[item['name']] = palette[len(color_map) % len(palette)]
        show_leg = item['name'] not in added_to_legend
        added_to_legend.add(item['name'])
        for trace in create_box_with_edges(item['x'], item['y'], item['z'], item['l'], item['w'], item['h'], color_map[item['name']], item['name'], show_leg):
            fig.add_trace(trace)

    fig.update_layout(
        title=f"<b>Visualisasi 3D - {method_name}</b>",
        scene=dict(xaxis_title='Panjang (X) cm', yaxis_title='Lebar (Y) cm', zaxis_title='Tinggi (Z) cm', aspectmode='data'),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(title="Daftar Barang:", x=1.05, y=0.5, bordercolor="Black", borderwidth=1),
        height=600
    )
    return fig

def get_plot_images(fig):
    views = {
        "Depan": dict(x=0, y=-2, z=0),
        "Belakang": dict(x=0, y=2, z=0),
        "Kiri": dict(x=-2, y=0, z=0),
        "Kanan": dict(x=2, y=0, z=0),
        "Atas": dict(x=0, y=0, z=2.5)
    }
    images_bytes = {}
    for name, eye in views.items():
        fig.update_layout(scene_camera=dict(eye=eye))
        # Membutuhkan library 'kaleido' untuk to_image
        img_bytes = fig.to_image(format="png", width=800, height=500)
        images_bytes[name] = img_bytes
    return images_bytes

# =========================
# FUNGSI GENERATOR PDF (UNIFIED)
# =========================
def create_unified_pdf_report(results_dict, all_items, container):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    
    for method, data in results_dict.items():
        if data['result'] is None: continue
        
        placed_items = data['result']
        elapsed_time = data['time']
        
        total_requested = len(all_items)
        total_placed = len(placed_items)
        total_weight = sum(i['weight'] for i in placed_items)
        total_volume = sum(i['volume'] for i in placed_items)
        container_volume = container['L'] * container['W'] * container['H']
        utilization_vol = (total_volume / container_volume) * 100

        pdf.add_page()
        # --- Header ---
        pdf.set_font("helvetica", "B", 16)
        pdf.set_fill_color(0, 0, 0)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 12, f" LAPORAN HASIL OPTIMASI - {method}", ln=True, align="C", fill=True)
        pdf.ln(5)
        
        # --- Ringkasan Eksekutif ---
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Ringkasan Eksekutif", ln=True)
        
        pdf.set_font("helvetica", "", 10)
        pdf.cell(95, 6, f"Waktu Komputasi: {elapsed_time:.3f} detik", ln=False)
        pdf.cell(95, 6, f"Barang Dimuat: {total_placed} / {total_requested} box", ln=True)
        pdf.cell(95, 6, f"Utilisasi Ruang (Volume): {utilization_vol:.2f}%", ln=False)
        pdf.cell(95, 6, f"Total Berat: {total_weight:,.1f} / {container['max_kg']} kg", ln=True)
        pdf.ln(5)

        # --- Visualisasi 3D Images ---
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Tangkapan Layar Visualisasi 3D", ln=True)
        
        fig = visualize(placed_items, container, method)
        img_dict = get_plot_images(fig)
        
        # Menyusun 5 gambar dalam 1 halaman
        y_start = pdf.get_y()
        pdf.set_font("helvetica", "I", 9)
        
        # Depan
        pdf.cell(95, 5, "Tampak Depan", ln=False, align="C")
        # Belakang
        pdf.cell(95, 5, "Tampak Belakang", ln=True, align="C")
        pdf.image(io.BytesIO(img_dict["Depan"]), x=10, y=pdf.get_y(), w=90)
        pdf.image(io.BytesIO(img_dict["Belakang"]), x=110, y=pdf.get_y(), w=90)
        pdf.ln(60) # space for image
        
        # Kiri
        pdf.cell(95, 5, "Tampak Kiri", ln=False, align="C")
        # Kanan
        pdf.cell(95, 5, "Tampak Kanan", ln=True, align="C")
        pdf.image(io.BytesIO(img_dict["Kiri"]), x=10, y=pdf.get_y(), w=90)
        pdf.image(io.BytesIO(img_dict["Kanan"]), x=110, y=pdf.get_y(), w=90)
        pdf.ln(60)
        
        # Atas (Tengah bawah)
        pdf.cell(0, 5, "Tampak Atas", ln=True, align="C")
        pdf.image(io.BytesIO(img_dict["Atas"]), x=60, y=pdf.get_y(), w=90)
        
        pdf.add_page() # Pindah halaman untuk tabel
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, f"Rincian Penempatan Barang ({method})", ln=True)
        
        # Header Tabel
        pdf.set_font("helvetica", "B", 8)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(10, 8, "No", 1, 0, "C", True)
        pdf.cell(60, 8, "Nama Barang", 1, 0, "C", True)
        pdf.cell(35, 8, "Dimensi (cm)", 1, 0, "C", True)
        pdf.cell(20, 8, "Berat", 1, 0, "C", True)
        pdf.cell(20, 8, "Fragile", 1, 0, "C", True)
        pdf.cell(45, 8, "Koordinat (X,Y,Z)", 1, 1, "C", True)
        
        # Isi Tabel
        pdf.set_font("helvetica", "", 8)
        for idx, item in enumerate(placed_items, 1):
            fragile_txt = "Ya" if item['fragile'] else "Tidak"
            dim_txt = f"{item['l']}x{item['w']}x{item['h']}"
            pos_txt = f"({item['x']:.0f}, {item['y']:.0f}, {item['z']:.0f})"
            nama_brg = str(item['name'])[:30] + "..." if len(str(item['name'])) > 30 else str(item['name'])
            
            pdf.cell(10, 7, str(idx), 1, 0, "C")
            pdf.cell(60, 7, nama_brg, 1, 0, "L")
            pdf.cell(35, 7, dim_txt, 1, 0, "C")
            pdf.cell(20, 7, f"{item['weight']} kg", 1, 0, "C")
            pdf.cell(20, 7, fragile_txt, 1, 0, "C")
            pdf.cell(45, 7, pos_txt, 1, 1, "C")

    return pdf.output()

# =========================
# PAGES
# =========================
def login_page():
    st.markdown("""
        <style>
        .stApp { background: #000000; }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stForm"] { background-color: grey; border-radius: 12px; padding: 40px 30px; border: none; }
        [data-testid="stFormSubmitButton"] > button { background-color: #000000; color: white; font-weight: bold; border: none; border-radius: 6px; padding: 10px; margin-top: 15px; }
        [data-testid="stFormSubmitButton"] > button:hover { background-color: #3b88e8; }
        .spacer { height: 15vh; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<div class='spacer'></div>", unsafe_allow_html=True)
    _, col2, _ = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form", clear_on_submit=False):
            st.markdown("<h2 style='text-align: center; color: black; margin-bottom: 20px;'>Login</h2>", unsafe_allow_html=True)
            username = st.text_input("Username", placeholder="Username", label_visibility="collapsed")
            password = st.text_input("Password", type="password", placeholder="Password", label_visibility="collapsed")
            if st.form_submit_button("Login", use_container_width=True):
                if username == "admin" and password == "admin123":
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Username atau Password salah!")

def dashboard_optimasi():
    st.markdown("### ⚙️ Konfigurasi Kontainer")
    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    with col_c1: c_length = st.number_input("Panjang (cm)", min_value=1, value=600)
    with col_c2: c_width = st.number_input("Lebar (cm)", min_value=1, value=250)
    with col_c3: c_height = st.number_input("Tinggi (cm)", min_value=1, value=250)
    with col_c4: c_max_kg = st.number_input("Kapasitas (kg)", min_value=1, value=30000)

    custom_container = {'L': c_length, 'W': c_width, 'H': c_height, 'max_kg': c_max_kg}

    uploaded_file = st.file_uploader("Upload Dataset (CSV / Excel)", type=["csv","xlsx"])
    if uploaded_file:
        try: df = load_dataset(uploaded_file)
        except: df = load_default_dataset()
    else: df = load_default_dataset()

    with st.expander("📝 Edit Dataset", expanded=False):
        edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")

    try: items = expand_items(edited_df)
    except: st.stop()

    time_limit = st.slider("Batas Waktu MILP (detik)", 30, 36000, 60, 30)

    if st.button("🚀 JALANKAN SEMUA OPTIMASI (FA-FFD, GA, MILP)", use_container_width=True, type="primary"):
        if len(items) == 0:
            st.warning("Data kosong!")
            return
            
        all_res = {}
        
        with st.spinner("Menghitung FA-FFD..."):
            s = time.time()
            res_faffd = fa_ffd(items, custom_container)
            all_res['FA-FFD'] = {'result': res_faffd, 'time': time.time() - s}
            
        with st.spinner("Menghitung Genetic Algorithm..."):
            s = time.time()
            res_ga = genetic_algorithm(items, custom_container)
            all_res['GA'] = {'result': res_ga, 'time': time.time() - s}
            
        with st.spinner(f"Menghitung MILP Gurobi (Time Limit {time_limit}s)... Mohon Ditunggu"):
            s = time.time()
            try:
                res_milp = run_milp_optimization(items, custom_container, time_limit)
                all_res['MILP'] = {'result': res_milp, 'time': time.time() - s}
            except:
                all_res['MILP'] = {'result': None, 'time': 0}
                
        st.session_state['all_results'] = all_res
        st.session_state['current_items'] = items
        st.session_state['current_container'] = custom_container

    # --- TAMPILAN SATU HALAMAN ---
    if st.session_state['all_results'] is not None:
        results = st.session_state['all_results']
        items = st.session_state['current_items']
        container = st.session_state['current_container']
        
        st.markdown("---")
        st.header("📊 Hasil Komparasi Optimasi Keseluruhan")
        
        for method, data in results.items():
            if data['result'] is None: continue
            
            st.subheader(f"Hasil {method}")
            placed = data['result']
            vol_util = (sum(i['volume'] for i in placed) / (container['L']*container['W']*container['H'])) * 100
            
            total_berat = sum(i['weight'] for i in placed)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Barang Termuat", f"{len(placed)} / {len(items)}", f"{(len(placed)/len(items))*100:.1f}%")
            c2.metric("Utilisasi Volume", f"{vol_util:.2f}%")
            c3.metric("Total Berat", f"{total_berat:,.1f} kg", f"MAX: {container['max_kg']} kg")
            c4.metric("Waktu Eksekusi", f"{data['time']:.3f} detik")
            
            st.plotly_chart(visualize(placed, container, method), use_container_width=True)
            st.divider()

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("📄 Generate & Download Laporan Lengkap (PDF)", use_container_width=True):
                with st.spinner("Sedang memotret 3D dan menyusun PDF (Sekitar 10 detik)..."):
                    pdf_bytes = create_unified_pdf_report(results, items, container)
                    st.download_button("Klik untuk Mengunduh PDF", data=bytes(pdf_bytes), file_name="Laporan_Keseluruhan.pdf", mime="application/pdf")
        
        with col_btn2:
            if st.button("💾 Simpan Semua Hasil ke MongoDB", type="primary", use_container_width=True):
                with st.spinner("Menyimpan..."):
                    success, msg = save_all_to_mongodb(results, container, items)
                    if success: st.success(msg)
                    else: st.error(msg)

def history_page():
    st.header("🗄️ Riwayat Hasil Optimasi (MongoDB)")
    histories = get_all_history()
    
    if not histories:
        st.info("Belum ada data riwayat di database.")
        return
        
    df_hist = pd.DataFrame([{
        "Batch ID": h['batch_id'],
        "Waktu": h['waktu_simpan'].strftime("%Y-%m-%d %H:%M:%S"),
        "Total Request": h['total_request_item'],
        "Dimensi Kontainer": f"{h['kontainer']['L']}x{h['kontainer']['W']}x{h['kontainer']['H']}"
    } for h in histories])
    
    st.dataframe(df_hist, use_container_width=True, hide_index=True)
    
    st.markdown("### 🔍 Lihat Detail & Visualisasi")
    selected_batch = st.selectbox("Pilih Batch ID untuk melihat detail:", [h['batch_id'] for h in histories])
    
    if selected_batch:
        doc = next((h for h in histories if h['batch_id'] == selected_batch), None)
        container = doc['kontainer']
        
        for method, data in doc['metode'].items():
            st.subheader(f"Metode: {method}")
            placed = data['placed_items']
            vol_util = (sum(i['volume'] for i in placed) / (container['L']*container['W']*container['H'])) * 100
            
            total_berat = sum(i['weight'] for i in placed)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Barang Termuat", f"{len(placed)} box")
            c2.metric("Utilisasi Volume", f"{vol_util:.2f}%")
            c3.metric("Total Berat", f"{total_berat:,.1f} kg") 
            c4.metric("Waktu Eksekusi", f"{data['waktu_komputasi']:.3f} detik")
            
            st.plotly_chart(visualize(placed, container, method), use_container_width=True)
            
            with st.expander(f"Tabel Rincian {method}"):
                st.dataframe(pd.DataFrame(placed)[['name', 'l', 'w', 'h', 'weight', 'x', 'y', 'z', 'fragile']], use_container_width=True)
            st.divider()

# =========================
# APP ROUTER
# =========================
if not st.session_state['logged_in']:
    login_page()
else:
    with st.sidebar:
        st.title("Menu Admin")
        st.session_state['current_page'] = st.radio("Navigasi", ["Dashboard Optimasi", "Riwayat Database"])
        st.write("---")
        if st.button("Logout", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

    if st.session_state['current_page'] == "Dashboard Optimasi":
        dashboard_optimasi()
    elif st.session_state['current_page'] == "Riwayat Database":
        history_page()