"""End-to-end acceptance checks for core workflows using an isolated SQLite DB."""
import json, os, subprocess, sys, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PYTHON=sys.executable

class OticaFlowSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="otica-test-")
        cls.port=18741
        env=os.environ.copy(); env.update({"OTICA_DATA_DIR":cls.tmp.name,"PORT":str(cls.port),"HOST":"127.0.0.1","ADMIN_PASSWORD":"senha-teste-forte-123","SESSION_SECRET":"test-secret-that-is-long-enough"})
        cls.proc=subprocess.Popen([PYTHON,str(ROOT/"server.py")],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        cls.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/health",timeout=.2) as r:
                    if r.status==200: break
            except Exception: time.sleep(.1)
        else: raise RuntimeError("API não iniciou")
        cls.call("/login",{"username":"admin","password":"senha-teste-forte-123"})

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=5); cls.tmp.cleanup()

    def setUp(self):
        import sqlite3
        con=sqlite3.connect(Path(self.tmp.name)/"otica.db")
        for table in ("sale_items","prescriptions","lab_orders","receivables","purchase_items","payables","purchases","stock_movements","cash_movements","audit_log","sales","customers","products"):
            con.execute(f"DELETE FROM {table}")
        con.commit(); con.close()

    @classmethod
    def call(cls,path,data=None,method=None,opener=None):
        raw=json.dumps(data).encode() if data is not None else None
        req=urllib.request.Request(f"http://127.0.0.1:{cls.port}/api{path}",data=raw,method=method or ("POST" if raw is not None else "GET"),headers={"Content-Type":"application/json"})
        try:
            with (opener or cls.opener).open(req,timeout=5) as r: return r.status,(json.loads(r.read()) if r.status!=204 else None)
        except urllib.error.HTTPError as e: return e.code,json.loads(e.read())

    def test_sale_rx_stock_finance_purchase_and_reports(self):
        code,p=self.call("/products",{"name":"Lente de teste","sku":"TST-1","category":"Lentes","stock":8,"minimum_stock":1,"cost":20,"price":45})
        self.assertEqual(code,201); pid=p["id"]
        code,c=self.call("/customers",{"name":"Cliente de teste","document":"00000000000","phone":"000"})
        self.assertEqual(code,201)
        code,sale=self.call("/sales",{"customer_id":c["id"],"items":[{"product_id":pid,"quantity":2,"unit_price":45}],"installments":3,"first_due_date":"2026-11-05","paid_now":30,"payment_method":"Pix","prescription":{"lens_description":"Progressiva","right_sphere":"-1.00","left_sphere":"-0.75","estimated_date":"2026-11-20"}})
        self.assertEqual(code,201); self.assertEqual(sale["total"],90)
        self.assertEqual(float(self.call("/products")[1][0]["stock"]),6)
        receivables=self.call("/receivables")[1]; self.assertEqual(len(receivables),3); self.assertEqual(receivables[0]["status"],"Pago")
        code,_=self.call(f"/receivables/{receivables[1]['id']}/payment",{"amount":10})
        self.assertEqual(code,200)
        lab=self.call("/lab-orders")[1]; self.assertEqual(lab[0]["status"],"Pendente")
        code,_=self.call(f"/lab-orders/{lab[0]['id']}",{"status":"Em produção"}); self.assertEqual(code,200)
        code,purchase=self.call("/purchases",{"items":[{"product_id":pid,"quantity":4,"unit_cost":20}],"description":"Reposição","due_date":"2026-11-30"})
        self.assertEqual(code,201); self.assertEqual(purchase["total"],80)
        code,adj=self.call("/stock-adjustments",{"product_id":pid,"quantity":1,"direction":"Saída","reason":"Contagem de teste"}); self.assertEqual(code,200)
        self.assertEqual(float(self.call("/products")[1][0]["stock"]),9)
        code,report=self.call("/reports/sales?from=2020-01-01&to=2030-01-01")
        self.assertEqual(code,200); self.assertEqual(report["total"],90); self.assertEqual(len(report["rows"]),1)

    def test_received_amount_cannot_exceed_sale_total(self):
        _,p=self.call("/products",{"name":"Item de validação","sku":"TST-2","stock":2,"price":10})
        code,_=self.call("/sales",{"items":[{"product_id":p["id"],"quantity":1,"unit_price":10}],"paid_now":11})
        self.assertEqual(code,400)

    def test_legacy_archive_active_filter_and_seller_link(self):
        import sqlite3
        con=sqlite3.connect(Path(self.tmp.name)/"otica.db")
        con.execute("INSERT INTO legacy_sources(table_name,file_name,dbf_version,record_count,deleted_count,fields) VALUES(?,?,?,?,?,?)",("TEST__CLIENTES","TEST/CLIENTES.DBF",3,2,1,"[]"))
        source_id=con.execute("SELECT id FROM legacy_sources WHERE table_name='TEST__CLIENTES'").fetchone()[0]
        con.execute("INSERT INTO legacy_rows(source_id,row_number,deleted,payload) VALUES(?,?,?,?)",(source_id,1,0,'{"NOME":"Cliente ativo"}'))
        con.execute("INSERT INTO legacy_rows(source_id,row_number,deleted,payload) VALUES(?,?,?,?)",(source_id,2,1,'{"NOME":"Cliente excluído"}'))
        con.execute("INSERT INTO sellers(legacy_id,name) VALUES(?,?)",("S-TEST","Vendedor legado"))
        seller_id=con.execute("SELECT id FROM sellers WHERE legacy_id='S-TEST'").fetchone()[0]
        con.commit(); con.close()
        code,rows=self.call(f"/legacy/rows?source={source_id}&q=Cliente%20ativo")
        self.assertEqual(code,200); self.assertEqual(rows["total"],1); self.assertEqual(len(rows["rows"]),1)
        _,product=self.call("/products",{"name":"Produto do vendedor","sku":"TST-SELLER","stock":2,"price":15})
        code,sale=self.call("/sales",{"seller_id":seller_id,"items":[{"product_id":product["id"],"quantity":1,"unit_price":15}]})
        self.assertEqual(code,201)
        con=sqlite3.connect(Path(self.tmp.name)/"otica.db")
        linked=con.execute("SELECT seller_id,seller_name FROM sales WHERE id=?",(sale["id"],)).fetchone(); con.close()
        self.assertEqual(linked,(seller_id,"Vendedor legado"))

    def test_unpaid_sale_cancellation_and_cash_entry(self):
        _,p=self.call("/products",{"name":"Item cancelável","sku":"TST-3","stock":3,"price":25})
        _,sale=self.call("/sales",{"items":[{"product_id":p["id"],"quantity":1,"unit_price":25}],"installments":1})
        self.assertEqual(float(self.call("/products")[1][0]["stock"]),2)
        code,result=self.call(f"/sales/{sale['id']}/cancel",{})
        self.assertEqual(code,200); self.assertEqual(result["status"],"cancelled")
        all_products=self.call("/products")[1]; item=next(x for x in all_products if x["id"]==p["id"])
        self.assertEqual(float(item["stock"]),3)
        code,_=self.call("/cash-movements",{"direction":"Saída","category":"Despesa","description":"Lançamento de teste","amount":12.5})
        self.assertEqual(code,201); self.assertEqual(self.call("/cash-movements")[1][0]["category"],"Despesa")

    def test_paid_sale_requires_refund_confirmation(self):
        _,p=self.call("/products",{"name":"Item com sinal","sku":"TST-4","stock":2,"price":40})
        _,sale=self.call("/sales",{"items":[{"product_id":p["id"],"quantity":1,"unit_price":40}],"paid_now":10})
        code,info=self.call(f"/sales/{sale['id']}/cancel",{})
        self.assertEqual(code,409); self.assertTrue(info["requires_refund"]); self.assertEqual(info["received_total"],10)
        code,_=self.call(f"/sales/{sale['id']}/cancel",{"refund_confirmed":True})
        self.assertEqual(code,200)
        movements=self.call("/cash-movements")[1]
        self.assertTrue(any(x["category"]=="Estorno de venda" and float(x["amount"])==10 for x in movements))

    def test_role_permissions_and_concurrent_stock(self):
        code,_=self.call("/users",{"username":"caixa-teste","full_name":"Caixa de teste","role":"cashier","password":"senha-caixa-teste-123"})
        self.assertEqual(code,201)
        import http.cookiejar
        cashier=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.call("/login",{"username":"caixa-teste","password":"senha-caixa-teste-123"},opener=cashier)
        code,_=self.call("/products",{"name":"Produto negado","price":2},opener=cashier)
        self.assertEqual(code,403)
        _,p=self.call("/products",{"name":"Último item","sku":"TST-5","stock":2,"price":8})
        from concurrent.futures import ThreadPoolExecutor
        payload={"items":[{"product_id":p["id"],"quantity":2,"unit_price":8}],"installments":1}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.call("/sales",payload),range(2)))
        self.assertEqual(sum(status==201 for status,_ in results),1)
        final=next(x for x in self.call("/products")[1] if x["id"]==p["id"])
        self.assertEqual(float(final["stock"]),0)

if __name__=="__main__": unittest.main()
