// Runs the actual inline admin script against a minimal DOM and mocked HTTP.
// No customer data or production requests are used.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../server/templates/admin.html'),'utf8');
function setup(){
  const nodes=new Map(), requests=[];
  function node(id){if(!nodes.has(id))nodes.set(id,{value:'',style:{},dataset:{},handlers:{},className:'',textContent:'',innerHTML:'',disabled:false,addEventListener(k,f){this.handlers[k]=f},setAttribute(){},removeAttribute(){},showModal(){this.open=true},close(){this.open=false}});return nodes.get(id)}
  const ctx=vm.createContext({console,URLSearchParams,Intl,Date,Map,Set,Number,JSON,String,Boolean,Promise,Error,
    document:{querySelector:node,querySelectorAll:()=>[]},window:{addEventListener(){}},
    localStorage:{getItem:()=>'',setItem(){},removeItem(){}},confirm:()=>true,
    fetch:async(url,options={})=>{requests.push({url,options});return{ok:true,status:200,json:async()=>({ok:true,errors:[],summary:{},product:{config_version:2,free:{photo_limit:0},invite:{reward_days:0}}})}}
  });
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],ctx);
  return{ctx,node,requests,run:s=>vm.runInContext(s,ctx)};
}
test('license classifications and safe rendering',()=>{
  const {run}=setup();
  assert.equal(run('licenseState({has_license:false})'),'none');
  assert.equal(run('licenseState({has_license:true,license_type:"lifetime"})'),'lifetime');
  assert.equal(run('licenseState({has_license:true,license_type:"term",expires_at:"2000-01-01T00:00:00Z"})'),'expired');
  assert.equal(run('licenseState({has_license:true,license_type:"term",expires_at:"2099-01-01T00:00:00Z"})'),'term');
  assert.equal(run(`escapeHtml(${JSON.stringify('<script>"&')})`),'&lt;script&gt;&quot;&amp;');
  assert.match(run('formatTime("2026-09-08T07:00:00Z")'),/15:00/);
});
test('account search matches full device and invitation identifiers',()=>{
  const {run,node}=setup();
  run('accountsCache=[{account:{id:1,username:"A"},license:{machines:[{machine_id:"DEVICE-123"}]},invite_code:"INVITE1"},{account:{id:2,username:"B"},license:{machines:[]}}]');
  node('#accountSearch').value='device-123';run('filterAccounts()');
  assert.equal(node('#accountCount').textContent,'显示 1 / 2 个账号');
  node('#accountSearch').value='invite1';run('filterAccounts()');
  assert.equal(node('#accountCount').textContent,'显示 1 / 2 个账号');
});
test('grouping is scoped and original evidence is escaped',()=>{
  const {run,node}=setup();node('#errorView').value='groups';
  run('errorsCache=[{id:2,fingerprint:"same",message:"<script>alert(1)</script>",context:{status:500},severity:"error"},{id:1,fingerprint:"same",severity:"error"}];renderErrors()');
  assert.match(node('#errorScope').textContent,/显示 1 组/);
  assert.match(node('#errorRows').innerHTML,/本次 2 次/);
  assert.ok(!node('#errorRows').innerHTML.includes('<script>'));
  run('openError(2)');assert.match(node('#errorDetail').innerHTML,/非已确认原因/);
});
test('zero product settings are preserved',async()=>{
  const {run,node}=setup();await run('loadProductConfig()');
  assert.equal(node('#cfgFreeLimit').value,0);assert.equal(node('#cfgInviteDays').value,0);
});
test('resolve and reopen use existing endpoint and note payload',async()=>{
  const {run,node,requests}=setup();
  for(const resolved of [false,true]){
    run(`selectedError={id:8,resolved:${resolved}}`);node('#resolutionNote').value=' 已核查 ';
    await node('#saveErrorBtn').handlers.click();
    const request=requests.filter(r=>r.options.method==='POST').at(-1);
    assert.equal(request.url,'/api/admin/errors/8/resolve');
    assert.deepEqual(JSON.parse(request.options.body),{resolved:!resolved,note:'已核查'});
  }
});
test('license submission retains account, duration and machine limit',async()=>{
  const {node,requests}=setup();
  node('#licenseAccountId').value='7';node('#licenseType').value='term';node('#licenseDays').value='45';node('#licenseLimit').value='2';
  await node('#licenseForm').handlers.submit({preventDefault(){}});
  assert.deepEqual(JSON.parse(requests[0].options.body),{account_id:7,license_type:'term',valid_days:45,machine_limit:2});
});
test('failed and malformed responses are not reported as successful',async()=>{
  const {ctx,run,node}=setup();
  ctx.fetch=async()=>({ok:false,status:401,json:async()=>({ok:false,error:'登录失效'})});
  await assert.rejects(run('api("/api/admin/accounts")'),/登录失效/);
  assert.equal(node('#mainBox').style.display,'none');assert.match(node('#loginNotice').textContent,/重新登录/);
  ctx.fetch=async()=>({ok:true,status:200,json:async()=>{throw Error('html')}});
  await assert.rejects(run('api("/api/admin/accounts")'),/返回内容异常/);
});
test('account status filter hides archived accounts by default selection',()=>{
  const {run,node}=setup();node('#accountStatusFilter').value='active';
  run('accountsCache=[{account:{id:1,username:"normal",status:"active"},license:{}},{account:{id:2,username:"archived",status:"disabled"},license:{}}];filterAccounts()');
  assert.equal(node('#accountCount').textContent,'显示 1 / 2 个账号');
  assert.ok(!node('#rows').innerHTML.includes('archived'));
  node('#accountStatusFilter').value='disabled';run('filterAccounts()');
  assert.match(node('#rows').innerHTML,/恢复账号/);
});
test('dashboard distinguishes unavailable history and preserves zero metrics',()=>{
  const {run,node}=setup();
  run('renderDashboard({day:"2026-09-08",today_active:0,recent_active:0,week_active:0,trend:[{day:"2026-09-07",active:null},{day:"2026-09-08",active:0}],latest:[],channels:[]})');
  assert.match(node('#usageTrend').innerHTML,/未采集/);
  assert.match(node('#usageStats').innerHTML,/>0</);
  assert.match(node('#usageCoverage').textContent,/不补造历史/);
});
