import {useEffect,useState} from 'react';
import {GenerationJobPanel} from './StudioV3';
import {BookOpen,CheckCircle2,Image as ImageIcon,RefreshCw,ShieldCheck,Upload,WandSparkles} from 'lucide-react';

type Action=(op:()=>Promise<void>)=>Promise<void>;
interface Character {id:string;name:string;reference_asset_id:string|null}
interface Candidate {id:string;url:string;approved:boolean;created_at:string}
interface Status {story:{ready:boolean;model:string;preview_approval:boolean};image:{ready:boolean;model:string;reference_mode:string;candidate_approval:boolean};warning:string}
interface DraftPanel {sequence:number;scene:string;camera:string;dialogues:{speaker_name:string|null;text:string}[]}
interface Draft {id:string;status:string;draft:{outline:string;panels:DraftPanel[]};created_at?:string}
async function req<T>(path:string,init:RequestInit={}):Promise<T>{
 const res=await fetch('/api'+path,init);
 if(!res.ok){const json=await res.json().catch(()=>({detail:'请求失败'}));throw Error(typeof json.detail==='string'?json.detail:JSON.stringify(json.detail));}
 return res.json() as Promise<T>;
}
const requestJson=(body?:object)=>({method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});

export function AIStatusPanel(){
 const [status,setStatus]=useState<Status|null>(null);
 const [error,setError]=useState('');
 useEffect(()=>{req<Status>('/ai/status').then(setStatus).catch(e=>setError(String(e)));},[]);
 return <div className="ai-module">
   <h3><WandSparkles size={17}/> 真实 AI 模型接入</h3>
   {error&&<p className="ai-error">{error}</p>}
   {!status?<p className="hint">正在检查模型配置…</p>:<>
      <div className="ai-status"><div><strong>剧情大模型</strong><span className={'tag '+(status.story.ready?'good':'pending')}>{status.story.ready?'已配置':'未配置'}</span><p>{status.story.model||'STORY_MODEL 尚未指定'}</p></div>
      <div><strong>画格生图模型</strong><span className={'tag '+(status.image.ready?'good':'pending')}>{status.image.ready?'已配置':'未配置'}</span><p>{status.image.model||'IMAGE_MODEL 尚未指定'}</p></div></div>
      <p className="hint">角色参考模式：{status.image.reference_mode==='edits'?'图片编辑接口（支持上传参考图）':'未启用。当前仅文字提示词生图'}。本地环境变量配置，不会向浏览器返回 API Key。</p>
      <div className="readout"><strong>配置方式</strong><p>后端环境变量：STORY_API_BASE_URL、STORY_MODEL、STORY_API_KEY；IMAGE_API_BASE_URL、IMAGE_MODEL、IMAGE_API_KEY；需要角色参考图时将 IMAGE_REFERENCE_MODE 设为 edits。</p><p>模型接口需支持相应 OpenAI-compatible 格式；生图响应必须提供 data[0].b64_json。图片 URL 下载被禁用。</p></div>
   </>}
 </div>;
}

export function CharacterReference({character,action,onChanged}:{character:Character;action:Action;onChanged:()=>Promise<void>}){
 return <div className="reference-row">
    {character.reference_asset_id?<img className="reference-thumb" alt={character.name+'参考定妆照'} src={'/api/assets/'+character.reference_asset_id}/>:<div className="reference-thumb placeholder"><ImageIcon size={19}/></div>}
    <label className="secondary button-link tiny-upload"><Upload size={14}/>{character.reference_asset_id?'更换定妆照':'上传定妆照'}
      <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{
        const file=e.target.files?.[0];e.target.value='';
        if(!file)return;
        void action(async()=>{
          const fd=new FormData();fd.append('file',file);
          await req('/characters/'+character.id+'/reference',{method:'POST',body:fd});
          await onChanged();
        });
      }}/></label>
 </div>;
}

