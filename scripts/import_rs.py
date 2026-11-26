"""Download Receita Federal establishment files from the Casa dos Dados mirror; validate RS and export Parquet."""
import argparse,csv,hashlib,io,json,re,subprocess,tempfile,zipfile
from pathlib import Path
from collections import Counter
from contextlib import ExitStack
import duckdb

BASE='https://dados-abertos-rf-cnpj.casadosdados.com.br/arquivos/'
FIELDS=['cnpj','nome_fantasia','tipo','situacao','abertura','cnae','atividade','cnaes_secundarios','municipio']
STATUS={'01':'NULA','02':'ATIVA','03':'SUSPENSA','04':'INAPTA','08':'BAIXADA'}
def download(base,name,root):
    path=root/name
    subprocess.run(['curl','--fail','--location','--retry','4','--retry-delay','3','--connect-timeout','30','--max-time','3600','--output',str(path),base+name],check=True)
    return path
def rows(path):
    with zipfile.ZipFile(path) as z:
        files=[x for x in z.infolist() if not x.is_dir()]
        if len(files)!=1: raise ValueError(f'Arquivo inesperado: {path.name}')
        with z.open(files[0]) as f,io.TextIOWrapper(f,encoding='latin-1',newline='') as t:
            yield from csv.reader(t,delimiter=';',quotechar='"')
def collect(source,out,expected=497,min_rows=4_000_000):
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); scratch=root/'csv';scratch.mkdir()
        muni=dict((r[0],r[1]) for r in rows(download(source,'Municipios.zip',root)))
        cnaes=dict((r[0],r[1]) for r in rows(download(source,'Cnaes.zip',root)))
        counts=Counter(); parts=[]
        with ExitStack() as stack:
            writers={}
            for i in range(10):
                name=f'Estabelecimentos{i}.zip';p=download(source,name,root);scanned=selected=0
                for r in rows(p):
                    scanned+=1
                    if len(r)!=30: raise ValueError(f'{name}: layout inválido na linha {scanned}')
                    if r[19]!='RS':continue
                    city=r[20];cnpj=''.join(r[:3])
                    if not re.fullmatch(r'\d{14}',cnpj) or city not in muni or not re.fullmatch(r'\d{4}',city):raise ValueError(f'{name}: registro inválido na linha {scanned}')
                    if city not in writers:
                        f=stack.enter_context((scratch/f'{city}.csv').open('w',encoding='utf-8',newline=''));writers[city]=csv.writer(f);writers[city].writerow(FIELDS)
                    writers[city].writerow([cnpj,r[4],{'1':'MATRIZ','2':'FILIAL'}.get(r[3],r[3]),STATUS.get(r[5],r[5]),r[10],r[11],cnaes.get(r[11],''),r[12],muni[city]])
                    counts[city]+=1;selected+=1
                if not scanned or not selected:raise ValueError(f'{name}: arquivo vazio ou sem RS')
                parts.append({'file':name,'scanned':scanned,'rs':selected});p.unlink();print(name,scanned,selected,flush=True)
        if len(counts)!=expected or sum(counts.values())<min_rows:raise ValueError(f'Cobertura insuficiente: {len(counts)} cidades / {sum(counts.values())} linhas')
        cities=[]
        with duckdb.connect() as db:
            db.execute("SET memory_limit='2GB'");db.execute('SET threads=2')
            for code,n in sorted(counts.items()):
                target=out/f'{code}.parquet'
                db.read_csv(str(scratch/f'{code}.csv'),all_varchar=True,header=True).create_view('source',replace=True)
                db.sql('SELECT * FROM source ORDER BY cnpj').write_parquet(str(target),compression='zstd')
                actual,distinct=db.execute('SELECT count(*),count(DISTINCT cnpj) FROM read_parquet(?)',[str(target)]).fetchone()
                if actual!=n or distinct!=n:raise ValueError(f'{code}: contagem ou duplicação incorreta')
                cities.append({'id':code,'name':muni[code],'rows':n,'asset':target.name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        n,distinct=db_global(out)
        if n!=sum(counts.values()) or n!=distinct:raise ValueError('Contagem estadual ou duplicação incorreta')
        manifest={'scope':f'RS completo: {len(cities)} municípios, todos os status cadastrais; fonte de estabelecimentos.','source':source,'rows':n,'cities':sorted(cities,key=lambda c:c['name']),'parts':parts,'fields':FIELDS,'bytes':sum(c['bytes'] for c in cities)}
        (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print('VALIDADO',n,len(cities),manifest['bytes'],flush=True)
        return manifest
def db_global(out):
    with duckdb.connect() as db:
        db.execute("SET memory_limit='2GB'");return db.execute('SELECT count(*),count(DISTINCT cnpj) FROM read_parquet(?)',[str(out/'*.parquet')]).fetchone()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot',required=True);p.add_argument('--out',type=Path,default=Path('release'));a=p.parse_args()
    if not re.fullmatch(r'20\d\d-\d\d-\d\d',a.snapshot):p.error('Data deve ser AAAA-MM-DD do espelho')
    if a.out.exists() and any(a.out.iterdir()):p.error('Pasta de saída precisa estar vazia')
    collect(BASE+a.snapshot+'/',a.out)
