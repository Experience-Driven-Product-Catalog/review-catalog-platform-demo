"""After editing ignored .env, update both deployed Lambda environments safely."""
from pathlib import Path
import json
import boto3
from dotenv import dotenv_values
root=Path(__file__).resolve().parents[1]
env=dotenv_values(root/'.env');key=env.get('OPENAI_API_KEY','')
if not key or key.startswith('placeholder-'):raise SystemExit('Put the real OPENAI_API_KEY in .env first. The key will not be printed.')
deployment=json.loads((root/'deployment.json').read_text())
client=boto3.Session(region_name=deployment['region']).client('lambda')
for field in ['ReportFunction','ChatFunction']:
 name=deployment[field];config=client.get_function_configuration(FunctionName=name)
 variables=config['Environment']['Variables'];variables['OPENAI_API_KEY']=key
 client.update_function_configuration(FunctionName=name,Environment={'Variables':variables},RevisionId=config['RevisionId'])
 client.get_waiter('function_updated_v2').wait(FunctionName=name)
 print(name+': API key updated')