export function StoryAI({projectId,action,onChanged}:{projectId:string;action:Action;onChanged:()=>Promise<void>}){
 const [drafts,setDrafts]=useState<Draft[]>([]);
 const [selected,setSelected]=useState('');
 const [error,setError]=useState('');
 const reload=async()=>setDrafts(await req<Draft[]>('/projects/'+projectId+'/story-drafts'));
 useEffect(()=>{setDrafts([]);setSelected('');reload().catch(e=>setError(String(e)));},[projectId]);
 const draft=drafts.find(d=>d.id===selected)||drafts[0];
 return <div className="ai-module">
   <h3><BookOpen size={17}/> AI 剧情创作 · 审核模式</h3>
   <p className="hint">调用已配置的剧本大模型，生成每格场景、景别和中文台词。先审阅、再明确批准；不会修改已有分镜和对白。</p>
   <button className="primary" onClick={()=>void action(async()=>{
     const result=await req<Draft>('/projects/'+projectId+'/story:ai',requestJson());
     await reload();setSelected(result.id);
   })}><WandSparkles size={16}/> AI 生成待审剧本</button>
   {error&&<p className="ai-error">{error}</p>}
   {drafts.length>0&&<div className="draft"><label>剧本候选</label><select value={draft?.id||''} onChange={e=>setSelected(e.target.value)}>
     {drafts.map(x=><option key={x.id} value={x.id}>{x.created_at?x.created_at.slice(0,19):x.id.slice(0,8)} · {x.status}</option>)}</select>
     {draft&&<><p><strong>剧情大纲：</strong>{draft.draft.outline}</p>
      <div className="draft-scenes">{draft.draft.panels.map(p=><div key={p.sequence}><strong>第{p.sequence}格 · {p.camera}</strong><p>{p.scene}</p>{p.dialogues.map((d,i)=><p className="dialogue-preview" key={i}>{d.speaker_name||'旁白'}：「{d.text}」</p>)}</div>)}</div>
      <button className="primary" disabled={draft.status!=='pending'} onClick={()=>void action(async()=>{await req('/story-drafts/'+draft.id+'/apply',requestJson());await Promise.all([onChanged(),reload()]);})}><CheckCircle2 size={16}/> 确认采用此剧本</button>
      <p className="hint">保护规则：如果项目已有对白，系统将拒绝采用新剧本，避免覆盖人工编辑成果。建议在新项目中先使用 AI 生成。</p>
     </>}
   </div>}
 </div>;
}

export function PanelAI({projectId,panelId,characters,action,onChanged}:{projectId:string;panelId:string;characters:Character[];action:Action;onChanged:()=>Promise<void>}){
 const [candidates,setCandidates]=useState<Candidate[]>([]);
 const [selected,setSelected]=useState<string[]>([]);
 const [override,setOverride]=useState('');
 const [error,setError]=useState('');
 const [lastInfo,setLastInfo]=useState('');
 const reload=async()=>setCandidates(await req<Candidate[]>('/panels/'+panelId+'/candidates'));
 useEffect(()=>{setCandidates([]);setError('');setLastInfo('');setSelected([]);setOverride('');reload().catch(e=>setError(String(e)));},[panelId]);
 return <div className="ai-module">
   <h3><ImageIcon size={17}/> AI 单格生图与候选审核</h3>
   <p className="hint">从场景、景别、人设创建冻结提示词，提交后台生图任务；图片不含对白，采用候选后单独叠字。</p>
   <label>本格出场角色（全部不选时使用项目所有角色）</label>
   <div className="ai-cast">{characters.map(c=><label key={c.id}><input type="checkbox" checked={selected.includes(c.id)} onChange={e=>setSelected(a=>e.target.checked?[...a,c.id]:a.filter(x=>x!==c.id))}/>{c.name}{c.reference_asset_id?' · 有参考图':''}</label>)}</div>
   <label>补充画面提示词（可选）</label><textarea rows={3} maxLength={2000} value={override} onChange={e=>setOverride(e.target.value)} placeholder="例如：保留更多上方留白，人物惊讶的表情特写"/>
   <GenerationJobPanel projectId={projectId} panelId={panelId} selectedCharacters={selected} override={override} action={action} onChanged={async()=>{await Promise.all([reload(),onChanged()]);}}/>
   {error&&<p className="ai-error">{error}</p>}{lastInfo&&<p className="hint">{lastInfo}</p>}
   <div className="candidate-list">{candidates.map(c=><div key={c.id} className="candidate"><img src={c.url} alt="AI候选图"/><div className="line spread"><small>{c.id.slice(0,8)}</small>{c.approved?<span className="tag good"><ShieldCheck size={12}/> 已采用</span>:<button className="secondary small" onClick={()=>void action(async()=>{await req('/panels/'+panelId+'/approve/'+c.id,requestJson());await Promise.all([reload(),onChanged()]);})}><CheckCircle2 size={14}/> 采用</button>}</div></div>)}</div>
   <button className="secondary small" onClick={()=>void reload()}><RefreshCw size={14}/> 刷新候选</button>
 </div>;
}
