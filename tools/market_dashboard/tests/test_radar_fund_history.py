import copy
from pathlib import Path
import tempfile
import unittest
import urllib.error
from tools.market_dashboard import radar_fund_history as history


def response():
    return {'rc':0,'data':{'code':'600519','market':1,'name':'sample','klines':['2026-11-20,-100,20,80,-70,-30,-1,0.2,0.8,-0.7,-0.3,100,-2','2026-11-19,120,-20,-100,70,50,1.2,-0.2,-1,0.7,0.5,102,1']}}


class HistoryTest(unittest.TestCase):
    def test_parses_yuan_and_keeps_absent_dates_absent(self):
        parsed=history.parse_history(response(),'600519.SH')
        self.assertEqual(list(parsed),['2026-11-19','2026-11-20'])
        self.assertEqual(parsed['2026-11-20'],{'date':'2026-11-20','mainNetFlow':-100,'largeNetFlow':-70,'superNetFlow':-30,'close':100,'changePct':-2})
        self.assertNotIn('2026-11-18',parsed)

    def test_rejects_identity_dates_duplicates_and_invalid_numbers(self):
        for code in ('600519.SZ','../600519.SH','600519.SH?x=1'):
            with self.assertRaises(ValueError):history.parse_history(response(),code)
        for transform in (lambda d:d['data'].update(code='600518'),lambda d:d['data']['klines'].append(d['data']['klines'][0]),lambda d:d['data']['klines'].__setitem__(0,d['data']['klines'][0].replace('2026-11-20','2026-02-30')),lambda d:d['data']['klines'].__setitem__(0,d['data']['klines'][0].replace(',-100,',',NaN,')),lambda d:d['data']['klines'].__setitem__(0,d['data']['klines'][0].replace(',-70,',',9999,'))):
            raw=copy.deepcopy(response());transform(raw)
            with self.assertRaises(ValueError):history.parse_history(raw,'600519.SH')

    def test_success_is_cached_across_clients_and_bad_identity_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            client=history.HistoryClient(Path(directory),'https://codex-market-radar.newsmonitor.pages.dev','secret',transport=lambda url,headers:calls.append(url) or response())
            client.get('600519.SH');client.get('600519.SH');self.assertEqual(len(calls),1)
            history.HistoryClient(Path(directory),'https://newsmonitor.pages.dev','other',transport=lambda *args:(_ for _ in ()).throw(AssertionError('no request'))).get('600519.SH')
            with self.assertRaises(ValueError):client.get('601318.SH')
            self.assertFalse((Path(directory)/'601318.SH.json').exists())
            self.assertNotIn('secret',''.join(p.read_text() for p in Path(directory).glob('*.json')))

    def test_rejects_untrusted_urls_and_oversized_payload(self):
        for url in ('http://newsmonitor.pages.dev','https://newsmonitor.pages.dev.evil.test','https://evil.test','https://newsmonitor.pages.dev/other','https://secret@newsmonitor.pages.dev','https://newsmonitor.pages.dev?x=1'):
            with self.assertRaises(ValueError):history.HistoryClient(Path('/tmp'),url,'secret')
        with tempfile.TemporaryDirectory() as directory:
            client=history.HistoryClient(Path(directory),'https://newsmonitor.pages.dev','secret',transport=lambda *args:dict(response(),padding='x'*200001))
            with self.assertRaises(history.HistoryError):client.get('600519.SH')
            self.assertEqual(list(Path(directory).glob('*.json')),[])

    def test_forbidden_and_rate_limit_stop_without_leaking_token(self):
        for status in (403,429):
            with tempfile.TemporaryDirectory() as directory:
                calls=[]
                def transport(url,headers):
                    calls.append(url);raise urllib.error.HTTPError(url,status,'secret',{},None)
                client=history.HistoryClient(Path(directory),'https://newsmonitor.pages.dev','secret',transport=transport)
                for code in ('600519.SH','601318.SH'):
                    with self.assertRaises(history.HistoryError) as caught:client.get(code)
                    self.assertIn(str(status),str(caught.exception));self.assertNotIn('secret',str(caught.exception))
                self.assertEqual(len(calls),1)

    def test_redirect_handler_never_reissues_authenticated_request(self):
        handler=history.NoRedirect()
        self.assertIsNone(handler.redirect_request(None,None,302,'redirect',{},'https://evil.test'))

if __name__=='__main__':unittest.main()
