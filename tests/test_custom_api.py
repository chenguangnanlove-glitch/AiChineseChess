"""集中适配、校验、连接测试（仅 mock，不调用真实 API）。"""
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from models.api_config import validate_config, build_payload, ConfigError, clean_text, endpoint_url, request_headers, is_local_base_url, normalize_base_url
from models.llm_player import LLMPlayer
import app as server
import mock_openai_server as mock

FAKE_KEY = 'test-only-secret-not-a-real-key'


def cfg(**over):
    return dict(provider='custom', display_name='自定义 A', model_name='provider-a/model-1',
                base_url='https://example.invalid/v1', api_key=FAKE_KEY,
                thinking_mode='disabled', max_output=1024, timeout=2, **over)


class ConfigTests(unittest.TestCase):
    def test_provider_parameters_do_not_cross(self):
        for provider in ('custom', 'gemini', 'deepseek', 'kimi', 'anthropic'):
            c = cfg(); c['provider'] = provider; c['thinking_mode'] = 'low' if provider == 'kimi' else 'disabled'
            if provider == 'anthropic':
                c['model_name'] = 'claude-sonnet-4-5'
                c.pop('max_output', None)
            c = validate_config(c)
            p = build_payload(c, [{'role':'system','content':'sys'},{'role':'user','content':'hi'}], testing=False)
            if provider in ('custom', 'gemini'):
                self.assertNotIn('thinking', p); self.assertNotIn('reasoning_effort', p)
                self.assertEqual(p['max_tokens'], 1024)
            elif provider == 'kimi':
                self.assertNotIn('thinking', p); self.assertNotIn('max_tokens', p)
                self.assertEqual(p['max_completion_tokens'], 1024)
            elif provider == 'anthropic':
                self.assertEqual(p['max_tokens'], 4096)
                self.assertEqual(p['system'], 'sys')
                self.assertEqual(p['messages'], [{'role':'user','content':'hi'}])
                self.assertNotIn('thinking', p); self.assertNotIn('reasoning_effort', p)
                self.assertIn('x-api-key', request_headers(c))
                self.assertEqual(request_headers(c)['anthropic-version'], '2023-06-01')
                self.assertNotIn('Authorization', request_headers(c))
            else:
                self.assertEqual(p['thinking'], {'type': 'disabled'})
        # 显式自定义 provider：即便模型名里有 deepseek / kimi，也不能发送私有参数。
        p = LLMPlayer(**{k:v for k,v in cfg().items() if k != 'id'})
        self.assertEqual(p.provider, 'custom')
        c = cfg(); c['model_name'] = 'deepseek-kimi-custom'
        self.assertNotIn('thinking', build_payload(validate_config(c), []))

    def test_invalid_config(self):
        for field, value in [('base_url', 'file:///etc/passwd'), ('base_url', 'https://key@host/v1'),
                             ('base_url','https://host/v1?api_key=secret'),
                             ('model_name',''), ('model_name','space model'), ('max_output',3),
                             ('timeout',601), ('timeout','2.5'), ('thinking_mode','max'), ('provider','bedrock'), ('provider', ['custom'])]:
            c = cfg(); c[field]=value
            with self.subTest(field=field,value=value), self.assertRaises(ConfigError): validate_config(c)

    def test_base_url_suffixes_are_stripped(self):
        c = cfg(); c['base_url'] = 'https://api.example.invalid/v1/chat/completions'
        self.assertEqual(validate_config(c)['base_url'], 'https://api.example.invalid/v1')
        c = cfg(); c.update(provider='anthropic', model_name='claude-sonnet-4-5', thinking_mode='disabled',
                            base_url='https://api.anthropic.com/v1/messages')
        out = validate_config(c)
        self.assertEqual(out['base_url'], 'https://api.anthropic.com/v1')
        self.assertTrue(endpoint_url(out).endswith('/v1/messages'))

    def test_empty_key_allowed_only_on_localhost(self):
        for host in ('localhost', '127.0.0.1', '[::1]'):
            c = cfg(); c['api_key'] = ''; c['base_url'] = f'http://{host}:11434/v1'
            out = validate_config(c)
            self.assertEqual(out['api_key'], '')
            self.assertFalse('Authorization' in request_headers(out) or 'x-api-key' in request_headers(out))
            self.assertTrue(is_local_base_url(out['base_url']))
        c = cfg(); c['api_key'] = ''
        with self.assertRaisesRegex(ConfigError, '重新输入'):
            validate_config(c)

    def test_clean_text_masks_anthropic_keys(self):
        ant = 'sk-ant-api03-ABCDEFGHIJKLMNOP'
        raw = f'x-api-key: {ant} and Authorization: Bearer sk-proj-ABCDEFGH and leftover {ant}'
        cleaned = clean_text(raw, ant)
        self.assertNotIn(ant, cleaned)
        self.assertNotIn('sk-proj-ABCDEFGH', cleaned)
        self.assertIn('[已隐藏密钥]', cleaned)

    def test_missing_key_clear_error(self):
        c=cfg(); c['api_key']=''
        with self.assertRaisesRegex(ConfigError, '重新输入'): validate_config(c)

    def test_test_caps_and_parameters(self):
        c=cfg(); c.update(provider='deepseek', thinking_mode='high',max_output=8192)
        p=build_payload(validate_config(c), [],testing=True)
        self.assertEqual(p['max_tokens'],64); self.assertEqual(p['thinking'],{'type':'disabled'})
        c.update(provider='kimi',thinking_mode='high',max_output=16384)
        p=build_payload(validate_config(c),[],testing=True)
        self.assertEqual(p['max_completion_tokens'],512);self.assertEqual(p['reasoning_effort'],'low')


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),mock.Handler)
        cls.base=f'http://127.0.0.1:{cls.http.server_port}'
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.client=server.app.test_client()
        cls.original_dir=server.GAMES_DIR
        server.GAMES_DIR=tempfile.mkdtemp(prefix='aichess-custom-test-')

    @classmethod
    def tearDownClass(cls):
        cls.client.post('/api/stop_battle')
        cls.http.shutdown()
        server.GAMES_DIR=cls.original_dir

    def setUp(self):
        with mock.state_lock: mock.state.update(mode='ok', fail_remaining=0, requests=[], request_count=0)

    def request_cfg(self,path='/v1'):
        c=cfg();c['base_url']=self.base+path;return c

    def probe(self,c):
        return self.client.post('/api/test_connection',json={'confirmed':True,'config':c}).get_json()

    def test_probe_success_and_requires_confirmation(self):
        with patch('app.requests.post', side_effect=AssertionError('must not call')):
            r=self.client.post('/api/test_connection',json={'config':self.request_cfg()})
            self.assertEqual(r.status_code,400)
        r=self.probe(self.request_cfg());self.assertEqual(r['status'],'success');self.assertEqual(r['http_status'],200)
        self.assertNotIn(FAKE_KEY,json.dumps(r));self.assertEqual(mock.state['request_count'],1)
        sent=mock.state['requests'][-1];self.assertFalse(sent['stream']);self.assertEqual(sent['max_tokens'],64)

    def test_probe_401_no_key_echo(self):
        r=self.probe(self.request_cfg('/error/401'))
        self.assertEqual(r['http_status'],401);self.assertIn('认证失败',r['message']);self.assertNotIn(FAKE_KEY,json.dumps(r))

    def test_probe_timeout(self):
        with mock.state_lock: mock.state.update(mode='hang',fail_remaining=1,hang_seconds=4)
        t=time.monotonic();r=self.probe(self.request_cfg())
        self.assertIn('超时',r['message']);self.assertLess(time.monotonic()-t,3)

    def test_invalid_start_is_config_error(self):
        c=self.request_cfg();c['base_url']='file:///tmp/forbidden'
        r=self.client.post('/api/start_battle',json={'red_player':c,'black_player':self.request_cfg()})
        self.assertEqual(r.status_code,400);self.assertEqual(r.get_json()['error_type'],'config')
        self.assertEqual(mock.state['request_count'],0)

    def test_upstream_400_not_a_chess_error_and_key_scrubbed(self):
        c=self.request_cfg('/echo-error/v1'); c['model_name']='deepseek-in-name-but-custom'
        p=LLMPlayer(**c)
        captured=io.StringIO()
        with contextlib.redirect_stdout(captured):
            r=p.get_move('........./'*9+'.........',[],legal_moves=['a0a1'])
        self.assertTrue(r['fatal']);self.assertEqual(r['error_type'],'config')
        self.assertNotIn(FAKE_KEY,captured.getvalue()+json.dumps(r))

    def test_two_custom_models_battle(self):
        red=self.request_cfg('/style=engine/v1');black=self.request_cfg('/style=engine/v1')
        red['model_name']='custom-red-engine';black['model_name']='custom-black-engine'
        red['max_output']=1536;black['max_output']=2048
        board='/'.join(['...ak....','.........','.........','.........','........R','R........','........p','.........','.........','...KA....'])
        with patch.dict(os.environ,{'AICHESS_MOVE_DELAY':'0.01'}):
            r=self.client.post('/api/start_battle',json={'red_player':red,'black_player':black,'initial_board':board}).get_json()
            self.assertEqual(r['status'],'success',r)
            battle=server.current_battle
            battle.loop_thread.join(timeout=20)
        self.assertEqual(battle.status,'finished')
        self.assertEqual(battle.result['reason'],'checkmate')
        sent=mock.state['requests'];self.assertEqual({r['model'] for r in sent},{'custom-red-engine','custom-black-engine'})
        for request in sent:
            self.assertEqual(request['max_tokens'], 1536 if request['model']=='custom-red-engine' else 2048)
            self.assertNotIn('thinking',request);self.assertNotIn('reasoning_effort',request)
        record=open(battle.recorder.path).read()
        self.assertNotIn(FAKE_KEY,record)
        self.assertNotIn(FAKE_KEY,json.dumps(self.client.get('/api/get_battle_status').get_json()))

    def ant_cfg(self, path='/v1', **over):
        c = cfg()
        c.update(provider='anthropic', display_name='Claude', model_name='claude-sonnet-4-5',
                 thinking_mode='disabled', base_url=self.base+path, max_output=1024, timeout=5)
        c.update(over)
        return c

    def simple_move(self, player):
        return player.get_move('........./'*9+'.........', [], legal_moves=['a0a1'])

    def test_anthropic_probe_stream_and_json(self):
        r = self.probe(self.ant_cfg())
        self.assertEqual(r['status'], 'success', r)
        self.assertEqual(r['http_status'], 200)
        self.assertNotIn(FAKE_KEY, json.dumps(r))
        sent = mock.state['requests'][-1]
        self.assertTrue(sent['has_x_api_key'])
        self.assertFalse(sent['has_authorization'])
        self.assertEqual(sent['anthropic_version'], '2023-06-01')
        self.assertFalse(sent['stream'])
        self.assertEqual(sent['max_tokens'], 128)
        self.assertTrue(sent['path'].rstrip('/').endswith('/messages'))

        # 流式走法 + 思考增量
        p = LLMPlayer(**self.ant_cfg())
        result = self.simple_move(p)
        self.assertEqual(result.get('move'), 'a0a1', result)
        self.assertTrue((result.get('thinking') or result.get('analysis')), result)
        self.assertNotIn(FAKE_KEY, json.dumps(result))
        stream_req = mock.state['requests'][-1]
        self.assertTrue(stream_req['stream'])
        self.assertTrue(stream_req['has_x_api_key'])

        # 非流式 JSON（强制 json-message）
        p = LLMPlayer(**self.ant_cfg('/json-message/v1'))
        result = self.simple_move(p)
        self.assertEqual(result.get('move'), 'a0a1', result)
        self.assertIn('真正该走', result.get('thinking') or '')

    def test_anthropic_error_key_scrubbed(self):
        p = LLMPlayer(**self.ant_cfg('/echo-ant-error/v1'))
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            r = self.simple_move(p)
        self.assertTrue(r['fatal'])
        blob = captured.getvalue() + json.dumps(r)
        self.assertNotIn(FAKE_KEY, blob)
        self.assertNotIn('sk-ant-', blob)

    def test_auto_switch_max_completion_tokens(self):
        c = self.request_cfg('/require-max-completion/v1')
        r = self.probe(c)
        self.assertEqual(r['status'], 'success', r)
        reqs = [x for x in mock.state['requests'] if 'require-max-completion' in x.get('path','')]
        self.assertGreaterEqual(len(reqs), 2)
        self.assertIn('max_tokens', reqs[0])
        self.assertNotIn('max_completion_tokens', reqs[0])
        self.assertIn('max_completion_tokens', reqs[-1])
        self.assertNotIn('max_tokens', reqs[-1])

        with mock.state_lock:
            mock.state.update(requests=[], request_count=0)
        p = LLMPlayer(**c)
        result = self.simple_move(p)
        self.assertEqual(result.get('move'), 'a0a1', result)
        reqs = mock.state['requests']
        self.assertGreaterEqual(len(reqs), 2)
        self.assertIn('max_tokens', reqs[0])
        self.assertIn('max_completion_tokens', reqs[-1])
        self.assertTrue(reqs[-1].get('stream'))

    def test_auto_disable_stream_and_json_content_type(self):
        p = LLMPlayer(**self.request_cfg('/no-stream/v1'))
        result = self.simple_move(p)
        self.assertEqual(result.get('move'), 'a0a1', result)
        reqs = [x for x in mock.state['requests'] if '/no-stream' in x.get('path','')]
        self.assertGreaterEqual(len(reqs), 2)
        self.assertTrue(reqs[0].get('stream'))
        self.assertFalse(reqs[-1].get('stream'))

        with mock.state_lock:
            mock.state.update(requests=[], request_count=0)
        p = LLMPlayer(**self.request_cfg('/json-completion/v1'))
        result = self.simple_move(p)
        self.assertEqual(result.get('move'), 'a0a1', result)
        self.assertIn('思考一下', result.get('thinking') or '')
        self.assertEqual(len(mock.state['requests']), 1)
        self.assertTrue(mock.state['requests'][0].get('stream'))

    def test_localhost_empty_key_omits_auth_headers(self):
        c = self.request_cfg()
        c['api_key'] = ''
        r = self.probe(c)
        self.assertEqual(r['status'], 'success', r)
        sent = mock.state['requests'][-1]
        self.assertFalse(sent['has_authorization'])
        self.assertFalse(sent['has_x_api_key'])

        p = LLMPlayer(**c)
        result = self.simple_move(p)
        self.assertEqual(result.get('move'), 'a0a1', result)
        sent = mock.state['requests'][-1]
        self.assertFalse(sent['has_authorization'])
        self.assertFalse(sent['has_x_api_key'])

        remote = cfg(); remote['api_key'] = ''
        with self.assertRaisesRegex(ConfigError, '重新输入'):
            validate_config(remote)
        r = self.client.post('/api/test_connection', json={'confirmed': True, 'config': remote}).get_json()
        self.assertEqual(r.get('error_type'), 'config')
        self.assertIn('重新输入', r.get('message') or '')




if __name__=='__main__': unittest.main()
