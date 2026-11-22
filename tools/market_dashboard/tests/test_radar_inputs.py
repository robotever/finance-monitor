import json
from pathlib import Path
import tempfile
import unittest
from tools.market_dashboard import radar_inputs as radar


def aggregate(code='000852.SH'):
    return {'dataTableDTOList': [{'code': code, 'entityName': '中证1000(指数)', 'nameMap': {'u':'上涨家数','d':'下跌家数','f':'平盘家数','m':'主力净流入资金','t':'成交额'},'fieldSet':[{'returnCode':k,'unitName':'家' if k in ('u','d','f') else '元'} for k in ('u','d','f','m','t')],'rawTable':{'headName':['2026-11-20','2026-11-19'],'u':['2','1'],'d':['1','2'],'f':['0','0'],'m':['-10000',None],'t':['20000','30000']},'table':{}}]}


def unavailable_members(*args):
    raise ValueError('members unavailable')


def screen(rows=None,total=2):
    return {'data':{'data':{'totalCondition':'股票代码', 'allResults':{'result':{'total':total,'totalRecordCount':total,'columns':[{'key':'flow','title':'主力净额(元)','unit':'元','dateMsg':'2026.11.20'},{'key':'amt','title':'成交额(元)','unit':'元','dateMsg':'2026.11.20'},{'key':'CHG','title':'涨跌幅(%)','dateMsg':'2026.11.20'}],'dataList':rows or [{'SECURITY_CODE':'600001','MARKET_SHORT_NAME':'SH','flow':'1.2亿','amt':'2亿','CHG':'1'},{'SECURITY_CODE':'000001','MARKET_SHORT_NAME':'SZ','flow':'-300万','amt':'4亿','CHG':'-1'}]}}}}}


