from types import SimpleNamespace as NS
import json,time
import pytest
from fastapi.testclient import TestClient
from demo import agent,catalog
from demo.app import app,ChatRequest,ReportRequest

class Responses:
 def __init__(self,responses):self.responses=iter(responses);self.calls=[]
 def create(self,**kw):self.calls.append(kw);return next(self.responses)

def response(id,output=None,text='검색 결과입니다.'):
 return NS(id=id,status='completed',output=output or [],output_text=text)

def test_chat_chain_and_new_session(monkeypatch):
 fake=Responses([response('resp_1',[NS(type='function_call',name='search_products',arguments=json.dumps({'size_classes':[27]}),call_id='call1')]),response('resp_2')])
 monkeypatch.setattr(agent,'client',lambda:NS(responses=fake))
 result=list(agent.chat_events(ChatRequest(message='27인치 찾아줘')))[-1]['data']
 assert 'previous_response_id' not in fake.calls[0]
 assert fake.calls[1]['previous_response_id']=='resp_1'
 assert fake.calls[1]['input'][0]['type']=='function_call_output'
 assert fake.calls[0]['model']=='gpt-6.1-sol'
 assert fake.calls[0]['reasoning']=={'effort':'medium'}
 assert result['applied_filters']=={'size_classes':[27]}
 fake2=Responses([response('resp_3')]);monkeypatch.setattr(agent,'client',lambda:NS(responses=fake2))
 request=ChatRequest(message='이 조건에서 비교해줘',**{k:result[k] for k in ('continuation','previous_response_id','applied_filters','applied_conditions')})
 list(agent.chat_events(request))
 assert fake2.calls[0]['previous_response_id']=='resp_2'
 assert '[27]' in fake2.calls[0]['input'][0]['content']
 fake3=Responses([response('resp_new')]);monkeypatch.setattr(agent,'client',lambda:NS(responses=fake3))
 list(agent.chat_events(ChatRequest(message='새 대화')))
 assert 'previous_response_id' not in fake3.calls[0]

def test_invalid_and_expired_session(monkeypatch):
 monkeypatch.setattr(agent,'client',lambda:object())
 with pytest.raises(agent.PublicError):list(agent.chat_events(ChatRequest(message='hello',previous_response_id='resp_other')))
 token=agent.sign({'response_id':'resp_a','filters':{},'conditions':[],'expires':time.time()-1,'version':catalog.metadata()['source_data_version']})
 with pytest.raises(agent.PublicError):agent.verify(token)
 with pytest.raises(agent.PublicError):agent.verify(token+'a')

def test_report_extraction_is_not_stored(monkeypatch):
 calls=[]
 unit=agent.Unit(raw_aspect='가격',raw_status='저렴함',excerpt='저렴해요',opinion='저렴해 만족함',sentiment='positive')
 def parse(**kwargs):calls.append(kwargs);return NS(status='completed',output_parsed=agent.Extraction(opinion_units=[unit]))
 monkeypatch.setattr(agent,'client',lambda:NS(responses=NS(parse=parse)))
 result=list(agent.report_events(ReportRequest(product_id='aoc-q27g2s',review='저렴해요')))[-1]['data']
 assert result['units'][0]['mapping_state']=='mapped_exact'
 assert calls[0]['store'] is False
 assert calls[0]['model']=='gpt-6-luna'
 assert calls[0]['reasoning']=={'effort':'high'}
 with pytest.raises(agent.PublicError):list(agent.report_events(ReportRequest(product_id='aoc-q27g2s',review='비싸요')))

def test_api_without_key_is_explicit_and_validates_inputs():
 client=TestClient(app)
 assert client.get('/catalog').json()['api_ready'] is False
 r=client.post('/chat',json={'message':'안녕'})
 assert 'API_KEY_REQUIRED' in r.text
 assert 'no-store'==r.headers['cache-control']
 assert client.post('/report',json={'product_id':'aoc-q27g2s','review':'x'*8001}).status_code==422
 assert client.post('/chat',json={'message':'x','extra':'no'}).status_code==422
