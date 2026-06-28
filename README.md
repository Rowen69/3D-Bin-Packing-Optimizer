# 3D-Bin-Packing-Optimizer
Aplikasi optimasi penataan barang 3D (3DBPP) dengan constraint fragile. Membandingkan metode MILP, Genetic Algorithm, dan FA-FFD.

# 📦 3D Bin Packing Optimization Dashboard

Sebuah aplikasi berbasis web interaktif yang dikembangkan menggunakan **Python** dan **Streamlit** untuk menyelesaikan masalah optimasi logistik, khususnya **3D Bin Packing Problem (3DBPP)**. 

Aplikasi ini dirancang untuk memaksimalkan utilisasi ruang kontainer dan meminimalkan ruang kosong dengan mempertimbangkan batasan berat, dimensi, dan aturan khusus untuk barang rapuh (*fragile*). Cocok diterapkan untuk manajemen logistik pengiriman barang atau pemuatan peralatan *event* (seperti LED Bulb, Metal Frame, Strobe, dll).

## 🚀 Fitur Utama
- **Multi-Algorithm Optimization:** Membandingkan tiga metode penyelesaian secara langsung:
  1. **FA-FFD (Fragile-Aware First Fit Decreasing):** Algoritma heuristik yang cepat dan efisien.
  2. **Genetic Algorithm (GA):** Algoritma metaheuristik berbasis populasi untuk mencari solusi optimal.
  3. **MILP (Mixed Integer Linear Programming):** Pemodelan matematis eksak menggunakan *solver* **Gurobi** untuk hasil yang paling optimal.
- **Fragile-Aware Constraints:** Sistem secara ketat mencegah barang rapuh ditimpa oleh barang lain, dan mencegah barang rapuh diletakkan di bawah barang non-rapuh.
- **Interactive 3D Visualization:** Menampilkan hasil penataan barang di dalam kontainer secara 3D menggunakan **Plotly**.
- **Database Integration:** Menyimpan riwayat hasil optimasi ke dalam database **MongoDB**.
- **Automated Reporting:** Fitur ekspor hasil komputasi, visualisasi 3D dari berbagai sudut (depan, belakang, atas, sisi), dan rincian koordinat barang ke dalam format PDF.

## 🛠️ Teknologi yang Digunakan
- **Frontend/Framework:** Streamlit
- **Data Manipulation:** Pandas, NumPy
- **Optimization Solver:** Gurobipy (Gurobi Optimizer)
- **Visualization:** Plotly, Kaleido (untuk ekspor gambar statis)
- **Database:** PyMongo (MongoDB)
- **Reporting:** FPDF

## 💻 Cara Menjalankan Secara Lokal (Local Deployment)

1. **Clone repository ini:**
   ```bash
   git clone [https://github.com/username-anda/nama-repository.git](https://github.com/username-anda/nama-repository.git)
   cd nama-repository
