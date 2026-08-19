
const {useState,useEffect,useRef,useMemo} = React;

const DATA_URL    = './data/explorer_data.json';
const GEO_URL     = './data/wb_adm0.json';      // WB GAD country polygons (built by prepare_shapes.py)
const BORDERS_URL = './data/wb_borders.json';   // boundary + coastline lines, dash styles pre-baked
const GREY        = '#dde4ea';   // countries not covered by the simulation

/* map styling ported from the paper repo's plotting.py
   (MAP_COLORS / BORDER_LINESTYLES / get_special_map_colors) */
const COAST_COLOR  = '#4682b4';               // steelblue ocean line
const BORDER_COLOR = 'rgba(255,255,255,0.9)'; // white boundary lines
const ESH_COLOR    = '#c8c8c8';               // Western Sahara is always lightgrey
const SPECIAL_REGIONS = {                     // disputed region -> countries whose colors it takes
  'Aksai Chin':['CHN','IND'],
  'Jammu and Kashmir':['IND'],
  'Gilgit Baltistan':['PAK'],
  'Arunachal Pradesh':['CHN','IND'],
  'Abyei':['SSD','SDN'],
  'Ilemi Triangle':['KEN','SSD'],
};

/* ============================ VARIABLES ============================
   All values arrive already scaled in explorer_data.json:
   risk_to_* are expressed as % of GDP, resilience as %. */
const VARS={
  riskAssets:{label:'Risk to assets',short:'Assets',unit:'% GDP',stops:['#edf2f7','#9cc0d8','#2166ac'],bad:true,log:true,
    get:c=>c.riskAssets,fmt:v=>v.toFixed(2),
    desc:'Expected annual asset damages from disasters as a share of GDP.'},
  riskConsumption:{label:'Risk to consumption',short:'Consumption',unit:'% GDP',stops:['#f1eef6','#b3a2c7','#6a51a3'],bad:true,log:true,
    get:c=>c.riskConsumption,fmt:v=>v.toFixed(2),
    desc:'Expected annual consumption losses as a share of GDP.'},
  riskWellbeing:{label:'Risk to well-being',short:'Well-being',unit:'% GDP',stops:['#fdece8','#ec9a8d','#b2182b'],bad:true,log:true,
    get:c=>c.riskWellbeing,fmt:v=>v.toFixed(2),
    desc:'Expected annual well-being losses as a share of GDP.'},
  resilience:{label:'Socio-economic resilience',short:'Resilience',unit:'%',stops:['#eef6f3','#86c0ad','#1b7a5f'],bad:false,
    get:c=>c.resilience,fmt:v=>v.toFixed(0),
    desc:'Ratio of asset damages to well-being losses. Higher = a population maintains well-being despite larger asset damages.'},
  recovery:{label:'Recovery duration',short:'Recovery',unit:'yrs',stops:['#f2f0ec','#e0a34a','#8a3412'],bad:true,log:true,
    get:c=>c.recovery,fmt:v=>v.toFixed(1),
    desc:'Time for affected households to recover 95% of their disaster losses (population-weighted, years).'},
};
/* metrics that always exist per country; recovery is only shown if present in the data */
const VAR_KEYS=Object.keys(VARS);

/* quintile sub-metrics (decompose exactly to the national totals) */
const QVARS={
  incomeShare  :{label:'Income share', unit:'%',     stops:['#dfeaf2','#86c0ad','#1b7a5f'], get:q=>q.incomeShare,  fmt:v=>v.toFixed(0)},
  riskWellbeing:{label:'Risk to well-being', unit:'% GDP', stops:VARS.riskWellbeing.stops, get:q=>q.riskWellbeing, fmt:v=>v.toFixed(2)},
  riskAssets   :{label:'Risk to assets', unit:'% GDP',     stops:VARS.riskAssets.stops,    get:q=>q.riskAssets,    fmt:v=>v.toFixed(2)},
};

/* color ramp utils */
function hx(h){h=h.replace('#','');return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)];}
function ramp(stops,t){t=Math.max(0,Math.min(1,t));const n=stops.length-1;const i=Math.min(n-1,Math.floor(t*n));const f=t*n-i;
  const a=hx(stops[i]),b=hx(stops[i+1]);return `rgb(${Math.round(a[0]+(b[0]-a[0])*f)},${Math.round(a[1]+(b[1]-a[1])*f)},${Math.round(a[2]+(b[2]-a[2])*f)})`;}

