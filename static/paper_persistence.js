(()=>{
  const BACKUP_KEY='swingLabPaperStateBackupV1';
  const originalFetch=window.fetch.bind(window);

  function urlText(input){return typeof input==='string'?input:(input&&input.url)||''}
  function pathOf(input){try{return new URL(urlText(input),location.href).pathname}catch{return''}}
  function methodOf(input,init){return String(init?.method||(input&&input.method)||'GET').toUpperCase()}
  function hasActivity(state){
    if(!state||!Array.isArray(state.orders))return false;
    const events=Array.isArray(state.events)?state.events:[];
    const start=Number(state.starting_cash_krw),cash=Number(state.cash_krw);
    return state.orders.length>0||events.length>0||(Number.isFinite(start)&&Number.isFinite(cash)&&Math.abs(start-cash)>.5);
  }
  function readBackup(){try{const x=JSON.parse(localStorage.getItem(BACKUP_KEY)||'null');return x&&Array.isArray(x.orders)?x:null}catch{return null}}
  function saveBackup(state){try{if(state&&Array.isArray(state.orders))localStorage.setItem(BACKUP_KEY,JSON.stringify(state))}catch{}}
  function jsonResponse(data,status=200){return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json; charset=utf-8'}})}

  window.fetch=async function(input,init={}){
    const response=await originalFetch(input,init);
    const path=pathOf(input),method=methodOf(input,init);
    if(!path.startsWith('/api/paper'))return response;
    try{
      const data=await response.clone().json();
      if(!response.ok||data?.error)return response;
      if(path==='/api/paper'&&method==='GET'&&!hasActivity(data)){
        const backup=readBackup();
        if(hasActivity(backup)){
          const headers=new Headers(init?.headers||(input&&input.headers)||{});
          headers.set('Content-Type','application/json');
          const restoredResponse=await originalFetch('/api/paper/restore',{method:'POST',cache:'no-store',headers,body:JSON.stringify({state:backup})});
          const restored=await restoredResponse.clone().json();
          if(restoredResponse.ok&&!restored?.error){saveBackup(restored);return jsonResponse(restored)}
        }
      }
      saveBackup(data);
    }catch{}
    return response;
  };
})();
