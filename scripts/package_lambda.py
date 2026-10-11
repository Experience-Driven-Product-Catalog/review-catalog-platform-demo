"""Build a reproducible Linux x86_64 Lambda ZIP without Docker."""
from pathlib import Path
import shutil,subprocess,zipfile,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'.build';out.mkdir(exist_ok=True)
package=out/'package'
shutil.rmtree(package,ignore_errors=True)
shutil.copytree(ROOT/'backend',package,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
subprocess.run(['uv','export','--no-dev','--no-emit-project','--format','requirements-txt','--output-file',str(out/'requirements.txt')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
subprocess.run(['uv','pip','install','--python-version','3.12','--python-platform','x86_64-manylinux_2_28','--only-binary',':all:','--target',str(package/'lib'),'-r',str(out/'requirements.txt')],cwd=ROOT,check=True)
for p in package.rglob('__pycache__'):shutil.rmtree(p)
(package/'run.sh').chmod(0o755)
archive=out/'lambda.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(package.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(package))
print('Lambda ZIP:',round(archive.stat().st_size/1024/1024,2),'MiB; sha256:',hashlib.sha256(archive.read_bytes()).hexdigest())
