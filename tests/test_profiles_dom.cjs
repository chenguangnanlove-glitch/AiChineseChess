/* DOM 单元测试（jsdom，不是真浏览器/布局实测）。
 * npm install --prefix /tmp/aichess-dom-tests jsdom@26
 * NODE_PATH=/tmp/aichess-dom-tests/node_modules node tests/test_profiles_dom.cjs /tmp/aichess-page.html
 * HTML 生成：uv run python -c "from app import app; print(app.test_client().get('/').data.decode())" > /tmp/aichess-page.html
 */
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(process.argv[2], 'utf8');
const FAKE='test-only-browser-key-not-real';
const pause=()=>new Promise(r=>setTimeout(r,30));
let calls=[], conf=true, alerts=[];
async function page(stored={}) {
 const dom=new JSDOM(html,{url:'http://localhost:5003',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window;
 const context=new Proxy({}, {get:(o,k)=>o[k] || (()=>{}),set:(o,k,v)=>(o[k]=v,true)});
 w.HTMLCanvasElement.prototype.getContext=()=>context;
 const sock={on(){},onAny(){},off(){},disconnect(){}};
 w.io=()=>sock; w.alert=s=>alerts.push(s); w.confirm=()=>conf;
 w.fetch=async(url,opts={})=>{
  calls.push({url,body:opts.body?JSON.parse(opts.body):null});
  if(url==='/api/test_connection')return{json:async()=>({status:'success',http_status:200,message:'HTTP 200：接口正常'})};
  return {json:async()=>({status:'no_battle'})};
 };
 Object.entries(stored).forEach(([k,v])=>w.localStorage.setItem(k,v));
 w.eval(fs.readFileSync(path.join(root,'static/js/profiles.js'),'utf8'));
 w.eval(fs.readFileSync(path.join(root,'static/js/chess.js'),'utf8'));
 await pause();
 return dom;
}
function fill(w,id,v){const el=w.document.getElementById(id);el.value=v;el.dispatchEvent(new w.Event('input',{bubbles:true}));}
function choose(w,id,v){const el=w.document.getElementById(id);el.value=v;el.dispatchEvent(new w.Event('change',{bubbles:true}));}
(async()=>{
 let dom=await page(),w=dom.window;
 const el=id=>w.document.getElementById(id);
 assert.equal(el('red-model').options.length,10);assert.equal(el('black-model').options.length,10);
 assert.equal(el('red-api-key').type,'password');assert.equal(el('black-api-key').type,'password');
 assert.equal(el('red-model').value,'ds-flash');assert.equal(el('black-model').value,'kimi-fast');
 fill(w,'red-api-key',FAKE);
 choose(w,'red-model','kimi-fast');assert.equal(el('black-model').value,'kimi-fast');
 choose(w,'red-model','ds-flash');assert.equal(el('red-api-key').value,FAKE);
 w.document.querySelector('[data-target="red-api-key"]').click();assert.equal(el('red-api-key').type,'text');
 w.document.querySelector('[data-target="red-api-key"]').click();assert.equal(el('red-api-key').type,'password');
 el('new-profile').click();
 fill(w,'profile-name','自定义 Alpha');fill(w,'profile-url','https://api.example.invalid/v1');fill(w,'profile-model','provider-a/model-1');
 fill(w,'profile-max','1536');fill(w,'profile-timeout','10');el('assign-red').click();
 const customId=el('red-model').value;
 assert.notEqual(customId,'ds-flash');assert.equal(el('black-model').value,'kimi-fast');
 fill(w,'red-api-key',FAKE);fill(w,'black-api-key','test-black-only-key');
 let r=w.APIProfiles.config('red');assert.equal(r.provider,'custom');assert.equal(r.model_name,'provider-a/model-1');assert.equal(r.max_output,1536);
 assert.equal(r.api_key,FAKE);
 // 保存与切换不得自动发 API 请求；只有点击测试、确认后才调用。
 assert.equal(calls.filter(c=>c.url==='/api/test_connection').length,0);
 conf=false; w.document.querySelector('.test-side[data-side="red"]').click();await pause();
 assert.equal(calls.filter(c=>c.url==='/api/test_connection').length,0);
 conf=true;w.document.querySelector('.test-side[data-side="red"]').click();await pause();
 let probes=calls.filter(c=>c.url==='/api/test_connection');assert.equal(probes.length,1);assert.equal(probes[0].body.confirmed,true);
 assert.equal(el('red-test-status').textContent,'HTTP 200：接口正常');assert(!el('red-test-status').textContent.includes(FAKE));
 const stored=Object.fromEntries(Object.keys(w.localStorage).map(k=>[k,w.localStorage.getItem(k)]));
 assert(!JSON.stringify(stored).includes(FAKE));assert(!JSON.stringify(stored).includes('api_key'));
 assert.equal(w.sessionStorage.length,0);
 // 锁定与解锁（对战/暂停中）
 w.APIProfiles.lock(true);assert(el('red-model').disabled);assert(el('black-api-key').disabled);assert(el('new-profile').disabled);
 w.APIProfiles.lock(false);assert(!el('red-model').disabled);assert(el('red-thinking-mode').disabled); // custom 无私有思考参数
 // 展开长日志，使用 textContent 防止 HTML 注入
 w.addBattleLogEntry('<script>BAD</script> '+ '长错误'.repeat(1000),'system');
 el('expand-log').click();assert(el('battle-log').classList.contains('expanded'));assert.equal(el('battle-log').querySelectorAll('script').length,0);
 // 更新配置清空关联 key，但不改变另一方选择
 fill(w,'profile-name','自定义 Alpha 修改');el('profile-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
 assert.equal(el('red-api-key').value,'');assert.equal(el('black-model').value,'kimi-fast');assert.equal(el('black-api-key').value,'test-black-only-key');
 const saved=Object.fromEntries(Object.keys(w.localStorage).map(k=>[k,w.localStorage.getItem(k)]));
 dom.window.close();
 dom=await page(saved);w=dom.window;
 assert.equal(w.document.getElementById('red-model').value,customId);
 assert.equal(w.document.getElementById('red-api-key').value,'');assert.equal(w.document.getElementById('black-api-key').value,'');
 assert.throws(()=>w.APIProfiles.config('red'),/重新输入/);
 // Claude 预设与本机空 key
 const opts=[...w.document.getElementById('profile-provider').options].map(o=>o.value);
 assert(opts.includes('anthropic'));assert(opts.includes('custom'));
 choose(w,'profile-list','claude-sonnet');
 assert.equal(w.document.getElementById('profile-provider').value,'anthropic');
 assert.equal(w.document.getElementById('profile-url').value,'https://api.anthropic.com/v1');
 assert.match(w.document.getElementById('provider-help').textContent,/Messages API|Anthropic|Claude/);
 choose(w,'red-model','claude-sonnet');
 assert.match(w.document.getElementById('red-endpoint').textContent,/anthropic/);
 assert.throws(()=>w.APIProfiles.config('red'),/重新输入/);
 w.document.getElementById('new-profile').click();
 fill(w,'profile-name','本机 Ollama');choose(w,'profile-provider','custom');
 fill(w,'profile-url','http://127.0.0.1:11434/v1');fill(w,'profile-model','llama3.2');
 fill(w,'profile-max','1024');fill(w,'profile-timeout','30');w.document.getElementById('assign-red').click();
 const localId=w.document.getElementById('red-model').value;
 assert.equal(w.document.getElementById('red-api-key').value,'');
 const localCfg=w.APIProfiles.config('red');
 assert.equal(localCfg.api_key,'');assert.equal(localCfg.provider,'custom');
 assert.match(w.document.getElementById('red-api-key').placeholder,/Ollama/);
 assert.match(w.document.getElementById('red-endpoint').textContent,/可留空/);
 // localhost and ::1 also allowed
 w.document.getElementById('new-profile').click();
 fill(w,'profile-name','本机 IPv6');fill(w,'profile-url','http://[::1]:1234/v1');
 fill(w,'profile-model','local-model');fill(w,'profile-max','1024');fill(w,'profile-timeout','30');
 w.document.getElementById('assign-black').click();
 const v6=w.APIProfiles.config('black');
 assert.equal(v6.api_key,'');
 // 远程空 key 仍拦截（上面刷新后的自定义配置）
 choose(w,'profile-list',customId);w.document.getElementById('delete-profile').click();
 assert(!w.document.getElementById('profile-list').querySelector(`option[value="${customId}"]`));
 const stored2=JSON.stringify(Object.keys(w.localStorage).map(k=>w.localStorage.getItem(k)));
 assert(!stored2.includes('自定义 Alpha 修改'));
 // 自动去掉多余尾缀
 w.document.getElementById('new-profile').click();
 fill(w,'profile-name','Claude 手动');choose(w,'profile-provider','anthropic');
 fill(w,'profile-url','https://api.anthropic.com/v1/messages');fill(w,'profile-model','claude-sonnet-4-5');
 fill(w,'profile-max','4096');fill(w,'profile-timeout','180');w.document.getElementById('assign-red').click();
 fill(w,'red-api-key','sk-ant-testkey-not-real');
 const stripped2=w.APIProfiles.config('red');
 assert.equal(stripped2.base_url,'https://api.anthropic.com/v1');
 assert.equal(stripped2.provider,'anthropic');
 const stored3=JSON.stringify(Object.keys(w.localStorage).map(k=>w.localStorage.getItem(k)));
 assert(!stored3.includes('sk-ant-testkey-not-real'));
 dom.window.close();
 const low=[
  {id:'ds-flash',display_name:'DeepSeek V4 Flash（更快）',provider:'deepseek',base_url:'https://api.deepseek.com/v1',model_name:'deepseek-flash',thinking_mode:'disabled',max_output:1024,timeout:90},
  {id:'kimi-fast',display_name:'Kimi K3.1 Pro 高速版（更快）',provider:'kimi',base_url:'https://api.moonshot.cn/v1',model_name:'kimi-k3.1-pro-highspeed',thinking_mode:'low',max_output:1024,timeout:90},
  {id:'ollama-local',display_name:'Ollama 本地模型',provider:'custom',base_url:'http://127.0.0.1:11434/v1',model_name:'llama3.2',thinking_mode:'disabled',max_output:1024,timeout:90},
 ];
 dom=await page({'aichess.apiProfiles.v1':JSON.stringify(low)});
 const migrated=JSON.parse(dom.window.localStorage.getItem('aichess.apiProfiles.v1'));
 const find=id=>migrated.find(p=>p.id===id);
 assert.equal(find('ds-flash').max_output,4096);
 assert.equal(find('kimi-fast').max_output,8192);
 assert.equal(find('ollama-local').max_output,1024);
 assert.match(dom.window.document.getElementById('profile-status').textContent,/输出上限/);
 dom.window.close();
 console.log('PASS DOM: 双方独立选择、增改删/保存、刷新 key 清空且不落盘、手动显隐、仅确认后测试、运行时锁定、长日志展开与 HTML 转义、Claude 预设、本机空 key、地址尾缀自动去掉、旧的低输出上限会调高且本机配置不动');
 console.log('NOTE: jsdom 不计算真实 CSS 布局；小屏/粘性工具栏需真实浏览器验收。');
})().catch(e=>{console.error(e);process.exit(1);});
