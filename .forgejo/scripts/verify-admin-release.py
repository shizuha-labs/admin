"""Read-only convergence proof for the existing Admin API/outbox release owners."""
import argparse,hashlib,json,re,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
COMPONENTS={'shizuha-admin':'shizuha-admin','shizuha-admin-worker':'worker','shizuha-admin-beat':'beat'}
SOURCE_FILES=('organizations/models.py','organizations/views.py','organizations/jit_dispatch.py','organizations/tasks.py','shizuha_admin/settings.py')
def run(args):
 result=subprocess.run(args,capture_output=True,timeout=20)
 if result.returncode:raise ValueError('Admin release read-only command refused')
 return result.stdout
def get(kind,name=None):
 args=['kubectl','get',kind,'-n','shizuha']+([name]if name else [])+['-o','json']
 return json.loads(run(args))
def owner(value,kind):
 refs=[x for x in value['metadata'].get('ownerReferences',[])if x.get('controller')]
 if len(refs)!=1 or refs[0].get('kind')!=kind:raise ValueError('Exact controller ownership required')
 return refs[0]['uid']
def existing_owners():
 out={}
 for name,container in COMPONENTS.items():
  dep=get('deployment',name);meta=dep['metadata'];annotations=meta.get('annotations',{})
  if meta.get('name')!=name or meta.get('namespace')!='shizuha' or meta.get('deletionTimestamp') or meta.get('labels',{}).get('app.kubernetes.io/managed-by')!='Helm' or annotations.get('meta.helm.sh/release-name')!='shizuha-admin' or annotations.get('meta.helm.sh/release-namespace')!='shizuha':raise ValueError('Existing canonical Helm release owner required')
  if len([c for c in dep['spec']['template']['spec']['containers']if c['name']==container])!=1:raise ValueError('Existing component container required')
  out[name]=meta['uid']
 return out
def inspect(image,names,uids):
 rs={r['metadata']['uid']:r for r in get('replicasets')['items']};pods=get('pods')['items'];out={}
 for name in names:
  dep=get('deployment',name);meta=dep['metadata'];spec=dep['spec'];status=dep.get('status',{});count=spec.get('replicas',1);container=COMPONENTS[name]
  if meta['uid']!=uids[name] or meta.get('deletionTimestamp') or type(count)is not int or count<=0:raise ValueError('Existing Deployment identity/replicas changed')
  if status.get('observedGeneration',0)<meta['generation'] or any(status.get(k,0)!=count for k in ('replicas','updatedReplicas','readyReplicas','availableReplicas')) or status.get('unavailableReplicas',0)!=0:raise ValueError('Deployment is not fully converged')
  template=[c for c in spec['template']['spec']['containers']if c['name']==container]
  if len(template)!=1 or template[0]['image']!=image:raise ValueError('Deployment source image differs')
  owned_rs={uid:r for uid,r in rs.items()if any(x.get('controller')and x.get('kind')=='Deployment'and x['uid']==meta['uid']for x in r['metadata'].get('ownerReferences',[]))}
  owned=[p for p in pods if any(x.get('controller')and x.get('kind')=='ReplicaSet'and x['uid']in owned_rs for x in p['metadata'].get('ownerReferences',[]))]
  if len(owned)!=count:raise ValueError('Old or missing owned Pods remain')
  selected=[]
  for pod in owned:
   r=owned_rs[owner(pod,'ReplicaSet')]
   if owner(r,'Deployment')!=meta['uid']:raise ValueError('ReplicaSet owner changed')
   rcontainers=[c for c in r['spec']['template']['spec']['containers']if c['name']==container]
   pc=[c for c in pod['spec']['containers']if c['name']==container];cs=[c for c in pod.get('status',{}).get('containerStatuses',[])if c['name']==container]
   if len(rcontainers)!=1 or rcontainers[0]['image']!=image or len(pc)!=1 or pc[0]['image']!=image or len(cs)!=1 or cs[0].get('image')!=image:raise ValueError('Owned Pod/ReplicaSet image differs')
   if pod['metadata'].get('deletionTimestamp') or pod['status'].get('phase')!='Running' or not any(x.get('type')=='Ready'and x.get('status')=='True'for x in pod['status'].get('conditions',[])) or not cs[0].get('ready') or not all(c.get('ready')for c in pod['status'].get('containerStatuses',[])):raise ValueError('Owned Pod is not Ready')
   if not re.search(r'sha256:[0-9a-f]{64}$',cs[0].get('imageID','')):raise ValueError('Immutable resolved Pod image required')
   selected.append({'name':pod['metadata']['name'],'uid':pod['metadata']['uid'],'replicaset_uid':r['metadata']['uid'],'image_id':cs[0]['imageID']})
  out[name]={'uid':meta['uid'],'generation':meta['generation'],'replicas':count,'pods':sorted(selected,key=lambda p:p['uid'])}
 return out
def verify(image,source_sha,phase,timeout,baseline=None):
 if not re.fullmatch('[0-9a-f]{40}',source_sha) or image!='localhost:30500/shizuha-admin:admin-'+source_sha[:7]:raise ValueError('Exact current source/image required')
 if run(['git','-C',str(ROOT),'rev-parse','HEAD']).strip().decode()!=source_sha or run(['git','-C',str(ROOT),'status','--porcelain']):raise ValueError('Native checked-out source differs')
 owners=existing_owners()
 if phase=='preflight':return {'source_sha':source_sha,'image':image,'owners':owners}
 if not isinstance(baseline,dict) or set(baseline)!={'source_sha','image','owners'} or baseline['source_sha']!=source_sha or baseline['image']!=image or baseline['owners']!=owners:raise ValueError('Pre-write owner identities changed')
 expected={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in SOURCE_FILES}
 names=tuple(COMPONENTS)if phase=='all'else ('shizuha-admin-worker','shizuha-admin-beat')
 uids=owners;deadline=time.monotonic()+timeout
 while True:
  try:
   if existing_owners()!=uids:raise ValueError('Existing owner identity changed')
   before=inspect(image,names,uids)
   code="import hashlib,json;from pathlib import Path;print(json.dumps({n:hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest()for n in "+repr(SOURCE_FILES)+"}))"
   for name,component in before.items():
    for pod in component['pods']:
     actual=json.loads(run(['kubectl','exec','-n','shizuha',pod['name'],'-c',COMPONENTS[name],'--','/app/.venv/bin/python','-c',code]))
     if actual!=expected:raise ValueError('Ready Pod application source differs')
   after=inspect(image,names,uids)
   if after!=before or existing_owners()!=uids:raise ValueError('Owner/Pod/source changed during verification')
   return {'source_sha':source_sha,'image':image,'phase':phase,'components':before,'application_source_sha256':expected}
  except (ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
   if time.monotonic()>=deadline:raise ValueError('Admin release did not converge to exact owned Ready sources')
   time.sleep(min(2,max(0,deadline-time.monotonic())))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-sha',required=True);p.add_argument('--image',required=True);p.add_argument('--phase',choices=('preflight','consumers','all'),default='all');p.add_argument('--expected-owners');p.add_argument('--timeout-seconds',type=int,default=300);a=p.parse_args()
 if not 0<=a.timeout_seconds<=300:raise ValueError('Existing bounded rollout deadline required')
 print(json.dumps(verify(a.image,a.source_sha,a.phase,a.timeout_seconds,json.loads(a.expected_owners)if a.expected_owners else None),sort_keys=True))
if __name__=='__main__':
 try:main()
 except (ValueError,KeyError,TypeError,OSError,subprocess.TimeoutExpired,json.JSONDecodeError):raise SystemExit('Admin release source/ownership verification refused')
