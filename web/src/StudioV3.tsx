import {useEffect,useRef,useState} from 'react';
import type {PointerEvent} from 'react';
import {Check,Clock3,ImagePlus,Move,RefreshCw,RotateCcw,ShieldCheck,SquareArrowOutUpRight,Trash2} from 'lucide-react';

type Action=(f:()=>Promise<void>)=>Promise<void>;
interface Reference {id:string;asset_id:string;character_id:string;angle:string;note:string;created_at:string}
interface Job {id:string;panel_id:string;status:string;provider:string;attempt:number;max_attempts:number;candidate_asset_id:string|null;error_code:string|null}
interface Dialogue {id:string;text:string;locked:boolean;x:number;y:number;w:number;h:number}
interface Panel {id:string;approved_asset_id:string|null;dialogues:Dialogue[]}

async function request<T>(path:string,init:RequestInit={}):Promise<T>{
 const response=await fetch('/api'+path,init);
 if(!response.ok){
  const error=await response.json().catch(()=>({detail:'请求失败'}));
  throw Error(typeof error.detail==='string'?error.detail:JSON.stringify(error.detail));
 }
 return response.json() as Promise<T>;
}
const post=(body?:object):RequestInit=>({method:'POST',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});

export function VersionedCharacterReferences({characterId,activeAsset,action,onChanged}:{characterId:string;activeAsset:string|null;action:Action;onChanged:()=>Promise<void>}){
 const [references,setReferences]=useState<Reference[]>([]);
 const [angle,setAngle]=useState('front');
 const [note,setNote]=useState('');
 const [error,setError]=useState('');
 const refresh=()=>request<Reference[]>('/characters/'+characterId+'/references').then(setReferences);
 useEffect(()=>{setReferences([]);setError('');void refresh().catch(e=>setError(String(e)));},[characterId]);
 return <div className="versioned-assets">
  <div className="line spread"><strong>角色定妆参考资产</strong><small>保留全部历史版本</small></div>
  <div className="line">
   <select aria-label="定妆照角度" value={angle} onChange={e=>setAngle(e.target.value)}>
    <option value="front">正面</option><option value="side">侧面</option><option value="back">背面</option>
    <option value="expression">表情</option><option value="outfit">服装</option>
   </select>
   <input aria-label="参考图备注" placeholder="版本备注（可选）" maxLength={300} value={note} onChange={e=>setNote(e.target.value)}/>
  </div>
  <label className="secondary button-link tiny-upload"><ImagePlus size={15}/> 新增参考图版本
   <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{
    const file=e.target.files?.[0];e.target.value='';
    if(!file)return;
    void action(async()=>{
     const fd=new FormData();fd.append('file',file);
     const q=new URLSearchParams({angle,note});
     await request('/characters/'+characterId+'/references?'+q.toString(),{method:'POST',body:fd});
     setNote('');await Promise.all([refresh(),onChanged()]);
    });
   }}/>
  </label>
  {error&&<p className="ai-error">{error}</p>}
  <div className="reference-gallery">{references.map(r=><div key={r.id} className={'reference-card '+(activeAsset===r.asset_id?'active':'')}>
   <img src={'/api/assets/'+r.asset_id} alt={'角色参考 '+r.angle}/>
   <div className="line spread"><small>{r.angle} · {r.note||'未备注'}</small>{activeAsset===r.asset_id&&<ShieldCheck size={15}/>}</div>
   {activeAsset!==r.asset_id&&<button className="secondary small" onClick={()=>void action(async()=>{
    await request('/characters/'+characterId+'/references/'+r.id+'/activate',post());
    await onChanged();
   })}><Check size={14}/> 设为当前定妆</button>}
  </div>)}</div>
  {references.length===0&&<p className="hint">暂无版本化参考图。上传后可以随时切换当前定妆，而不会删除历史图片。</p>}
 </div>;
}

