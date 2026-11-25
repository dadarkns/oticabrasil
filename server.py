"""Otica web app: stdlib HTTP server with SQLite development and PostgreSQL support."""
from __future__ import annotations

import base64, hashlib, hmac, json, os, secrets, sqlite3, time, traceback
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("OTICA_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "local-dev-secret-change-before-deploy").encode()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
SESSIONS: dict[str, tuple[int, float]] = {}


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, saved: str) -> bool:
    try:
        raw = base64.b64decode(saved)
        return hmac.compare_digest(raw[16:], hashlib.pbkdf2_hmac("sha256", password.encode(), raw[:16], 240_000))
    except Exception:
        return False


def connect():
    if DATABASE_URL:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL requer psycopg. Instale requirements.txt.") from exc
        con = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        con.execute("SET TIME ZONE 'UTC'")
        return con, True
    con = sqlite3.connect(DATA_DIR / "otica.db", timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con, False


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'sales', password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, legacy_id TEXT, name TEXT NOT NULL, document TEXT, phone TEXT, email TEXT, address TEXT, city TEXT, notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, legacy_id TEXT, name TEXT NOT NULL, contact TEXT, document TEXT, phone TEXT, email TEXT, address TEXT, city TEXT, state TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sellers(id INTEGER PRIMARY KEY, legacy_id TEXT UNIQUE, name TEXT NOT NULL, document TEXT, phone TEXT, address TEXT, city TEXT, state TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS doctors(id INTEGER PRIMARY KEY, legacy_id TEXT, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY, legacy_id TEXT, name TEXT NOT NULL, phone TEXT, address TEXT, city TEXT, discount_percent NUMERIC NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS payment_methods(id INTEGER PRIMARY KEY, legacy_id TEXT, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, legacy_id TEXT UNIQUE, sku TEXT, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Armações', brand TEXT, model TEXT, unit TEXT DEFAULT 'UN', color TEXT, size TEXT, lens_type TEXT, stock NUMERIC NOT NULL DEFAULT 0, minimum_stock NUMERIC NOT NULL DEFAULT 0, cost NUMERIC NOT NULL DEFAULT 0, price NUMERIC NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, customer_id INTEGER REFERENCES customers(id), store_id INTEGER REFERENCES stores(id), seller_id INTEGER REFERENCES sellers(id), seller_name TEXT, status TEXT NOT NULL DEFAULT 'confirmed', subtotal NUMERIC NOT NULL, discount NUMERIC NOT NULL DEFAULT 0, total NUMERIC NOT NULL, payment_method TEXT, notes TEXT, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sale_items(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id), product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL, quantity NUMERIC NOT NULL, unit_price NUMERIC NOT NULL, discount NUMERIC NOT NULL DEFAULT 0, total NUMERIC NOT NULL);
CREATE TABLE IF NOT EXISTS prescriptions(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id), doctor_id INTEGER REFERENCES doctors(id), doctor_name TEXT, lens_description TEXT, addition TEXT, right_sphere TEXT, right_cylinder TEXT, right_axis TEXT, right_dnp TEXT, right_height TEXT, left_sphere TEXT, left_cylinder TEXT, left_axis TEXT, left_dnp TEXT, left_height TEXT, near_right_sphere TEXT, near_left_sphere TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS lab_orders(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id), status TEXT NOT NULL DEFAULT 'Pendente', estimated_date TEXT, received_at TEXT, started_at TEXT, ready_at TEXT, delivered_at TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS receivables(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id), installment INTEGER NOT NULL, due_date TEXT NOT NULL, amount NUMERIC NOT NULL, paid NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'Aberto', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, supplier_id INTEGER REFERENCES suppliers(id), description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'confirmed', total NUMERIC NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id), product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL, quantity NUMERIC NOT NULL, unit_cost NUMERIC NOT NULL, total NUMERIC NOT NULL);
CREATE TABLE IF NOT EXISTS payables(id INTEGER PRIMARY KEY, purchase_id INTEGER REFERENCES purchases(id), supplier_id INTEGER REFERENCES suppliers(id), description TEXT NOT NULL, due_date TEXT NOT NULL, amount NUMERIC NOT NULL, paid NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'Aberto', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cash_movements(id INTEGER PRIMARY KEY, direction TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL, amount NUMERIC NOT NULL, reference_type TEXT, reference_id INTEGER, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), direction TEXT NOT NULL, quantity NUMERIC NOT NULL, reason TEXT NOT NULL, reference_type TEXT, reference_id INTEGER, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT, detail TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS legacy_sources(id INTEGER PRIMARY KEY, table_name TEXT NOT NULL UNIQUE, file_name TEXT NOT NULL, dbf_version INTEGER NOT NULL, record_count INTEGER NOT NULL, deleted_count INTEGER NOT NULL, fields TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS legacy_rows(id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES legacy_sources(id) ON DELETE CASCADE, row_number INTEGER NOT NULL, deleted INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(source_id,row_number));
CREATE INDEX IF NOT EXISTS ix_products_name ON products(name); CREATE INDEX IF NOT EXISTS ix_sales_created ON sales(created_at); CREATE INDEX IF NOT EXISTS ix_receivables_due ON receivables(due_date,status); CREATE INDEX IF NOT EXISTS ix_lab_status ON lab_orders(status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_customers_legacy ON customers(legacy_id); CREATE UNIQUE INDEX IF NOT EXISTS ux_suppliers_legacy ON suppliers(legacy_id); CREATE UNIQUE INDEX IF NOT EXISTS ux_doctors_legacy ON doctors(legacy_id); CREATE UNIQUE INDEX IF NOT EXISTS ux_stores_legacy ON stores(legacy_id); CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_methods_legacy ON payment_methods(legacy_id);
"""


def init_db():
    con, pg = connect()
    if pg:
        con.execute((ROOT / "migrations" / "001_initial_postgres.sql").read_text(encoding="utf-8"))
        con.commit()
    else:
        con.executescript(SCHEMA_SQLITE)
        if "seller_id" not in {r[1] for r in con.execute("PRAGMA table_info(sales)").fetchall()}:
            con.execute("ALTER TABLE sales ADD COLUMN seller_id INTEGER REFERENCES sellers(id)")
        con.commit()
    row = con.execute("SELECT id FROM users WHERE username=?" if not pg else "SELECT id FROM users WHERE username=%s", ("admin",)).fetchone()
    if not row:
        if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 10:
            con.close()
            raise RuntimeError("Defina ADMIN_PASSWORD com pelo menos 10 caracteres antes da primeira inicialização.")
        con.execute("INSERT INTO users(username,full_name,role,password_hash,active) VALUES(?,?,?,?,TRUE)" if not pg else "INSERT INTO users(username,full_name,role,password_hash,active) VALUES(%s,%s,%s,%s,TRUE)", ("admin", "Administrador", "admin", password_hash(ADMIN_PASSWORD)))
        con.commit()
    for table, vals in [("stores", ("Matriz", "", "", "")), ("payment_methods", ("Dinheiro",)), ("payment_methods", ("Cartão",)), ("payment_methods", ("Pix",))]:
        if table == "stores":
            store_count=con.execute("SELECT COUNT(*) AS n FROM stores").fetchone()
            c=store_count["n"] if pg else store_count[0]
            if not c: con.execute("INSERT INTO stores(name,phone,address,city) VALUES(?,?,?,?)" if not pg else "INSERT INTO stores(name,phone,address,city) VALUES(%s,%s,%s,%s)", vals)
        else:
            q = "SELECT id FROM payment_methods WHERE name=?" if not pg else "SELECT id FROM payment_methods WHERE name=%s"
            if not con.execute(q, vals).fetchone(): con.execute("INSERT INTO payment_methods(name) VALUES(?)" if not pg else "INSERT INTO payment_methods(name) VALUES(%s)", vals)
    con.commit(); con.close()


def query(sql: str, params=(), one=False):
    con, pg = connect()
    try:
        if pg: sql = sql.replace("?", "%s")
        cur = con.execute(sql, params)
        if cur.description:
            rows = cur.fetchall()
            result = [dict(r) for r in rows]
            return result[0] if one and result else (None if one else result)
        con.commit(); return {"rowcount": cur.rowcount}
    finally: con.close()


def scalar(sql: str, params=()):
    r = query(sql, params, one=True)
    return next(iter(r.values())) if r else 0


def as_money(value, default=0):
    try:
        d = Decimal(str(value or default))
        if not d.is_finite() or d < 0: raise ValueError()
        return round(float(d), 2)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Valor monetário inválido")


def audit(uid, action, entity, entity_id=None, detail=None):
    query("INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?)", (uid, action, entity, str(entity_id) if entity_id is not None else None, json.dumps(detail, ensure_ascii=False) if detail is not None else None))


def row_insert(table, fields: dict, pg=False):
    cols = list(fields)
    marks = ",".join(["%s" if pg else "?"] * len(cols))
    sql = f"INSERT INTO {table}({','.join(cols)}) VALUES({marks})"
    if pg: sql += " RETURNING id"
    con, _ = connect()
    try:
        cur = con.execute(sql, tuple(fields[c] for c in cols))
        ident = cur.fetchone()["id"] if pg else cur.lastrowid
        con.commit(); return ident
    finally: con.close()


def to_json(value):
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, (datetime, date)): return value.isoformat()
    return str(value)


class Handler(BaseHTTPRequestHandler):
    server_version = "OticaWeb/0.1"
    def log_message(self, fmt, *args): print("%s - %s" % (self.address_string(), fmt % args))
    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False, default=to_json).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"); self.end_headers(); self.wfile.write(raw)
    def body(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n > 1_000_000: raise ValueError("Requisição muito grande")
        return json.loads(self.rfile.read(n) or b"{}")
    def session(self):
        c = SimpleCookie(); c.load(self.headers.get("Cookie", "")); token = c.get("otica_session").value if c.get("otica_session") else ""
        item = SESSIONS.get(token)
        if item and item[1] > time.time(): return token, item[0]
        if token: SESSIONS.pop(token, None)
        return None, None
    def user(self):
        _, uid = self.session()
        return query("SELECT id,username,full_name,role FROM users WHERE id=? AND active=TRUE" if not DATABASE_URL else "SELECT id,username,full_name,role FROM users WHERE id=%s AND active=TRUE", (uid,), True) if uid else None
    def require(self, roles=None):
        u = self.user()
        if not u: self.send_json({"error":"Sessão necessária"},401); return None
        if roles and u["role"] not in roles: self.send_json({"error":"Sem permissão para esta operação"},403); return None
        return u
    def do_GET(self):
        p = urlparse(self.path); path=p.path; qs=parse_qs(p.query)
        if path == "/" or path.startswith("/static/"):
            file = ROOT / ("static/index.html" if path=="/" else path.removeprefix("/"))
            if not file.is_file() or ROOT not in file.resolve().parents: self.send_error(404); return
            data=file.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8" if file.suffix==".html" else "text/"+("css" if file.suffix==".css" else "javascript")+"; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path == "/api/health": self.send_json({"ok":True,"database":"postgresql" if DATABASE_URL else "sqlite"}); return
        u=self.require()
        if not u:return
        if path=="/api/me": self.send_json(u); return
        if path in ("/api/legacy/sources","/api/legacy/rows"):
            if u["role"] not in ("admin","manager"):
                self.send_json({"error":"Somente gerente ou administrador pode consultar o arquivo legado"},403); return
            if path=="/api/legacy/sources":
                self.send_json(query("SELECT id,table_name,file_name,record_count,deleted_count,record_count-deleted_count active_count,imported_at FROM legacy_sources ORDER BY file_name")); return
            source=qs.get("source",[""])[0]
            if not source: self.send_json({"error":"Informe a fonte legada"},400); return
            src=query("SELECT id,table_name,file_name FROM legacy_sources WHERE table_name=? OR CAST(id AS TEXT)=?",(source,source),True)
            if not src: self.send_json({"error":"Fonte legada não encontrada"},404); return
            try: limit=max(1,min(100,int(qs.get("limit",[50])[0]))); offset=max(0,int(qs.get("offset",[0])[0]))
            except ValueError: self.send_json({"error":"Paginação inválida"},400); return
            terms=["source_id=?","deleted=0"]; params=[src["id"]]
            if qs.get("q") and qs["q"][0].strip(): terms.append("LOWER(CAST(payload AS TEXT)) LIKE LOWER(?)"); params.append("%"+qs["q"][0].strip()+"%")
            where=" AND ".join(terms)
            total=scalar(f"SELECT COUNT(*) FROM legacy_rows WHERE {where}",params)
            rows=query(f"SELECT row_number,payload FROM legacy_rows WHERE {where} ORDER BY row_number LIMIT {limit} OFFSET {offset}",params)
            self.send_json({"source":src,"total":total,"limit":limit,"offset":offset,"rows":rows}); return
        if path=="/api/dashboard":
            today_sql="CAST(created_at AS DATE)=CURRENT_DATE" if DATABASE_URL else "date(created_at)=date('now')"
            revenue_month_sql="substr(CAST(created_at AS TEXT),1,7)=substr(CAST(CURRENT_TIMESTAMP AS TEXT),1,7)"
            self.send_json({"products":scalar("SELECT COUNT(*) FROM products WHERE active=TRUE"),"customers":scalar("SELECT COUNT(*) FROM customers"),"low_stock":scalar("SELECT COUNT(*) FROM products WHERE active=TRUE AND stock<=minimum_stock"),"sales_today":scalar(f"SELECT COUNT(*) FROM sales WHERE {today_sql} AND status='confirmed'"),"revenue_month":scalar(f"SELECT COALESCE(SUM(total),0) FROM sales WHERE status='confirmed' AND {revenue_month_sql}"),"receivables_open":scalar("SELECT COALESCE(SUM(amount-paid),0) FROM receivables WHERE status NOT IN ('Pago','Cancelado')"),"lab_pending":scalar("SELECT COUNT(*) FROM lab_orders WHERE status NOT IN ('Pronto','Entregue','Cancelado')"),"recent_sales":query("SELECT s.id,s.number,s.total,s.status,s.created_at,c.name customer FROM sales s LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC LIMIT 7")}); return
        routes={"/api/products":("products","id,name,sku,category,brand,stock,minimum_stock,price,cost,active"),"/api/customers":("customers","id,name,document,phone,email,city,created_at"),"/api/suppliers":("suppliers","id,name,contact,phone,email,city"),"/api/sellers":("sellers","id,legacy_id,name,document,phone,address,city,state,active"),"/api/doctors":("doctors","id,name"),"/api/sales":("sales","id,number,total,status,payment_method,created_at"),"/api/receivables":("receivables","id,sale_id,installment,due_date,amount,paid,status"),"/api/payables":("payables","id,supplier_id,description,due_date,amount,paid,status"),"/api/lab-orders":("lab_orders","id,sale_id,status,estimated_date,received_at,started_at,ready_at,delivered_at,notes"),"/api/stores":("stores","id,name,phone,city"),"/api/payment-methods":("payment_methods","id,name,active")}
        if path in routes:
            table, cols=routes[path]; terms=[]; params=[]
            if qs.get("q") and table in ("products","customers","suppliers","doctors"):
                field="name"; terms.append(f"{field} LIKE ?"); params.append("%"+qs["q"][0]+"%")
            if table=="lab_orders":
                sql="SELECT l.*,s.number sale_number,c.name customer FROM lab_orders l JOIN sales s ON s.id=l.sale_id LEFT JOIN customers c ON c.id=s.customer_id ORDER BY l.id DESC LIMIT 300"
            elif table=="receivables": sql="SELECT r.*,s.number sale_number,c.name customer FROM receivables r JOIN sales s ON s.id=r.sale_id LEFT JOIN customers c ON c.id=s.customer_id ORDER BY r.due_date LIMIT 500"
            elif table=="payables": sql="SELECT p.*,v.name supplier FROM payables p LEFT JOIN suppliers v ON v.id=p.supplier_id ORDER BY p.due_date LIMIT 500"
            elif table=="sales": sql="SELECT s.*,c.name customer FROM sales s LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC LIMIT 500"
            else: sql=f"SELECT {cols} FROM {table}"+(" WHERE "+" AND ".join(terms) if terms else "")+" ORDER BY id DESC LIMIT 500"
            self.send_json(query(sql,params)); return
        if path=="/api/reports/sales":
            start=qs.get("from",[date.today().replace(day=1).isoformat()])[0]; end=qs.get("to",[date.today().isoformat()])[0]
            date_filter="CAST(s.created_at AS DATE)>=%s::date AND CAST(s.created_at AS DATE)<=%s::date" if DATABASE_URL else "date(s.created_at)>=date(?) AND date(s.created_at)<=date(?)"
            total_filter="CAST(created_at AS DATE)>=%s::date AND CAST(created_at AS DATE)<=%s::date" if DATABASE_URL else "date(created_at)>=date(?) AND date(created_at)<=date(?)"
            self.send_json({"rows":query(f"SELECT s.number,s.created_at,c.name customer,s.total,s.status FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE {date_filter} ORDER BY s.created_at DESC",(start,end)),"total":scalar(f"SELECT COALESCE(SUM(total),0) FROM sales WHERE status='confirmed' AND {total_filter}",(start,end))}); return
        if path=="/api/cash-movements":
            self.send_json(query("SELECT id,direction,category,description,amount,created_at FROM cash_movements ORDER BY id DESC LIMIT 500")); return
        if path=="/api/purchases":
            self.send_json(query("SELECT p.id,p.description,p.total,p.status,p.created_at,s.name supplier FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id ORDER BY p.id DESC LIMIT 300")); return
        if path=="/api/users":
            if u["role"]!="admin": self.send_json({"error":"Sem permissão"},403); return
            self.send_json(query("SELECT id,username,full_name,role,active,created_at FROM users ORDER BY id")); return
        self.send_json({"error":"Não encontrado"},404)
    def do_POST(self):
        path=urlparse(self.path).path
        try: data=self.body()
        except Exception as e: self.send_json({"error":str(e)},400); return
        if path=="/api/login":
            r=query("SELECT id,username,full_name,role,password_hash FROM users WHERE username=? AND active=TRUE" if not DATABASE_URL else "SELECT id,username,full_name,role,password_hash FROM users WHERE username=%s AND active=TRUE",(str(data.get("username","")),),True)
            if not r or not verify_password(str(data.get("password","")),r["password_hash"]): self.send_json({"error":"Usuário ou senha inválidos"},401); return
            token=secrets.token_urlsafe(32); SESSIONS[token]=(r["id"],time.time()+8*60*60); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Set-Cookie",f"otica_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"+("; Secure" if os.environ.get("COOKIE_SECURE")=="1" else "")); self.end_headers(); self.wfile.write(json.dumps({k:r[k] for k in ("id","username","full_name","role")}).encode()); return
        if path=="/api/logout":
            token,_=self.session()
            if token: SESSIONS.pop(token,None)
            self.send_response(204); self.send_header("Set-Cookie","otica_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"); self.end_headers(); return
        u=self.require()
        if not u:return
        try:
            if path in ("/api/products","/api/customers","/api/suppliers","/api/doctors","/api/stores","/api/payment-methods"):
                if path in ("/api/products","/api/suppliers","/api/doctors","/api/stores","/api/payment-methods") and u["role"] not in ("admin","manager"):
                    self.send_json({"error":"Somente gerente ou administrador pode alterar este cadastro"},403); return
                allowed={"/api/products":("products",("sku","name","category","brand","model","unit","color","size","lens_type","stock","minimum_stock","cost","price")),"/api/customers":("customers",("name","document","phone","email","address","city","notes")),"/api/suppliers":("suppliers",("name","contact","document","phone","email","address","city","state")),"/api/doctors":("doctors",("name",)),"/api/stores":("stores",("name","phone","address","city","discount_percent")),"/api/payment-methods":("payment_methods",("name",))}
                table,keys=allowed[path]; fields={k:data.get(k) for k in keys if k in data}
                if not fields.get("name"): raise ValueError("Informe o nome")
                if table=="products":
                    fields["stock"]=as_money(fields.get("stock")); fields["minimum_stock"]=as_money(fields.get("minimum_stock")); fields["cost"]=as_money(fields.get("cost")); fields["price"]=as_money(fields.get("price")); fields.setdefault("category","Armações")
                if table=="customers" and fields.get("document"):
                    if query("SELECT id FROM customers WHERE document=?" if not DATABASE_URL else "SELECT id FROM customers WHERE document=%s",(fields["document"],),True): raise ValueError("Documento já cadastrado")
                ident=row_insert(table,fields,DATABASE_URL!=""); audit(u["id"],"criar",table,ident,fields); self.send_json({"id":ident},201); return
            if path=="/api/sales": self.create_sale(data,u); return
            if path.startswith("/api/sales/") and path.endswith("/cancel"):
                if u["role"] not in ("admin","manager"): self.send_json({"error":"Somente gerente ou administrador pode cancelar vendas"},403); return
                self.cancel_sale(path,u,data); return
            if path=="/api/purchases":
                if u["role"] not in ("admin","manager"): self.send_json({"error":"Somente gerente ou administrador pode registrar compras"},403); return
                self.create_purchase(data,u); return
            if path=="/api/stock-adjustments":
                if u["role"] not in ("admin","manager"): self.send_json({"error":"Somente gerente ou administrador pode ajustar o estoque"},403); return
                self.stock_adjustment(data,u); return
            if path=="/api/cash-movements":
                if u["role"] not in ("admin","manager","cashier"): self.send_json({"error":"Sem permissão para movimentar o caixa"},403); return
                self.create_cash_movement(data,u); return
            if path.startswith("/api/receivables/") or path.startswith("/api/payables/"):
                if u["role"] not in ("admin","manager","cashier"): self.send_json({"error":"Sem permissão para registrar baixas"},403); return
                self.record_payment(path,data,u); return
            if path.startswith("/api/lab-orders/"):
                if u["role"] not in ("admin","manager"): self.send_json({"error":"Somente gerente ou administrador pode atualizar laboratório"},403); return
                self.update_lab(path,data,u); return
            if path=="/api/users":
                if u["role"]!="admin": self.send_json({"error":"Sem permissão"},403); return
                if len(str(data.get("password","")))<10: raise ValueError("A senha deve ter ao menos 10 caracteres")
                ident=row_insert("users",{"username":data["username"],"full_name":data["full_name"],"role":data["role"],"password_hash":password_hash(data["password"])},DATABASE_URL!=""); audit(u["id"],"criar","user",ident); self.send_json({"id":ident},201); return
            self.send_json({"error":"Não encontrado"},404)
        except Exception as e:
            self.send_json({"error":str(e)},400)

    def create_sale(self,d,u):
        items=d.get("items") or []
        if not items: raise ValueError("Adicione ao menos um produto")
        discount=as_money(d.get("discount",0)); subtotal=0
        for it in items:
            product=query("SELECT id,name,stock,price FROM products WHERE id=? AND active=TRUE" if not DATABASE_URL else "SELECT id,name,stock,price FROM products WHERE id=%s AND active=TRUE",(int(it["product_id"]),),True)
            if not product: raise ValueError("Produto não encontrado")
            qty=as_money(it.get("quantity",1)); price=as_money(it.get("unit_price",product["price"])); disc=as_money(it.get("discount",0)); total=round(qty*price-disc,2)
            if qty<=0 or total<0: raise ValueError("Quantidade ou desconto inválido")
            if float(product["stock"])<qty: raise ValueError(f"Estoque insuficiente: {product['name']}")
            it.update({"_product":product,"_qty":qty,"_price":price,"_discount":disc,"_total":total}); subtotal+=qty*price
        total=round(subtotal-discount,2)
        if total<0: raise ValueError("Desconto maior que o subtotal")
        installments=int(d.get("installments",1)); installments=max(1,min(installments,36))
        due=str(d.get("first_due_date") or date.today().isoformat()); payment=str(d.get("payment_method") or "Dinheiro")
        seller_id=int(d["seller_id"]) if d.get("seller_id") else None
        seller=query("SELECT id,name FROM sellers WHERE id=? AND active=TRUE" if not DATABASE_URL else "SELECT id,name FROM sellers WHERE id=%s AND active=TRUE",(seller_id,),True) if seller_id else None
        if seller_id and not seller: raise ValueError("Vendedor não encontrado ou inativo")
        seller_name=seller["name"] if seller else (d.get("seller_name") or u["full_name"])
        con,pg=connect(); q="%s" if pg else "?"
        try:
            cur=con.cursor(); cur.execute(f"INSERT INTO sales(number,customer_id,store_id,seller_id,seller_name,status,subtotal,discount,total,payment_method,notes,created_by) VALUES({','.join([q]*12)}) RETURNING id" if pg else "INSERT INTO sales(number,customer_id,store_id,seller_id,seller_name,status,subtotal,discount,total,payment_method,notes,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(f"V{datetime.now():%y%m%d%H%M%S}{secrets.randbelow(90)+10}",d.get("customer_id") or None,d.get("store_id") or 1,seller_id,seller_name,"confirmed",subtotal,discount,total,payment,d.get("notes"),u["id"]))
            sale_id=cur.fetchone()["id"] if pg else cur.lastrowid
            for it in items:
                p=it["_product"]; cur.execute(f"INSERT INTO sale_items(sale_id,product_id,product_name,quantity,unit_price,discount,total) VALUES({','.join([q]*7)})",(sale_id,p["id"],p["name"],it["_qty"],it["_price"],it["_discount"],it["_total"]))
                cur.execute(f"UPDATE products SET stock=stock-{q},updated_at=CURRENT_TIMESTAMP WHERE id={q} AND stock>={q}",(it["_qty"],p["id"],it["_qty"]))
                if cur.rowcount!=1: raise ValueError(f"Estoque alterado por outro operador: {p['name']}. Atualize a tela e tente novamente.")
                cur.execute(f"INSERT INTO stock_movements(product_id,direction,quantity,reason,reference_type,reference_id,created_by) VALUES({','.join([q]*7)})",(p["id"],"Saída",it["_qty"],"Venda", "sale",sale_id,u["id"]))
            if d.get("prescription"):
                x=d["prescription"]; fields=["doctor_id","doctor_name","lens_description","addition","right_sphere","right_cylinder","right_axis","right_dnp","right_height","left_sphere","left_cylinder","left_axis","left_dnp","left_height","near_right_sphere","near_left_sphere","notes"]
                vals=[sale_id]+[x.get(k) for k in fields]; cur.execute(f"INSERT INTO prescriptions(sale_id,{','.join(fields)}) VALUES({','.join([q]*len(vals))})",tuple(vals))
                cur.execute(f"INSERT INTO lab_orders(sale_id,status,estimated_date,notes) VALUES({q},{q},{q},{q})",(sale_id,"Pendente",x.get("estimated_date"),x.get("notes")))
            paid_now=as_money(d.get("paid_now",0))
            if paid_now>total: raise ValueError("O valor recebido não pode superar o total da venda")
            first_due=date.fromisoformat(due)
            for n in range(installments):
                amount=round(total/installments,2) if n<installments-1 else round(total-round(total/installments,2)*(installments-1),2)
                paid=min(paid_now,amount); paid_now-=paid
                month_index=first_due.month-1+n; year=first_due.year+month_index//12; month=month_index%12+1
                import calendar
                due_date=first_due.replace(year=year,month=month,day=min(first_due.day,calendar.monthrange(year,month)[1]))
                cur.execute(f"INSERT INTO receivables(sale_id,installment,due_date,amount,paid,status) VALUES({','.join([q]*6)})",(sale_id,n+1,due_date.isoformat(),amount,paid,"Pago" if paid>=amount else ("Parcial" if paid else "Aberto")))
            if d.get("paid_now",0): cur.execute(f"INSERT INTO cash_movements(direction,category,description,amount,reference_type,reference_id,created_by) VALUES({','.join([q]*7)})",("Entrada","Venda",f"Venda {sale_id}",as_money(d.get("paid_now")),"sale",sale_id,u["id"]))
            cur.execute(f"INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES({','.join([q]*5)})",(u["id"],"criar","sale",str(sale_id),json.dumps({"total":total},ensure_ascii=False)))
            con.commit(); self.send_json({"id":sale_id,"total":total},201)
        except: con.rollback(); raise
        finally: con.close()

    def cancel_sale(self,path,u,data):
        sale_id=int(path.strip("/").split("/")[-2]); con,pg=connect(); q="%s" if pg else "?"
        try:
            cur=con.cursor()
            if not pg: cur.execute("BEGIN IMMEDIATE")
            sale=cur.execute(f"SELECT id,status FROM sales WHERE id={q}"+(" FOR UPDATE" if pg else ""),(sale_id,)).fetchone()
            if not sale: raise ValueError("Venda não encontrada")
            if sale["status"]!="confirmed": raise ValueError("Venda já cancelada ou indisponível")
            paid=cur.execute(f"SELECT COALESCE(SUM(paid),0) AS paid FROM receivables WHERE sale_id={q}",(sale_id,)).fetchone()["paid"]
            if float(paid)>0 and not data.get("refund_confirmed"):
                con.rollback(); self.send_json({"error":"A venda tem valores recebidos. Registre a devolução fora do sistema e confirme o estorno para concluir.","requires_refund":True,"received_total":float(paid)},409); return
            if float(paid)>0:
                cur.execute(f"INSERT INTO cash_movements(direction,category,description,amount,reference_type,reference_id,created_by) VALUES({','.join([q]*7)})",("Saída","Estorno de venda",f"Devolução da venda {sale_id}",float(paid),"sale",sale_id,u["id"]))
            items=cur.execute(f"SELECT product_id,product_name,quantity FROM sale_items WHERE sale_id={q}",(sale_id,)).fetchall()
            for item in items:
                cur.execute(f"UPDATE products SET stock=stock+{q},updated_at=CURRENT_TIMESTAMP WHERE id={q}",(item["quantity"],item["product_id"]))
                cur.execute(f"INSERT INTO stock_movements(product_id,direction,quantity,reason,reference_type,reference_id,created_by) VALUES({','.join([q]*7)})",(item["product_id"],"Entrada",item["quantity"],"Cancelamento de venda","sale",sale_id,u["id"]))
            cur.execute(f"UPDATE sales SET status='cancelled' WHERE id={q}",(sale_id,))
            cur.execute(f"UPDATE receivables SET status='Cancelado' WHERE sale_id={q}",(sale_id,))
            cur.execute(f"UPDATE lab_orders SET status='Cancelado' WHERE sale_id={q}",(sale_id,))
            cur.execute(f"INSERT INTO audit_log(user_id,action,entity,entity_id) VALUES({q},{q},{q},{q})",(u["id"],"cancelar","sale",str(sale_id)))
            con.commit(); self.send_json({"id":sale_id,"status":"cancelled"})
        except: con.rollback(); raise
        finally: con.close()

    def create_purchase(self,d,u):
        items=d.get("items") or []
        if not items: raise ValueError("Adicione ao menos um produto")
        due=str(d.get("due_date") or date.today().isoformat()); supplier=d.get("supplier_id") or None
        con,pg=connect(); q="%s" if pg else "?"
        try:
            cur=con.cursor(); total=0; validated=[]
            for it in items:
                p=cur.execute(f"SELECT id,name FROM products WHERE id={q}",(int(it["product_id"]),)).fetchone()
                if not p: raise ValueError("Produto não encontrado")
                qty=as_money(it.get("quantity",1)); cost=as_money(it.get("unit_cost",0))
                if qty<=0: raise ValueError("Quantidade de compra precisa ser maior que zero")
                line_total=round(qty*cost,2); total+=line_total; validated.append((p,qty,cost,line_total))
            cur.execute(f"INSERT INTO purchases(supplier_id,description,total,created_by) VALUES({q},{q},{q},{q}) RETURNING id" if pg else "INSERT INTO purchases(supplier_id,description,total,created_by) VALUES(?,?,?,?)",(supplier,d.get("description") or "Compra de produtos",round(total,2),u["id"]))
            purchase_id=cur.fetchone()["id"] if pg else cur.lastrowid
            for p,qty,cost,line_total in validated:
                cur.execute(f"UPDATE products SET stock=stock+{q},cost={q},updated_at=CURRENT_TIMESTAMP WHERE id={q}",(qty,cost,p["id"]))
                cur.execute(f"INSERT INTO purchase_items(purchase_id,product_id,product_name,quantity,unit_cost,total) VALUES({','.join([q]*6)})",(purchase_id,p["id"],p["name"],qty,cost,line_total))
                cur.execute(f"INSERT INTO stock_movements(product_id,direction,quantity,reason,reference_type,reference_id,created_by) VALUES({','.join([q]*7)})",(p["id"],"Entrada",qty,"Compra","purchase",purchase_id,u["id"]))
            cur.execute(f"INSERT INTO payables(purchase_id,supplier_id,description,due_date,amount) VALUES({q},{q},{q},{q},{q})",(purchase_id,supplier,d.get("description") or "Compra de produtos",due,round(total,2)))
            cur.execute(f"INSERT INTO audit_log(user_id,action,entity,detail) VALUES({q},{q},{q},{q})",(u["id"],"criar","purchase",json.dumps({"total":total},ensure_ascii=False)))
            con.commit(); self.send_json({"id":purchase_id,"total":round(total,2)},201)
        except: con.rollback(); raise
        finally: con.close()

    def stock_adjustment(self,d,u):
        product_id=int(d.get("product_id")); quantity=as_money(d.get("quantity")); direction=d.get("direction"); reason=str(d.get("reason","")).strip()
        if direction not in ("Entrada","Saída") or quantity<=0 or not reason: raise ValueError("Informe direção, quantidade e motivo do ajuste")
        con,pg=connect(); q="%s" if pg else "?"
        try:
            cur=con.cursor(); p=cur.execute(f"SELECT id,stock FROM products WHERE id={q} FOR UPDATE" if pg else f"SELECT id,stock FROM products WHERE id={q}",(product_id,)).fetchone()
            if not p: raise ValueError("Produto não encontrado")
            new_stock=float(p["stock"])+(quantity if direction=="Entrada" else -quantity)
            if new_stock<0: raise ValueError("O ajuste deixaria o estoque negativo")
            cur.execute(f"UPDATE products SET stock={q},updated_at=CURRENT_TIMESTAMP WHERE id={q}",(new_stock,product_id))
            cur.execute(f"INSERT INTO stock_movements(product_id,direction,quantity,reason,created_by) VALUES({','.join([q]*5)})",(product_id,direction,quantity,reason,u["id"]))
            cur.execute(f"INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES({','.join([q]*5)})",(u["id"],"ajuste","product",str(product_id),json.dumps({"movimento":direction,"quantidade":quantity,"motivo":reason},ensure_ascii=False)))
            con.commit(); self.send_json({"stock":new_stock})
        except: con.rollback(); raise
        finally: con.close()

    def create_cash_movement(self,d,u):
        direction=str(d.get("direction","")); category=str(d.get("category","")).strip(); description=str(d.get("description","")).strip(); amount=as_money(d.get("amount"))
        if direction not in ("Entrada","Saída") or not category or not description or amount<=0: raise ValueError("Informe tipo, categoria, descrição e valor maior que zero")
        con,pg=connect(); q="%s" if pg else "?"
        try:
            cur=con.cursor(); cur.execute(f"INSERT INTO cash_movements(direction,category,description,amount,created_by) VALUES({','.join([q]*5)}) RETURNING id" if pg else "INSERT INTO cash_movements(direction,category,description,amount,created_by) VALUES(?,?,?,?,?)",(direction,category,description,amount,u["id"]))
            ident=cur.fetchone()["id"] if pg else cur.lastrowid
            cur.execute(f"INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES({','.join([q]*5)})",(u["id"],"registrar","cash_movement",str(ident),json.dumps({"direcao":direction,"categoria":category,"valor":amount},ensure_ascii=False)))
            con.commit(); self.send_json({"id":ident},201)
        except: con.rollback(); raise
        finally: con.close()

    def record_payment(self,path,d,u):
        kind="receivables" if path.startswith("/api/receivables/") else "payables"; parts=path.strip("/").split("/"); ident=int(parts[-2] if parts[-1]=="payment" else parts[-1]); amount=as_money(d.get("amount")); q="%s" if DATABASE_URL else "?"
        con,pg=connect()
        try:
            cur=con.cursor(); row=cur.execute(f"SELECT amount,paid,status FROM {kind} WHERE id={q}",(ident,)).fetchone()
            if not row: raise ValueError("Parcela não encontrada")
            balance=float(row["amount"])-float(row["paid"])
            if amount<=0 or amount>balance: raise ValueError("Valor de baixa maior que o saldo ou inválido")
            new_paid=float(row["paid"])+amount; status="Pago" if new_paid>=float(row["amount"]) else "Parcial"
            cur.execute(f"UPDATE {kind} SET paid={q},status={q} WHERE id={q}",(new_paid,status,ident))
            direction="Entrada" if kind=="receivables" else "Saída"; category="Recebimento" if kind=="receivables" else "Pagamento"
            cur.execute(f"INSERT INTO cash_movements(direction,category,description,amount,reference_type,reference_id,created_by) VALUES({','.join([q]*7)})",(direction,category,f"{category} parcela {ident}",amount,kind,ident,u["id"]))
            cur.execute(f"INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES({','.join([q]*5)})",(u["id"],"baixa",kind,str(ident),json.dumps({"valor":amount})))
            con.commit(); self.send_json({"id":ident,"paid":new_paid,"status":status})
        except: con.rollback(); raise
        finally: con.close()

    def update_lab(self,path,d,u):
        ident=int(path.rsplit("/",1)[1]); allowed={"Pendente","Recebido","Em produção","Pronto","Entregue"}; status=str(d.get("status",""))
        if status not in allowed: raise ValueError("Etapa inválida")
        stamp={"Recebido":"received_at","Em produção":"started_at","Pronto":"ready_at","Entregue":"delivered_at"}.get(status)
        q="%s" if DATABASE_URL else "?"; fields=["status=?" if not DATABASE_URL else "status=%s"]; params=[status]
        if stamp: fields.append(f"{stamp}=CURRENT_TIMESTAMP")
        if "notes" in d: fields.append("notes="+q); params.append(d["notes"])
        params.append(ident); result=query(f"UPDATE lab_orders SET {','.join(fields)} WHERE id={q}",params)
        audit(u["id"],"atualizar","lab_order",ident,{"status":status}); self.send_json({"updated":result["rowcount"]>0})

    def do_PUT(self): self.send_json({"error":"Use as ações de criação e atualização disponíveis na interface"},405)
    def do_DELETE(self): self.send_json({"error":"Exclusão física indisponível; use cancelamento ou inativação para preservar histórico"},405)


if __name__ == "__main__":
    init_db()
    host=os.environ.get("HOST","127.0.0.1"); port=int(os.environ.get("PORT","8000"))
    print(f"Ótica Web disponível em http://{host}:{port} | banco: {'PostgreSQL' if DATABASE_URL else 'SQLite local'}")
    ThreadingHTTPServer((host,port),Handler).serve_forever()
