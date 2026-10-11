"""Deploy/update the entire AWS demo. Reads secrets without printing them."""
from pathlib import Path
import sys,json,hashlib,time,secrets,os
import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values,set_key
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'infra'))
from template import template

def apply(cf,name,body,parameters=None):
 args={'StackName':name,'TemplateBody':json.dumps(body),'Capabilities':['CAPABILITY_IAM'],'Tags':[{'Key':'Project','Value':'review-catalog-platform-demo'}]}
 if parameters:args['Parameters']=[{'ParameterKey':k,'ParameterValue':v} for k,v in parameters.items()]
 try:
  existing=cf.describe_stacks(StackName=name)['Stacks'][0]
  if existing['StackStatus']=='ROLLBACK_COMPLETE':
   cf.delete_stack(StackName=name)
   cf.get_waiter('stack_delete_complete').wait(StackName=name,WaiterConfig={'Delay':3,'MaxAttempts':100})
   cf.create_stack(**args)
  else:
   try:cf.update_stack(**args)
   except ClientError as e:
    if 'No updates are to be performed' in str(e):return cf.describe_stacks(StackName=name)['Stacks'][0]
    raise
 except ClientError as e:
  if 'does not exist' in str(e):cf.create_stack(**args)
  else:raise
 previous=None
 while True:
  stack=cf.describe_stacks(StackName=name)['Stacks'][0];status=stack['StackStatus']
  if status!=previous:print(name,status,flush=True);previous=status
  if status in ['CREATE_COMPLETE','UPDATE_COMPLETE']:return stack
  if 'IN_PROGRESS' not in status:
   events=cf.describe_stack_events(StackName=name)['StackEvents']
   for e in events:
    if e['ResourceStatus'].endswith('FAILED'):print(e['LogicalResourceId'],e.get('ResourceStatusReason',''))
   raise RuntimeError('Deployment failed: '+status)
  time.sleep(5)

def main():
 env=dotenv_values(ROOT/'.env');region=env.get('AWS_REGION','ap-northeast-2');session=boto3.Session(region_name=region)
 account=session.client('sts').get_caller_identity()['Account'];cf=session.client('cloudformation');s3=session.client('s3')
 bucket=f'review-catalog-demo-{account}-{region}'
 bootstrap={'AWSTemplateFormatVersion':'2010-09-09','Resources':{'Artifacts':{'Type':'AWS::S3::Bucket','DeletionPolicy':'Retain','UpdateReplacePolicy':'Retain','Properties':{'BucketName':bucket,'PublicAccessBlockConfiguration':{'BlockPublicAcls':True,'BlockPublicPolicy':True,'IgnorePublicAcls':True,'RestrictPublicBuckets':True},'BucketEncryption':{'ServerSideEncryptionConfiguration':[{'ServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]},'VersioningConfiguration':{'Status':'Enabled'},'LifecycleConfiguration':{'Rules':[{'Id':'ExpireOldVersions','Status':'Enabled','NoncurrentVersionExpiration':{'NoncurrentDays':30}}]}}}}}
 apply(cf,'review-catalog-platform-demo-storage',bootstrap)
 archive=ROOT/'.build/lambda.zip';database=ROOT/'data/catalog.sqlite'
 sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 code_sha=sha(archive);catalog_sha=sha(database)
 code_key=f'code/{code_sha}.zip';catalog_key=f'catalog/{catalog_sha}.sqlite'
 s3.upload_file(str(archive),bucket,code_key);s3.upload_file(str(database),bucket,catalog_key)
 signing=env.get('SESSION_SIGNING_SECRET')
 if not signing:
  signing=secrets.token_urlsafe(48);set_key(str(ROOT/'.env'),'SESSION_SIGNING_SECRET',signing)
 origin='https://experience-driven-product-catalog.github.io'
 body=template(bucket,code_key,catalog_key,catalog_sha,code_sha,origin)
 (ROOT/'.build/cloudformation.json').write_text(json.dumps(body,indent=2))
 cf.validate_template(TemplateBody=json.dumps(body))
 stack=apply(cf,'review-catalog-platform-demo',body,{'OpenAIKey':env['OPENAI_API_KEY'],'SessionSecret':signing})
 outputs={o['OutputKey']:o['OutputValue'] for o in stack['Outputs']}
 outputs.update(region=region,catalog_sha256=catalog_sha,code_sha256=code_sha,stack='review-catalog-platform-demo')
 (ROOT/'deployment.json').write_text(json.dumps(outputs,indent=2)+'\n')
 (ROOT/'frontend/.env.local').write_text('VITE_API_URL='+outputs['ApiUrl']+'\n')
 print(json.dumps(outputs,indent=2),flush=True)

if __name__=='__main__':main()
