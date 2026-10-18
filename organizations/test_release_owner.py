"""Actual native shell + read-only owner/source verifier, synthetic Kubernetes only."""
import hashlib,json,os,shutil,subprocess,tempfile,textwrap,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NAMES={'shizuha-admin':'shizuha-admin','shizuha-admin-worker':'worker','shizuha-admin-beat':'beat'}
SOURCE_FILES=['organizations/models.py','organizations/views.py','organizations/jit_dispatch.py','organizations/tasks.py','shizuha_admin/settings.py']
FAKE=r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['FAKE_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
with open(os.environ['FAKE_CALLS'],'a')as f:f.write(json.dumps(a)+'\n')
names={'shizuha-admin':'shizuha-admin','shizuha-admin-worker':'worker','shizuha-admin-beat':'beat'}
def has(v):return v in a
def target():return next((x.split('/')[-1]for x in a if x.split('/')[-1]in names),None)
def dep(n):
 if s.get('missing')==n:raise SystemExit(1)
 c=names[n];r=0 if s.get('zero_replicas')==n else 1
 return {'metadata':{'name':n,'namespace':'shizuha','uid':('changed-'+n if (s.get('uid_drift')==n and sum('deployment'in x and n in x for x in [json.loads(y)for y in Path(os.environ['FAKE_CALLS']).read_text().splitlines()])>1) or (s.get('uid_after_exec')==n and any('exec'in json.loads(y)for y in Path(os.environ['FAKE_CALLS']).read_text().splitlines())) else 'dep-'+n),'generation':2,'labels':{'app.kubernetes.io/managed-by':'Other'if s.get('foreign_owner')==n else 'Helm'},'annotations':{'meta.helm.sh/release-name':'shizuha-admin','meta.helm.sh/release-namespace':'shizuha'}},'spec':{'replicas':r,'selector':{'matchLabels':{'owner':n}},'template':{'spec':{'containers':[{'name':c,'image':s['images'][n]}]}}},'status':{'observedGeneration':2,'replicas':r,'updatedReplicas':r,'readyReplicas':0 if s.get('unready')==n else r,'availableReplicas':r,'unavailableReplicas':0}}
def rs(n):return {'metadata':{'name':'rs-'+n,'uid':'rs-'+n,'ownerReferences':[{'kind':'Deployment','uid':'dep-'+n,'controller':True}]},'spec':{'template':{'spec':{'containers':[{'name':names[n],'image':s['images'][n]}]}}}}
def pod(n):
 c=names[n];uid='wrong'if s.get('wrong_owner')==n else 'rs-'+n
 return {'metadata':{'name':'pod-'+n,'uid':'pod-'+n,'ownerReferences':[{'kind':'ReplicaSet','uid':uid,'controller':True}]},'spec':{'containers':[{'name':c,'image':s['images'][n]}]},'status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}],'containerStatuses':[{'name':c,'image':s['images'][n],'imageID':'containerd://sha256:'+'a'*64,'ready':True}]}}
if has('get'):
 n=target()
 if has('secret'):
  if s.get('missing_secret'):raise SystemExit(1)
  print('present')
 elif any('jsonpath' in x for x in a):
  if any('HIVE_SERVICE_SIGNING_KEY'in x for x in a):print('hive-service-signing-key key')
  else:print(s['images'][n])
 elif has('deployment')or has('deploy'):print(json.dumps(dep(n)))
 elif has('replicasets')or has('rs'):print(json.dumps({'items':[rs(n)for n in names]}))
 elif has('pods'):
  rows=[pod(n)for n in names]
  if s.get('old_pod'):
   old=pod(s['old_pod']);old['metadata']['name']='retained-old';old['metadata']['uid']='retained-old';old['spec']['containers'][0]['image']='localhost:30500/shizuha-admin:admin-old';rows.append(old)
  print(json.dumps({'items':rows}))
 else:raise SystemExit(2)
elif has('patch'):
 n=target();s['images'][n]=s['image'];p.write_text(json.dumps(s));print('{}')
elif has('set')and has('image'):
 n=target();s['images'][n]=s['image'];p.write_text(json.dumps(s));print('updated')
elif has('rollout'):print('rolled out')
elif has('exec'):
 if has('manage.py'):pass
 else:
  n=next((x for x in a if x.startswith('pod-')), '')[4:];v=dict(s['hashes'])
  if s.get('stale_source')==n:v['organizations/jit_dispatch.py']='0'*64
  print(json.dumps(v))
else:raise SystemExit(2)
'''
class ReleaseOwnerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.repo=self.base/'repo';self.repo.mkdir();self.bin=self.base/'bin';self.bin.mkdir();self.state=self.base/'state.json';self.calls=self.base/'calls.jsonl'
  for n in SOURCE_FILES:
   p=self.repo/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic '+n+'\n')
  helper=ROOT/'.forgejo/scripts/verify-admin-release.py'
  if helper.exists():
   p=self.repo/'.forgejo/scripts/verify-admin-release.py';p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(helper,p)
  self.env=dict(os.environ,PATH=str(self.bin)+os.pathsep+os.environ['PATH'],FAKE_STATE=str(self.state),FAKE_CALLS=str(self.calls),GIT_AUTHOR_NAME='Synthetic',GIT_COMMITTER_NAME='Synthetic',GIT_AUTHOR_EMAIL='fixture@example.invalid',GIT_COMMITTER_EMAIL='fixture@example.invalid')
  fixture_paths=SOURCE_FILES+(['.forgejo/scripts/verify-admin-release.py']if helper.exists()else [])
  for args in [('init','-q'),('add','--',*fixture_paths),('commit','-qm','synthetic source')]:subprocess.run(['git','-C',str(self.repo),*args],env=self.env,check=True,capture_output=True)
  self.sha=subprocess.check_output(['git','-C',str(self.repo),'rev-parse','HEAD'],env=self.env,text=True).strip();self.image='localhost:30500/shizuha-admin:admin-'+self.sha[:7]
  self.data={'image':self.image,'images':{n:'localhost:30500/shizuha-admin:admin-old'for n in NAMES},'hashes':{n:hashlib.sha256((self.repo/n).read_bytes()).hexdigest()for n in SOURCE_FILES}}
  p=self.bin/'kubectl';p.write_text(FAKE);p.chmod(0o755);self.save()
 def save(self):self.state.write_text(json.dumps(self.data))
 def calls_list(self):return [json.loads(x)for x in self.calls.read_text().splitlines()]if self.calls.exists()else []
 def shell(self):
  text=(ROOT/'.forgejo/workflows/deploy.yml').read_text();block=text.split('      - name: Deploy multi-arch image + verify\n',1)[1].split('        run: |\n',1)[1];return textwrap.dedent(block).replace('${{ github.sha }}',self.sha)
 def verify(self):
  args=['python3','.forgejo/scripts/verify-admin-release.py','--source-sha',self.sha,'--image',self.image,'--timeout-seconds','0']
  pre=subprocess.run(args+['--phase','preflight'],cwd=self.repo,env=self.env,capture_output=True,text=True)
  if pre.returncode:return pre
  return subprocess.run(args+['--expected-owners',pre.stdout.strip()],cwd=self.repo,env=self.env,capture_output=True,text=True)
 def test_actual_native_owner_rolls_and_verifies_all_three(self):
  result=subprocess.run(['bash','-euo','pipefail','-c',self.shell()],cwd=self.repo,env=self.env,capture_output=True,text=True,timeout=20);self.assertEqual(result.returncode,0,result.stderr)
  value=json.loads(self.state.read_text());self.assertEqual(value['images'],{n:self.image for n in NAMES})
  calls=self.calls_list();verified={next((v for v in a if v.startswith('pod-')), '')[4:]for a in calls if 'exec'in a and 'manage.py'not in a};self.assertEqual(verified,set(NAMES))
  api_patch=next(i for i,a in enumerate(calls)if 'patch'in a and 'shizuha-admin'in a)
  for name in ('shizuha-admin-worker','shizuha-admin-beat'):
   self.assertTrue(any('exec'in a and 'pod-'+name in a for a in calls[:api_patch]))
 def test_deploy_job_checks_out_its_own_exact_source(self):
  text=(ROOT/'.forgejo/workflows/deploy.yml').read_text().split('  deploy:\n',1)[1];self.assertIn('uses: actions/checkout@v4',text);self.assertIn('git rev-parse HEAD',text)
 def test_verifier_accepts_all_three_exact_owned_ready_sources_read_only(self):
  self.data['images']={n:self.image for n in NAMES};self.save();r=self.verify();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(set(json.loads(r.stdout)['components']),set(NAMES));self.assertFalse(any('patch'in a or 'set'in a for a in self.calls_list()))
 def test_stale_source_or_wrong_owner_or_partial_readiness_refuses(self):
  for field,n in [('stale_source','shizuha-admin-worker'),('stale_source','shizuha-admin-beat'),('wrong_owner','shizuha-admin-worker'),('unready','shizuha-admin-beat'),('old_pod','shizuha-admin-worker'),('uid_drift','shizuha-admin-worker'),('uid_after_exec','shizuha-admin-worker'),('zero_replicas','shizuha-admin-beat')]:
   with self.subTest(field=field,name=n):
    self.data['images']={x:self.image for x in NAMES};self.data[field]=n;self.save();self.assertNotEqual(self.verify().returncode,0);del self.data[field]
 def test_foreign_helm_owner_and_missing_signing_key_refuse_before_any_write(self):
  for field,value in [('foreign_owner','shizuha-admin-worker'),('missing_secret',True)]:
   with self.subTest(field=field):
    self.data[field]=value;self.save();self.calls.unlink(missing_ok=True);r=subprocess.run(['bash','-euo','pipefail','-c',self.shell()],cwd=self.repo,env=self.env,capture_output=True,text=True,timeout=20);self.assertNotEqual(r.returncode,0);self.assertFalse(any('patch'in a or 'set'in a for a in self.calls_list()));del self.data[field]
 def test_missing_existing_worker_refuses_before_any_write(self):
  for name in NAMES:
   with self.subTest(name=name):
    self.data['missing']=name;self.save();self.calls.unlink(missing_ok=True);r=subprocess.run(['bash','-euo','pipefail','-c',self.shell()],cwd=self.repo,env=self.env,capture_output=True,text=True,timeout=20);self.assertNotEqual(r.returncode,0);self.assertFalse(any('patch'in a or 'set'in a for a in self.calls_list()))
if __name__=='__main__':unittest.main()
