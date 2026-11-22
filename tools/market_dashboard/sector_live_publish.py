"""Bounded, resumable transport for the accepted public view documents."""
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PART_BYTES=256*1024
MAX_BODY_BYTES=950*1024
MAX_BATCH_RAW_BYTES=64*1024
PRIVATE=re.compile(r'Bearer\s|X-api-key|ak_[A-Za-z0-9]{15,}|/Users/|access_token|refresh_token',re.I)
KEY=re.compile(r'latest|catalog-(?:industry|concept)|history-(?:industry|concept)-(?:return1d|strength|opportunity|risk)|detail-88[156]\d{3}\.TI')


def digest(value):return hashlib.sha256(value).hexdigest()


def _atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.pending')
    temporary.write_text(json.dumps(value,separators=(',',':')));temporary.chmod(0o600);temporary.replace(path)


def prepare_documents(directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    generation=manifest['generation']
    if not re.fullmatch('[0-9a-f]{64}',generation):raise ValueError('INVALID_GENERATION')
    documents=[];digests=[];keys=[];current_members=0;current_valid=0
    for file in sorted((directory/generation).glob('*.json')):
        key=file.stem
        if not KEY.fullmatch(key):raise ValueError('INVALID_DOCUMENT_KEY')
        content=file.read_bytes()
        if PRIVATE.search(content.decode('utf8')):raise ValueError('PRIVATE_EXPORT')
        value=json.loads(content)
        if not isinstance(value,dict):raise ValueError('INVALID_EXPORT')
        if key.startswith('detail-') and isinstance(value.get('constituentsByDate'),dict):
            current=value['constituentsByDate'].get(manifest['marketDate'],{})
            current_members+=current.get('total',0);current_valid+=current.get('validCount',0)
        compressed=gzip.compress(content,mtime=0)
        if len(compressed)>4*1024*1024:raise ValueError('DOCUMENT_TOO_LARGE')
        full_digest=digest(compressed);digests.append(key+':'+full_digest);keys.append(key)
        count=(len(compressed)+PART_BYTES-1)//PART_BYTES
        for index in range(count):
            part=compressed[index*PART_BYTES:(index+1)*PART_BYTES]
            documents.append(dict(key=key,gzipBase64=base64.b64encode(part).decode('ascii'),
                digest=full_digest,partIndex=index,partCount=count,partDigest=digest(part),_rawBytes=len(content)))
    if len(keys)!=491 or len([k for k in keys if k.startswith('detail-881')])!=90 or len([k for k in keys if k.startswith(('detail-885','detail-886'))])!=390:
        raise ValueError('INCOMPLETE_EXPORT')
    if current_members and not current_valid:raise ValueError('CURRENT_CONSTITUENT_DATA_UNAVAILABLE')
    manifest={k:manifest[k] for k in ('generation','marketDate','observedAt','exportedAt','storageMode','historyBaseGeneration','sourceGeneration') if k in manifest}
    if manifest.get('storageMode')=='daily-v1':
        if not re.fullmatch('[0-9a-f]{64}',manifest.get('historyBaseGeneration','')) or generation!=digest(('daily-v1\n'+manifest.get('sourceGeneration','')).encode()):raise ValueError('INVALID_DAILY_GENERATION')
    manifest.update(mode='live',automaticUpdates=True)
    return dict(generation=generation,manifest=manifest,documentCount=len(keys),
        digest=digest('\n'.join(digests).encode()),documents=documents)


def publish_export(directory,transport,*,checkpoint,max_workers=2,expected_active_generation=None):
    if expected_active_generation is not None and not re.fullmatch('[0-9a-f]{64}',expected_active_generation):raise ValueError('INVALID_EXPECTED_GENERATION')
    started=time.monotonic()
    prepared=prepare_documents(directory);generation=prepared['generation']
    checkpoint=Path(checkpoint)
    prior=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    state=prior if prior.get('generation')==generation else dict(generation=generation,uploaded=[],activated=False)
    state.update(sourceGeneration=prepared['manifest'].get('sourceGeneration',generation),storageMode=prepared['manifest'].get('storageMode','full'))
    transport({k:v for k,v in prepared.items() if k!='documents'}|{'action':'begin'})
    uploaded=set(state['uploaded']);batch=[];batches=[]
    for document in prepared['documents']:
        identity=f"{document['key']}:{document['partIndex']}:{document['partDigest']}"
        if identity in uploaded:continue
        raw_size=sum(d.get('_rawBytes',MAX_BATCH_RAW_BYTES+1) for d in batch)+document.get('_rawBytes',MAX_BATCH_RAW_BYTES+1)
        if batch and (len(batch)>=6 or raw_size>MAX_BATCH_RAW_BYTES or len(json.dumps(dict(action='documents',generation=generation,documents=batch+[document])).encode())>MAX_BODY_BYTES):
            batches.append(batch);batch=[]
        batch.append(document)
    if batch:batches.append(batch)
    pool=ThreadPoolExecutor(max_workers=max_workers)
    futures={}
    try:
        futures={pool.submit(transport,dict(action='documents',generation=generation,documents=[{k:v for k,v in d.items() if not k.startswith('_')} for d in items])):items for items in batches}
        for future in as_completed(futures):
            try:future.result()
            except Exception:
                state['lastFailedParts']=[{'key':d['key'],'partIndex':d['partIndex']} for d in futures[future]]
                _atomic(checkpoint,state)
                raise
            uploaded.update(f"{d['key']}:{d['partIndex']}:{d['partDigest']}" for d in futures[future])
            state['uploaded']=sorted(uploaded);_atomic(checkpoint,state)
    except Exception:
        for future in futures:future.cancel()
        raise
    finally:pool.shutdown(wait=True,cancel_futures=True)
    activation=dict(action='activate',generation=generation)
    if expected_active_generation is not None:activation['expectedActiveGeneration']=expected_active_generation
    transport(activation)
    state.pop('lastFailedParts',None);state['activated']=True;_atomic(checkpoint,state)
    return dict(generation=generation,sourceGeneration=prepared['manifest'].get('sourceGeneration',generation),documents=prepared['documentCount'],parts=len(prepared['documents']),
        requests=len(batches)+2,elapsedSeconds=time.monotonic()-started,
        plannedWireBytes=sum(len(json.dumps([{k:v for k,v in d.items() if not k.startswith('_')} for d in items],separators=(',',':')).encode()) for items in batches))


class LiveTransport:
    def __init__(self,token,*,base='https://newsmonitor.pages.dev',opener=urlopen,sleep=time.sleep):
        if base!='https://newsmonitor.pages.dev':raise ValueError('INVALID_PUBLICATION_HOST')
        if not token or any(c in token for c in '\r\n'):raise ValueError('MISSING_PUBLISH_CREDENTIAL')
        self.token,self.base,self.opener,self.sleep=token,base,opener,sleep
        self.deadline=None
        self.context=ssl.create_default_context()
        system_ca=Path('/etc/ssl/cert.pem')
        if sys.platform=='darwin' and system_ca.is_file():
            # python.org macOS builds may lack their own CA symlink. Reuse the
            # OS trust bundle; never disable certificate or hostname checks.
            self.context.load_verify_locations(cafile=str(system_ca))

    def __call__(self,body):
        encoded=json.dumps(body,separators=(',',':')).encode()
        if len(encoded)>1024*1024:raise ValueError('PUBLICATION_BODY_TOO_LARGE')
        for attempt in range(3):
            remaining=self.deadline-time.monotonic() if self.deadline is not None else 35
            if remaining<=0:raise ValueError('PUBLICATION_DEADLINE_EXCEEDED')
            request=Request(self.base+'/api/sector-live/publish',data=encoded,method='POST',
                headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json','User-Agent':'FinanceMonitorMarketDashboard/1.0'})
            try:
                with self.opener(request,timeout=min(35,remaining),context=self.context) as response:
                    result=json.loads(response.read(1024*1024))
                if result.get('ok') is not True:raise ValueError('PUBLICATION_REJECTED')
                return result
            except HTTPError as error:
                retryable=error.code in (408,429,500,502,503,504)
                if not retryable or attempt==2:
                    safe=''
                    try:
                        raw=error.read(4096).decode('utf8',errors='replace')
                        try:code=json.loads(raw).get('error','')
                        except Exception:
                            match=re.search(r'error\s*code\s*:?\s*(1\d{3})',raw,re.I)
                            code='CLOUDFLARE_'+match.group(1) if match else 'WORKER_RESOURCE_LIMIT' if 'exceeded resource limits' in raw.lower() else ''
                        if isinstance(code,str) and re.fullmatch('[A-Z0-9_]{1,80}',code):safe='_'+code
                    except Exception:pass
                    raise ValueError('PUBLICATION_HTTP_'+str(error.code)+safe) from None
            except URLError as error:
                if isinstance(error.reason,ssl.SSLCertVerificationError):raise ValueError('PUBLICATION_SSL_CERTIFICATE_FAILED') from None
                if attempt==2:raise ValueError('PUBLICATION_NETWORK_FAILED') from None
            except (TimeoutError,OSError):
                if attempt==2:raise ValueError('PUBLICATION_NETWORK_FAILED') from None
            self.sleep(2**attempt)