function fmtNum(n){if(n==null)return '—';if(n>=1e9)return (n/1e9).toFixed(2)+'B';if(n>=1e6)return (n/1e6).toFixed(1)+'M';if(n>=1e3)return (n/1e3).toFixed(0)+'K';return Math.round(n);}
function quantile(sorted,p){
  if(!sorted.length)return 0;
  const idx=(sorted.length-1)*p,lo=Math.floor(idx),hi=Math.ceil(idx);
  if(lo===hi)return sorted[lo];
  return sorted[lo]+(sorted[hi]-sorted[lo])*(idx-lo);
}

/* 50/50 blend of two css colors (hex or rgb()), like blend_colors in plotting.py */
function parseColor(c){
  if(c[0]==='#')return hx(c);
  const m=c.match(/\d+(\.\d+)?/g);return m?m.slice(0,3).map(Number):[0,0,0];
}
function blendColors(c1,c2,t=.5){
  const a=parseColor(c1),b=parseColor(c2);
  return `rgb(${Math.round(a[0]+(b[0]-a[0])*t)},${Math.round(a[1]+(b[1]-a[1])*t)},${Math.round(a[2]+(b[2]-a[2])*t)})`;
}

/* ===================== POLICY LOOKUP (pre-computed single-policy scenarios) =====================
   Each country ships data/policies/<ISO>.json: for every response series (one lever at a time) a
   `param` grid (index 0 = no-policy baseline) plus one array per output metric. The frontend does a
   plain table lookup — no live model. This is the seam a future per-country emulator would slot into
   (manifest.method === 'emulator'); adjustedMetrics() is the single place that would dispatch. */
const POLICY_URL='./data/policies/';
const POL_CACHE={};
function loadPolicy(iso){
  if(!POL_CACHE[iso])
    POL_CACHE[iso]=fetch(POLICY_URL+iso+'.json').then(r=>r.ok?r.json():null).catch(()=>null);
  return POL_CACHE[iso];
}
/* the series id backing a lever at the current scope / PDS variant */
function seriesId(lever,scope,variant){
  if(lever.kind==='pds')return lever.variants[variant];
  return (lever.series&&(lever.series[scope]||lever.series.all))||null;
}
/* highest reachable step index for a series (arrays carry null past the feasible range, e.g. deep
   poorest-quintile steps that the model can't solve for some countries) */
function feasibleMax(series,outputs){
  const key=outputs[0]; let last=0;
  for(let i=0;i<series[key].length;i++) if(series[key][i]!=null) last=i;
  return last;
}
/* country metrics with one active policy applied at step `idx` (baseline when no policy) */
function adjustedMetrics(c,pol,manifest,active){
  if(!pol||!manifest||!active||!active.sid) return c;
  const s=pol.series&&pol.series[active.sid]; if(!s) return c;
  const out={...c};
  for(const m of manifest.outputs){const v=s[m]&&s[m][active.idx]; if(v!=null) out[m]=v;}
  return out;
}

