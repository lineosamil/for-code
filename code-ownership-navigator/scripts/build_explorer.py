#!/usr/bin/env python3
"""Build exactly one offline, self-contained HTML code explorer from a repository.

No third-party Python modules, network access, or generated companion files.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

LANG = {'.py':'Python','.pyw':'Python','.js':'JavaScript','.mjs':'JavaScript','.cjs':'JavaScript','.jsx':'JSX','.ts':'TypeScript','.tsx':'TSX','.vue':'Vue','.svelte':'Svelte','.go':'Go','.rs':'Rust','.java':'Java','.kt':'Kotlin','.swift':'Swift','.cs':'C#','.c':'C','.cc':'C++','.cpp':'C++','.h':'C/C++','.hpp':'C++','.rb':'Ruby','.php':'PHP','.html':'HTML','.css':'CSS','.scss':'SCSS','.sql':'SQL','.sh':'Shell'}
OMIT = {'.git','.hg','.svn','.venv','venv','env','node_modules','dist','build','target','.next','.nuxt','coverage','__pycache__','.cache','.pytest_cache','.mypy_cache','.idea','.vscode','vendor','out','bin','obj','.turbo','storybook-static','site-packages','bower_components','.gradle','.tox','generated'}
BAD_FILES = {'package-lock.json','yarn.lock','pnpm-lock.yaml','poetry.lock','Cargo.lock','Gemfile.lock','Pipfile.lock'}
BAD_PREFIX = ('.env','.git','id_rsa','id_ed25519','credentials','secrets','private_key')
SUSPECT = re.compile(r'(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|authorization|bearer\s|-----BEGIN|AKIA[0-9A-Z]{16})')
KEYWORDS = {'if','for','while','switch','catch','function','return','typeof','delete','await','yield','class','new','super','assert','print','len','map','filter','setTimeout','setInterval','require','import','console','isinstance','raise','else','elif','with','try'}
FUNC_JS = [
 re.compile(r'\b(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\('),
 re.compile(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>'),
 re.compile(r'\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:memo|forwardRef)\s*\('),
]
FUNC_GO = re.compile(r'^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(')
FUNC_RUST = re.compile(r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*\(')
FUNC_GENERIC = re.compile(r'^\s*(?:(?:public|private|protected|static|async|export|final|override|virtual|inline|abstract|suspend|def)\s+)*(?:[\w<>\[\],.?*&:]+\s+)+([A-Za-z_][\w$]*)\s*\(')
CALL_RE = re.compile(r'(?<![\w$])([A-Za-z_$][\w$]*)\s*\(')
JS_IMPORT = re.compile(r'(?:\b(?:import|export)\b[^;\n]*?\bfrom\s*|\bimport\s*\(|\brequire\s*\()\s*[\'\"]([^\'\"]+)[\'\"]')
CSS_HTML_LINK = re.compile(r'(?:src|href)=[\'\"]([^\'\"]+)[\'\"]')


def short(text, n=280):
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:n]


def safe_excerpt(lines, start, end, budget=24):
    out=[]
    for no in range(max(1,start), min(len(lines),end,start+budget-1)+1):
        s=lines[no-1]
        if SUSPECT.search(s): s='[보안상 숨긴 줄]'
        out.append({'n':no,'t':s[:240]})
    return out


def get_role(path):
    x=path.lower()
    if re.search(r'(^|/)(test|tests|spec|__tests__)/|(?:_test|\.test|\.spec)\.',x):return '테스트'
    if re.search(r'api|route|controller|endpoint|server',x):return 'API · 요청 처리'
    if re.search(r'component|view|page|screen|ui|widget',x):return '화면 · UI'
    if re.search(r'db|model|schema|repository|store|migration',x):return '데이터 · 저장'
    if re.search(r'config|setting|env',x):return '설정'
    if re.search(r'util|helper|common|shared|lib/',x):return '공통 기능'
    if re.search(r'(^|/)(main|app|index|cli|manage|entry|__main__)\.',x):return '시작 지점 후보'
    return '비즈니스 로직 · 기타'


def file_list(root, output, max_files, max_file_bytes, omit_extra):
    found=[]; skipped=0; skip_symlinks=0
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in OMIT and d not in omit_extra and not d.startswith('.') and not (Path(base)/d).is_symlink())
        for filename in sorted(files):
            path=Path(base)/filename
            if filename in BAD_FILES or filename.startswith(BAD_PREFIX) or filename.startswith('.') or path.is_symlink():
                skip_symlinks+=int(path.is_symlink()); continue
            if path.suffix.lower() not in LANG: continue
            if path.resolve()==output.resolve():continue
            try: st=path.stat()
            except OSError: continue
            if st.st_size>max_file_bytes:skipped+=1;continue
            found.append(path)
    found.sort(key=lambda p:p.relative_to(root).as_posix().lower())
    extra=max(0,len(found)-max_files)
    return found[:max_files],skipped+extra,skip_symlinks


def python_inspect(text, path, file_id, allow_code):
    lines=text.splitlines()
    modules=[]; entries=[]; funcs=[]; aliases={}
    try: tree=ast.parse(text,filename=path)
    except SyntaxError as e: return funcs, modules, entries, aliases, f'Python 구문 분석 실패 ({e.lineno}행): {short(e.msg,100)}'
    for stmt in ast.walk(tree):
        if isinstance(stmt,ast.Import):
            for entry in stmt.names:
                modules.append({'spec':entry.name,'kind':'python'});aliases[entry.asname or entry.name.split('.')[0]]=entry.name
        if isinstance(stmt,ast.ImportFrom):
            dots='.'*stmt.level; mod=dots+(stmt.module or '')
            modules.append({'spec':mod,'kind':'python'})
            for entry in stmt.names:aliases[entry.asname or entry.name]=mod+'::'+entry.name
    def expr_name(expr):
        if isinstance(expr,ast.Name):return expr.id
        if isinstance(expr,ast.Attribute):
            root=expr_name(expr.value)
            return (root+'.' if root else '')+expr.attr
        return ''
    def visit(nodes, prefix='', cls=''):
        for node in nodes:
            if isinstance(node,ast.ClassDef):visit(node.body,prefix+node.name+'.',node.name)
            elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                qualified=prefix+node.name
                calls=[]
                for child in ast.walk(node):
                    if isinstance(child,ast.Call):
                        s=expr_name(child.func)
                        if s and s not in calls and s.split('.')[0] not in KEYWORDS:calls.append(s)
                decor=[expr_name(d.func) if isinstance(d,ast.Call) else expr_name(d) for d in node.decorator_list]
                sig=short(lines[node.lineno-1],220)
                doc=short(ast.get_docstring(node),280)
                item={'id':'','file':file_id,'name':node.name,'qual':qualified,'line':node.lineno,'end':getattr(node,'end_lineno',node.lineno),'signature':sig,'summary':doc,'callsRaw':calls[:80],'calls':[],'calledBy':[],'kind':'python-ast','decorators':decor,'code':safe_excerpt(lines,node.lineno,getattr(node,'end_lineno',node.lineno)) if allow_code else []}
                funcs.append(item)
                if any(d and re.search(r'(^|\.)(get|post|put|delete|patch|route|command|task)$',d) for d in decor):
                    entries.append((qualified,'엔드포인트 / 명령'))
                if node.name in ('main','run','app','cli','start','handle_request','handler','process','execute','get','post') and not prefix:entries.append((qualified,'시작 / 주요 기능'))
                visit(node.body,prefix+node.name+'.',cls)
    visit(tree.body)
    if re.search(r'if\s+__name__\s*==\s*[\'\"]__main__[\'\"]',text):
        for f in funcs:
            if f['name']=='main':entries.append((f['qual'],'직접 실행'))
    return funcs,modules,entries,aliases,''


def other_inspect(text, path, file_id, lang, allow_code):
    lines=text.splitlines(); entries=[]; funcs=[]; imports=[]; aliases={}
    if lang in ('JavaScript','TypeScript','JSX','TSX','Vue','Svelte'):
        imports=[{'spec':p,'kind':'js'} for p in JS_IMPORT.findall(text)]
    elif lang in ('HTML','CSS','SCSS'):
        imports=[{'spec':p,'kind':'asset'} for p in CSS_HTML_LINK.findall(text)]
    parser='regex-heuristic'
    for i,line in enumerate(lines):
        m=None
        if lang in ('JavaScript','TypeScript','JSX','TSX','Vue','Svelte'):
            for reg in FUNC_JS:
                m=reg.search(line)
                if m:break
        elif lang=='Go':m=FUNC_GO.match(line)
        elif lang=='Rust':m=FUNC_RUST.match(line)
        elif lang not in ('HTML','CSS','SCSS','SQL','Shell'):
            m=FUNC_GENERIC.match(line)
        if not m:continue
        name=m.group(1)
        if name in KEYWORDS:continue
        if len(funcs)>2500:break
        # A pragmatic, bounded approximation: stop after next function declaration or 70 lines.
        end=min(i+70,len(lines)); balance=0; opened=False
        for k in range(i,end):
            ln=lines[k].split('//',1)[0]
            balance+=ln.count('{')-ln.count('}')
            if '{' in ln: opened=True
            if opened and balance<=0:end=k+1;break
        body='\n'.join(lines[i:end])
        calls=list(dict.fromkeys(c for c in CALL_RE.findall(body) if c not in KEYWORDS and c!=name))[:80]
        fun={'id':'','file':file_id,'name':name,'qual':name,'line':i+1,'end':end,'signature':short(line,220),'summary':'','callsRaw':calls,'calls':[],'calledBy':[],'kind':parser,'decorators':[],'code':safe_excerpt(lines,i+1,end) if allow_code else []}
        funcs.append(fun)
        if re.search(r'\b(?:export|default|route|app\.|router\.)\b',line) or name.lower() in ('main','app','server','handler','index','run','start','setup'):
            entries.append((name,'진입 / 공개 기능 후보'))
    return funcs,imports,entries,aliases,''


def resolve_import(spec, file_path, candidates, kind):
    spec=spec.split('?')[0].split('#')[0]
    choices=[]
    if kind=='python':
        if spec.startswith('.'):
            level=len(spec)-len(spec.lstrip('.'))
            rest=spec[level:].replace('.','/')
            base=Path(file_path).parent
            for _ in range(max(0,level-1)):base=base.parent
            x=(base/rest).as_posix() if rest else base.as_posix()
        else:x=spec.replace('.','/')
        choices=[x+'.py',x+'/__init__.py',x+'.pyw']
    else:
        if not spec.startswith('.'):return None
        x=(Path(file_path).parent/spec).as_posix()
        import posixpath
        x=posixpath.normpath(x)
        choices=[x,*(x+ext for ext in ('.js','.jsx','.ts','.tsx','.mjs','.cjs','.vue','.svelte','.html','.css')),*(x+'/index'+ext for ext in ('.js','.ts','.tsx','.jsx'))]
    for c in choices:
        if c in candidates:return candidates[c]
    return None


def build(root, output, max_files, max_file_bytes, allow_code, omitted, annotations):
    files=[]; functions=[]; entries=[]; warnings=[]; alias_by_file={}; raw_imports={}
    paths,skipped,symlinks=file_list(root,output,max_files,max_file_bytes,set(omitted))
    if not paths:raise ValueError('지원되는 소스 파일을 찾을 수 없습니다. 제외 경로/프로젝트 폴더를 확인하세요.')
    for abs_path in paths:
        rel=abs_path.relative_to(root).as_posix(); fid=len(files)
        try:text=abs_path.read_text(encoding='utf-8-sig',errors='replace')
        except (OSError,UnicodeError):warnings.append(f'읽기 실패: {rel}');continue
        lines=text.splitlines(); lang=LANG[abs_path.suffix.lower()]
        node={'id':fid,'path':rel,'language':lang,'role':get_role(rel),'lines':len(lines),'sha':hashlib.sha256(text.encode()).hexdigest()[:10],'imports':[],'functions':[],'notes':''}
        if lang=='Python': funs,imports,ens,aliases,error=python_inspect(text,rel,fid,allow_code)
        else:funs,imports,ens,aliases,error=other_inspect(text,rel,fid,lang,allow_code)
        if error:node['notes']=error;warnings.append(f'{rel}: {error}')
        node['id']=len(files)
        for fun in funs:
            fun['file']=node['id'];fun['id']=len(functions);node['functions'].append(fun['id']);functions.append(fun)
        for qual,kind in ens:
            match=next((f['id'] for f in funs if f['qual']==qual),None)
            if match is not None:entries.append({'fn':match,'kind':kind})
        files.append(node);alias_by_file[node['id']]=aliases;raw_imports[node['id']]=imports
    path_ids={f['path']:f['id'] for f in files}
    for f in files:
        for item in raw_imports[f['id']]:
            target=resolve_import(item['spec'],f['path'],path_ids,item['kind'])
            if target is not None and target!=f['id'] and target not in f['imports']:f['imports'].append(target)
    lookup={}
    for f in functions:
        parent=files[f['file']]
        lookup[(f['file'],f['qual'])]=f['id']
    # Only same-file or explicitly imported edges count; never claim heuristic edges are definitive runtime order.
    import_name_index={}
    for fn in functions:
        mod=files[fn['file']]['path']
        module=mod.rsplit('.',1)[0].replace('/','.')
        import_name_index.setdefault((module,fn['name']),[]).append(fn['id'])
    for fn in functions:
        parent=files[fn['file']]; byname={}
        for other_id in parent['functions']:
            other=functions[other_id];byname.setdefault(other['name'],[]).append(other_id)
        aliases=alias_by_file.get(fn['file'],{})
        for raw in fn['callsRaw']:
            found=None
            if raw.startswith('self.') or raw.startswith('cls.'):
                shortname=raw.rsplit('.',1)[-1]
                classname=fn['qual'].split('.')[0]
                found=lookup.get((fn['file'],classname+'.'+shortname))
            if found is None and '.' not in raw:
                ids=byname.get(raw,[])
                if len(ids)==1:found=ids[0]
            if found is None and raw in aliases:
                alias=aliases[raw]
                if '::' in alias:
                    mod,sym=alias.split('::',1)
                    if not mod.startswith('.'):
                        ids=import_name_index.get((mod,sym),[])
                        if len(ids)==1:found=ids[0]
            if found is None and '.' in raw:
                alias_name,sub=raw.split('.',1)
                if alias_name in aliases:
                    mod=aliases[alias_name]
                    ids=import_name_index.get((mod,sub.split('.')[0]),[])
                    if len(ids)==1:found=ids[0]
            if found is None and '.' not in raw:
                for imported_id in parent['imports']:
                    candidates=[fid for fid in files[imported_id]['functions'] if functions[fid]['name']==raw]
                    if len(candidates)==1:
                        # Only confident enough if the symbol is explicitly imported in Python.
                        if parent['language']=='Python' and raw not in aliases:continue
                        found=candidates[0];break
            if found is not None and found!=fn['id'] and found not in fn['calls']:fn['calls'].append(found)
    for f in functions:
        for to in f['calls']:
            if f['id'] not in functions[to]['calledBy']:functions[to]['calledBy'].append(f['id'])
    # Entry candidates: explicit first, then independent main/route functions, then top connected nodes.
    features=[]; seen=set()
    for item in entries:
        if item['fn'] in seen:continue
        fn=functions[item['fn']]; seen.add(fn['id'])
        features.append({'id':len(features),'fn':fn['id'],'title':fn['qual'],'kind':item['kind'],'summary':fn['summary'] or get_role(files[fn['file']]['path']),'evidence':'후보: 이름·데코레이터·내보내기 규칙'})
    if len(features)<8:
        ranked=sorted(functions,key=lambda f:(len(f['calledBy'])==0, len(f['calls'])+len(f['calledBy']),f['name'].lower() in ('main','app','run')),reverse=True)
        for fn in ranked:
            if fn['id'] in seen or files[fn['file']]['role']=='테스트':continue
            seen.add(fn['id']);features.append({'id':len(features),'fn':fn['id'],'title':fn['qual'],'kind':'주요 함수 후보','summary':fn['summary'] or files[fn['file']]['role'],'evidence':'후보: 정적 호출 관계 및 이름'});
            if len(features)>=14:break
    ann=annotations or {}
    file_ann=ann.get('files',{})
    fn_ann=ann.get('functions',{})
    feature_ann=ann.get('features',{})
    for f in files:
        if f['path'] in file_ann and isinstance(file_ann[f['path']],str):f['notes']=short(file_ann[f['path']],450)
    for f in functions:
        key=files[f['file']]['path']+'::'+f['qual']
        if key in fn_ann and isinstance(fn_ann[key],str):f['summary']=short(fn_ann[key],550)
    for feature in features:
        f=functions[feature['fn']];key=files[f['file']]['path']+'::'+f['qual']
        if key in feature_ann and isinstance(feature_ann[key],str):feature['summary']=short(feature_ann[key],550)
    commit='';branch='';dirty=''
    for args, name in [(['git','rev-parse','--short','HEAD'],'commit'),(['git','branch','--show-current'],'branch'),(['git','status','--porcelain','--untracked-files=no'],'dirty')]:
        try:
            proc=subprocess.run(args,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=3)
            if proc.returncode==0:
                if name=='commit':commit=proc.stdout.strip()
                elif name=='branch':branch=proc.stdout.strip()
                else:dirty='수정 중' if proc.stdout.strip() else '커밋과 일치'
        except (OSError,subprocess.TimeoutExpired):pass
    meta={'name':root.name,'generated':dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='minutes'),'commit':commit or '정보 없음','branch':branch or '정보 없음','workingTree':dirty or '확인 불가','skipped':skipped,'skippedSymlink':symlinks,'codeIncluded':allow_code,'analysis':'Python은 AST, 다른 언어는 정규식 기반 후보 탐지. 정적 호출 관계는 실제 실행 순서를 보증하지 않습니다.','warningCount':len(warnings)}
    return {'meta':meta,'files':files,'functions':functions,'features':features,'warnings':warnings[:35]}


def main():
    ap=argparse.ArgumentParser(description='Generate ONE standalone code-explorer.html from a project')
    ap.add_argument('project',type=Path,help='Project root')
    ap.add_argument('--output',type=Path,help='Output HTML; default <project>/code-explorer.html')
    ap.add_argument('--max-files',type=int,default=900)
    ap.add_argument('--max-file-bytes',type=int,default=240000)
    ap.add_argument('--exclude',action='append',default=[],help='Directory name to omit; repeat as needed')
    ap.add_argument('--no-code',action='store_true',help='Do not embed even sanitized code excerpts')
    ap.add_argument('--annotations',type=Path,help='Optional existing temporary JSON with {files,functions,features} explanation maps')
    args=ap.parse_args()
    root=args.project.expanduser().resolve()
    if not root.is_dir():ap.error('프로젝트 디렉터리가 존재하지 않습니다.')
    output=(args.output or root/'code-explorer.html').expanduser().resolve()
    if args.max_files<1 or args.max_file_bytes<1:ap.error('limits must be positive')
    ann={}
    if args.annotations:
        ann=json.loads(args.annotations.read_text(encoding='utf-8'))
        if not isinstance(ann,dict):ap.error('--annotations must contain a JSON object')
    data=build(root,output,args.max_files,args.max_file_bytes,not args.no_code,args.exclude,ann)
    template=(Path(__file__).parent.parent/'assets'/'explorer.template.html').read_text(encoding='utf-8')
    js=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    html=template.replace('/*__DATA__*/',js)
    if '/*__DATA__*/' in html:raise RuntimeError('HTML data slot not resolved')
    if output.exists():
        with output.open('r',encoding='utf-8',errors='replace') as previous:
            if 'code-ownership-navigator-generated' not in previous.read(300):
                raise ValueError('출력 위치에 기존의 다른 파일이 있어 덮어쓰지 않습니다. 다른 --output 경로를 선택하세요.')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html,encoding='utf-8')
    print(f'HTML: {output}\nFiles: {len(data["files"])}; functions: {len(data["functions"])}; features: {len(data["features"])}; skipped: {data["meta"]["skipped"]}')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        print(f'Error: {exc}',file=sys.stderr);sys.exit(2)
