from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import subprocess

roots = ['app', 'prompts', 'knowledge', 'signatures', 'clients', 'scripts']
files = [p for root in roots for p in Path(root).rglob('*')
         if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
files += [Path('Dockerfile'), Path('docker-compose.yml'), Path('requirements.txt')]
bundle = Path('tmp/responder-deploy-20261104.zip')
with ZipFile(bundle, 'w', ZIP_DEFLATED) as archive:
 for p in files:
  archive.write(p, p.as_posix())
subprocess.run(['scp','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes',
                str(bundle),'root@167.71.63.154:/tmp/responder-deploy-20261104.zip'],check=True)
print(f'Transferred {len(files)} runtime files for staging.')
