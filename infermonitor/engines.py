import json,re,urllib.request,urllib.error
class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None
_NO_REDIRECT=urllib.request.build_opener(_NoRedirect)
def get(url,timeout,limit):
 try:
  req=urllib.request.Request(url,headers={"User-Agent":"InferMonitor/0.1","Accept":"application/json,text/plain,*/*"})
  with _NO_REDIRECT.open(req,timeout=timeout) as r:
   b=r.read(limit+1)
   if len(b)>limit:return "too_large",None,r.status
   return "ok",b.decode("utf-8","replace"),r.status
 except urllib.error.HTTPError as e:return "http_error",e.read(2048).decode("utf-8","replace"),e.code
 except Exception as e:return "unreachable",str(e),None
SAMPLE=re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*?)\})?\s+([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|NaN|[+-]?Inf)$')
LABEL=re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"')
def parse_prom(body,source):
 out=[]
 for line in body.splitlines():
  m=SAMPLE.match(line.strip())
  if not m:continue
  name,rawlabels,raw=m.groups()
  try:v=float(raw)
  except ValueError:continue
  if not (float("-inf")<v<float("inf")):continue
  labels={k:val.replace('\\n','\n').replace('\\\"','"').replace('\\\\','\\') for k,val in LABEL.findall(rawlabels or "")}
  out.append({"name":name,"value":v,"unit":None,"scope":"engine","source":source,"availability":"available","semantics":"raw Prometheus sample; type is defined by exposition","labels":labels})
 return out
class Adapter:
 def __init__(self,engine):self.engine=engine
 def identify(self,base,http):
  if self.engine=="polystrata":
   state,body,status=http(base+"/metrics")
   try:d=json.loads(body) if body else {}
   except ValueError:d={}
   hs,hb,hstatus=http(base+"/health")
   try:h=json.loads(hb) if hb else {}
   except ValueError:h={}
   version=d.get("engine",{}).get("version") if isinstance(d,dict) and isinstance(d.get("engine"),dict) else None
   ok=isinstance(d,dict) and (version is not None or any(k in d for k in ("hardware_static","requests","max_context","expert_cache_mib")))
   ok=ok or (isinstance(h,dict) and ("max_context" in h or ("loaded" in h and "model" in h)))
   return ok,{"metrics_status":status,"health_status":hstatus,"engine_version":version,"signature":"PolyStrata JSON metrics/health" if ok else None}
  if self.engine=="exl3rdna4":
   hs,hb,hstatus=http(base+"/health")
   try:d=json.loads(hb) if hb else {}
   except ValueError:d={}
   ok=isinstance(d,dict) and isinstance(d.get("issues"),list) and d.get("status") is not None
   ev={"health_status":hstatus,"signature":None}
   if not ok:
    rs,rb,rstatus=http(base+"/redoc")
    ev["redoc_status"]=rstatus
    if rs=="ok" and "TabbyAPI" in (rb or ""):ok=True
   if ok:ev["signature"]="TabbyAPI health/redoc fingerprint (EXL3 RDNA4 recipe)"
   return ok,ev
  state,body,status=http(base+"/metrics")
  if state=="ok" and ("llamacpp:" in body or ("# TYPE" in body and "llama_" in body)):return True,{"metrics_status":status,"signature":"llama.cpp Prometheus exposition"}
  return False,{"metrics_status":status}
 def collect(self,base,http):
  if self.engine=="exl3rdna4":
   result={"metrics":[],"diagnostics":{}}
   hs,hb,hstatus=http(base+"/health")
   result["diagnostics"]["/health"]={"state":hs,"status":hstatus}
   d=None
   if hs=="ok" and hb:
    try:d=json.loads(hb)
    except ValueError:d=None
   if isinstance(d,dict):
    result["metrics"].append({"name":"exl3rdna4.healthy","value":1.0 if d.get("status")=="healthy" else 0.0,"unit":None,"scope":"engine","source":"exl3rdna4.health","availability":"available","semantics":"1 when /health reports status healthy, 0 otherwise"})
    result["metrics"].append({"name":"exl3rdna4.health_issues_total","value":float(len(d.get("issues"))) if isinstance(d.get("issues"),list) else 0.0,"unit":None,"scope":"engine","source":"exl3rdna4.health","availability":"available","semantics":"number of entries in the /health issues list"})
   ms,mb,mstatus=http(base+"/v1/models")
   result["diagnostics"]["/v1/models"]={"state":ms,"status":mstatus}
   return result
  if self.engine=="llamacpp":
   state,body,status=http(base+"/metrics")
   return {"metrics":parse_prom(body or "","llamacpp.prometheus") if state=="ok" else [],"diagnostics":{"/metrics":{"state":state,"status":status}}}
  result={"metrics":[],"diagnostics":{}}
  for path in ("/health","/props","/metrics"):
   state,body,status=http(base+path);result["diagnostics"][path]={"state":state,"status":status}
   try:d=json.loads(body) if state=="ok" and body else None
   except ValueError:d=None
   if isinstance(d,dict):
    def walk(x,key):
     if isinstance(x,dict):
      for k,v in x.items():walk(v,key+"."+k)
     elif isinstance(x,list):
      for i,v in enumerate(x):
       if isinstance(v,dict):walk(v,key+"["+str(i)+"]")
     elif isinstance(x,(int,float)) and not isinstance(x,bool):
      result["metrics"].append({"name":key,"value":x,"unit":None,"scope":"engine","source":"polystrata.json","availability":"available","semantics":"raw engine field; no unit inferred"})
    walk(d,path)
    # The supplied Strata telemetry notes define prompt-read tok/s as prompt_read / prompt_ms.
    if path=="/metrics" and isinstance(d.get("requests"),list):
     for i,request in enumerate(d["requests"]):
      if isinstance(request,dict) and isinstance(request.get("prompt_read"),(int,float)) and isinstance(request.get("prompt_ms"),(int,float)) and request["prompt_ms"]>0:
       result["metrics"].append({"name":"polystrata.request.prompt_read_tokens_per_second","value":request["prompt_read"]*1000/request["prompt_ms"],"unit":"tokens/s","scope":"request","source":"polystrata.json","availability":"available","semantics":"prompt_read / prompt_ms; request index "+str(i)})
  state,body,status=http(base+"/metrics/prometheus")
  if state=="ok" and body and "# TYPE" in body:result["metrics"]+=parse_prom(body,"polystrata.prometheus")
  return result
