import React, {useCallback, useEffect, useState} from 'react';
import {BookOpen, Clapperboard, Download, FileText, Film, Image as ImageIcon, LayoutGrid, Lock, LockOpen, Plus, RefreshCw, Save, Settings, ShieldCheck, Sparkles, Upload, Users} from 'lucide-react';

type Nav = 'projects' | 'characters' | 'story' | 'panels' | 'compose' | 'settings';
interface Project {id:string;title:string;premise:string;style:string;panel_count:number;outline:string;updated_at:string}
interface Character {id:string;name:string;appearance:string;personality:string;reference_asset_id:string|null}
interface Dialogue {id:string;panel_id:string;speaker_id:string|null;text:string;locked:boolean;version:number;x:number;y:number;w:number;h:number}
interface Panel {id:string;sequence:number;scene:string;camera:string;approved_asset_id:string|null;dialogues:Dialogue[]}
interface Snapshot {project:Project;characters:Character[];panels:Panel[]}
interface Validation {valid:boolean;errors:string[]}
const menu: {key:Nav; label:string; icon:React.ComponentType<{size?:number}>}[] = [
  {key:'projects',label:'项目工作台',icon:LayoutGrid},
  {key:'characters',label:'角色档案',icon:Users},
  {key:'story',label:'剧情工坊',icon:BookOpen},
  {key:'panels',label:'逐格分镜',icon:Film},
  {key:'compose',label:'漫画合成',icon:Clapperboard},
  {key:'settings',label:'模型与设置',icon:Settings}
];

