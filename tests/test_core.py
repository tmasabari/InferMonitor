import tempfile,unittest
from pathlib import Path
from infermonitor.config import load_config,save_config,add_endpoint,set_endpoint_enabled,remove_endpoint,EndpointError,UnknownEndpointError,DuplicateEndpointError,EndpointLimitError
from infermonitor.plugins import Plugin,Registry
from infermonitor.engines import parse_prom, Adapter
from infermonitor.history import History
from infermonitor.system import LinuxMemoryProvider, SystemInventoryProvider, AmdRocmProcessProvider
class Tests(unittest.TestCase):
 def test_memory_provider_schema(self):
  m=LinuxMemoryProvider(refresh_seconds=0).collect()
  self.assertIn('state',m);self.assertIn('fields',m);self.assertIn('processes',m)
  self.assertIn('processes_semantics',m)
  if m['processes']:
   self.assertIn('cmdline',m['processes'][0])
 def test_system_inventory_schema(self):
  s=SystemInventoryProvider().collect()
  self.assertIn('cpu',s);self.assertIn('os',s);self.assertIn('storage_devices',s)
 def test_amd_memory_unit_parser(self):
  self.assertEqual(AmdRocmProcessProvider._number('1.5 GiB'),(1610612736,'bytes'))
  self.assertEqual(AmdRocmProcessProvider._number('bad'),(None,None))
 def test_parse_prometheus(self):
  x=parse_prom('llamacpp:requests_processing{slot="0"} 2\nllamacpp:kv_cache_usage_ratio 0.5',"fixture")
  self.assertEqual(len(x),2);self.assertEqual(x[0]["labels"]["slot"],"0")
 def test_duplicate_plugin(self):
  r=Registry();r.register(Plugin("x","1",(),lambda c:None),{"a":1})
  with self.assertRaises(ValueError):r.register(Plugin("x","1",(),lambda c:None),{"b":2})
 def test_config_default(self):
  with tempfile.TemporaryDirectory() as d:
   c=load_config(str(Path(d)/"cfg.json"));self.assertEqual(c["server"]["host"],"127.0.0.1")
 def test_jsonl_partial_line(self):
  with tempfile.TemporaryDirectory() as d:
   h=History(d,7);h.append({"observed_at":"2026-01-01T00:00:00Z","endpoints":[]})
   with h.path.open("a") as f:f.write('{"bad":')
   self.assertEqual(len(h.query()),1)
 def test_exl3rdna4_adapter(self):
  b="http://127.0.0.1:8096";routes={b+"/health":("ok",'{"status":"healthy","issues":[]}',200),b+"/v1/models":("http_error",'{"detail":"Please provide an API key"}',401)}
  http=lambda url:routes.get(url,("unreachable","no route",None))
  a=Adapter("exl3rdna4")
  ok,ev=a.identify(b,http)
  self.assertTrue(ok);self.assertEqual(ev["health_status"],200);self.assertIn("TabbyAPI",ev["signature"])
  r=a.collect(b,http)
  self.assertEqual(r["diagnostics"]["/health"],{"state":"ok","status":200})
  self.assertEqual(r["diagnostics"]["/v1/models"],{"state":"http_error","status":401})
  m={x["name"]:x["value"] for x in r["metrics"]}
  self.assertEqual(m.get("exl3rdna4.healthy"),1.0)
  self.assertEqual(m.get("exl3rdna4.health_issues_total"),0.0)
  routes2={b+"/health":("http_error",'{"detail":"Not Found"}',404),b+"/redoc":("ok","<title>TabbyAPI - ReDoc</title>",200)}
  ok2,ev2=a.identify(b,lambda url:routes2.get(url,("unreachable","no route",None)))
  self.assertTrue(ok2);self.assertEqual(ev2["redoc_status"],200)
  routes3={b+"/health":("ok",'{"status":"ok"}',200)}
  ok3,_=a.identify(b,lambda url:routes3.get(url,("unreachable","no route",None)))
  self.assertFalse(ok3)
 def test_endpoint_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   c=load_config(str(Path(d)/"c.json"))
   ep=add_endpoint(c,9100)
   self.assertEqual(ep["url"],"http://127.0.0.1:9100");self.assertTrue(ep["enabled"])
   with self.assertRaises(DuplicateEndpointError):add_endpoint(c,9100)
   add_endpoint(c,9200)
   with self.assertRaises(EndpointLimitError):add_endpoint(c,9300)
   with self.assertRaises(EndpointError):add_endpoint(c,0)
   with self.assertRaises(EndpointError):add_endpoint(c,70000)
   with self.assertRaises(UnknownEndpointError):remove_endpoint(c,"nope")
   with self.assertRaises(UnknownEndpointError):set_endpoint_enabled(c,"nope",True)
   with self.assertRaises(EndpointLimitError):set_endpoint_enabled(c,"local-8081",True)
   set_endpoint_enabled(c,"local-9200",False)
   set_endpoint_enabled(c,"local-8081",True)
   remove_endpoint(c,"local-9100")
   save_config(c,str(Path(d)/"c2.json"))
   c2=load_config(str(Path(d)/"c2.json"))
   self.assertEqual(c2["endpoints"],c["endpoints"])
   self.assertIn({"id":"local-8081","url":"http://127.0.0.1:8081","enabled":True,"engine":"auto"},c2["endpoints"])
if __name__=="__main__":unittest.main()