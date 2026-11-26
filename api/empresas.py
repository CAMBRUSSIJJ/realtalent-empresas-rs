from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
import hmac,json,os,re,tempfile,hashlib,shutil
import duckdb, urllib.request,time
_CACHE={}
DEFAULT_REPO='CAMBRUSSIJJ/realtalent-empresas-rs'

def gh(url):
 headers={'Accept':'application/vnd.github+json','User-Agent':'RealTalent-RS','X-GitHub-Api-Version':'2022-11-28'}
 token=os.getenv('GH_DATA_TOKEN')
 if token:headers['Authorization']='Bearer '+token
 return urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=15)

def fetch_asset(asset,path):
 url=asset['browser_download_url']
 if not url.startswith('https://github.com/'):raise RuntimeError('URL inválida')
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RealTalent-RS'}),timeout=20) as response,open(path,'wb') as dst:
  shutil.copyfileobj(response,dst)

def release():
 repo=os.getenv('GH_DATA_REPO',DEFAULT_REPO)
 if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise RuntimeError('Repo inválido')
 tag=os.getenv('GH_DATA_TAG','')
 if tag and not re.fullmatch(r'rs-[A-Za-z0-9-]+',tag):raise RuntimeError('Tag inválida')
 if _CACHE.get('key')==(repo,tag) and time.monotonic()-_CACHE['time']<300:return _CACHE['data']
 endpoint='/tags/'+tag if tag else '/latest'
 base='https://api.github.com/repos/'+repo+'/releases'
 with gh(base+endpoint) as response:r=json.load(response)
 if not r['tag_name'].startswith('rs-'):raise RuntimeError('Release não é base RS')
 assets={};page=1
 while True:
  with gh(base+'/'+str(r['id'])+'/assets?per_page=100&page='+str(page)) as response:batch=json.load(response)
  for a in batch:assets[a['name']]=a
  if len(batch)<100:break
  page+=1
 with tempfile.TemporaryDirectory() as temp:
  p=os.path.join(temp,'manifest.json');fetch_asset(assets['manifest.json'],p)
  with open(p,encoding='utf-8') as response:m=json.load(response)
 if len(m['cities'])!=497 or sum(c['rows'] for c in m['cities'])!=m['rows']:raise RuntimeError('Manifesto inválido')
 if any(c['asset'] not in assets or assets[c['asset']]['size']!=c['bytes'] for c in m['cities']):raise RuntimeError('Release incompleta')
 _CACHE.update(key=(repo,tag),time=time.monotonic(),data=(m,assets));return m,assets

def filters(q):
 clauses=[];args=[]
 def get(k):return q.get(k,[''])[0].strip()
 if (s:=get('cnpj')):
  s=re.sub(r'[^0-9]','',s)
  if len(s)!=14:raise ValueError('Informe um CNPJ com 14 dígitos.')
  clauses.append('cnpj = ?');args.append(s)
 if (s:=get('cnae')):
  s=re.sub(r'[^0-9]','',s)
  if len(s)!=7:raise ValueError('CNAE deve conter 7 dígitos.')
  clauses.append("(cnae = ? OR list_contains(string_split(regexp_replace(coalesce(cnaes_secundarios,''), '\\s+', '', 'g'), ','), ?))");args.extend([s,s])
 if (s:=get('q')):
  if not 2<=len(s)<=100:raise ValueError('Pesquisa entre 2 e 100 caracteres.')
  clauses.append("(contains(lower(coalesce(nome_fantasia,'')),lower(?)) OR contains(lower(coalesce(atividade,'')),lower(?)))");args.extend([s,s])
 if get('ativos')=='1':clauses.append("lower(situacao) = 'ativa'")
 for name,op in [('de','>='),('ate','<=')]:
  if (s:=get(name)):
   if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',s):raise ValueError('Data inválida.')
   clauses.append('abertura '+op+' ?');args.append(s.replace('-',''))
 try:offset=int(get('offset') or 0)
 except ValueError:raise ValueError('Página inválida.')
 if not 0<=offset<=10000:raise ValueError('Refine a consulta; limite de 10.000 resultados.')
 return (' WHERE '+' AND '.join(clauses) if clauses else ''),args,offset

class handler(BaseHTTPRequestHandler):
 def send_json(self,code,obj):
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(json.dumps(obj,ensure_ascii=False).encode())
 def do_GET(self):
  try:
   secret=os.getenv('SEARCH_ACCESS_CODE','')
   if secret and not hmac.compare_digest(self.headers.get('Authorization','').encode(),('Bearer '+secret).encode()):return self.send_json(401,{'error':'Código de acesso inválido.'})
   q=parse_qs(urlparse(self.path).query);m,assets=release()
   if q.get('action')==['cities']:return self.send_json(200,{'cities':[{k:c[k] for k in ('id','name','rows')} for c in m['cities']],'rows':m['rows'],'scope':m['scope'],'source':m['source']})
   city=next((c for c in m['cities'] if c['id']==q.get('city',[''])[0]),None)
   if not city:raise ValueError('Selecione um município disponível.')
   where,args,offset=filters(q)
   with tempfile.TemporaryDirectory() as tmp:
    path=os.path.join(tmp,'data.parquet');fetch_asset(assets[city['asset']],path)
    if os.path.getsize(path)!=city['bytes'] or hashlib.sha256(open(path,'rb').read()).hexdigest()!=city['sha256']:raise RuntimeError('Integrity check failed')
    with duckdb.connect() as db:
     db.execute("SET memory_limit='256MB'");db.execute('SET threads=2')
     db.read_parquet(path).create_view('companies');cols='cnpj,nome_fantasia,tipo,situacao,abertura,cnae,atividade,municipio';cur=db.execute(f'SELECT {cols} FROM companies{where} ORDER BY cnpj LIMIT 51 OFFSET ?',args+[offset]);rows=[dict(zip([x[0] for x in cur.description],r)) for r in cur.fetchall()]
   self.send_json(200,{'rows':rows[:50],'has_more':len(rows)>50,'offset':offset})
  except ValueError as e:self.send_json(400,{'error':str(e)})
  except Exception as e:
   print('consulta indisponível:',type(e).__name__,flush=True)
   self.send_json(503,{'error':'Base temporariamente indisponível. Confira a release publicada no GitHub.'})