async function api<T>(path:string,options:RequestInit={}):Promise<T> {
  const response=await fetch('/api'+path,options);
  if(!response.ok) {
    const body=await response.json().catch(()=>({detail:'接口请求失败'}));
    throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail??body));
  }
  return response.json() as Promise<T>;
}
const json=(method:string, data?:unknown):RequestInit=>({method,headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
function DialogueEditor({data,characters,changed,action}:{data:Dialogue;characters:Character[];changed:()=>Promise<void>;action:(f:()=>Promise<void>)=>Promise<void>}) {
  const [text,setText]=useState(data.text);
  const [speaker,setSpeaker]=useState(data.speaker_id||'');
  const [x,setX]=useState(String(data.x));
  const [y,setY]=useState(String(data.y));
  const [w,setW]=useState(String(data.w));
  const [h,setH]=useState(String(data.h));
  useEffect(()=>{setText(data.text);setSpeaker(data.speaker_id||'');setX(String(data.x));setY(String(data.y));setW(String(data.w));setH(String(data.h));},[data.id,data.version]);
  return <div className="dialogue">
    <div className="line spread"><strong>{data.locked?'已锁定对白':'可编辑对白'}</strong><span className="muted">v{data.version}</span></div>
    <label>说话角色</label>
    <select value={speaker} disabled={data.locked} onChange={e=>setSpeaker(e.target.value)}><option value="">旁白 / 未指定</option>{characters.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select>
    <label>中文原文（绘制时原样使用）</label>
    <textarea rows={2} value={text} disabled={data.locked} maxLength={300} onChange={e=>setText(e.target.value)}/>
    <div className="coordinates">{[['X',x,setX],['Y',y,setY],['宽',w,setW],['高',h,setH]].map(([name,value,change])=><label key={String(name)}>{String(name)}<input type="number" step=".01" min="0" max="1" value={String(value)} disabled={data.locked} onChange={e=>(change as (s:string)=>void)(e.target.value)}/></label>)}</div>
    <div className="line">
      {!data.locked&&<button className="primary small" onClick={()=>action(async()=>{await api('/dialogues/'+data.id,json('PATCH',{text,speaker_id:speaker||null,x:Number(x),y:Number(y),w:Number(w),h:Number(h)}));await changed();})}><Save size={15}/> 保存文字与位置</button>}
      <button className="secondary small" onClick={()=>action(async()=>{await api('/dialogues/'+data.id+'/'+(data.locked?'unlock':'lock'),json('POST'));await changed();})}>{data.locked?<LockOpen size={15}/>:<Lock size={15}/>} {data.locked?'解锁':'锁定'}</button>
    </div>
  </div>;
}

export default function App() {
  const [nav,setNav]=useState<Nav>('projects');
  const [projects,setProjects]=useState<Project[]>([]);
  const [current,setCurrent]=useState<Snapshot|null>(null);
  const [selectedPanel,setSelectedPanel]=useState('');
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const [revision,setRevision]=useState(0);
  const [validation,setValidation]=useState<Validation|null>(null);
  const [projectForm,setProjectForm]=useState({title:'',premise:'',style:'3D动画电影风',panel_count:4});
  const [characterForm,setCharacterForm]=useState({name:'',appearance:'',personality:''});
  const [dialogueText,setDialogueText]=useState('');
  const [dialogueSpeaker,setDialogueSpeaker]=useState('');
  const [scene,setScene]=useState('');
  const [camera,setCamera]=useState('中景');

  const loadList=useCallback(async()=>setProjects(await api<Project[]>('/projects')),[]);
  const load=useCallback(async(id:string)=>{
    const snapshot=await api<Snapshot>('/projects/'+id);
    setCurrent(snapshot);setRevision(n=>n+1);
    setSelectedPanel(old=>snapshot.panels.some(p=>p.id===old)?old:snapshot.panels[0]?.id||'');
  },[]);
  useEffect(()=>{loadList().catch(e=>setMessage(String(e)));},[loadList]);
  const panel=current?.panels.find(p=>p.id===selectedPanel);
  useEffect(()=>{setScene(panel?.scene||'');setCamera(panel?.camera||'中景');},[panel?.id,panel?.scene,panel?.camera]);
  const act=async(f:()=>Promise<void>)=>{
    setBusy(true);setMessage('');
    try{await f();setMessage('操作成功，内容已保存');}
    catch(e){setMessage(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const changed=async()=>{if(current)await load(current.project.id);};
  const createProject=()=>act(async()=>{
    const p=await api<Project>('/projects',json('POST',projectForm));
    await loadList();await load(p.id);setNav('characters');setProjectForm({title:'',premise:'',style:'3D动画电影风',panel_count:4});
  });
  const createCharacter=()=>act(async()=>{
    if(!current)return;
    await api('/projects/'+current.project.id+'/characters',json('POST',characterForm));
    setCharacterForm({name:'',appearance:'',personality:''});await changed();
  });
  const upload=async(file:File)=>{
    if(!panel)return;
    await act(async()=>{
      const form=new FormData();form.append('file',file);
      const asset=await api<{id:string}>('/panels/'+panel.id+'/assets',{method:'POST',body:form});
      await api('/panels/'+panel.id+'/approve/'+asset.id,json('POST'));
      await changed();
    });
  };
  const selectedTitle=current?.project.title||'尚未选择漫画项目';
  const projectId=current?.project.id;
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-symbol"><Sparkles size={20}/></span><div><strong>Comic Studio AI</strong><small>专业漫画创作平台 · MVP</small></div></div>
      <div className="side-label">创作空间</div>
      <nav>{menu.map(item=><button key={item.key} onClick={()=>setNav(item.key)} className={'nav-item '+(nav===item.key?'active':'')}><item.icon size={18}/>{item.label}</button>)}</nav>
      <div className="side-foot"><div className="dot"/>本地工作模式 · 0.1.0<br/><small>当前为单用户开发版本</small></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><div className="eyebrow">COMIC CREATION WORKSPACE</div><h1>{selectedTitle}</h1><p>{current?.project.premise||'创建漫画项目，开始一条完整的创作工作流'}</p></div><div className="line"><button className="secondary" onClick={()=>act(loadList)}><RefreshCw size={16}/> 刷新项目</button>{current&&<span className="pill">{current.project.panel_count}格漫画</span>}</div></header>
      {message&&<div role="status" className="notice" onClick={()=>setMessage('')}>{message} <span className="muted">×</span></div>}
      {nav==='projects'&&<section className="content-grid">
        <div className="surface"><h2><Plus size={20}/> 新建漫画项目</h2><p className="hint">从一个创意开始，逐步构建角色、故事和画格。</p>
          <label>漫画标题</label><input placeholder="例如：大小姐与司机" value={projectForm.title} onChange={e=>setProjectForm({...projectForm,title:e.target.value})}/>
          <label>故事构想</label><textarea rows={3} placeholder="写下这个故事要讲什么…" value={projectForm.premise} onChange={e=>setProjectForm({...projectForm,premise:e.target.value})}/>
          <div className="form-row"><div><label>画格数</label><select value={projectForm.panel_count} onChange={e=>setProjectForm({...projectForm,panel_count:Number(e.target.value)})}>{[4,6,8,12].map(v=><option key={v} value={v}>{v} 格</option>)}</select></div><div><label>整体画风</label><select value={projectForm.style} onChange={e=>setProjectForm({...projectForm,style:e.target.value})}>{['3D动画电影风','日系动漫风','国风神话漫画','现代科技科普漫画'].map(v=><option key={v}>{v}</option>)}</select></div></div>
          <button className="primary" onClick={createProject} disabled={busy||!projectForm.title.trim()}><Plus size={17}/> 建立项目</button>
        </div>
        <div className="surface"><h2><LayoutGrid size={20}/> 现有项目</h2>{projects.length===0?<div className="empty">还没有漫画项目。创建第一个作品吧。</div>:<div className="project-list">{projects.map(p=><button className={'project-item '+(p.id===projectId?'chosen':'')} key={p.id} onClick={()=>act(async()=>{await load(p.id);setNav('panels');})}><span><strong>{p.title}</strong><small>{p.premise||'暂无故事介绍'}</small></span><span className="pill">{p.panel_count}格</span></button>)}</div>}</div>
      </section>}
      {nav!=='projects'&&!current&&<div className="surface empty">请先在「项目工作台」创建或选择一个漫画项目。</div>}
      {nav==='characters'&&current&&<section className="content-grid">
        <div className="surface"><h2><Users size={20}/> 人设档案</h2><p className="hint">每个角色的基础视觉特征和性格设定都与项目关联。</p>
          <label>角色名称</label><input value={characterForm.name} onChange={e=>setCharacterForm({...characterForm,name:e.target.value})} placeholder="例如：布偶猫大小姐"/>
          <label>外观与服装设定</label><textarea rows={3} value={characterForm.appearance} onChange={e=>setCharacterForm({...characterForm,appearance:e.target.value})} placeholder="毛色、体型、衣着、配饰…"/>
          <label>性格与说话方式</label><textarea rows={3} value={characterForm.personality} onChange={e=>setCharacterForm({...characterForm,personality:e.target.value})} placeholder="例如：骄傲、嘴硬、喜欢吐槽"/>
          <button className="primary" disabled={busy||!characterForm.name.trim()} onClick={createCharacter}><Plus size={16}/> 保存角色</button>
        </div>
        <div className="surface"><h2>角色列表 <span className="muted">({current.characters.length})</span></h2>{current.characters.length?current.characters.map(c=><div className="character" key={c.id}><div className="avatar">{c.name.slice(0,1)}</div><div><strong>{c.name}</strong><p>{c.appearance||'尚未填写外观'}</p><small>{c.personality||'尚未填写性格'}</small></div></div>):<div className="empty">还没有角色，先建立角色档案。</div>}<p className="hint">定妆照及角色版本锁定将在下一阶段实现。</p></div>
      </section>}
      {nav==='story'&&current&&<section className="surface"><h2><BookOpen size={20}/> 剧情工坊</h2><p className="hint">当前实现离线 Mock 分镜规划，不会调用付费模型，也不会覆盖已保存的对白和图片。</p>
        <div className="readout"><span className="muted">项目题材</span><p>{current.project.premise||current.project.title}</p><span className="muted">创作风格</span><p>{current.project.style}</p></div>
        <button className="primary" disabled={busy} onClick={()=>act(async()=>{await api('/projects/'+current.project.id+'/story:mock',json('POST'));await changed();})}><Sparkles size={18}/> 生成离线示例剧情 / 分镜</button>
        <h3>剧情大纲</h3><div className="readout">{current.project.outline||'暂无大纲。可以生成离线示例，或到逐格分镜手动创作。'}</div>
        <h3>分镜内容预览</h3><div className="chapter-list">{current.panels.map(p=><div key={p.id} className="chapter"><span>第 {p.sequence} 格</span><strong>{p.scene}</strong></div>)}</div>
      </section>}
      {nav==='panels'&&current&&<section className="workbench">
        <div className="surface"><h2><LayoutGrid size={20}/> 画格列表</h2><div className="panel-list">{current.panels.map(p=><button key={p.id} className={'panel-tile '+(p.id===selectedPanel?'selected':'')} onClick={()=>setSelectedPanel(p.id)}>{p.approved_asset_id?<img src={'/api/assets/'+p.approved_asset_id} alt={'第'+p.sequence+'格'} />:<div className="panel-placeholder"><ImageIcon size={24}/></div>}<span>第 {p.sequence} 格 <small>{p.dialogues.length}条对白</small></span></button>)}</div></div>
        <div className="surface">{panel&&<><h2>第 {panel.sequence} 格 · 详细编辑</h2>
          <label>场景与人物动作</label><textarea rows={3} value={scene} onChange={e=>setScene(e.target.value)}/>
          <label>镜头景别</label><select value={camera} onChange={e=>setCamera(e.target.value)}>{['远景','全景','中景','近景','特写','俯拍','仰拍'].map(s=><option key={s}>{s}</option>)}</select>
          <button className="secondary" disabled={busy} onClick={()=>act(async()=>{await api('/panels/'+panel.id,json('PATCH',{scene,camera}));await changed();})}><Save size={16}/> 保存分镜</button>
          <div className="section-head"><h3>逐格画面</h3><span className="pill">{panel.approved_asset_id?'已有批准图片':'尚无图片'}</span></div>
          {panel.approved_asset_id&&<img className="scene-image" src={'/api/assets/'+panel.approved_asset_id} alt="当前画格"/>}
          <label className="upload"><Upload size={17}/> 上传并采用无字画面<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{const file=e.target.files?.[0];if(file)void upload(file);e.target.value='';}}/></label>
          <p className="hint">图片为独立资产。更改台词时不会重新生成图片；上传新图只替换当前画格。</p>
        </>}</div>
        <div className="surface"><h2><FileText size={20}/> 中文对白</h2>{panel&&<><p className="hint">对白存储与图片分离，导出时使用真实中文字形绘制。</p>
          {panel.dialogues.map(d=><DialogueEditor key={d.id} data={d} characters={current.characters} changed={changed} action={act}/>)}
          <h3>新增对白</h3><label>说话角色</label><select value={dialogueSpeaker} onChange={e=>setDialogueSpeaker(e.target.value)}><option value="">旁白 / 未指定</option>{current.characters.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <label>中文台词</label><textarea rows={3} value={dialogueText} maxLength={300} placeholder="请填写准确的中文对白…" onChange={e=>setDialogueText(e.target.value)}/>
          <button className="primary" disabled={busy||!dialogueText.trim()} onClick={()=>act(async()=>{await api('/panels/'+panel.id+'/dialogues',json('POST',{text:dialogueText,speaker_id:dialogueSpeaker||null}));setDialogueText('');await changed();})}><Plus size={16}/> 添加对白</button>
          </>}</div>
      </section>}
      {nav==='compose'&&current&&<section className="surface"><div className="line spread"><h2><Clapperboard size={20}/> 漫画合成</h2><span className="pill">1920 × 1080 · {current.project.panel_count}格</span></div>
        <p className="hint">服务端按固定布局将批准画面与原始中文对白合成；检查文字超框、气泡越界和重叠。</p>
        <div className="line"><button className="primary" onClick={()=>act(async()=>{setValidation(await api('/projects/'+current.project.id+'/validate'));})}><ShieldCheck size={17}/> 检查排版</button>
          <a className="secondary button-link" href={'/api/projects/'+current.project.id+'/export.svg'}><Download size={17}/> SVG</a>
          <a className="secondary button-link" href={'/api/projects/'+current.project.id+'/export.png'}><Download size={17}/> PNG</a>
          <a className="secondary button-link" href={'/api/projects/'+current.project.id+'/export.json'}><Download size={17}/> JSON</a>
        </div>
        {validation&&<div className={'validation '+(validation.valid?'ok':'bad')}>{validation.valid?'排版校验通过':validation.errors.map((error,i)=><div key={i}>{error}</div>)}</div>}
        <div className="preview-wrap"><img key={revision} src={'/api/projects/'+current.project.id+'/export.svg?v='+revision} alt="合成效果预览" /></div>
        <p className="hint">当前提供固定网格和位置参数编辑。拖拽式画布、图层与可视化气泡尾巴将在后续版本提供。</p>
      </section>}
      {nav==='settings'&&<section className="surface"><h2><Settings size={20}/> 模型接入与运行状态</h2><div className="readout"><strong>当前生成模式：Mock（本地示例）</strong><p>本版本无需图像 API Key，手工上传图片并进行确定性中文排版。</p><p>还未连接真实的 LLM、图像生成服务、ComfyUI 或 GPU Worker。</p></div><h3>计划中的模型能力</h3><div className="chapter-list">{['OpenAI兼容LLM：剧本与对白生成','图像模型：参考图与逐格生图','局部重绘：角色与画面修正','多Worker任务队列与进度追踪'].map(x=><div className="chapter" key={x}><span>待开发</span>{x}</div>)}</div></section>}
      <footer>Comic Studio AI · v0.1 单用户开发版 · 未配置登录与访问控制，请仅在本机或可信网络使用。</footer>
    </main>
  </div>;
}
