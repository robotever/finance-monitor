"""Strict parsing and bounded, authenticated access to official fund-flow history.

Transport injection: callable(url, headers) -> decoded official response dictionary.
No retries, redirects, proxy rotation or MX requests are performed by this module.
"""
from datetime import date
import json
import math
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

MAX_PAYLOAD = 200_000
TIMEOUT = 25
ENDPOINT = '/api/market-radar/fund-history'
USER_AGENT = 'FinanceMonitorMarketDashboard/1.0'


class HistoryError(RuntimeError):
    """A stable failure containing no credentials or provider response body."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _code(code):
    if not isinstance(code,str) or not re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)',code):
        raise ValueError('Invalid history security code')
    ticker,market=code.split('.')
    valid=(market=='SH' and ticker.startswith('6') or market=='SZ' and ticker.startswith(('0','3')) or market=='BJ' and ticker.startswith(('4','8','92')))
    if not valid:raise ValueError('Invalid history security market')
    return ticker,1 if market=='SH' else 0


def parse_history(raw,code):
    """Return only actual dated rows; missing/suspended dates remain absent."""
    ticker,market=_code(code)
    if not isinstance(raw,dict) or raw.get('rc')!=0:raise ValueError('History provider failure')
    data=raw.get('data')
    if not isinstance(data,dict) or data.get('code')!=ticker or type(data.get('market')) is not int or data['market']!=market:
        raise ValueError('History identity mismatch')
    rows=data.get('klines')
    if not isinstance(rows,list) or not rows:raise ValueError('Empty history')
    parsed={}
    for row in rows:
        if not isinstance(row,str):raise ValueError('Invalid history row')
        cells=row.split(',')
        if not 13<=len(cells)<=15:raise ValueError('Invalid history columns')
        day=cells[0]
        try:
            if date.fromisoformat(day).isoformat()!=day:raise ValueError()
            numbers=[float(value) for value in cells[1:]]
        except (ValueError,TypeError,OverflowError):raise ValueError('Invalid history date or number') from None
        if day in parsed or not all(math.isfinite(value) for value in numbers):raise ValueError('Duplicate history date or nonfinite number')
        main,large,super_large=numbers[0],numbers[3],numbers[4]
        if abs(main-large-super_large)>max(100,abs(main)*1e-6):raise ValueError('History main-flow classification mismatch')
        close=numbers[10];change=numbers[11]
        if close<=0:raise ValueError('Invalid history close')
        parsed[day]={'date':day,'mainNetFlow':main,'largeNetFlow':large,'superNetFlow':super_large,'close':close,'changePct':change}
    return {day:parsed[day] for day in sorted(parsed)}


def _base_url(value):
    if not isinstance(value,str):raise ValueError('Invalid history URL')
    try:
        parts=urllib.parse.urlsplit(value)
        host=parts.hostname or ''
        trusted=host=='newsmonitor.pages.dev' or host.endswith('.newsmonitor.pages.dev')
        if (parts.scheme!='https' or not trusted or parts.username is not None or parts.password is not None or parts.port not in (None,443) or parts.query or parts.fragment or parts.path.rstrip('/') not in ('',ENDPOINT)):
            raise ValueError()
    except (ValueError,TypeError):raise ValueError('Untrusted history URL') from None
    return 'https://'+host+ENDPOINT


class HistoryClient:
    def __init__(self,cache:Path,base_url:str,token:str,transport=None):
        self.cache=Path(cache);self.base_url=_base_url(base_url)
        if not isinstance(token,str) or not token or '\r' in token or '\n' in token:raise ValueError('Invalid history credential')
        self._token=token;self.transport=transport;self._stopped=None

    def _fetch(self,url,headers):
        if self.transport:return self.transport(url,headers)
        try:
            import certifi
            context=ssl.create_default_context(cafile=certifi.where())
        except ImportError:context=ssl.create_default_context()
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=context))
        request=urllib.request.Request(url,headers=headers)
        with opener.open(request,timeout=TIMEOUT) as response:
            length=response.headers.get('Content-Length')
            if length is not None and int(length)>MAX_PAYLOAD:raise HistoryError('History payload too large')
            payload=response.read(MAX_PAYLOAD+1)
        if len(payload)>MAX_PAYLOAD:raise HistoryError('History payload too large')
        return json.loads(payload)

    def get(self,code):
        _code(code)
        path=self.cache/(code+'.json')
        if path.exists():
            try:
                if path.stat().st_size>MAX_PAYLOAD:raise ValueError('Oversized cache')
                return parse_history(json.loads(path.read_text()),code)
            except Exception:
                path.unlink(missing_ok=True)
                raise HistoryError('Invalid history cache removed') from None
        if self._stopped is not None:raise HistoryError(f'History source stopped (HTTP {self._stopped})')
        url=self.base_url+'?'+urllib.parse.urlencode({'code':code})
        headers={'Authorization':'Bearer '+self._token,'User-Agent':USER_AGENT,'Accept':'application/json'}
        try:
            raw=self._fetch(url,headers)
            encoded=json.dumps(raw,ensure_ascii=False,allow_nan=False).encode()
            if len(encoded)>MAX_PAYLOAD:raise HistoryError('History payload too large')
        except urllib.error.HTTPError as error:
            if error.code in (403,429):self._stopped=error.code
            raise HistoryError(f'History request rejected (HTTP {error.code})') from None
        except HistoryError:raise
        except Exception:raise HistoryError('History request failed') from None
        # Validation errors are deliberately distinguishable from network errors.
        parsed=parse_history(raw,code)
        self.cache.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=path.with_suffix('.tmp')
        temporary.write_bytes(encoded);temporary.chmod(0o600);temporary.replace(path)
        return parsed
