"""Read and audit Clipper/dBase DBFs; stage every row and map known master data.

Example (dry-run only): python tools/dbf_import.py "C:/legacy/ARQUIVOS OTICA"
Example import: DATABASE_URL=postgresql://... python tools/dbf_import.py "C:/legacy/ARQUIVOS OTICA" --import
"""
import argparse, json, os, re, sqlite3, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def field_name(raw):
    return re.sub(r"[^A-Z0-9_]", "", raw.decode("ascii","replace").upper()).strip("_") or "FIELD"

def read_dbf(path):
    data=path.read_bytes()
    if len(data)<32: raise ValueError("arquivo menor que cabeçalho DBF")
    version=data[0]; count=int.from_bytes(data[4:8],"little"); header_len=int.from_bytes(data[8:10],"little"); record_len=int.from_bytes(data[10:12],"little")
    fields=[]; offset=1; pos=32
    while pos<header_len and data[pos]!=0x0D:
        desc=data[pos:pos+32]
        if len(desc)<32: raise ValueError("descritor de campo truncado")
        name=field_name(desc[:11].split(b"\0",1)[0]); typ=chr(desc[11]); length=desc[16]; decimals=desc[17]
        fields.append({"name":name,"type":typ,"length":length,"decimals":decimals,"offset":offset})
        offset+=length; pos+=32
    if not fields or offset-1>record_len: raise ValueError("layout de campos inválido")
    rows=[]; deleted=0; actual=0; warnings=[]
    for i in range(count):
        start=header_len+i*record_len; rec=data[start:start+record_len]
        if len(rec)<record_len: warnings.append(f"registro {i+1} truncado"); break
        actual+=1; is_deleted=rec[:1]==b"*"; deleted+=int(is_deleted); payload={}
        for f in fields:
            raw=rec[f["offset"]:f["offset"]+f["length"]]
            try:
                if f["type"] in "CVM": value=raw.rstrip(b" \0").decode("cp850","replace")
                elif f["type"] in "NFI":
                    # Keep decimal values textual in the archive to avoid a float round-trip.
                    s=raw.strip().decode("ascii","replace"); value=s if not s else (s if "." in s else int(s))
                elif f["type"]=="D": value=raw.decode("ascii","replace")
                elif f["type"]=="L": value=raw.decode("ascii","replace")
                else: value=raw.hex()
            except Exception: value=raw.hex()
            payload[f["name"]]=value
        rows.append((i+1,is_deleted,payload))
    return {"file":path.name,"version":version,"record_count":count,"actual_count":actual,"active_count":actual-deleted,"deleted_count":deleted,"record_length":record_len,"fields":fields,"rows":rows,"warnings":warnings}

def open_db():
    url=os.environ.get("DATABASE_URL")
    if url:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(url,row_factory=dict_row),True
    data_dir=Path(os.environ.get("OTICA_DATA_DIR",ROOT/"data")); data_dir.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(data_dir/"otica.db"); con.execute("PRAGMA foreign_keys=ON")
    return con,False

def q(pg): return "%s" if pg else "?"

def initialize(con,pg):
    if pg:
        con.execute((ROOT/"migrations"/"001_initial_postgres.sql").read_text(encoding="utf-8"))
    else:
        from server import SCHEMA_SQLITE
        con.executescript(SCHEMA_SQLITE)

def stage(con,pg,tables):
    mark=q(pg)
    # Replace the complete legacy snapshot atomically; only active records are staged.
    con.execute("DELETE FROM legacy_sources")
    for t in tables:
        name=t.get("source_key",Path(t["file"]).stem.upper())
        field_json=json.dumps(t["fields"],ensure_ascii=False)
        if pg:
            cur=con.execute("INSERT INTO legacy_sources(table_name,file_name,dbf_version,record_count,deleted_count,fields) VALUES(%s,%s,%s,%s,%s,%s::jsonb) RETURNING id",(name,t["file"],t["version"],t["actual_count"],t["deleted_count"],field_json)); sid=cur.fetchone()["id"]
        else:
            cur=con.execute("INSERT INTO legacy_sources(table_name,file_name,dbf_version,record_count,deleted_count,fields) VALUES(?,?,?,?,?,?)",(name,t["file"],t["version"],t["actual_count"],t["deleted_count"],field_json)); sid=cur.lastrowid
        for rownum,deleted,payload in t["rows"]:
            if deleted:
                continue
            payload={k:("[REDACTED]" if re.search(r"(SENHA|PASSWORD|PASSWD|TOKEN|SECRET|CHAVE)",k,re.I) else v) for k,v in payload.items()}
            payload_json=json.dumps(payload,ensure_ascii=False)
            if pg: con.execute("INSERT INTO legacy_rows(source_id,row_number,deleted,payload) VALUES(%s,%s,%s,%s::jsonb)",(sid,rownum,deleted,payload_json))
            else: con.execute("INSERT INTO legacy_rows(source_id,row_number,deleted,payload) VALUES(?,?,?,?)",(sid,rownum,int(deleted),payload_json))