export function GenerationJobPanel({projectId,panelId,selectedCharacters,override,action,onChanged}:{projectId:string;panelId:string;selectedCharacters:string[];override:string;action:Action;onChanged:()=>Promise<void>}){
 const [jobs,setJobs]=useState<Job[]>([]);
 const [provider,setProvider]=useState<'mock'|'ai'>('ai');
 const [error,setError]=useState('');
 const seen=useRef('');
 useEffect(()=>{
  let active=true;
  const poll=async()=>{
   try{
    const result=(await request<Job[]>('/projects/'+projectId+'/jobs')).filter(j=>j.panel_id===panelId);
    if(!active)return;
    setJobs(result);
    setError('');
    const success=result.filter(j=>j.status==='succeeded').map(j=>j.id).join('|');
    if(success!==seen.current){seen.current=success;if(success)void onChanged();}
   }catch(e){if(active)setError(String(e));}
  };
  seen.current='';
  void poll();
  const interval=window.setInterval(()=>void poll(),3500);
  return ()=>{active=false;window.clearInterval(interval)};
 },[projectId,panelId]);
 const queue=()=>action(async()=>{
  await request('/panels/'+panelId+'/jobs',post({provider,character_ids:selectedCharacters,prompt_override:override}));
  const result=await request<Job[]>('/projects/'+projectId+'/jobs');
  setJobs(result.filter(j=>j.panel_id===panelId));
 });
 return <div className="job-module">
  <div className="line spread"><strong><Clock3 size={15}/> 后台画格生成任务</strong><small>排队/执行/重试</small></div>
  <div className="line"><select aria-label="生成服务" value={provider} onChange={e=>setProvider(e.target.value as 'mock'|'ai')}><option value="ai">真实生图模型</option><option value="mock">本地演示 Mock</option></select>
  <button className="primary small" onClick={()=>void queue()}><ImagePlus size={15}/> 提交后台任务</button></div>
  {error&&<p className="ai-error">{error}</p>}
  {jobs.slice(0,12).map(job=><div className="job-row" key={job.id}>
    <div><strong>{job.provider==='mock'?'Mock':'AI'} · {job.status}</strong><small>尝试 {job.attempt}/{job.max_attempts} · {job.id.slice(0,8)}</small>{job.error_code&&<small className="ai-error">{job.error_code}</small>}</div>
    <div className="line">
      {job.status==='succeeded'&&<span className="tag good"><ShieldCheck size={13}/> 候选已就绪</span>}
      {['queued','running'].includes(job.status)&&<button className="secondary small" onClick={()=>void action(async()=>{await request('/jobs/'+job.id+'/cancel',post());setJobs(await request<Job[]>('/projects/'+projectId+'/jobs').then(j=>j.filter(x=>x.panel_id===panelId)));})}><Trash2 size={13}/> 取消</button>}
      {job.status==='failed'&&job.attempt<job.max_attempts&&<button className="secondary small" onClick={()=>void action(async()=>{await request('/jobs/'+job.id+'/retry',post());setJobs(await request<Job[]>('/projects/'+projectId+'/jobs').then(j=>j.filter(x=>x.panel_id===panelId)));})}><RotateCcw size={13}/> 重试</button>}
    </div>
  </div>)}
  <p className="hint">后台任务完成后进入候选图片，不会自动替换已批准画格。任务恢复依赖独立 Worker 进程。</p>
 </div>;
}

type Geometry={x:number;y:number;w:number;h:number};
type Drag={id:string;mode:'move'|'resize';startX:number;startY:number;start:Geometry;current:Geometry};
const clamp=(v:number,a:number,b:number)=>Math.max(a,Math.min(b,v));

export function BubbleCanvas({panel,action,onChanged}:{panel:Panel;action:Action;onChanged:()=>Promise<void>}){
 const container=useRef<HTMLDivElement|null>(null);
 const drag=useRef<Drag|null>(null);
 const [positions,setPositions]=useState<Record<string,Geometry>>({});
 useEffect(()=>{setPositions({});drag.current=null},[panel.id,panel.dialogues.map(d=>d.version??0).join(':')]);
 const begin=(e:PointerEvent<HTMLDivElement>,d:Dialogue,mode:'move'|'resize')=>{
  const geom=positions[d.id]||{x:d.x,y:d.y,w:d.w,h:d.h};
  drag.current={id:d.id,mode,startX:e.clientX,startY:e.clientY,start:geom,current:geom};
  e.currentTarget.setPointerCapture(e.pointerId);e.preventDefault();e.stopPropagation();
 };
 const move=(e:PointerEvent<HTMLDivElement>)=>{
  const current=drag.current;const bounds=container.current?.getBoundingClientRect();
  if(!current||!bounds)return;
  const dx=(e.clientX-current.startX)/bounds.width;
  const dy=(e.clientY-current.startY)/bounds.height;
  const g=current.start;
  const next=current.mode==='move'?
    {x:clamp(g.x+dx,0,1-g.w),y:clamp(g.y+dy,0,1-g.h),w:g.w,h:g.h}:
    {x:g.x,y:g.y,w:clamp(g.w+dx,.15,1-g.x),h:clamp(g.h+dy,.12,1-g.y)};
  current.current=next;
  setPositions(prev=>({...prev,[current.id]:next}));
 };
 const end=(e:PointerEvent<HTMLDivElement>)=>{
  const entry=drag.current;drag.current=null;
  if(!entry)return;
  if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
  const g=entry.current;
  const changed=Object.keys(g).some(key=>Math.abs(g[key as keyof Geometry]-entry.start[key as keyof Geometry])>.0001);
  if(changed)void action(async()=>{await request('/dialogues/'+entry.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(g)});await onChanged()});
 };
 return <div className="bubble-editor">
  <div className="line spread"><strong><Move size={16}/> 拖动和缩放对白气泡</strong><small>只改布局，不改原文</small></div>
  <div className="bubble-stage" ref={container}>
   {panel.approved_asset_id?<img src={'/api/assets/'+panel.approved_asset_id} alt="当前画格" draggable={false}/>:<div className="stage-placeholder">当前格尚无画面</div>}
   {panel.dialogues.map(d=>{
    const g=positions[d.id]||d;
    return <div key={d.id} className="editable-bubble" style={{left:g.x*100+'%',top:g.y*100+'%',width:g.w*100+'%',height:g.h*100+'%'}}
      onPointerDown={e=>begin(e,d,'move')} onPointerMove={move} onPointerUp={end} onPointerCancel={()=>{drag.current=null;setPositions({})}}>
     <span>{d.text}</span><div className="bubble-resize" title="拖动右下角缩放" onPointerDown={e=>begin(e,d,'resize')}/>
    </div>;
   })}
  </div>
  <p className="hint">拖动气泡主体调整位置，拖动右下角方块调整宽高；松开鼠标自动保存。锁定对白也可以调整位置。服务端导出前会检查文字超框或重叠。</p>
 </div>;
}
