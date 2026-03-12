from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3, os

app = Flask(__name__)
app.secret_key = "inventory_secret_123"
DB = "inventory.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER DEFAULT 0,
            unit_price REAL DEFAULT 0.0,
            supplier TEXT,
            location TEXT,
            low_stock_threshold INTEGER DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0:
        sample = [
            ("Wireless Mouse",    "WM-001", "Electronics",  45, 29.99, "TechSupply Co",   "Aisle A1", 10),
            ("USB-C Cable 1m",    "UC-002", "Electronics", 120,  9.99, "CablePro Ltd",    "Aisle A2",  20),
            ("Office Chair",      "OC-003", "Furniture",     8, 199.99,"FurniWorld",       "Warehouse B", 5),
            ("Notebook A4",       "NB-004", "Stationery",   60,  3.49, "PaperPlus",       "Aisle C1", 15),
            ("HDMI Cable 2m",     "HC-005", "Electronics",   7, 14.99, "CablePro Ltd",    "Aisle A2", 10),
            ("Standing Desk",     "SD-006", "Furniture",     3, 349.99,"FurniWorld",       "Warehouse B",  2),
            ("Ballpoint Pens x10","BP-007", "Stationery",   90,  5.99, "PaperPlus",       "Aisle C2", 20),
            ("Webcam HD 1080p",   "WC-008", "Electronics",  15, 59.99, "TechSupply Co",   "Aisle A1",  8),
        ]
        conn.executemany("""
            INSERT INTO products (name, sku, category, quantity, unit_price, supplier, location, low_stock_threshold)
            VALUES (?,?,?,?,?,?,?,?)
        """, sample)
    conn.commit()
    conn.close()

# ── Helpers ─────────────────────────────────────

def log_movement(product_id, movement_type, qty, note=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO stock_movements (product_id, type, quantity, note) VALUES (?,?,?,?)",
        (product_id, movement_type, qty, note)
    )
    conn.commit()
    conn.close()

# ── Routes ──────────────────────────────────────

@app.route("/")
def index():
    search   = request.args.get("q", "")
    category = request.args.get("category", "")
    stock    = request.args.get("stock", "")   # "low" filter

    conn = get_db()
    query  = "SELECT * FROM products WHERE 1=1"
    params = []

    if search:
        query += " AND (name LIKE ? OR sku LIKE ? OR supplier LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if category:
        query += " AND category = ?"
        params.append(category)
    if stock == "low":
        query += " AND quantity <= low_stock_threshold"

    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()

    # Stats
    total_products  = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_value     = conn.execute("SELECT SUM(quantity * unit_price) FROM products").fetchone()[0] or 0
    low_stock_count = conn.execute("SELECT COUNT(*) FROM products WHERE quantity <= low_stock_threshold").fetchone()[0]
    out_of_stock    = conn.execute("SELECT COUNT(*) FROM products WHERE quantity = 0").fetchone()[0]
    categories      = conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()

    conn.close()
    return render_template("index.html",
        products=rows, search=search,
        selected_category=category, stock_filter=stock,
        total_products=total_products, total_value=total_value,
        low_stock_count=low_stock_count, out_of_stock=out_of_stock,
        categories=categories
    )

@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        name      = request.form["name"].strip()
        sku       = request.form["sku"].strip().upper()
        category  = request.form["category"].strip()
        quantity  = int(request.form.get("quantity", 0))
        price     = float(request.form.get("unit_price", 0))
        supplier  = request.form.get("supplier", "").strip()
        location  = request.form.get("location", "").strip()
        threshold = int(request.form.get("low_stock_threshold", 10))

        if not name or not sku or not category:
            flash("Name, SKU and Category are required.", "error")
            return redirect(url_for("add"))

        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO products (name, sku, category, quantity, unit_price, supplier, location, low_stock_threshold)
                VALUES (?,?,?,?,?,?,?,?)
            """, (name, sku, category, quantity, price, supplier, location, threshold))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            conn.close()
            if quantity > 0:
                log_movement(pid, "IN", quantity, "Initial stock")
            flash(f'Product "{name}" added successfully!', "success")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            flash(f'SKU "{sku}" already exists.', "error")
            return redirect(url_for("add"))

    return render_template("form.html", product=None, action="Add")

@app.route("/edit/<int:pid>", methods=["GET", "POST"])
def edit(pid):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not product:
        conn.close()
        flash("Product not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        name      = request.form["name"].strip()
        sku       = request.form["sku"].strip().upper()
        category  = request.form["category"].strip()
        quantity  = int(request.form.get("quantity", 0))
        price     = float(request.form.get("unit_price", 0))
        supplier  = request.form.get("supplier", "").strip()
        location  = request.form.get("location", "").strip()
        threshold = int(request.form.get("low_stock_threshold", 10))

        old_qty = product["quantity"]
        conn.execute("""
            UPDATE products SET name=?, sku=?, category=?, quantity=?,
            unit_price=?, supplier=?, location=?, low_stock_threshold=?,
            updated_at=CURRENT_TIMESTAMP WHERE id=?
        """, (name, sku, category, quantity, price, supplier, location, threshold, pid))
        conn.commit()
        conn.close()

        # Log stock change
        diff = quantity - old_qty
        if diff > 0:
            log_movement(pid, "IN",  diff,  "Manual adjustment")
        elif diff < 0:
            log_movement(pid, "OUT", abs(diff), "Manual adjustment")

        flash(f'Product "{name}" updated.', "success")
        return redirect(url_for("index"))

    conn.close()
    return render_template("form.html", product=product, action="Edit")

@app.route("/delete/<int:pid>", methods=["POST"])
def delete(pid):
    conn = get_db()
    product = conn.execute("SELECT name FROM products WHERE id=?", (pid,)).fetchone()
    if product:
        conn.execute("DELETE FROM stock_movements WHERE product_id=?", (pid,))
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
        flash(f'Product "{product["name"]}" deleted.', "success")
    conn.close()
    return redirect(url_for("index"))

@app.route("/restock/<int:pid>", methods=["POST"])
def restock(pid):
    qty  = int(request.form.get("qty", 0))
    note = request.form.get("note", "Restock").strip()
    if qty <= 0:
        flash("Quantity must be greater than 0.", "error")
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute("""
        UPDATE products SET quantity = quantity + ?, updated_at=CURRENT_TIMESTAMP WHERE id=?
    """, (qty, pid))
    conn.commit()
    conn.close()
    log_movement(pid, "IN", qty, note)
    flash(f"Added {qty} units to stock.", "success")
    return redirect(url_for("index"))

@app.route("/sell/<int:pid>", methods=["POST"])
def sell(pid):
    qty  = int(request.form.get("qty", 0))
    note = request.form.get("note", "Sale").strip()
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not product:
        conn.close()
        flash("Product not found.", "error")
        return redirect(url_for("index"))
    if qty <= 0 or qty > product["quantity"]:
        conn.close()
        flash("Invalid quantity.", "error")
        return redirect(url_for("index"))
    conn.execute("""
        UPDATE products SET quantity = quantity - ?, updated_at=CURRENT_TIMESTAMP WHERE id=?
    """, (qty, pid))
    conn.commit()
    conn.close()
    log_movement(pid, "OUT", qty, note)
    flash(f"Sold {qty} units of {product['name']}.", "success")
    return redirect(url_for("index"))

@app.route("/movements/<int:pid>")
def movements(pid):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    logs    = conn.execute("""
        SELECT * FROM stock_movements WHERE product_id=? ORDER BY created_at DESC
    """, (pid,)).fetchall()
    conn.close()
    return render_template("movements.html", product=product, logs=logs)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