def val(row,*names,default=None):
    for name in names:
        v=row.get(name)
        if v not in (None,""): return str(v).strip()
    return default

def import_masters(con,pg,tables):
    mark=q(pg)
    mappings={
      "PRODUTOS":("products",lambda r:{"legacy_id":"PRODUTOS:"+val(r,"CODIGO","CODIG","COD","MATS",default=""),"sku":val(r,"CODIGO","CODIG","COD"),"name":val(r,"DESCRICAO","DESCRI","NOME",default="(sem descrição)"),"category":val(r,"TIPO","CRITICA",default="Armações"),"brand":val(r,"MARCA"),"model":val(r,"MODELO"),"unit":val(r,"UNIDADE",default="UN"),"color":val(r,"COR"),"size":val(r,"TAMANHO"),"lens_type":val(r,"TIPO"),"stock":r.get("ESTOQUE") or 0,"minimum_stock":r.get("MINIMO") or 0,"cost":r.get("PRECOUNITC") or 0,"price":r.get("PRECOUNITV") or 0}),
      "LENTES":("products",lambda r:{"legacy_id":"LENTES:"+val(r,"CODIGO","CODIG","COD",default=""),"sku":val(r,"CODIGO","CODIG","COD"),"name":val(r,"DESCRICAO","DESCRI","NOME",default="(sem descrição)"),"category":"Lentes","brand":val(r,"MARCA"),"model":val(r,"MODELO"),"unit":val(r,"UNIDADE",default="UN"),"color":val(r,"COR"),"size":val(r,"TAMANHO"),"lens_type":val(r,"TIPO"),"stock":r.get("ESTOQUE") or 0,"minimum_stock":r.get("MINIMO") or 0,"cost":r.get("PRECOUNITC") or 0,"price":r.get("PRECOUNITV") or 0}),
      "CLIENTES":("customers",lambda r:{"legacy_id":val(r,"MAT","MATRICULA","CODCLI"),"name":val(r,"NOME","NOMCLI",default="(sem nome)"),"document":val(r,"CPF","CGC","CNPJ","CGCCLI"),"phone":val(r,"FONE","TELEFONE","FONECLI"),"email":val(r,"EMAIL"),"address":val(r,"ENDER","ENDERECO","ENDCLI"),"city":val(r,"CIDADE","CIDCLI"),"notes":val(r,"OBS")}),
      "FORNECED":("suppliers",lambda r:{"legacy_id":val(r,"MAT","MATRICULA","CODFORNEC"),"name":val(r,"NOME","NOMEFANTASIA","RAZAO",default="(sem nome)"),"contact":val(r,"CONTATO"),"document":val(r,"CPF","CGC","CNPJ"),"phone":val(r,"FONE","TELEFONE"),"email":val(r,"EMAIL"),"address":val(r,"ENDER","ENDERECO"),"city":val(r,"CIDADE"),"state":val(r,"UF")}),
      "MEDICO":("doctors",lambda r:{"legacy_id":val(r,"MATSAT","MATSA","MAT"),"name":val(r,"NOMESAT","NOMESA","NOME",default="(sem nome)")}),
      "LOJA":("stores",lambda r:{"legacy_id":val(r,"MATSAT","MATSA","MAT"),"name":val(r,"NOMESAT","NOME",default="(sem nome)"),"phone":val(r,"FONESAT","FONE"),"address":val(r,"ENDSAT","ENDER"),"city":val(r,"CIDSAT","CIDADE"),"discount_percent":r.get("PERCDESC") or 0}),
      "TIPO":("payment_methods",lambda r:{"legacy_id":val(r,"MATSAT","MATS","MAT"),"name":val(r,"NOMESAT","NOMES","NOME",default="(sem nome)")}),
      "VENDEDOR":("sellers",lambda r:{"legacy_id":val(r,"MATSA","MAT","CODVEND"),"name":val(r,"NOMESA","NOME",default="(sem nome)"),"document":val(r,"CPFSA","CPF"),"phone":val(r,"FONESA","FONE"),"address":val(r,"ENDERSA","ENDER"),"city":val(r,"CIDADESA","CIDADE"),"state":val(r,"UFSA","UF")})}
    counts={}
    for t in tables:
        name=t.get("table_name",Path(t["file"]).stem.upper())
        if name not in mappings: continue
        dest,mapper=mappings[name]
        seen_customer_keys=set()
        for rownum,deleted,row in t["rows"]:
            if deleted: continue
            fields=mapper(row)
            if fields.get("legacy_id") in ("",None): fields["legacy_id"]=f"{name}:{rownum}"
            # A few active customer rows reuse the same legacy customer code.
            # Keep each row and make the collision explicit instead of overwriting it.
            if dest=="customers" and fields.get("legacy_id") in seen_customer_keys:
                fields["legacy_id"]=f"{fields['legacy_id']}#ROW:{rownum}"
            if dest=="customers": seen_customer_keys.add(fields.get("legacy_id"))
            if dest=="products" and fields["legacy_id"] is None: fields["legacy_id"]=name+":"+str(row.get("CODIGO") or "")
            cols=list(fields); vals=list(fields.values())
            conflict="legacy_id" if fields.get("legacy_id") else "id"
            updates=",".join(f"{c}=excluded.{c}" for c in cols if c not in ("legacy_id",))
            marks=",".join([mark]*len(cols))
            if pg:
                sql=f"INSERT INTO {dest}({','.join(cols)}) VALUES({marks}) ON CONFLICT({conflict}) DO UPDATE SET {updates}"
            else:
                sql=f"INSERT INTO {dest}({','.join(cols)}) VALUES({marks}) ON CONFLICT({conflict}) DO UPDATE SET {updates}"
            con.execute(sql,vals)
            counts[dest]=counts.get(dest,0)+1
    return counts

