// Resume a local mirror of the completed run using its generation-pinned GCS inventory.
const fs = require('node:fs');
const f = fs.promises;
const path = require('node:path');
const crypto = require('node:crypto');
const http2 = require('node:http2');
const {execFile} = require('node:child_process');
const execFileAsync = require('node:util').promisify(execFile);
const {performance} = require('node:perf_hooks');
const run = 'matlab-glop-cmp-20261028-fixes';
const plan = require(path.resolve(__dirname, '../cloud/replication-20261028/plans', run, 'launch.json'));
const uri = new URL(plan.run_uri);
const prefix = uri.pathname.slice(1) + '/';
const parent = path.resolve(__dirname, '../cloud-results', run);
const root = path.join(parent, 'final');
const previous = path.join(parent, 'recovery-backup-20261103');
const sdk = path.join(process.env.LOCALAPPDATA, 'Google/Cloud SDK/google-cloud-sdk');
const ca = fs.readFileSync(path.join(sdk, 'lib/third_party/certifi/cacert.pem'));
const python = path.join(process.env.LOCALAPPDATA, 'Programs/Python/Python312/python.exe');
const inventory = JSON.parse(fs.readFileSync(path.join(root, 'bucket-object-index.json')));
const old = new Set(JSON.parse(fs.readFileSync(path.join(previous,'remote-object-index.json'))).map(o=>o.name));
const sockets = [];
const directories = new Map();
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
let token = '', expiry = 0, refreshing;
async function authenticate() {
  if (Date.now() < expiry) return token;
  if (!refreshing) {
    refreshing = execFileAsync(python,['-B',path.join(sdk,'lib/gcloud.py'),'auth','print-access-token','--quiet'],
      {windowsHide:true,encoding:'utf8',timeout:240000})
      .then(({stdout})=>{token=stdout.trim(); expiry=Date.now()+40*60*1000; return token;})
      .finally(()=>{refreshing=undefined;});
  }
  return refreshing;
}
function session(slot) {
  if (!sockets[slot] || sockets[slot].closed || sockets[slot].destroyed) {
    const client=http2.connect('https://storage.googleapis.com',{ca});
    client.on('error',()=>{ if (sockets[slot]===client) sockets[slot]=null; });
    client.on('goaway',()=>{ if (sockets[slot]===client) sockets[slot]=null; client.close(); });
    sockets[slot]=client;
  }
  return sockets[slot];
}
async function fetchObject(o, slot) {
  const headers={':path':'/storage/v1/b/'+uri.host+'/o/'+encodeURIComponent(o.name)+'?alt=media&generation='+o.generation,authorization:'Bearer '+await authenticate()};
  return new Promise((resolve,reject)=>{
    const stream=session(slot).request(headers);
    let status=0; const chunks=[];
    stream.on('response',h=>{status=h[':status'];});
    stream.on('data',chunk=>chunks.push(chunk));
    stream.setTimeout(35000,()=>stream.destroy(new Error('Read timeout')));
    stream.on('error',reject);
    stream.on('aborted',()=>reject(new Error('Transfer interrupted')));
    stream.on('close',()=>{if(!stream.readableEnded)reject(new Error('Stream closed early'));});
    stream.on('end',()=>status===200?resolve(Buffer.concat(chunks)):reject(new Error('HTTP '+status)));
    stream.end();
  });
}
function valid(data,o) {
  return data && data.length===Number(o.size) && crypto.createHash('md5').update(data).digest('base64')===o.md5Hash;
}
async function readLocal(file) {
  try {return await f.readFile(file);} catch(e){ if(e.code==='ENOENT')return null; throw e;}
}
async function save(file,data) {
  const dir=path.dirname(file);
  if(!directories.has(dir)) directories.set(dir,f.mkdir(dir,{recursive:true}));
  await directories.get(dir);
  const tmp=file+'.'+process.pid+'.part';
  await f.writeFile(tmp,data);
  await f.rename(tmp,file);
}
async function one(o,slot) {
  const rel=o.name.slice(prefix.length);
  if(!o.name.startsWith(prefix) || rel.split('/').some(p=>!p || p==='.' || p==='..' || /[\\:]/.test(p))) throw new Error('Invalid object path');
  const file=path.join(root,rel);
  if(valid(await readLocal(file),o)) return 'present';
  if(old.has(o.name)){
    const data=await readLocal(path.join(previous,rel));
    if(valid(data,o)){ await save(file,data); return 'reused'; }
  }
  const data=await fetchObject(o,slot);
  if(!valid(data,o)) throw new Error('Wrong size or MD5');
  await save(file,data);
  return 'downloaded';
}
async function main() {
  const probe=process.argv.includes('--probe');
  const high=process.argv.includes('--high-trials');
  const middle=process.argv.includes('--middle-trials');
  const items=probe ? inventory.filter(o=>o.name.includes('/objects/trial_000000077') && !old.has(o.name)).slice(-128) : (high || middle) ? inventory.filter(o=>{
    const trial=/\/trial_(\d{12})[.]/.exec(o.name);
    if (!trial) return false;
    const id=Number(trial[1]);
    return high ? id>=55001 : id>=31000 && id<55001;
  }).reverse() : inventory;
  const stats={present:0,reused:0,downloaded:0}, errors=[];
  const start=performance.now();
  let next=0;
  async function worker(workerId) {
    while(next<items.length) {
      const o=items[next++];
      for(let attempt=0;attempt<5;attempt++) {
        try {stats[await one(o,workerId%4)]++;break;}
        catch(e){if(attempt===4){errors.push({name:o.name,error:e.message});if(errors.length<=3) console.log('Transfer error',o.name,e.message);}
          else await sleep(Math.min(5000,250*2**attempt)+Math.random()*150);}
      }
    }
  }
  const report=()=>({expected:items.length,verified:stats.present+stats.reused+stats.downloaded,...stats,errors:errors.length,elapsed_seconds:Math.round((performance.now()-start)/1000),updated_at:new Date().toISOString()});
  const timer=setInterval(()=>{const p=report();console.log(JSON.stringify(p));},45000);
  try { await Promise.all(Array.from({length:probe?16:64},(_,w)=>worker(w))); }
  finally { clearInterval(timer); for(const c of sockets) if(c && !c.destroyed) c.close(); }
  const result=report();
  console.log(JSON.stringify(result));
  if(!probe && !high && !middle){
    fs.writeFileSync(path.join(root,'transfer-progress.json'),JSON.stringify({...result,verified_objects:result.verified,status:errors.length?'incomplete':'transfer_complete'},null,2));
    if(errors.length) fs.writeFileSync(path.join(root,'transfer-errors.json'),JSON.stringify(errors,null,2));
  }
  if(errors.length || result.verified!==items.length) process.exitCode=1;
}
main().catch(e=>{console.error(e.message);process.exitCode=1; for(const c of sockets)if(c)c.destroy();});
