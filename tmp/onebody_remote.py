import pathlib
import subprocess
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig')
result = subprocess.run(
    ['ssh', '-i', 'C:/Users/AndRo/.ssh/leadaptive_droplet', '-o', 'BatchMode=yes',
     'root@167.71.63.154',
     'cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -'],
    input=source, capture_output=True, text=True, encoding='utf-8', timeout=300,
)
if len(sys.argv) > 2:
    pathlib.Path(sys.argv[2]).write_text(result.stdout, encoding='utf-8')
else:
    print(result.stdout)
if result.returncode:
    print(result.stderr, file=sys.stderr)
    raise SystemExit(result.returncode)