def main():
    ap=argparse.ArgumentParser(description="Auditoria e staging seguro de tabelas DBF Clipper")
    ap.add_argument("folder",type=Path,help="Pasta do conjunto de arquivos DBF")
    ap.add_argument("--import",dest="do_import",action="store_true",help="Grava staging integral e importa cadastros conhecidos no banco configurado")
    ap.add_argument("--include-vdos",action="store_true",help="Inclui também a cópia complementar da subpasta vDos")
    args=ap.parse_args()
    folders=[(args.folder,"BASE")]
    if args.include_vdos and (args.folder/"vDos").is_dir(): folders.append((args.folder/"vDos","VDOS"))
    files=[]
    for folder,label in folders:
        files.extend((p,label) for p in sorted(folder.glob("*.DBF"))+sorted(folder.glob("*.dbf")))
    unique={p.resolve():(p,label) for p,label in files}; files=list(unique.values())
    if not files: raise SystemExit("Nenhum DBF encontrado na pasta indicada")
    tables=[]
    for p,label in files:
        try:
            t=read_dbf(p); t["source_key"]=label+"__"+p.stem.upper(); t["table_name"]=p.stem.upper(); t["file"]=label+"/"+p.name; tables.append(t)
        except Exception as e: tables.append({"file":p.name,"error":str(e)})
    report={"folder":str(args.folder.resolve()),"tables":[],"totals":{"files":len(files),"readable":0,"records":0,"active":0,"deleted":0,"errors":0}}
    for t in tables:
        if "error" in t:
            report["tables"].append({"file":t["file"],"error":t["error"]}); report["totals"]["errors"]+=1; continue
        report["tables"].append({k:t[k] for k in ("file","version","record_count","actual_count","active_count","deleted_count","record_length","fields","warnings")})
        report["totals"]["readable"]+=1; report["totals"]["records"]+=t["actual_count"]; report["totals"]["active"]+=t["active_count"]; report["totals"]["deleted"]+=t["deleted_count"]
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.do_import:
        if report["totals"]["errors"]: raise SystemExit("Importação interrompida: existem DBFs ilegíveis; resolva os erros antes de continuar.")
        con,pg=open_db()
        try:
            initialize(con,pg); stage(con,pg,tables)
            # Supplemental copy first; the root copy is authoritative when a master key overlaps.
            ordered=sorted(tables,key=lambda t:0 if t.get("source_key","").startswith("VDOS__") else 1)
            counts=import_masters(con,pg,ordered); con.commit()
            print(json.dumps({"imported_to":"postgresql" if pg else "sqlite","staged_tables":len(tables),"source_records":report["totals"]["records"],"staged_active_records":report["totals"]["active"],"deleted_records_excluded":report["totals"]["deleted"],"canonical_master_rows":counts},ensure_ascii=False,indent=2))
        except: con.rollback(); raise
        finally: con.close()

if __name__=="__main__": main()