class RadarInputsTest(unittest.TestCase):
    def test_money_preserves_units_and_missing(self):
        self.assertEqual(radar.number('1.2万亿'),1200000000000)
        self.assertEqual(radar.number('-3,200万元'),-32000000)
        self.assertIsNone(radar.number('--'))
        with self.assertRaises(ValueError):radar.number('3美元')

    def test_aggregate_identity_sorted_dates_and_missing(self):
        h=radar.parse_aggregate(aggregate(),'small')
        self.assertEqual([p['date'] for p in h],['2026-11-19','2026-11-20'])
        self.assertIsNone(h[0]['mainNetFlow'])
        self.assertEqual(h[1]['mainNetFlow'],-10000)
        with self.assertRaises(ValueError):radar.parse_aggregate(aggregate('000300.SH'),'small')

    def test_exact_membership_signed_sum_and_reject_partial(self):
        p=radar.parse_screen(screen(),{'600001.SH','000001.SZ'},'2026-11-20')
        self.assertEqual(p['mainNetFlow'],117000000)
        self.assertEqual(p['fundMatched'],2)
        self.assertEqual(p['turnover'],600000000)
        self.assertEqual(p['up'],1)
        with self.assertRaises(ValueError):radar.parse_screen(screen(total=300),{'600001.SH','000001.SZ'},'2026-11-20')
        with self.assertRaises(ValueError):radar.parse_screen(screen(),{'600001.SH','000002.SZ'},'2026-11-20')
        with self.assertRaises(ValueError):radar.parse_screen(screen(),{'600001.SH','000001.SZ'},'2026-11-19')

    def test_failure_does_not_discard_history_or_fill_null(self):
        old=radar.parse_aggregate(aggregate(),'small')
        newer=dict(old[-1],mainNetFlow=None,up=1)
        merged=radar.merge_history(old,[newer])
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[-1]['mainNetFlow'],-10000)
        self.assertEqual(merged[-1]['up'],1)

    def test_current_membership_has_exact_identity_date_and_count(self):
        rows=[{'日期Date':'20261120','指数代码Index Code':'000919','指数名称 Index Name':'300价值','成份券代码Constituent Code':'000001','交易所Exchange':'深圳证券交易所'},
              {'日期Date':'20261120','指数代码Index Code':'000919','指数名称 Index Name':'300价值','成份券代码Constituent Code':'600001','交易所Exchange':'上海证券交易所'}]
        members,day=radar.parse_csi_rows(rows,'000919.SH',2)
        self.assertEqual(members,{'000001.SZ','600001.SH'})
        self.assertEqual(day,'2026-11-20')
        with self.assertRaises(ValueError):radar.parse_csi_rows(rows,'000922.SH',2)

    def test_business_error_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            client=radar.MXClient('secret',Path(directory),transport=lambda *args:{'status':0,'data':{'data':{'responseCode':500,'allResults':None}}})
            with self.assertRaises(RuntimeError):client.query('bad',screen=True)
            self.assertEqual(list(Path(directory).glob('*.json')),[])

    def test_collect_keeps_other_objects_and_public_bundle_aggregate_only(self):
        class Client:
            def query(self,text,screen=False):
                if '全部A股' in text:return aggregate('001071')
                raise RuntimeError('private source failure')
        bundle,failures=radar.collect(Client(),member_loader=unavailable_members,now=radar.datetime(2026,11,22,tzinfo=radar.ZoneInfo('Asia/Shanghai')))
        self.assertEqual(set(bundle),{'schemaVersion','observedAt','marketDate','objects'})
        self.assertEqual(set(bundle['objects']),set(radar.OBJECTS))
        self.assertEqual(bundle['objects']['small']['history'],[])
        self.assertEqual(bundle['marketDate'],'2026-11-20')
        self.assertNotIn('private',json.dumps(bundle))
        self.assertTrue(failures)

    def test_cli_writes_bundle_then_same_day_cache_without_credentials(self):
        from unittest.mock import patch
        class Client:
            def __init__(self,*args):pass
            def query(self,text,screen=False):
                if '全部A股' in text:return aggregate('001071')
                raise RuntimeError('unavailable')
        with tempfile.TemporaryDirectory() as directory:
            argv=['--state-root',directory,'--project-root',directory]
            with patch.object(radar,'MXClient',Client),patch.object(radar,'credential',return_value='secret'),patch.object(radar,'constituents',side_effect=ValueError('unavailable')):
                self.assertEqual(radar.main(argv),0)
            bundle=json.loads((Path(directory)/'latest.json').read_text())
            self.assertEqual(bundle['objects']['ashare']['history'][-1]['mainNetFlow'],-10000)
            with patch.object(radar,'credential',side_effect=AssertionError('should use same-day cache')):
                self.assertEqual(radar.main(argv),0)

    def test_total_source_failure_preserves_latest_without_success_marker(self):
        class Client:
            def query(self,*args,**kwargs):raise RuntimeError('offline')
        previous={'objects':{'ashare':{'history':radar.parse_aggregate(aggregate('001071'),'ashare')}}}
        with self.assertRaises(RuntimeError):radar.collect(Client(),previous,member_loader=unavailable_members)

    def test_frequency_limit_retries_without_caching_failure(self):
        responses=iter([{'status':112,'success':False,'data':None},{'status':0,'data':{}}])
        with tempfile.TemporaryDirectory() as directory:
            client=radar.MXClient('secret',Path(directory),transport=lambda *args:next(responses),sleeper=lambda seconds:None)
            self.assertEqual(client.query('retry')['status'],0)
            self.assertEqual(len(list(Path(directory).glob('*.json'))),1)

    def test_funding_can_populate_style_without_provider_history(self):
        class Client:
            def query(self,text,screen=False):
                if screen:return globals()['screen']()
                if '全部A股' in text:return aggregate('001071')
                raise RuntimeError('missing history')
        def members(code,expected):return {'600001.SH','000001.SZ'},'2026-11-22','CSI'
        bundle,_=radar.collect(Client(),member_loader=members)
        self.assertEqual(bundle['objects']['value']['history'][-1]['mainNetFlow'],117000000)
        self.assertEqual(bundle['objects']['value']['membershipAsOf'],'2026-11-22')
        self.assertEqual(bundle['objects']['value']['history'][-1]['membershipMode'],'current-members')

    def test_partial_batches_keep_matched_count_and_null_total(self):
        class Client:
            def query(self,text,screen=False):
                if screen and '[000001,000002,000003,000004,000005,000006,000007,000008,000009,000010]' in text:
                    raw=globals()['screen']();result=radar.screen_result(raw)
                    result['total']=result['totalRecordCount']=10
                    result['dataList']=[dict(result['dataList'][0],SECURITY_CODE=f'{i:06}',MARKET_SHORT_NAME='SZ') for i in range(1,11)]
                    return raw
                if not screen and '全部A股' in text:return aggregate('001071')
                raise RuntimeError('unavailable')
        def members(code,expected):return {f'{i:06}.SZ' for i in range(1,13)},'2026-11-22','CSI'
        bundle,_=radar.collect(Client(),member_loader=members,batch_size=10)
        p=bundle['objects']['value']['history'][-1]
        self.assertEqual(p['fundMatched'],10)
        self.assertEqual(p['fundExpected'],12)
        self.assertIsNone(p['mainNetFlow'])

    def test_full_funding_uses_same_member_turnover(self):
        class Client:
            def query(self,text,screen=False):
                if screen:return globals()['screen']()
                if '全部A股' in text:return aggregate('001071')
                if '沪深300' in text:return aggregate('000300.SH')
                raise RuntimeError('missing')
        bundle,_=radar.collect(Client(),member_loader=lambda *args:({'600001.SH','000001.SZ'},'2026-11-22','Hithink'))
        self.assertEqual(bundle['objects']['large']['history'][-1]['turnover'],600000000)
        self.assertEqual(sum(bundle['objects']['large']['history'][-1][k] for k in ('up','down','flat')),2)

    def test_string_business_success_is_accepted(self):
        raw=screen();raw['status']=0;raw['data']['data']['responseCode']='100'
        with tempfile.TemporaryDirectory() as directory:
            client=radar.MXClient('secret',Path(directory),transport=lambda *args:raw)
            self.assertEqual(len(radar.screen_result(client.query('valid',screen=True))['dataList']),2)

    def test_partial_run_records_cooldown_not_daily_success(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            argv=['--state-root',directory,'--project-root',directory]
            bundle={'schemaVersion':'radar-inputs-v1','marketDate':'2026-11-20','observedAt':radar.datetime.now(radar.ZoneInfo('Asia/Shanghai')).isoformat(),'objects':{}}
            with patch.object(radar,'credential',return_value='secret'),patch.object(radar,'collect',return_value=(bundle,['missing'])):
                self.assertEqual(radar.main(argv),0)
            self.assertFalse((Path(directory)/'last-success.json').exists())
            self.assertTrue((Path(directory)/'last-attempt.json').exists())

    def test_complete_funding_group_is_atomic_across_partial_and_aggregate_refresh(self):
        old=dict(radar.point('2026-11-20','current-members'),mainNetFlow=-100,turnover=1000,fundMatched=100,fundExpected=100,up=40)
        partial=dict(radar.point('2026-11-20','current-members'),turnover=5000,fundMatched=70,fundExpected=100,up=45)
        aggregate_refresh=dict(radar.point('2026-11-20'),turnover=99999,up=42)
        for newer in (partial,aggregate_refresh):
            p=radar.merge_history([old],[newer])[-1]
            for field in ('mainNetFlow','turnover','fundMatched','fundExpected','membershipMode'):self.assertEqual(p[field],old[field])
            self.assertEqual(p['up'],newer['up'])

    def test_wrong_identity_response_is_removed_from_private_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            client=radar.MXClient('secret',Path(directory),transport=lambda *args:aggregate('000300.SH'))
            with self.assertRaises(ValueError):radar.validated_query(client,'wrong',lambda raw:radar.parse_aggregate(raw,'small'))
            self.assertEqual(list(Path(directory).glob('*.json')),[])

    def test_invalid_funding_amount_relationship_is_rejected(self):
        raw=screen();rows=radar.screen_result(raw)['dataList'];rows[0]['flow']='900亿'
        with self.assertRaises(ValueError):radar.parse_screen(raw,{'600001.SH','000001.SZ'},'2026-11-20')

    def test_aggregate_cache_expires_but_explicit_daily_funding_stays_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            client=radar.MXClient('secret',Path(directory),transport=lambda endpoint,body:calls.append(endpoint) or {'status':0,'data':{}})
            client.query('history')
            cache=next(Path(directory).glob('*.json'))
            radar.os.utime(cache,(0,0))
            client.query('history')
            self.assertEqual(len(calls),2)

    def test_unstable_twenty_member_batch_falls_back_to_ten(self):
        class Client:
            def query(self,text,screen=False):
                codes=radar.re.search(r'\[(.*?)\]',text)[1].split(',')
                if len(codes)>10:raise ValueError('parser cannot handle batch')
                raw=globals()['screen']();result=radar.screen_result(raw)
                result['total']=result['totalRecordCount']=len(codes)
                result['dataList']=[dict(result['dataList'][0],SECURITY_CODE=code,MARKET_SHORT_NAME='SZ') for code in codes]
                return raw
        p=radar.member_funding_batch(Client(),{f'{i:06}.SZ' for i in range(1,21)},'2026-11-20')
        self.assertEqual(p['fundMatched'],20)
        self.assertEqual(p['mainNetFlow'],2400000000)

    def test_confirmed_nontrading_exclusion_is_date_and_membership_bound(self):
        config={'2026-11-20':{'small':{'members':['600185.SH','688798.SH'],'sources':['https://www.sse.com.cn/example.pdf']}}}
        members={'600185.SH','688798.SH','000001.SZ'}
        self.assertEqual(radar.confirmed_exclusions('small','2026-11-20',members,config),{'600185.SH','688798.SH'})
        self.assertEqual(radar.confirmed_exclusions('small','2026-11-23',members,config),set())
        with self.assertRaises(ValueError):radar.confirmed_exclusions('small','2026-11-20',{'000001.SZ'},config)

    def test_aggregate_uses_per_indicator_units_and_rejects_unknown(self):
        raw=aggregate();raw['dataTableDTOList'][0]['fieldSet'][3]['unitName']='万元'
        self.assertEqual(radar.parse_aggregate(raw,'small')[-1]['mainNetFlow'],-100000000)
        raw['dataTableDTOList'][0]['fieldSet'][3]['unitName']='美元'
        with self.assertRaises(ValueError):radar.parse_aggregate(raw,'small')
        raw['dataTableDTOList'][0]['fieldSet'][3]['unitName']='家'
        with self.assertRaises(ValueError):radar.parse_aggregate(raw,'small')

    def test_provider_added_positive_flow_filter_is_rejected(self):
        raw=screen();raw['data']['data']['totalCondition']='成份股 且 主力净额大于0元'
        with self.assertRaises(ValueError):radar.parse_screen(raw,{'600001.SH','000001.SZ'},'2026-11-20')

    def test_quota_exhaustion_stops_further_requests_but_keeps_success_cache(self):
        calls=[]
        with tempfile.TemporaryDirectory() as directory:
            client=radar.MXClient('secret',Path(directory),transport=lambda *args:calls.append(1) or {'status':113,'success':False,'data':None})
            with self.assertRaises(RuntimeError):client.query('quota')
            with self.assertRaises(RuntimeError):client.query('other')
            self.assertEqual(len(calls),1)

    def test_failed_ten_member_parser_falls_back_to_five(self):
        class Client:
            def query(self,text,screen=False):
                codes=radar.re.search(r'\[(.*?)\]',text)[1].split(',')
                if len(codes)>5:raise ValueError('AND rather than OR')
                raw=globals()['screen']();result=radar.screen_result(raw)
                result['total']=result['totalRecordCount']=len(codes)
                result['dataList']=[dict(result['dataList'][0],SECURITY_CODE=code,MARKET_SHORT_NAME='SZ') for code in codes]
                return raw
        p=radar.member_funding_batch(Client(),{f'{i:06}.SZ' for i in range(1,11)},'2026-11-20')
        self.assertEqual(p['fundMatched'],10)

    def test_partial_recursive_batches_retain_valid_five_member_coverage(self):
        class Client:
            def query(self,text,screen=False):
                codes=radar.re.search(r'\[(.*?)\]',text)[1].split(',')
                if codes!=['000001','000002','000003','000004','000005']:raise RuntimeError('quota exhausted')
                raw=globals()['screen']();result=radar.screen_result(raw);result['total']=result['totalRecordCount']=5
                result['dataList']=[dict(result['dataList'][0],SECURITY_CODE=code,MARKET_SHORT_NAME='SZ') for code in codes]
                return raw
        p=radar.member_funding_batch(Client(),{f'{i:06}.SZ' for i in range(1,11)},'2026-11-20')
        self.assertEqual(p['fundMatched'],5)
        self.assertEqual(p['fundExpected'],10)
        self.assertIsNone(p['mainNetFlow'])

    def test_closed_market_cutoff_excludes_intraday_and_reuses_friday_on_monday_morning(self):
        zone=radar.ZoneInfo('Asia/Shanghai')
        self.assertEqual(radar.closed_market_end(radar.datetime(2026,11,23,9,tzinfo=zone)),'2026-11-20')
        self.assertEqual(radar.closed_market_end(radar.datetime(2026,11,23,15,20,tzinfo=zone)),'2026-11-23')
        class Client:
            def query(self,text,screen=False):
                if '全部A股' not in text:raise ValueError('missing')
                raw=aggregate('001071');raw['dataTableDTOList'][0]['rawTable']['headName']=['2026-11-23','2026-11-20']
                return raw
        bundle,_=radar.collect(Client(),member_loader=unavailable_members,now=radar.datetime(2026,11,23,9,tzinfo=zone))
        self.assertEqual(bundle['marketDate'],'2026-11-20')

    def test_private_success_cache_migrates_across_dates_without_new_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'2026-11-22';old.mkdir()
            raw={'status':0,'data':{}}
            key=radar.hashlib.sha256(b'queryhello').hexdigest()+'.json'
            radar.atomic_json(old/key,raw)
            radar.migrate_private_cache(root)
            client=radar.MXClient('secret',root,transport=lambda *args:(_ for _ in ()).throw(AssertionError('no request')))
            self.assertEqual(client.query('hello'),raw)

    def test_public_fallback_rejects_wrong_date_missing_member_and_taxonomy(self):
        stamp=int(radar.datetime(2026,11,20,15,30,tzinfo=radar.ZoneInfo('Asia/Shanghai')).timestamp())
        rows=[{'f12':code,'f13':0,'f62':flow,'f66':flow,'f72':0,'f6':1000,'f3':change,'f124':stamp} for code,flow,change in [('301095',100,1),('000001',10,1),('000002',-20,-1),('000003',30,1)]]
        raw={'rc':0,'data':{'total':4,'diff':rows}}
        known={code+'.SZ':{'point':dict(radar.point('2026-11-20','current-members'),mainNetFlow=flow,turnover=1000,fundMatched=1,fundExpected=1),'flowText':str(flow),'turnoverText':'1000'} for code,flow in [('000001',10),('000002',-20),('000003',30)]}
        p=radar.parse_public_funding(raw,{'301095.SZ'},'2026-11-20',known)
        self.assertEqual(p['mainNetFlow'],100)
        with self.assertRaises(ValueError):radar.parse_public_funding(raw,{'301096.SZ'},'2026-11-20',known)
        with self.assertRaises(ValueError):radar.parse_public_funding(raw,{'301095.SZ'},'2026-11-19',known)
        rows[0]['f66']=99
        with self.assertRaises(ValueError):radar.parse_public_funding(raw,{'301095.SZ'},'2026-11-20',known)

    def test_public_fallback_rejects_control_unit_disagreement(self):
        stamp=int(radar.datetime(2026,11,20,15,30,tzinfo=radar.ZoneInfo('Asia/Shanghai')).timestamp())
        rows=[{'f12':code,'f13':0,'f62':flow,'f66':flow,'f72':0,'f6':1000,'f3':1,'f124':stamp} for code,flow in [('301095',100),('000001',100000),('000002',-200000),('000003',300000)]]
        known={code+'.SZ':{'point':dict(radar.point('2026-11-20','current-members'),mainNetFlow=flow,turnover=1000,fundMatched=1,fundExpected=1),'flowText':str(flow),'turnoverText':'1000'} for code,flow in [('000001',10),('000002',-20),('000003',30)]}
        with self.assertRaises(ValueError):radar.parse_public_funding({'rc':0,'data':{'total':4,'diff':rows}},{'301095.SZ'},'2026-11-20',known)

    def test_zero_turnover_is_never_complete(self):
        self.assertFalse(radar.funding_complete(dict(radar.point('2026-11-20'),mainNetFlow=0,turnover=0)))

    def test_fresh_continuous_suspensions_require_same_day_official_breadth(self):
        members={f'{i:06}.SZ' for i in range(1,999)}|{'600185.SH','688798.SH'}
        rows=[{'SECUCODE':code,'SECURITY_CODE':code[:6],'SUSPEND_EXPIRE':'连续停牌','SUSPEND_START_TIME':'2026-11-12 09:30:00','SUSPEND_END_TIME':None,'PREDICT_RESUME_DATE':None} for code in ('600185.SH','688798.SH')]
        rows.append(dict(rows[0],SECUCODE='000001.SZ',SECURITY_CODE='000001',SUSPEND_START_TIME='2026-11-24 09:30:00'))
        raw={'success':True,'code':0,'result':{'pages':1,'count':3,'data':rows}}
        breadth=dict(radar.point('2026-11-23'),up=29,down=966,flat=3)
        now=radar.datetime(2026,11,23,16,tzinfo=radar.ZoneInfo('Asia/Shanghai'))
        expected={'600185.SH','688798.SH'}
        self.assertEqual(radar.parse_current_suspensions(raw,members,'2026-11-23',breadth,now),expected)
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-24',breadth,now)
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-23',dict(breadth,up=30),now)
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-23',dict(breadth,up=None),now)
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-23',dict(breadth,date='2026-11-20'),now)
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-23',dict(breadth,membershipMode='current-members'),now)
        raw['result']['pages']=2
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-23',breadth,now)
        raw['result']['pages']=1;raw['result']['count']=4
        with self.assertRaises(ValueError):radar.parse_current_suspensions(raw,members,'2026-11-23',breadth,now)

    def test_suspension_resumption_end_and_single_day_status_do_not_exclude(self):
        import copy
        members={'600185.SH','688798.SH','000001.SZ'}
        rows=[{'SECUCODE':code,'SECURITY_CODE':code[:6],'SUSPEND_EXPIRE':'连续停牌','SUSPEND_START_TIME':'2026-11-12 09:30:00','SUSPEND_END_TIME':None,'PREDICT_RESUME_DATE':None} for code in ('600185.SH','688798.SH')]
        raw={'success':True,'code':0,'result':{'pages':1,'count':2,'data':rows}}
        breadth=dict(radar.point('2026-11-23'),up=1,down=0,flat=0)
        now=radar.datetime(2026,11,23,16,tzinfo=radar.ZoneInfo('Asia/Shanghai'))
        for change in ({'SUSPEND_END_TIME':'2026-11-23 15:00:00'},{'PREDICT_RESUME_DATE':'2026-11-23 00:00:00'},{'SUSPEND_EXPIRE':'停牌一天'},{'SUSPEND_START_TIME':'2026-11-24 09:30:00'}):
            candidate=copy.deepcopy(raw);candidate['result']['data'][0].update(change)
            with self.assertRaises(ValueError):radar.parse_current_suspensions(candidate,members,'2026-11-23',breadth,now)

    def test_dynamic_suspension_collection_marks_scope_and_eastmoney_source(self):
        from unittest.mock import patch
        inactive={'600185.SH','688798.SH'};active={'600001.SH','000001.SZ'}
        class Client:
            def query(self,text,screen=False):
                if screen:
                    raw=globals()['screen']()
                    for col in radar.screen_result(raw)['columns']:col['dateMsg']='2026.11.23'
                    return raw
                raw=aggregate('000852.SH');table=raw['dataTableDTOList'][0]['rawTable'];table['headName'][0]='2026-11-23';table['u'][0]='2';table['d'][0]='0'
                return raw
        class Public:
            def suspensions(self,members,day,breadth,now):
                self.inputs=(members,day,breadth,now)
                return inactive
        public=Public()
        with patch.object(radar,'OBJECTS',{'small':('中证1000',{'000852.SH'},'000852.SH',4)}):
            bundle,_=radar.collect(Client(),member_loader=lambda *args:(active|inactive,'2026-11-23','Hithink'),public_client=public,now=radar.datetime(2026,11,23,16,tzinfo=radar.ZoneInfo('Asia/Shanghai')))
        obj=bundle['objects']['small'];self.assertIn('Eastmoney',obj['sources']);self.assertIn('4成份，2有效交易样本，2',obj['scope']);self.assertEqual(obj['history'][-1]['fundExpected'],2)
        self.assertEqual(public.inputs[2]['membershipMode'],'provider-aggregate')

    def test_suspension_transport_is_refreshed_and_requires_provider_evidence(self):
        rows=[{'SECUCODE':'600185.SH','SECURITY_CODE':'600185','SUSPEND_EXPIRE':'连续停牌','SUSPEND_START_TIME':'2026-11-12 09:30:00','SUSPEND_END_TIME':None,'PREDICT_RESUME_DATE':None}]
        raw={'success':True,'code':0,'result':{'pages':1,'count':1,'data':rows}}
        calls=[]
        with tempfile.TemporaryDirectory() as directory:
            client=radar.EastmoneyClient(Path(directory),suspension_transport=lambda params:calls.append(params) or raw)
            now=radar.datetime(2026,11,23,16,tzinfo=radar.ZoneInfo('Asia/Shanghai'))
            members={'600185.SH','000001.SZ'};breadth=dict(radar.point('2026-11-23'),up=1,down=0,flat=0)
            self.assertEqual(client.suspensions(members,'2026-11-23',breadth,now),{'600185.SH'})
            self.assertEqual(client.suspensions(members,'2026-11-23',breadth,now),{'600185.SH'})
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0]['fd'],'2026-11-23')
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_cache_success_only_and_no_secret_in_error(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            client=radar.MXClient('secret',Path(directory),transport=lambda endpoint,body: calls.append(body) or {'status':0,'data':{'value':1}})
            self.assertEqual(client.query('hello'),client.query('hello'))
            self.assertEqual(len(calls),1)
            bad=radar.MXClient('secret',Path(directory),transport=lambda *args: (_ for _ in ()).throw(RuntimeError('secret')))
            with self.assertRaisesRegex(RuntimeError,'MX request failed') as caught:bad.query('bad')
            self.assertNotIn('secret',str(caught.exception))

if __name__=='__main__':unittest.main()
