import json
from pathlib import Path
from urllib.parse import urlsplit
DEFAULT = {"server":{"host":"127.0.0.1","port":8090},"collector":{"poll_interval_ms":1000,"request_timeout_ms":700,"max_response_bytes":1048576},"history":{"enabled":True,"directory":"./data","retention_days":7},"endpoints":[{"id":"local-8080","url":"http://127.0.0.1:8080","enabled":True,"engine":"auto"},{"id":"local-8081","url":"http://127.0.0.1:8081","enabled":False,"engine":"auto"},{"id":"local-8082","url":"http://127.0.0.1:8082","enabled":False,"engine":"auto"}]}
MAX_ENABLED=3
class EndpointError(ValueError):pass
class UnknownEndpointError(EndpointError):pass
class DuplicateEndpointError(EndpointError):pass
class EndpointLimitError(EndpointError):pass
def endpoint_count(cfg,enabled=None):
 return sum(1 for e in cfg["endpoints"] if enabled is None or e.get("enabled",True) is enabled)
def endpoint_by_id(cfg,endpoint_id):
 return next((e for e in cfg["endpoints"] if e["id"]==endpoint_id),None)
def add_endpoint(cfg,port):
 port=int(port)
 if not 1<=port<=65535:
  raise EndpointError("Port must be 1..65535")
 ep={"id":"local-%d"%port,"url":"http://127.0.0.1:%d"%port,"enabled":True,"engine":"auto"}
 if endpoint_by_id(cfg,ep["id"]) or any(e["url"]==ep["url"] for e in cfg["endpoints"]):
  raise DuplicateEndpointError("Port %d is already configured (%s)"%(port,ep["id"]))
 if endpoint_count(cfg,True)+1>MAX_ENABLED:
  raise EndpointLimitError("MVP supports at most three enabled endpoints; pause or remove one first")
 cfg["endpoints"].append(ep)
 return ep
def load_config(path):
 p=Path(path)
 if not p.exists():
  p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(DEFAULT,indent=2))
 c=json.loads(p.read_text())
 for k,v in DEFAULT.items():c.setdefault(k,v)
 enabled=[e for e in c["endpoints"] if e.get("enabled",True)]
 if len(enabled)>MAX_ENABLED:raise ValueError("MVP supports at most three enabled endpoints")
 if len({e["id"] for e in c["endpoints"]})!=len(c["endpoints"]):raise ValueError("Endpoint IDs must be unique")
 if c["server"]["host"] not in ("127.0.0.1","::1","localhost"):raise ValueError("MVP API must bind to loopback")
 for e in c["endpoints"]:
  if e.get("engine","auto") not in ("auto","polystrata","llamacpp","exl3rdna4"):raise ValueError("Invalid engine override")
  if not e["url"].startswith(("http://","https://")):raise ValueError("Only HTTP(S) endpoints are supported")
  u=urlsplit(e["url"])
  if u.hostname not in ("127.0.0.1","localhost","::1") or u.username or u.password:raise ValueError("MVP inference targets must be loopback URLs without embedded credentials")
 if not 500<=int(c["collector"]["poll_interval_ms"])<=60000:raise ValueError("Poll interval must be 500..60000 ms")
 return c
def save_config(cfg,path):
 p=Path(path)
 if p.parent and not p.parent.exists():p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(cfg,indent=2)+"\n")
def set_endpoint_enabled(cfg,endpoint_id,enabled):
 e=endpoint_by_id(cfg,endpoint_id)
 if e is None:
  raise UnknownEndpointError("Unknown endpoint %s"%endpoint_id)
 if enabled and e.get("enabled",True) is not True and endpoint_count(cfg,True)>=MAX_ENABLED:
  raise EndpointLimitError("MVP supports at most three enabled endpoints")
 e["enabled"]=bool(enabled)
 return e
def remove_endpoint(cfg,endpoint_id):
 e=endpoint_by_id(cfg,endpoint_id)
 if e is None:
  raise UnknownEndpointError("Unknown endpoint %s"%endpoint_id)
 cfg["endpoints"]=[x for x in cfg["endpoints"] if x["id"]!=endpoint_id]