/* ============================ APP ============================ */
function App(){
  const [feats,setFeats]=useState(null);
  const [paths,setPaths]=useState(null);        // boundary + coastline polylines (wb_borders.json)
  const [data,setData]=useState(null);          // explorer_data.json
  const [byIso,setByIso]=useState({});
  const [manifest,setManifest]=useState(null);  // data/policies/manifest.json (optional)
  const [err,setErr]=useState(null);
  const [vk,setVk]=useState('resilience');
  const [sel,setSel]=useState(null);            // iso
  const [groupBy,setGroupBy]=useState('inc');   // inc | region
  const [hiGroup,setHiGroup]=useState(null);    // highlighted group value
  const elRef=useRef(), wRef=useRef();
  const headRef=useRef(), stageRef=useRef(), sheetRef=useRef();

  /* load simulation data + country polygons */
  useEffect(()=>{(async()=>{
    try{
      const urls=[DATA_URL,GEO_URL,BORDERS_URL];
      const res=await Promise.all(urls.map(u=>fetch(u)));
      res.forEach((r,i)=>{if(!r.ok)throw new Error('Could not load '+urls[i]+' ('+r.status+')');});
      const [d,g,bd]=await Promise.all(res.map(r=>r.json()));
      const bi={}; d.countries.forEach(c=>{bi[c.iso]=c;});
      const fs=g.features||[];
      fs.forEach(f=>{const iso=f.properties.iso3; f.__c=iso?bi[iso]||null:null;});
      const pd=(bd.borders||[]).map(pts=>({pts})).concat((bd.coast||[]).map(pts=>({pts,coast:true})));
      setData(d);setByIso(bi);setFeats(fs);setPaths(pd);
      /* policy scenarios are optional: load the manifest if present, ignore if absent */
      fetch(POLICY_URL+'manifest.json').then(r=>r.ok?r.json():null).then(m=>setManifest(m)).catch(()=>{});
    }catch(e){setErr(e.message);}
  })();},[]);

  const countries = data?data.countries:[];
  const V=VARS[vk];
  const vkRef=useRef(vk); vkRef.current=vk;   // current metric for the (once-registered) hover handler
  const domain=useMemo(()=>{
    if(!countries.length)return [0,1];
    const vals=countries.map(c=>V.get(c)).sort((a,b)=>a-b);
    return [vals[0], vals[vals.length-1]];         // true min / max
  },[countries,vk]);

  /* normalised [0,1] position of a value on the current scale (log for skewed
     risk metrics, linear otherwise). Shared by the globe, legend and box plots. */
  const scaleT=(v)=>{
    if(V.log){const a=Math.log(domain[0]),b=Math.log(domain[1]);
      return (Math.log(Math.max(v,1e-12))-a)/(b-a);}
    return (v-domain[0])/(domain[1]-domain[0]);
  };

  const colorFor=(c)=>{
    if(!c)return GREY;                              // not covered by the simulation
    if(hiGroup){const g=groupBy==='inc'?c.incomeGroup:c.region; if(g!==hiGroup)return '#e6ebef';}
    return ramp(V.stops,scaleT(V.get(c)));
  };

  /* per-feature color — port of get_special_map_colors (plotting.py): Western Sahara is a fixed
     lightgrey; disputed regions take their single claimant's color, the shared color, or a 50/50
     blend when the two claimants' colors differ (blended with white if only one is simulated). */
  const featColor=(f)=>{
    const p=f.properties||{};
    if(p.iso3==='ESH')return ESH_COLOR;
    const nbs=!f.__c&&SPECIAL_REGIONS[p.name];
    if(nbs){
      const cs=nbs.filter(i=>byIso[i]).map(i=>colorFor(byIso[i]));
      if(cs.length===2)return cs[0]===cs[1]?cs[0]:blendColors(cs[0],cs[1]);
      if(cs.length===1)return nbs.length===1?cs[0]:blendColors(cs[0],'#ffffff');
    }
    return colorFor(f.__c);
  };

  /* init globe once feats ready */
  const hoverRef=useRef(null);

  /* expose the header height as --head-h so the fixed mobile globe/legend
     sit exactly below it (no hard-coded guess). */
  useEffect(()=>{
    const set=()=>{if(headRef.current)document.documentElement.style.setProperty('--head-h',headRef.current.offsetHeight+'px');};
    set();window.addEventListener('resize',set);
    const ro=headRef.current?new ResizeObserver(set):null;ro&&ro.observe(headRef.current);
    return ()=>{window.removeEventListener('resize',set);ro&&ro.disconnect();};
  },[feats,data]);

  /* mobile: when a country is picked, slide the bottom sheet up over the globe;
     when cleared, scroll back down to reveal the globe. */
  useEffect(()=>{
    if(window.innerWidth>820)return;
    if(sel&&sheetRef.current)sheetRef.current.scrollIntoView({behavior:'smooth',block:'start'});
    else if(!sel&&stageRef.current)stageRef.current.scrollTo({top:0,behavior:'smooth'});
  },[sel]);

  useEffect(()=>{
    if(!feats||!paths||!elRef.current||wRef.current)return;
    const w=Globe()(elRef.current)
      .backgroundColor('rgba(0,0,0,0)')
      .showAtmosphere(true).atmosphereColor('#bcd6e8').atmosphereAltitude(0.20)
      .showGraticules(true)
      .polygonsData(feats)
      .polygonAltitude(f=>f===hoverRef.current?0.045:0.012)
      .polygonCapColor(f=>featColor(f))
      .polygonSideColor(()=>'rgba(120,140,160,0.10)')
      /* countries carry no outline of their own (ec='none' in the paper maps): the white
         WB_GAD_Lines boundaries and the steelblue coastline are drawn as paths instead */
      .polygonStrokeColor(()=>'rgba(0,0,0,0)')
      .pathsData(paths)
      .pathPoints(d=>d.pts).pathPointLat(pt=>pt[1]).pathPointLng(pt=>pt[0])
      .pathPointAlt(0.0125)                         // just above the country caps
      .pathColor(d=>d.coast?COAST_COLOR:BORDER_COLOR)
      .pathTransitionDuration(0)
      .onPolygonHover(onHover)
      .onPolygonClick(f=>{if(f.__c)setSel(f.__c.iso);})
      .onGlobeClick(()=>{setSel(null);});
    try{w.globeMaterial().color.set('#9cc1da');w.globeMaterial().shininess=2;}catch(e){}
    try{const ls=w.lights()||[];ls.forEach(l=>{if(/Ambient/i.test(l.type))l.intensity=3.1;else l.intensity=0.25;});w.lights(ls);}catch(e){}
    w.controls().autoRotate=true;w.controls().autoRotateSpeed=0.42;w.controls().enableZoom=true;
    w.pointOfView({lat:18,lng:8,altitude:2.3},0);
    wRef.current=w;
    const stop=()=>{w.controls().autoRotate=false;};
    elRef.current.addEventListener('pointerdown',stop);
    const onResize=()=>{w.width(elRef.current.clientWidth);w.height(elRef.current.clientHeight);};
    onResize();window.addEventListener('resize',onResize);
    const ro=new ResizeObserver(onResize);ro.observe(elRef.current);
    return ()=>{window.removeEventListener('resize',onResize);ro.disconnect();};
  },[feats]);

  function onHover(f){
    hoverRef.current=f;const w=wRef.current;if(!w)return;
    w.polygonAltitude(ff=>ff===f?0.045:0.012);
    const tip=document.getElementById('tip');
    if(window.innerWidth<=820){tip.style.opacity=0;return;}   // no hover tooltip on mobile / touch
    if(f){
      tip.style.opacity=1;
      const nm=f.properties.name||'';
      if(f.__c){const c=f.__c;const Vh=VARS[vkRef.current];
        tip.innerHTML=`<b>${c.name}</b><div class="meta">${c.incomeLabel} · ${c.regionLabel}</div>
          <div style="margin-top:4px">${Vh.label}: <span class="v">${Vh.fmt(Vh.get(c))}${Vh.unit==='%'?'%':' '+Vh.unit}</span></div>`;
      }else{
        tip.innerHTML=`<b>${nm}</b><div class="na">Not covered by the simulation</div>`;
      }
      const mv=e=>{tip.style.left=e.clientX+'px';tip.style.top=e.clientY+'px';};
      window.__mv&&window.removeEventListener('pointermove',window.__mv);window.__mv=mv;window.addEventListener('pointermove',mv);
    } else {tip.style.opacity=0;}
  }

  /* recolor on variable / highlight change */
  useEffect(()=>{const w=wRef.current;if(!w)return;
    w.polygonCapColor(f=>featColor(f));},[vk,domain,hiGroup,groupBy]);

  /* focus camera on selection */
  useEffect(()=>{const w=wRef.current;if(!w||!sel)return;const c=byIso[sel];if(!c)return;
    const feat=feats.find(f=>f.__c===c); if(!feat)return;
    const p=repPoint(feat);if(p){
      w.controls().autoRotate=false;w.pointOfView({lat:p.lat,lng:p.lng,altitude:1.9},900);}},[sel]);

  /* representative point: centroid of the country's largest polygon (the mainland),
     so overseas territories / antimeridian-crossing parts don't skew the camera. */
  function repPoint(f){try{
    const g=f.geometry; if(!g)return null;
    const polys=g.type==='MultiPolygon'?g.coordinates:[g.coordinates];   // each: [outerRing, ...holes]
    let best=null,bestArea=-1;
    for(const poly of polys){
      const ring=poly[0]; if(!ring||ring.length<3)continue;
      let A=0,Cx=0,Cy=0;
      for(let i=0;i<ring.length-1;i++){
        const [x0,y0]=ring[i],[x1,y1]=ring[i+1];const cross=x0*y1-x1*y0;
        A+=cross;Cx+=(x0+x1)*cross;Cy+=(y0+y1)*cross;
      }
      A*=0.5;
      let cx,cy;
      if(Math.abs(A)>1e-9){cx=Cx/(6*A);cy=Cy/(6*A);}
      else{cx=ring.reduce((s,p)=>s+p[0],0)/ring.length;cy=ring.reduce((s,p)=>s+p[1],0)/ring.length;}
      const area=Math.abs(A);
      if(area>bestArea){bestArea=area;best={lng:cx,lat:cy};}
    }
    return best;
  }catch(e){return null;}}

  const cur=sel?byIso[sel]:null;

  /* group aggregates */
  const groups=useMemo(()=>{
    if(!countries.length)return [];
    const keyf=groupBy==='inc'?(c=>c.incomeGroup):(c=>c.region);
    const order=groupBy==='inc'?(data.incomeOrder||null):null;
    const labelf=groupBy==='inc'?(c=>c.incomeLabel):(c=>c.regionLabel);
    const m={},lab={};countries.forEach(c=>{const k=keyf(c);(m[k]=m[k]||[]).push(c);lab[k]=labelf(c);});
    let arr=Object.entries(m).map(([k,cs])=>{
      const vals=cs.map(c=>V.get(c)).sort((a,b)=>a-b);
      const q1=quantile(vals,0.25),med=quantile(vals,0.5),q3=quantile(vals,0.75);
      const iqr=q3-q1;
      const loW=Math.max(vals[0],q1-1.5*iqr);
      const hiW=Math.min(vals[vals.length-1],q3+1.5*iqr);
      return {key:k,label:lab[k],med,q1,q3,iqr,loW,hiW,n:cs.length};
    });
    if(order)arr.sort((a,b)=>order.indexOf(a.key)-order.indexOf(b.key));
    else arr.sort((a,b)=>b.med-a.med);
    return arr;
  },[countries,groupBy,vk]);
  const globalMedian=countries.length?quantile(countries.map(c=>V.get(c)).sort((a,b)=>a-b),0.5):0;

  const ranked=useMemo(()=>[...countries].sort((a,b)=>V.get(b)-V.get(a)),[countries,vk]);

  /* report */
  function downloadReport(){
    const rows=cur?reportCountry(cur):reportGlobal(V,globalMedian,groups,ranked,groupBy,data);
    const html=reportHTML(cur?cur.name:'Global overview',V,rows);
    const blob=new Blob([html],{type:'text/html'});const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=`unbreakable-${(cur?cur.name:'global').toLowerCase().replace(/\W+/g,'-')}.html`;a.click();
  }

  const ready=feats&&data;

  return (
    <div className="app">
      <header className="bar" ref={headRef}>
        <div className="brand">
          <span className="mark">Global Resilience<span style={{color:'var(--ink-3)',fontWeight:500}}> Explorer</span></span>
        </div>
        <div className="seg">
          {VAR_KEYS.map(k=><button key={k} className={k===vk?'on':''} onClick={()=>setVk(k)}>{VARS[k].label}</button>)}
        </div>
        <div className="grow"></div>
      </header>

      <div className="stage" ref={stageRef}>
        <div id="globe" ref={elRef}></div>
        <div className="stage-grad"></div>
        {!ready&&!err&&<div className="loading"><div className="spinner"></div>Loading baseline simulation…</div>}
        {err&&<div className="loading"><div style={{fontSize:22}}>⚠︎</div>
          <div>{err}</div>
          <div style={{fontSize:11.5,maxWidth:340}}>Run <code>python3 build_data.py</code> to generate the data, then serve the folder over http (e.g. <code>python3 -m http.server</code>) — opening the file directly via <code>file://</code> blocks the data fetches.</div></div>}

        {/* legend */}
        {ready&&<div className="legend">
          <h4>{V.label}</h4>
          <div className="desc">{V.desc}</div>
          <div className="ramp" style={{background:`linear-gradient(90deg,${V.stops.join(',')})`}}></div>
          <div className="scale mono"><span>{V.fmt(domain[0])}{V.unit==='%'?'%':''}</span>
            <span>{V.log?V.fmt(Math.exp((Math.log(domain[0])+Math.log(domain[1]))/2))+(V.unit==='%'?'%':''):(V.unit!=='%'?V.unit:'')}</span>
            <span>{V.fmt(domain[1])}{V.unit==='%'?'%':''}</span></div>
          <div className="polar"><span className="dirdot" style={{background:V.stops[V.stops.length-1]}}></span>
            Darker = {V.bad?'higher risk':'more resilient'}{V.unit!=='%'?' · '+V.unit:''}{V.log?' · log scale':''}</div>
          <div className="greyrow"><i></i>Grey = not covered by the simulation</div>
        </div>}

        {/* unified sidebar: global overview OR country profile */}
        {ready&&<aside className="sidebar" ref={sheetRef}>
        {cur ? <CountryPanel c={cur} vk={vk} onClose={()=>setSel(null)} manifest={manifest}/>
        : <div className="ov-scroll">
          <p className="ov-title">Global overview</p>
          <select className="ov-jump" value={sel||''} onChange={e=>setSel(e.target.value||null)}>
            <option value="">Jump to country…</option>
            {[...countries].sort((a,b)=>a.name.localeCompare(b.name)).map(c=><option key={c.iso} value={c.iso}>{c.name}</option>)}
          </select>
          <p className="ov-h">Global median · {V.label}</p>
          <div className="ov-stat mono">{V.fmt(globalMedian)}<span className="u">{V.unit}</span></div>
          <div className="ov-sub">{countries.length} countries simulated · {data.framework}</div>

          <div className="grp-tabs">
            <button className={groupBy==='inc'?'on':''} onClick={()=>{setGroupBy('inc');setHiGroup(null);}}>By income group</button>
            <button className={groupBy==='region'?'on':''} onClick={()=>{setGroupBy('region');setHiGroup(null);}}>By region</button>
          </div>
          {groups.map(g=>{
            const pos=v=>Math.max(0,Math.min(100,scaleT(v)*100));
            const lo=pos(g.loW),hi=pos(g.hiW),b1=pos(g.q1),b3=pos(g.q3),md=pos(g.med);
            return (
            <div key={g.key} className={'barrow'+(hiGroup&&hiGroup!==g.key?' dim':'')}
                 onClick={()=>setHiGroup(hiGroup===g.key?null:g.key)}>
              <div className="lab"><b>{g.label}</b><span className="val mono">{V.fmt(g.med)}{V.unit==='%'?'%':' '+V.unit}</span></div>
              <div className="boxtrack">
                <div className="axis"></div>
                <div className="whisker" style={{left:lo+'%',width:(hi-lo)+'%'}}></div>
                <div className="cap" style={{left:lo+'%'}}></div>
                <div className="cap" style={{left:hi+'%'}}></div>
                <div className="box" style={{left:b1+'%',width:(b3-b1)+'%',
                  background:ramp(V.stops,scaleT(g.med)),opacity:.85}}></div>
                <div className="median" style={{left:md+'%'}}></div>
              </div>
            </div>
            );
          })}
          <div className="ov-axis"><span>{V.fmt(domain[0])}{V.unit==='%'?'%':''}</span><span>{V.fmt(domain[1])}{V.unit==='%'?'%':''}</span></div>
          <div className="boxlegend">
            <span><i className="lg-med"></i>median</span>
            <span><i className="lg-box"></i>IQR (Q1–Q3)</span>
            <span><i className="lg-wh"></i>1.5·IQR range</span>
          </div>
          <div className="ov-sub" style={{marginTop:8,fontSize:11,color:'var(--ink-3)'}}>{hiGroup?'Highlighted on globe — click again to clear':'Click a group to highlight it on the globe'}</div>

          <div className="ranklist">
            <h5>{V.bad?'Highest':'Top'} — {V.short}</h5>
            {ranked.slice(0,5).map((c,i)=><div key={c.iso} className="rank" onClick={()=>setSel(c.iso)}>
              <span className="nm"><span className="ix">{i+1}</span>{c.name}</span><span className="rv">{V.fmt(V.get(c))}{V.unit==='%'?'%':''}</span></div>)}
            <h5 style={{marginTop:12}}>{V.bad?'Lowest':'Bottom'} — {V.short}</h5>
            {ranked.slice(-5).map((c,i)=><div key={c.iso} className="rank" onClick={()=>setSel(c.iso)}>
              <span className="nm"><span className="ix">{ranked.length-4+i}</span>{c.name}</span><span className="rv">{V.fmt(V.get(c))}{V.unit==='%'?'%':''}</span></div>)}
          </div>
        </div>}
        </aside>}

        {ready&&!cur&&<div className="hint">Click any simulated country on the globe to open its resilience profile</div>}
      </div>
    </div>
  );
}

/* ---------- country profile panel ---------- */
function CountryPanel({c,vk,onClose,manifest}){
  const metricKeys=['riskAssets','riskConsumption','riskWellbeing','resilience']
    .concat(c.recovery!=null?['recovery']:[]);
  const Q=QVARS.incomeShare;                 // quintile breakdown shows income share only
  const hasQuint=c.quint&&c.quint.length;
  const qvals=hasQuint?c.quint.map(Q.get):[];
  const qmax=hasQuint?Math.max(...qvals,1e-9):1;
  const qlabels=['Poorest','Q2','Q3','Q4','Richest'];

  /* single-policy what-if state (only one lever editable at a time) */
  const [pol,setPol]=useState(null);      // this country's data/policies/<iso>.json
  const [leverKey,setLeverKey]=useState(null);
  const [scope,setScope]=useState('all'); // exposure/vulnerability scope
  const [variant,setVariant]=useState('uniform'); // PDS variant
  const [idx,setIdx]=useState(0);         // step index (0 = baseline)
  useEffect(()=>{setPol(null);setLeverKey(null);setIdx(0);setScope('all');setVariant('uniform');
    let live=true;loadPolicy(c.iso).then(p=>{if(live)setPol(p);});return ()=>{live=false;};},[c.iso]);

  const hasSeries=(lv)=>lv.kind==='pds'
    ?Object.values(lv.variants).some(sid=>pol.series&&pol.series[sid])
    :!!(pol.series&&seriesId(lv,scope,variant)&&pol.series[seriesId(lv,scope,variant)]);
  const levers=(manifest&&pol)?manifest.levers.filter(hasSeries):[];
  const lever=leverKey?levers.find(l=>l.key===leverKey):null;
  const sid=lever?seriesId(lever,scope,variant):null;
  const S=sid&&pol?pol.series[sid]:null;
  const fmax=S?feasibleMax(S,manifest.outputs):0;
  const stepIdx=Math.min(idx,fmax);
  const changed=!!(lever&&S&&stepIdx>0);
  const adjusted=adjustedMetrics(c,pol,manifest,lever&&S?{sid,idx:stepIdx}:null);

  const pickLever=(k)=>{setLeverKey(k);setIdx(0);};
  const param=S?S.param[stepIdx]:null;
  const effLabel=()=>{
    if(!S||stepIdx===0)return '—';
    if(S.display==='share')return Math.round(param*100)+'% covered';
    return '−'+Math.round((1-param)*100)+'%';
  };

  return (<>
    <div className="dr-head">
      <button className="dr-close" onClick={onClose}>✕</button>
      <div className="dr-country">{c.name}</div>
      <div className="chips">
        <span className="chip acc">{c.incomeLabel}</span>
        <span className="chip">{c.regionLabel}</span>
        {c.pop&&<span className="chip">pop {fmtNum(c.pop)}</span>}
        {c.gdppc&&<span className="chip">GDP/cap ${fmtNum(c.gdppc)}</span>}
        {c.gini!=null&&<span className="chip">Gini {c.gini.toFixed(0)}</span>}
      </div>
    </div>
    <div className="dr-body">
      <div className="sec-t">Risk &amp; resilience profile{changed&&<span className="whatif">policy applied</span>}</div>
      <div className="mgrid">
        {metricKeys.map(k=>{
          const Vk=VARS[k],av=Vk.get(adjusted),bv=Vk.get(c),chg=changed&&Math.abs(av-bv)>1e-9;
          return (<div key={k} className={'metric'+(k===vk?' active':'')}>
            <div className="ml">{Vk.label}</div>
            <div className="mv">{Vk.fmt(av)}<span className="u">{Vk.unit}</span></div>
            {chg&&<div className="mbase">baseline {Vk.fmt(bv)}{Vk.unit==='%'?'%':''} <span className={((av>bv)===Vk.bad)?'dn':'up'}>{av>bv?'▲':'▼'} {Vk.fmt(Math.abs(av-bv))}</span></div>}
          </div>);
        })}
      </div>

      <div className="sec-t"><span>Income share by household quintile</span></div>
      {hasQuint?<>
      <div className="quint">
        {c.quint.map(q=>(
          <div className="qcol" key={q.q}>
            <span className="qv">{Q.fmt(Q.get(q))}{Q.unit==='%'?'%':''}</span>
            <div className="qbar" style={{height:(Q.get(q)/qmax*92)+'%',background:ramp(Q.stops,Q.get(q)/qmax)}}></div>
            <span className="qlab">{qlabels[q.q-1]}</span>
          </div>
        ))}
      </div>
      <div style={{fontSize:11,color:'var(--ink-3)',marginTop:6,lineHeight:1.4}}>
        Income quintiles, poorest (Q1) to richest (Q5).
      </div>
      </>:<div style={{fontSize:11.5,color:'var(--ink-3)'}}>No quintile breakdown available for this country.</div>}

      <div className="sec-t">Policy simulation</div>
      {(manifest&&pol&&levers.length)?(
        <div className="polbox">
          <div className="polhint">Apply a policy to see how the risk and resilience profile changes.</div>
          <div className="pol-picker">
            {levers.map(lv=><button key={lv.key} className={lv.key===leverKey?'on':''}
              onClick={()=>pickLever(lv.key===leverKey?null:lv.key)}>{lv.label}</button>)}
          </div>
          {lever&&<>
            {lever.kind!=='pds'&&lever.scopes&&lever.scopes.length>1&&
              <div className="pol-sub"><span className="pol-sub-l">Applies to</span>
                <span className="scope-tog">
                  <button className={scope==='all'?'on':''} onClick={()=>setScope('all')}>Whole population</button>
                  <button className={scope==='q1'?'on':''} onClick={()=>setScope('q1')}>Poorest 20%</button>
                </span></div>}
            {lever.kind==='pds'&&
              <div className="pol-sub"><span className="pol-sub-l">Aid type</span>
                <span className="scope-tog">
                  {Object.keys(lever.variants).map(v=><button key={v} className={variant===v?'on':''}
                    onClick={()=>setVariant(v)}>{(lever.variantLabels&&lever.variantLabels[v])||v}</button>)}
                </span></div>}
            <div className="pol-row">
              <div className="pol-lab"><span>{lever.kind==='pds'?'Coverage':'Reduction'}</span>
                <span className="pol-val">{effLabel()}</span></div>
              <input type="range" min="0" max={fmax} step="1" value={stepIdx}
                onChange={e=>setIdx(+e.target.value)}/>
            </div>
            <div className="polfoot">
              <button className="pol-reset" disabled={stepIdx===0} onClick={()=>setIdx(0)}>Reset to baseline</button>
              <span className="polnote">Country-level effect; quintile chart shows the baseline distribution.
                {manifest.synthetic&&<><br/><b>Synthetic placeholder data</b> — run build_policy_data.py.</>}</span>
            </div>
          </>}
        </div>
      ):(
        <div className="unavail">
          <h5><span className="badge">Not available</span> Policy scenarios unavailable</h5>
          <p>{manifest?'No pre-computed policy scenarios are bundled for this country yet.'
            :<>Policy scenarios are not built. Run <code>build_policy_data.py</code> to pre-compute
              them into <code>data/policies/</code>.</>}</p>
        </div>
      )}
    </div>
  </>);
}

/* ---------- report builders ---------- */
function reportCountry(c){
  const rows=[
    ['Region',c.regionLabel],['Income group',c.incomeLabel],
    c.gdppc?['GDP per capita','$'+fmtNum(c.gdppc)]:null,
    c.pop?['Population',fmtNum(c.pop)]:null,
    c.gini!=null?['Gini index',c.gini.toFixed(1)]:null,
    ['Risk to assets',c.riskAssets.toFixed(2)+'% GDP'],
    ['Risk to consumption',c.riskConsumption.toFixed(2)+'% GDP'],
    ['Risk to well-being',c.riskWellbeing.toFixed(2)+'% GDP'],
    ['Socio-economic resilience',c.resilience.toFixed(0)+'%'],
    c.recovery!=null?['Recovery duration',c.recovery.toFixed(1)+' yrs']:null,
  ].filter(Boolean);
  if(c.quint&&c.quint.length){
    rows.push(['— Risk to well-being by income quintile (% GDP)','']);
    const lab=['Poorest','Q2','Q3','Q4','Richest'];
    c.quint.forEach(q=>rows.push([lab[q.q-1]+' (income '+q.incomeShare.toFixed(0)+'%)',q.riskWellbeing.toFixed(3)]));
  }
  return rows;
}
function reportGlobal(V,avg,groups,ranked,groupBy,data){
  const rows=[['Indicator',V.label],['Global median',V.fmt(avg)+(V.unit==='%'?'%':' '+V.unit)],['Countries',ranked.length]];
  rows.push(['— Grouped by',groupBy==='inc'?'income group':'region']);
  groups.forEach(g=>rows.push([g.label+' (median · IQR)',
    V.fmt(g.med)+'  ['+V.fmt(g.q1)+'–'+V.fmt(g.q3)+']'+(V.unit==='%'?'%':' '+V.unit)]));
  rows.push(['Highest '+V.short,ranked[0].name+' ('+V.fmt(V.get(ranked[0]))+')'],
            ['Lowest '+V.short,ranked[ranked.length-1].name+' ('+V.fmt(V.get(ranked[ranked.length-1]))+')']);
  return rows;
}
function reportHTML(title,V,rows){
  return `<!doctype html><meta charset=utf8><title>Global Resilience Explorer — ${title}</title>
  <style>body{font-family:'IBM Plex Sans',Georgia,serif;max-width:720px;margin:48px auto;padding:0 24px;color:#16202b}
  h1{font-family:Georgia,serif;font-size:26px;border-bottom:3px solid #0f6e63;padding-bottom:10px}
  .sub{color:#7d8b9a;font-size:13px;margin-top:-6px}
  table{width:100%;border-collapse:collapse;margin-top:24px}
  td{padding:10px 4px;border-bottom:1px solid #e4e9ee;font-size:14px}
  td:last-child{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
  .ft{margin-top:32px;color:#7d8b9a;font-size:12px;line-height:1.5}</style>
  <h1>${title}</h1><div class="sub">Global Resilience Explorer · ${V.label} view · baseline simulation · generated ${new Date().toLocaleDateString()}</div>
  <table>${rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}</table>
  <div class="ft">Generated from the Global Unbreakable baseline simulation outputs. Socio-economic resilience is
  the ratio of expected asset damages to expected well-being losses.</div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
