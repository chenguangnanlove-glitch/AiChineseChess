/* 普通 API 配置仅存浏览器；key 不进入 localStorage/sessionStorage/URL/DOM 属性或日志。 */
window.APIProfiles = (() => {
    'use strict';
    const STORE = 'aichess.apiProfiles.v1';
    const SELECTED = 'aichess.selectedProfiles.v1';
    const byId = id => document.getElementById(id);
    const defaults = [
        ['ds-flash', 'DeepSeek V4 Flash（更快）', 'deepseek', 'deepseek-flash', 'disabled', '', 4096, 90],
        ['ds-pro', 'DeepSeek V4 Pro（更强）', 'deepseek', 'deepseek-v4-pro', 'disabled', '', 4096, 90],
        ['ds-chat', 'DeepSeek Chat（可能已停用）', 'deepseek', 'deepseek-chat', 'disabled', '', 4096, 90],
        ['kimi-fast', 'Kimi K3.1 Pro 高速版（更快）', 'kimi', 'kimi-k3.1-pro-highspeed', 'low'],
        ['kimi-pro', 'Kimi K3.1 Pro（更强）', 'kimi', 'kimi-k3.1-pro', 'high'],
        ['gemini-25', 'Gemini 2.5 Flash', 'gemini', 'gemini-2.5-flash', 'disabled'],
        ['gemini-38', 'Gemini 3.8 Flash', 'gemini', 'gemini-3.8-flash', 'disabled'],
        ['gemini-4h', 'Gemini 4 Hydrogen', 'gemini', 'gemini-4-hydrogen', 'disabled'],
        ['claude-sonnet', 'Claude Sonnet（Anthropic 原生）', 'anthropic', 'claude-sonnet-4-5', 'disabled', 'https://api.anthropic.com/v1', 4096, 180],
        ['ollama-local', 'Ollama 本地模型', 'custom', 'llama3.2', 'disabled', 'http://127.0.0.1:11434/v1', 1024, 90],
    ];
    const urls = {deepseek:'https://api.deepseek.com/v1', kimi:'https://api.moonshot.cn/v1', gemini:'https://generativelanguage.googleapis.com/v1beta/openai/', anthropic:'https://api.anthropic.com/v1', custom:''};
    const modes = {
        deepseek: [['disabled','快速 · 关闭思考'],['low','低强度'],['high','高强度']],
        kimi: [['low','低强度（不能关闭）'],['high','高强度']],
        gemini: [['disabled','不发送思考参数']], anthropic: [['disabled','不发送思考参数（官方 Messages API）']], custom: [['disabled','不发送思考参数']]
    };
    const localHosts = new Set(['localhost','127.0.0.1','::1']);
    function hostnameOf(base) {
        try { return new URL(base).hostname.replace(/^\[|\]$/g, '').toLowerCase(); } catch (_) { return ''; }
    }
    function isLocalHost(base) { return localHosts.has(hostnameOf(base)); }
    function normalizeBase(base) {
        return String(base || '').trim().replace(/\/+$/,'').replace(/\/(chat\/completions|messages)$/,'');
    }
    const fields = ['id','display_name','provider','base_url','model_name','max_output','timeout','thinking_mode'];
    const keys = new Map(); // side:id → key，仅当前页面内存，刷新即失去
    let profiles = [], selection = {red:'ds-flash',black:'kimi-fast'}, editing = null, locked = false;
    const profile = id => profiles.find(p => p.id === id);
    const whitelist = p => Object.fromEntries(fields.filter(k => p[k] !== undefined).map(k => [k,p[k]]));
    function writeStore() {
        try {
            localStorage.setItem(STORE, JSON.stringify(profiles.map(whitelist)));
            localStorage.setItem(SELECTED, JSON.stringify(selection));
            return true;
        } catch (_) { message('本地存储不可用，配置仅当前页面有效，请勿刷新。', true); return false; }
    }
    function outputFloor(p) {
        if (p.provider === 'kimi') return p.thinking_mode === 'high' ? 16384 : 8192;
        if (p.provider === 'deepseek') return p.thinking_mode && p.thinking_mode !== 'disabled' ? 8192 : 4096;
        if (p.provider === 'anthropic') return 2048;
        return 0;
    }
    function migrateBudgets(list) {
        const notes = [];
        for (const p of list) {
            const floor = outputFloor(p);
            if (floor && Number(p.max_output) < floor) {
                notes.push(`${p.display_name} 的最大输出 token 从 ${p.max_output} 调到 ${floor}`);
                p.max_output = floor;
            }
        }
        return notes;
    }
    function readStore() {
        const fresh = () => defaults.map(([id,display_name,provider,model_name,thinking_mode,base_url,max_output,timeout]) => ({id,display_name,provider,model_name,thinking_mode,base_url:base_url||urls[provider]||'',max_output:max_output||(provider==='kimi'?16384:provider==='anthropic'?4096:1024),timeout:timeout||((provider==='gemini'||provider==='anthropic')?180:90)}));
        let migrated = [];
        try {
            const stored = localStorage.getItem(STORE);
            profiles = stored === null ? fresh() : JSON.parse(stored).map(whitelist).filter(p => {
                try { check(p); return typeof p.id === 'string' && p.id.length < 200; } catch (_) { return false; }
            });
            if (stored !== null) {
                const have = new Set(profiles.map(p => p.id));
                for (const item of fresh()) { if (!have.has(item.id)) profiles.push(item); }
            }
            const chosen = JSON.parse(localStorage.getItem(SELECTED) || '{}');
            ['red','black'].forEach(side => { if (profile(chosen[side])) selection[side] = chosen[side]; });
            migrated = migrateBudgets(profiles);
            if (migrated.length) writeStore();
        } catch (_) { profiles = fresh(); }
        ['red','black'].forEach(side => { if (!profile(selection[side])) selection[side] = profiles[0]?.id || ''; });
        return migrated;
    }
    function check(p) {
        if (!p.display_name?.trim() || p.display_name.length > 100) throw Error('显示名称不能为空，最长 100 字符');
        if (!modes[p.provider]) throw Error('请选择支持的 provider');
        if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$/.test(p.model_name)) throw Error('model 请填准确 ID（不能含空格或中文，最长 200 字符）');
        let url;
        try { url = new URL(p.base_url); } catch (_) { throw Error('请填写完整 base_url，例如 https://服务商/v1'); }
        if (!['http:','https:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash || /[\s\\\x00-\x1f]/.test(p.base_url)) throw Error('base_url 仅支持 http(s)，不能含账号、密码、查询参数、空白或 #');
        p.base_url = normalizeBase(p.base_url);
        for (const [k,label,min,max] of [['max_output','最大输出 token',64,65536],['timeout','读取超时',2,600]]) {
            if (!Number.isInteger(Number(p[k])) || Number(p[k])<min || Number(p[k])>max) throw Error(`${label}须为 ${min}–${max} 的整数`);
        }
        if (!modes[p.provider].some(([v]) => v === p.thinking_mode)) throw Error('思考模式不适用于此 provider');
    }
    function modeOptions(el, provider, value) {
        el.replaceChildren(...modes[provider].map(([v,label]) => new Option(label,v)));
        el.value = modes[provider].some(([v]) => v===value) ? value : modes[provider][0][0];
    }
    function renderSelections() {
        ['red','black'].forEach(side => {
            const select = byId(`${side}-model`);
            select.replaceChildren(...profiles.map(p => new Option(p.display_name,p.id)));
            select.value = selection[side];
            renderSide(side);
        });
        const list = byId('profile-list');
        list.replaceChildren(...profiles.map(p => new Option(`${p.display_name} · ${p.model_name}`,p.id)));
        if (profile(editing)) list.value = editing;
        lock(locked);
    }
    function renderSide(side) {
        const p = profile(selection[side]);
        const endpoint = byId(`${side}-endpoint`), keyInput = byId(`${side}-api-key`);
        keyInput.type = 'password';
        const toggle = document.querySelector(`[data-target="${side}-api-key"]`);
        toggle.textContent='显示'; toggle.setAttribute('aria-pressed','false');
        byId(`${side}-test-status`).textContent='';
        keyInput.value = keys.get(`${side}:${selection[side]}`) || '';
        const local = p && isLocalHost(p.base_url);
        keyInput.placeholder = local ? '本地模型如 Ollama 可留空（不保存）' : '请输入 key（不保存；本地模型如 Ollama 可留空）';
        if (!p) { endpoint.textContent='请在下方添加 API 配置'; modeOptions(byId(`${side}-thinking-mode`),'custom'); return; }
        endpoint.textContent=`${p.provider} · ${p.model_name}\n${p.base_url}` + (local ? '\n本机地址：API key 可留空' : '');
        modeOptions(byId(`${side}-thinking-mode`), p.provider, p.thinking_mode);
    }
    function select(side) {
        selection[side] = byId(`${side}-model`).value;
        renderSide(side); writeStore(); lock(locked);
    }
    function sideWord(side) {
        const legend = document.querySelector(`.player-${side} legend`);
        const text = legend && legend.textContent.trim();
        return text || (side === 'red' ? '红方' : '黑方');
    }
    function config(side, requireKey = true) {
        const p = profile(selection[side]);
        if (!p) throw Error(`${sideWord(side)}：请先选择或添加 API 配置`);
        const key = byId(`${side}-api-key`).value.trim();
        const cfg = {...whitelist(p), thinking_mode:byId(`${side}-thinking-mode`).value, api_key:key};
        check(cfg);
        if (requireKey && !key && !isLocalHost(cfg.base_url)) throw Error(`${sideWord(side)}：请输入 API key（配置保存不包含 key；刷新后需重新输入）。本地模型如 Ollama 可留空`);
        if (key && /[\s\x00-\x1f]/.test(key)) throw Error('API key 不能含空白或换行');
        return cfg;
    }
    function message(text, error=false) {
        const el=byId('profile-status'); el.textContent=text; el.className=`test-status ${error?'error':'success'}`;
    }
    function loadEditor(id) {
        editing = id || null;
        const p = profile(id) || {display_name:'',provider:'custom',base_url:'',model_name:'',max_output:1024,timeout:90,thinking_mode:'disabled'};
        for (const [suffix,k] of [['name','display_name'],['provider','provider'],['url','base_url'],['model','model_name'],['max','max_output'],['timeout','timeout']]) byId(`profile-${suffix}`).value=p[k];
        modeOptions(byId('profile-thinking'),p.provider,p.thinking_mode);
        providerHelp(); message(id?'正在编辑；保存后仅影响下一局。':'新配置：请填写服务商给出的准确地址和模型 ID。');
    }
    function providerHelp() {
        const p=byId('profile-provider').value;
        byId('provider-help').textContent=({
            custom:'自定义仅发送 model / messages / stream / max_tokens。若服务只认 max_completion_tokens 或不支持流式，程序会自动重试。Ollama（http://127.0.0.1:11434/v1）和 LM Studio 等本机模型可留空 API key。',
            gemini:'使用 Google 的 OpenAI 兼容根地址，不是 Gemini 原生 generateContent 接口；不发送厂商思考参数。',
            deepseek:'只在 DeepSeek 模板发送 thinking、reasoning_effort 与 max_tokens。输出上限含思考。默认至少 4096；若正文仍被截断，对局会临时提高到不超过 8192，不换模型。',
            kimi:'Kimi 模板发送 reasoning_effort 与 max_completion_tokens；不能完全关思考。上限含思考 token，过低可能没有最终棋步。',
            anthropic:'使用 Anthropic 官方 Messages API（不是 OpenAI 格式）。默认地址 https://api.anthropic.com/v1，程序会自动请求 /messages。请填写控制台中的准确模型 ID（如 claude-sonnet-4-5）。'
        })[p];
    }
    function collectEditor() {
        const p={id:editing || (window.crypto?.randomUUID ? crypto.randomUUID() : `custom-${Date.now()}-${Math.random().toString(36).slice(2)}`),
            display_name:byId('profile-name').value.trim(),provider:byId('profile-provider').value,
            base_url:normalizeBase(byId('profile-url').value),model_name:byId('profile-model').value.trim(),
            max_output:Number(byId('profile-max').value),timeout:Number(byId('profile-timeout').value),thinking_mode:byId('profile-thinking').value};
        check(p); return p;
    }
    function save(assignSide) {
        if (locked) return;
        try {
            const p=collectEditor();
            const idx=profiles.findIndex(x=>x.id===p.id);
            if (idx<0) profiles.push(p); else profiles[idx]=p;
            // 已编辑 endpoint/provider/model 就清掉关联 key，避免发到不同服务商。
            ['red','black'].forEach(side=>keys.delete(`${side}:${p.id}`));
            editing=p.id; if (assignSide) selection[assignSide]=p.id;
            const persisted=writeStore(); renderSelections(); loadEditor(p.id);
            message(persisted ? '配置已保存（不含 key）。关联 key 已清空，请重新输入；另一方选择保持不变。' : '配置本次可用，但本地存储不可用，刷新将丢失。',!persisted);
        } catch(e) { message(e.message,true); }
    }
    async function test(side) {
        if (locked) return;
        let cfg; try { cfg=config(side); } catch(e) { alert(e.message); return; }
        const caps=cfg.provider==='kimi'?'最多 512 输出 token（含思考）':(cfg.provider==='anthropic'?'最多 128 输出 token':'最多 64 输出 token');
        const http=cfg.base_url.startsWith('http:')?'\n注意：HTTP 会明文传输 key；仅建议可信本地服务使用。':'';
        if (!confirm(`将向 ${cfg.base_url} 发送一次小请求，可能产生 API 费用。\n模型：${cfg.model_name}\n${caps}；最长 20 秒。不会保存或显示 key。${http}\n是否测试？`)) return;
        const el=byId(`${side}-test-status`), button=document.querySelector(`.test-side[data-side="${side}"]`);
        button.disabled=true; el.textContent='正在测试连接…（一次请求）'; el.className='test-status';
        try {
            const r=await fetch('/api/test_connection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,config:cfg})});
            const data=await r.json(); el.textContent=data.message || `测试失败（HTTP ${r.status}）`; el.className=`test-status ${data.status==='success'?'success':'error'}`;
        } catch (_) { el.textContent='无法连接本地象棋服务，请确认终端程序正在运行。'; el.className='test-status error'; }
        finally { button.disabled=locked; }
    }
    function lock(active) {
        locked=!!active;
        if (locked) document.querySelectorAll('.key-toggle').forEach(b=>{byId(b.dataset.target).type='password'; b.textContent='显示'; b.setAttribute('aria-pressed','false');});
        document.querySelectorAll('[data-setup]').forEach(el=>el.disabled=locked);
        // 自定义/Gemini 没有可以设置的思考参数
        ['red','black'].forEach(side=>{ const p=profile(selection[side]); if (!p || ['gemini','custom','anthropic'].includes(p.provider)) byId(`${side}-thinking-mode`).disabled=true; });
        byId('config-lock-note').textContent=locked?'当前对局进行/暂停中，配置锁定；可继续当前对局，或停止后修改下一局配置。':'停止状态：配置修改只用于下一局。key 不会被保存。';
    }
    function init() {
        const migrated = readStore(); renderSelections(); loadEditor(profiles[0]?.id);
        if (migrated && migrated.length) message('已自动提高过低的输出上限，避免回答在写出棋步前被截断（不是换模型）：' + migrated.join('；') + '。');
        ['red','black'].forEach(side=>{
            byId(`${side}-api-key`).addEventListener('input',()=>keys.set(`${side}:${selection[side]}`,byId(`${side}-api-key`).value));
            document.querySelector(`.test-side[data-side="${side}"]`).addEventListener('click',()=>test(side));
        });
        document.querySelectorAll('.key-toggle').forEach(b=>b.addEventListener('click',()=>{const input=byId(b.dataset.target);const show=input.type==='password';input.type=show?'text':'password';b.textContent=show?'隐藏':'显示';b.setAttribute('aria-pressed',String(show));}));
        byId('profile-list').addEventListener('change',e=>loadEditor(e.target.value));
        byId('new-profile').addEventListener('click',()=>{ byId('profile-list').selectedIndex=-1; loadEditor(null);byId('profile-name').focus(); });
        byId('profile-provider').addEventListener('change',()=>{
            const p=byId('profile-provider').value;byId('profile-url').value=urls[p];
            modeOptions(byId('profile-thinking'),p);
            byId('profile-max').value=p==='kimi'?16384:(p==='deepseek'||p==='anthropic'?4096:1024);
            byId('profile-timeout').value=(p==='gemini'||p==='anthropic')?180:90;
            providerHelp();
        });
        byId('profile-form').addEventListener('submit',e=>{e.preventDefault();save();});
        ['red','black'].forEach(side=>byId(`assign-${side}`).addEventListener('click',()=>save(side)));
        byId('delete-profile').addEventListener('click',()=>{
            if (!editing || locked || !confirm('删除此配置？不会删除已保存的棋谱。')) return;
            profiles=profiles.filter(p=>p.id!==editing);
            ['red','black'].forEach(side=>{keys.delete(`${side}:${editing}`);if(selection[side]===editing)selection[side]=profiles[0]?.id||'';});
            editing=profiles[0]?.id||null;writeStore();renderSelections();loadEditor(editing);message('配置已删除（棋谱保留）。');
        });
        byId('expand-log').addEventListener('click',e=>{const expanded=byId('battle-log').classList.toggle('expanded');e.target.textContent=expanded?'收起日志':'展开全部日志';});
    }
    return {init,select,config,lock};
})();
