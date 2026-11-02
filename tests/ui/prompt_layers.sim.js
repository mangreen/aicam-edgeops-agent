// UI 行為測試（Prompt 層：刪除、編輯後捲動）。用法：node tests/ui/prompt_layers.sim.js 或 make test-ui
const fs=require('fs'),vm=require('vm');
// 直接從 agent/ui/index.html 取出 <script>，在最小的假 DOM 中執行（不需要瀏覽器）
const html=fs.readFileSync(__dirname+'/../../agent/ui/index.html','utf8');
let src=html.match(/<script>([\s\S]*)<\/script>/)[1].replace(/boot\(\);setInterval\(poll,1500\);poll\(\);\s*$/,'');
const log=[],els={};
function mk(id){return {id,value:'',innerHTML:'',textContent:'',checked:false,disabled:false,style:{},offsetWidth:1,
  classList:{_s:new Set(),add(c){this._s.add(c)},remove(c){this._s.delete(c)},has(c){return this._s.has(c)}},
  scrollIntoView(o){log.push(['scrollIntoView',id,JSON.stringify(o)])},focus(){log.push(['focus',id])},appendChild(){},remove(){}}}
const ctx={document:{getElementById:id=>els[id]||(els[id]=mk(id)),createElement:()=>mk('x'),querySelector:()=>mk('q')},
 confirm:m=>{log.push(['confirm',m]);return ctx._confirm},_confirm:true,alert:m=>log.push(['alert',m]),EventSource:class{},setInterval(){},console,
 fetch:async(u,o={})=>{log.push(['fetch',o.method||'GET',u]);const j=(x,ok=true)=>({ok,json:async()=>x});
  if(u==='/api/prompts'&&!o.method)return j(ctx._prompts);if(u==='/api/guards')return j({chains:{input:['length']},recent:[]});
  if(o.method==='DELETE')return j(ctx._delOk?{ok:true}:{detail:'沒有這個 UI 層'},ctx._delOk);return j({})}};
ctx._delOk=true;
ctx._prompts={editable:true,layers:[
 {name:'system',scope:'all',priority:0,enabled:true,source:'file',content:'你是 agent',overrides_file:false},
 {name:'operator-scope',scope:'chat',priority:5,enabled:true,source:'ui',content:'只允許查詢',overrides_file:false},
 {name:'chat-style',scope:'chat',priority:10,enabled:true,source:'ui',content:'覆蓋層',overrides_file:true}]};
vm.createContext(ctx);
vm.runInContext(src+';this.__api={loadSec,editLayer,delLayer,clearForm,setF(v){F=v}};',ctx);
const A=ctx.__api;let fails=0;const ok=(c,m)=>{if(!c)fails++;console.log((c?'PASS ':'FAIL ')+m)};
(async()=>{
 A.setF({llm_probe:false,chat:true});
 await A.loadSec();
 const h=els.sec.innerHTML;
 ok((h.match(/onclick="delLayer\(/g)||[]).length===2,'刪除鈕只出現在 2 個 UI 層（檔案層沒有）');
 ok(/delLayer\(0\)/.test(h)===false && /delLayer\(1\)/.test(h) && /delLayer\(2\)/.test(h),'檔案層(index0)無刪除鈕；UI 層(1,2)有');
 ok(h.includes('刪除覆蓋層並恢復檔案層'),'覆蓋層的刪除說明為「恢復檔案層」');
 ok(h.includes('id="pform"')&&h.includes('id="ptitle"'),'編輯區有 id');
 log.length=0; A.editLayer(1);
 ok(log.some(l=>l[0]==='scrollIntoView'&&l[1]==='pform'&&l[2].includes('smooth')),'按「編輯」→ 平滑捲動到編輯區');
 ok(log.some(l=>l[0]==='focus'&&l[1]==='pc'),'捲動後聚焦到內容欄');
 ok(els.pn.value==='operator-scope'&&els.pc.value==='只允許查詢'&&els.ptitle.innerHTML.includes('編輯：operator-scope'),'表單帶入內容並顯示「編輯：名稱」');
 ok(els.pform.classList.has('flash'),'編輯區短暫高亮');
 log.length=0; await A.delLayer(1);
 ok(log.some(l=>l[0]==='confirm'),'刪除前有確認'); ok(log.some(l=>l[0]==='fetch'&&l[1]==='DELETE'&&l[2]==='/api/prompts/operator-scope'),'呼叫 DELETE /api/prompts/operator-scope');
 ok(log.some(l=>l[0]==='fetch'&&l[2]==='/api/prompts'&&l[1]==='GET'),'刪除後重新載入列表'); ok(els.pn.value==='','刪除正在編輯的層 → 表單清空');
 log.length=0; ctx._confirm=false; await A.delLayer(2);
 ok(!log.some(l=>l[0]==='fetch'&&l[1]==='DELETE'),'取消確認 → 不刪除');
 ctx._confirm=true; ctx._delOk=false; log.length=0; await A.delLayer(2);
 ok(log.some(l=>l[0]==='alert'),'後端 404 → 顯示錯誤訊息');
 ctx._confirm=true; log.length=0; await A.delLayer(2);
 const c=log.filter(l=>l[0]==='confirm')[0]; ok(c&&c[1].includes('恢復同名的檔案層'),'覆蓋層的確認訊息提到會恢復檔案層');
 ctx._prompts.editable=false; await A.loadSec(); ok(!els.sec.innerHTML.includes('delLayer('),'prompt_edit 關閉 → 唯讀，沒有刪除／編輯鈕');
process.exitCode=fails?1:0;
})();
