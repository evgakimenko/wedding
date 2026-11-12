#!/bin/bash
# Сборка: dev/app.src.html + dev/tpl.json -> index.html, dev/sw.src.js -> sw.js (корень репозитория = сайт)
set -e
cd "$(dirname "$0")/.."
python3 - <<'P'
import json,re,hashlib
tpl=json.load(open('dev/tpl.json')); src=open('dev/app.src.html').read()
out=src.replace('/*TPL*/null', json.dumps(tpl,ensure_ascii=False)); open('index.html','w').write(out)
open('/tmp/b.js','w').write(re.findall(r'<script>\n(.*?)</script>',out,re.S)[0])
open('sw.js','w').write(open('dev/sw.src.js').read().replace('__VER__',hashlib.md5(out.encode()).hexdigest()[:8]))
P
node --check /tmp/b.js && node --check sw.js && echo BUILD_OK
