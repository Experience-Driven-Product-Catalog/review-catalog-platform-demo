"""Verify deployed AWS paths; --live runs bounded real OpenAI requests."""
from pathlib import Path
import argparse,json,urllib.request
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
base=json.loads((root/'deployment.json').read_text())['ApiUrl']
def get(path):
 with urllib.request.urlopen(base+path,timeout=45) as r:return json.load(r)
def post(path,body):
 req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=330) as r:
  events=[]
  for line in r:
   if line.startswith(b'data: '):events.append(json.loads(line[6:]));print(path,events[-1]['type'],flush=True)
 return events
assert get('/health')['status']=='ok'
catalog=get('/catalog');assert len(catalog['products'])==9
print('AWS health + fixed catalog: PASS')
if not a.live:
 if not catalog['api_ready']:
  for route,body in [('/chat',{'message':'27인치 모니터'}),('/report',{'product_id':catalog['products'][0]['product_id'],'review':'가격이 저렴해서 좋아요.'})]:
   events=post(route,body);assert events[-1]['code']=='API_KEY_REQUIRED'
  print('Both Lambda streaming placeholder errors: PASS')
else:
 assert catalog['api_ready'],'API key is not configured'
 def result(events):
  assert events[-1]['type']=='result',events[-1]
  return events[-1]['data']
 first=result(post('/chat',{'message':'27인치 QHD 모니터를 찾아줘. 다른 조건은 추가하지 마.'}))
 assert first['previous_response_id'] and first['applied_conditions']
 follow={k:first[k] for k in ('previous_response_id','continuation','applied_filters','applied_conditions')}
 second=result(post('/chat',{'message':'앞선 조건을 유지하고 30만 원 이하로 좁혀줘.',**follow}))
 assert second['previous_response_id']!=first['previous_response_id']
 report=result(post('/report',{'product_id':catalog['products'][0]['product_id'],'review':'가격이 저렴해서 마음에 듭니다. 화면은 선명해요.'}))
 assert report['policy']['stored'] is False and report['overview']['aspects']
 print('Live two-turn chat and unified report: PASS')
