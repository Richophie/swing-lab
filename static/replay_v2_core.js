(()=>{
const baseLoad=window.loadSwingLabPool;
let worker=null,seq=0,metaCache=null;
const pending=new Map();
function supported(){return typeof Worker!=='undefined'}
function ensure(){
  if(worker)return worker;
  if(!supported())return null;
  worker=new Worker('/static/replay_worker.js?v=20260816-2');
  worker.onmessage=e=>{const m=e.data||{},p=pending.get(m.id);if(!p)return;if(m.type==='progress'){p.progress?.(m);return}pending.delete(m.id);if(m.type==='error')p.reject(new Error(m.error||'Worker 오류'));else p.resolve(m.data)};
  worker.onerror=e=>{const err=new Error(e?.message||'백테스트 Worker를 시작하지 못했습니다.');for(const p of pending.values())p.reject(err);pending.clear();try{worker.terminate()}catch{}worker=null};
  return worker;
}
function request(type,payload={},progress){return new Promise((resolve,reject)=>{const w=ensure();if(!w){reject(new Error('Web Worker 미지원'));return}const id=`btw-${Date.now()}-${++seq}`;pending.set(id,{resolve,reject,progress});w.postMessage({id,type,payload})})}
async function init(){if(metaCache)return metaCache;metaCache=await request('init');return metaCache}
async function run(payload,progress){return request('run',payload,progress)}
window.SwingReplayWorker={supported:supported(),init,run,reset(){try{worker?.terminate()}catch{}worker=null;metaCache=null;pending.clear()}};
window.loadSwingLabPool=async()=>{if(supported()){try{return await init()}catch(e){console.warn('V2 worker fallback',e)}}return baseLoad()};
})();
