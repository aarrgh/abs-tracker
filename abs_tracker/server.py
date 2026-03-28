"""
Minimal Flask web UI for MLB ABS Challenge Tracker.

Routes:
  GET /                              -> single-page HTML app
  GET /games?date=YYYY-MM-DD                    -> JSON game list for a date
  GET /games?from=YYYY-MM-DD&to=YYYY-MM-DD     -> JSON game list for a date range
  GET /takes?gamePk=XXXXX            -> JSON takes (all fields needed for the plot)
  GET /api/stats/batters             -> JSON season batter aggregates (from PostgreSQL)
  GET /api/stats/pitchers            -> JSON season pitcher aggregates
  GET /api/stats/catchers            -> JSON season catcher aggregates
  GET /api/stats/umpires             -> JSON season umpire aggregates
"""

import os

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, Response, jsonify, request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _DBSession

from .fetcher import fetch_game_feed, fetch_games_for_date_range
from .parser import extract_catchers, extract_hp_umpire, parse_game

_DATABASE_URL = os.environ.get("DATABASE_URL")
_db_engine = create_engine(_DATABASE_URL) if _DATABASE_URL else None

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Single-page HTML app (inline, no templates directory needed)
# Raw string to preserve JS \uXXXX escape sequences literally.
# ---------------------------------------------------------------------------
_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MLB ABS Tracker</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Verdana,Geneva,sans-serif;background:#0d1117;color:#c9d1d9;
     display:flex;flex-direction:column;height:100vh;overflow:hidden}
/* Tab bar */
#tab-bar{display:flex;background:#161b22;border-bottom:2px solid #21262d;flex-shrink:0;padding:0 12px}
.tab-btn{padding:10px 18px;background:none;border:none;border-bottom:2px solid transparent;
         color:#8b949e;cursor:pointer;font-family:inherit;font-size:13px;margin-bottom:-2px;width:auto}
.tab-btn:hover{color:#c9d1d9}
.tab-btn.tab-active{color:#79c0ff;border-bottom-color:#1f6feb}
/* Game view */
#view-game{display:flex;flex:1;overflow:hidden}
#view-stats{display:none;flex:1;flex-direction:column;overflow:hidden}
#sidebar{width:268px;min-width:268px;border-right:1px solid #21262d;padding:14px;
         overflow-y:auto;display:flex;flex-direction:column;gap:10px}
#main{flex:1;padding:16px 20px;overflow-y:auto}
h1{margin:0 0 4px;font-size:14px;color:#79c0ff;letter-spacing:.4px}
label{font-size:11px;color:#8b949e}
input[type=date],select{width:100%;padding:6px 8px;background:#161b22;border:1px solid #30363d;
                 color:#c9d1d9;border-radius:4px;font-family:inherit;font-size:12px;
                 color-scheme:dark}
select option{background:#161b22}
button{width:100%;padding:7px;background:#1f6feb;border:none;color:#fff;border-radius:4px;
       cursor:pointer;font-family:inherit;font-size:12px}
button:hover{background:#388bfd}
.game-row{padding:7px 9px;border-radius:4px;cursor:pointer;font-size:11px;line-height:1.5;
          border:1px solid transparent;margin-bottom:3px}
.game-row:hover{background:#161b22;border-color:#30363d}
.game-row.active{background:#0d419d;border-color:#1f6feb}
.gstatus{color:#8b949e;font-size:10px;display:block}
#plot-title{margin:0 0 12px;font-size:13px;color:#79c0ff;display:none}
#plot-area{display:none;gap:24px;align-items:flex-start}
svg{display:block}
#legend{min-width:190px;font-size:12px;line-height:1.9}
#legend b{color:#79c0ff}
.leg{display:flex;align-items:center;gap:8px}
.dot{width:12px;height:12px;border-radius:50%;flex-shrink:0}
#tip{position:fixed;display:none;background:rgba(13,17,23,.96);border:1px solid #444;
     padding:9px 13px;font-size:12px;line-height:1.75;pointer-events:none;border-radius:5px;
     max-width:275px;box-shadow:0 4px 14px rgba(0,0,0,.6)}
#counts{color:#8b949e;line-height:1.6}
.muted{color:#8b949e;font-size:12px}
#filter-panel{width:260px;font-size:11px;display:none;flex-shrink:0}
.fp-head{color:#79c0ff;font-weight:bold;margin-bottom:4px;font-size:12px}
.fp-label{color:#8b949e;font-size:10px;margin:8px 0 2px;text-transform:uppercase;letter-spacing:.4px}
.fp-teams{display:flex;gap:6px}
.fp-team{flex:1;min-width:0}
.fp-team-name{color:#6e7681;font-size:9px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}
.fp-names{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:2px}
.fp-chip{padding:2px 6px;border-radius:3px;background:#161b22;border:1px solid #30363d;
         cursor:pointer;color:#c9d1d9;font-size:11px;font-family:inherit;line-height:1.5}
.fp-chip:hover{border-color:#79c0ff}
.fp-chip.fp-active{background:#0d419d;border-color:#1f6feb}
/* Statistics tab */
#stats-subtabs{display:flex;gap:4px;padding:10px 14px;border-bottom:1px solid #21262d;flex-shrink:0}
.stab-btn{padding:5px 12px;background:#161b22;border:1px solid #30363d;color:#8b949e;
           border-radius:3px;cursor:pointer;font-family:inherit;font-size:12px;width:auto}
.stab-btn:hover{color:#c9d1d9;border-color:#555}
.stab-btn.stab-active{background:#0d419d;border-color:#1f6feb;color:#79c0ff}
#stats-main{flex:1;padding:14px 16px;overflow-y:auto}
#stats-search{padding:5px 9px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;
               border-radius:4px;font-family:inherit;font-size:12px;width:220px;margin-bottom:10px}
#stats-search::placeholder{color:#484f58}
#stats-tbl-wrap{overflow-x:auto}
.stats-tbl{border-collapse:collapse;font-size:12px;white-space:nowrap}
.stats-tbl th{padding:6px 10px;text-align:right;color:#8b949e;border-bottom:1px solid #30363d;
               cursor:pointer;user-select:none;font-weight:normal}
.stats-tbl th.sort-asc::after{content:" \25b2";font-size:9px}
.stats-tbl th.sort-desc::after{content:" \25bc";font-size:9px}
.stats-tbl td{padding:5px 10px;border-bottom:1px solid #161b22;text-align:right;color:#8b949e}
.stats-tbl tr:hover td{background:#161b22}
#stats-msg{font-size:12px;color:#8b949e;padding:4px 0}
</style>
</head>
<body>
<div id="tab-bar">
  <button class="tab-btn tab-active" id="tab-game">Game View</button>
  <button class="tab-btn" id="tab-stats">Statistics</button>
</div>
<div id="view-game">
  <div id="sidebar">
    <h1>MLB ABS Tracker</h1>
    <div>
      <label for="dt">Date</label>
      <input type="date" id="dt">
    </div>
    <div>
      <label for="teamFilter">Team</label>
      <select id="teamFilter"><option value="">All Teams</option></select>
    </div>
    <div id="gameList"></div>
  </div>
  <div id="main">
    <p id="placeholder" class="muted">Select a date and click a game to view the ABS zone plot.</p>
    <p id="loadingMsg" class="muted" style="display:none">Loading&#8230;</p>
    <h2 id="plot-title"></h2>
    <div id="plot-area">
      <svg id="sv"></svg>
      <div id="legend">
        <b>Challenge Outcome</b>
        <div class="leg"><div class="dot" style="background:#4caf50"></div>Successful (overturned)</div>
        <div class="leg"><div class="dot" style="background:#f44336"></div>Failed (upheld)</div>
        <div class="leg"><div class="dot" style="background:#ffeb3b"></div>Missed opportunity</div>
        <div class="leg"><div class="dot" style="background:#9e9e9e"></div>Correct / no challenge</div>
        <br>
        <b>Call (stroke)</b>
        <div class="leg"><div class="dot" style="border:2px solid #eee;background:transparent"></div>Called Strike</div>
        <div class="leg"><div class="dot" style="border:1.5px solid #555;background:transparent"></div>Called Ball</div>
        <br>
        <b>Zone</b>
        <div style="display:flex;align-items:center;gap:8px">
          <div style="width:32px;height:12px;border:1.5px dashed #4488cc"></div>
          <span id="zone-label">ABS ref (6'0")</span>
        </div>
        <br>
        <div id="counts"></div>
      </div>
      <div id="filter-panel"></div>
    </div>
    <footer style="text-align:center;padding:18px 24px;font-size:10px;color:#484f58;border-top:1px solid #21262d;margin-top:24px">
      <a href="https://github.com/aarrgh/abs-tracker" target="_blank" rel="noopener"
         style="color:#58a6ff;text-decoration:none;margin-bottom:6px;display:inline-flex;align-items:center;gap:5px">
        <svg height="14" viewBox="0 0 16 16" fill="#58a6ff" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
        aarrgh/abs-tracker
      </a><br>
      This tool is an independent fan project and is not affiliated with or endorsed by Major League Baseball.
      All team names, player names, and statistical data are the property of MLB and its member clubs.
    </footer>
  </div>
</div>
<div id="view-stats">
  <div id="stats-subtabs">
    <button class="stab-btn stab-active" data-entity="batters">Batters</button>
    <button class="stab-btn" data-entity="pitchers">Pitchers</button>
    <button class="stab-btn" data-entity="catchers">Catchers</button>
    <button class="stab-btn" data-entity="umpires">Umpires</button>
  </div>
  <div id="stats-main">
    <input type="text" id="stats-search" placeholder="Filter by name&#8230;">
    <div id="stats-msg" style="display:none"></div>
    <div id="stats-tbl-wrap"></div>
  </div>
</div>
<div id="tip"></div>
<script>
const NS='http://www.w3.org/2000/svg';
const mg={t:24,r:20,b:32,l:40};
const PX0=-2,PX1=2,PZ0=0.5,PZ1=5.5;
const SCALE=85;  // px per foot — equal on both axes so balls render as circles
const W=(PX1-PX0)*SCALE,H=(PZ1-PZ0)*SCALE;
const SW=W+mg.l+mg.r,SH=H+mg.t+mg.b;
const sx=px=>mg.l+(px-PX0)/(PX1-PX0)*W;
const sy=pz=>mg.t+(1-(pz-PZ0)/(PZ1-PZ0))*H;
const COL={successful:'#4caf50',failed:'#f44336',missed:'#ffeb3b',none:'#9e9e9e',unknown:'#555'};
const tip=document.getElementById('tip');

function mk(tag,a,p){
  const e=document.createElementNS(NS,tag);
  for(const[k,v]of Object.entries(a))e.setAttribute(k,v);
  (p||document.getElementById('sv')).appendChild(e);return e;
}
function gtxt(x,y,s,a={}){
  const e=mk('text',{x,y,'font-size':10,fill:'#555',...a});
  e.textContent=s;return e;
}

function buildPlotBase(){
  const sv=document.getElementById('sv');
  sv.setAttribute('width',SW);sv.setAttribute('height',SH);
  while(sv.firstChild)sv.removeChild(sv.firstChild);
  for(let x=-1.5;x<=1.51;x+=0.5){
    mk('line',{x1:sx(x),y1:mg.t,x2:sx(x),y2:mg.t+H,stroke:'#21262d','stroke-width':1});
    gtxt(sx(x),mg.t+H+13,x.toFixed(1),{'text-anchor':'middle'});
  }
  for(let z=1;z<=5.01;z+=0.5){
    mk('line',{x1:mg.l,y1:sy(z),x2:mg.l+W,y2:sy(z),stroke:'#21262d','stroke-width':1});
    gtxt(mg.l-4,sy(z)+3.5,z.toFixed(1),{'text-anchor':'end'});
  }
  {const e=mk('text',{x:mg.l+W/2,y:SH-2,'text-anchor':'middle','font-size':10,fill:'#555'});
   e.textContent='pX (ft, catcher POV)';}
  {const e=mk('text',{x:9,y:mg.t+H/2,'text-anchor':'middle','font-size':10,fill:'#555',
    transform:`rotate(-90,9,${mg.t+H/2})`});e.textContent='pZ (ft)';}
  mk('line',{x1:sx(0),y1:mg.t,x2:sx(0),y2:mg.t+H,stroke:'#21262d','stroke-width':1,'stroke-dasharray':'3,3'});
  mk('line',{x1:sx(-0.708),y1:sy(PZ0)+2,x2:sx(0.708),y2:sy(PZ0)+2,stroke:'#444','stroke-width':2});
}

function renderPlot(takes){
  buildPlotBase();
  const hw=0.708;
  let refT=6*0.535,refB=6*0.27,zoneLabel="ABS ref (6\u20180\u2033)";
  if(activeFilter&&activeFilter.role==='batter'&&currentData){
    const bt=(currentData.takes||[]).find(t=>t.batter_name===activeFilter.name&&t.abs_zone_top!=null);
    if(bt){
      refT=bt.abs_zone_top;refB=bt.abs_zone_bottom;
      const htFt=refT/0.535;
      const ft=Math.floor(htFt),inch=Math.round((htFt-ft)*12);
      zoneLabel=`ABS zone (${activeFilter.name}, ${ft}\u2018${inch}\u2033)`;
    }
  }
  mk('rect',{x:sx(-hw),y:sy(refT),width:sx(hw)-sx(-hw),height:sy(refB)-sy(refT),
    fill:'none',stroke:'#4488cc','stroke-width':1.5,'stroke-dasharray':'6,3'});
  const zl=document.getElementById('zone-label');if(zl)zl.textContent=zoneLabel;
  const counts={successful:0,failed:0,missed:0,none:0};
  const ballR=2.9/24*SCALE;  // 2.9" diameter → radius in px
  const sortedTakes=[...takes].sort((a,b)=>(a.challenge_outcome==='none'?0:1)-(b.challenge_outcome==='none'?0:1));
  for(const t of sortedTakes){
    if(t.px==null||t.pz==null)continue;
    counts[t.challenge_outcome]=(counts[t.challenge_outcome]||0)+1;
    const cx=sx(t.px),cy=sy(t.pz);
    const col=COL[t.challenge_outcome]||'#666';
    const isStrike=t.call_result==='Called Strike';
    const c=mk('circle',{cx,cy,r:ballR,fill:col,opacity:t.challenge_outcome==='none'?'0.3':'0.88',
      stroke:isStrike?'#eee':'#555','stroke-width':isStrike?1.8:.8,cursor:'pointer'});
    const zStr=t.abs_zone_bottom!=null
      ?`${t.abs_zone_bottom.toFixed(2)}\u2013${t.abs_zone_top.toFixed(2)} ft`:'N/A';
    const inn=`${t.inning}${t.half_inning==='top'?'T':'B'}`;
    c.addEventListener('mouseenter',()=>{
      const cb=t.count_balls,cs=t.count_strikes;
      let outcomeLine='';
      if(t.has_review){
        const who=t.challenger_name||'Unknown';
        const pos=t.challenger_name?(t.challenger_name===t.catcher_name?'C':t.challenger_name===t.pitcher_name?'P':t.challenger_name===t.batter_name?'AB':null):null;
        const label=pos?`${who} (${pos})`:who;
        if(t.challenge_outcome==='successful'){
          if(t.is_strike){
            outcomeLine=`Challenged by ${label}<br>`+
              `Call REVERSED \u2014 Ball ${cb!=null?cb+1:'?'} becomes Strike ${cs??'?'}`;
          } else {
            outcomeLine=`Challenged by ${label}<br>`+
              `Call REVERSED \u2014 Strike ${cs!=null?cs+1:'?'} becomes Ball ${cb??'?'}`;
          }
        } else {
          const callStr=t.is_ball?`Ball ${cb??'?'}`:`Strike ${cs??'?'}`;
          outcomeLine=`Challenged by ${label}<br>Call UPHELD \u2014 ${callStr}`;
        }
      } else if(t.challenge_outcome==='missed'){
        if(t.is_ball){
          outcomeLine=`Challenge MISSED \u2014 Ball ${cb??'?'}, should be Strike ${cs!=null?cs+1:'?'}`;
        } else {
          outcomeLine=`Challenge MISSED \u2014 Strike ${cs??'?'}, should be Ball ${cb!=null?cb+1:'?'}`;
        }
      }
      const origCall=t.challenge_outcome==='successful'
        ?(t.is_strike?'Ball':'Called Strike')
        :t.call_result;
      tip.innerHTML=
        `<b>${t.batter_name}</b> vs ${t.pitcher_name}<br>`+
        `Catcher: ${t.catcher_name||'\u2014'}<br>`+
        `Umpire: ${t.umpire_name||'\u2014'}<br>`+
        `Inning: ${inn} &nbsp; Pitch #${t.pitch_number}<br>`+
        `Call: <b>${origCall}</b><br>`+
        (outcomeLine?outcomeLine+'<br>':'')+
        (!outcomeLine?`ABS verdict: <b>${t.abs_result}</b><br>`:'')+
        `pX=${t.px!=null?t.px.toFixed(3):'\u2014'} &nbsp;`+
        `pZ=${t.pz!=null?t.pz.toFixed(3):'\u2014'}<br>`+
        `Batter ABS zone: ${zStr}`;
      tip.style.display='block';
    });
    c.addEventListener('mousemove',e=>{
      tip.style.left=(e.clientX+16)+'px';
      tip.style.top=(e.clientY-18)+'px';
    });
    c.addEventListener('mouseleave',()=>{tip.style.display='none';});
  }
  const plotted=takes.filter(t=>t.px!=null).length;
  document.getElementById('counts').innerHTML=
    `Takes plotted: ${plotted}<br>`+
    `\u2022 Successful: ${counts.successful||0}<br>`+
    `\u2022 Failed: ${counts.failed||0}<br>`+
    `\u2022 Missed: ${counts.missed||0}<br>`+
    `\u2022 Correct/none: ${counts.none||0}`;
}

// --- Participant filter panel ---
let currentData=null, activeFilter=null;

function buildParticipants(takes, awayTeam, homeTeam){
  const s={
    batter:{away:new Set(),home:new Set()},
    pitcher:{away:new Set(),home:new Set()},
    catcher:{away:new Set(),home:new Set()},
    umpire:new Set()
  };
  for(const t of takes){
    // top half: away bats, home pitches/catches; bottom half: home bats, away pitches/catches
    const isTop=t.half_inning==='top';
    if(t.batter_name) s.batter[isTop?'away':'home'].add(t.batter_name);
    if(t.pitcher_name) s.pitcher[isTop?'home':'away'].add(t.pitcher_name);
    if(t.catcher_name) s.catcher[isTop?'home':'away'].add(t.catcher_name);
    if(t.umpire_name) s.umpire.add(t.umpire_name);
  }
  return{
    batter:{away:[...s.batter.away].sort(),home:[...s.batter.home].sort()},
    pitcher:{away:[...s.pitcher.away].sort(),home:[...s.pitcher.home].sort()},
    catcher:{away:[...s.catcher.away].sort(),home:[...s.catcher.home].sort()},
    umpire:[...s.umpire].sort(),
    awayTeam, homeTeam
  };
}

function renderFilterPanel(participants){
  const panel=document.getElementById('filter-panel');
  const teamSections=[
    {role:'batter',label:'Batters'},
    {role:'pitcher',label:'Pitchers'},
    {role:'catcher',label:'Catchers'},
  ];
  let html='<div class="fp-head">Participants</div>';
  for(const{role,label}of teamSections){
    const{away,home}=participants[role];
    if(!away.length&&!home.length)continue;
    html+=`<div class="fp-label">${label}</div><div class="fp-teams">`;
    for(const[side,names]of[['away',away],['home',home]]){
      const teamName=side==='away'?participants.awayTeam:participants.homeTeam;
      html+=`<div class="fp-team"><div class="fp-team-name">${teamName}</div><div class="fp-names">`;
      for(const n of names){
        const active=activeFilter&&activeFilter.role===role&&activeFilter.name===n;
        html+=`<button class="fp-chip${active?' fp-active':''}" data-role="${role}" data-name="${n}">${n}</button>`;
      }
      html+='</div></div>';
    }
    html+='</div>';
  }
  if(participants.umpire.length){
    html+=`<div class="fp-label">Umpire</div><div class="fp-names">`;
    for(const n of participants.umpire){
      const active=activeFilter&&activeFilter.role==='umpire'&&activeFilter.name===n;
      html+=`<button class="fp-chip${active?' fp-active':''}" data-role="umpire" data-name="${n}">${n}</button>`;
    }
    html+='</div>';
  }
  panel.innerHTML=html;
  panel.style.display='block';
  panel.querySelectorAll('.fp-chip').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const role=btn.dataset.role,name=btn.dataset.name;
      if(activeFilter&&activeFilter.role===role&&activeFilter.name===name){
        activeFilter=null;
      }else{
        activeFilter={role,name};
      }
      renderFilterPanel(participants);
      applyAndRender();
    });
  });
}

function getFilteredTakes(takes){
  if(!activeFilter)return takes;
  const{role,name}=activeFilter;
  return takes.filter(t=>{
    if(role==='batter')return t.batter_name===name;
    if(role==='pitcher')return t.pitcher_name===name;
    if(role==='catcher')return t.catcher_name===name;
    if(role==='umpire')return t.umpire_name===name;
    return true;
  });
}

function applyAndRender(){
  if(!currentData)return;
  renderPlot(getFilteredTakes(currentData.takes));
}

// --- Game list: auto-load all games from opening day, filter client-side ---
const OPENING_DAY='2026-03-25';
let allGames=[];

function fmtDate(d){
  return`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

async function loadAllGames(){
  const gl=document.getElementById('gameList');
  gl.innerHTML='<span class="muted" style="font-size:11px">Loading\u2026</span>';
  try{
    const today=fmtDate(new Date());
    const resp=await fetch(`/games?from=${OPENING_DAY}&to=${today}`);
    if(!resp.ok)throw new Error(resp.statusText);
    const raw=await resp.json();
    allGames=raw
      .filter(g=>g.status!=='Preview')
      .sort((a,b)=>b.game_date.localeCompare(a.game_date)||b.gamePk-a.gamePk);
    populateTeamFilter(allGames);
    renderGameList(allGames);
  }catch(e){
    gl.innerHTML='<span style="color:#f44336;font-size:11px">Error loading games.</span>';
  }
}

document.getElementById('dt').addEventListener('change',()=>renderGameList(getFilteredGames()));
document.getElementById('teamFilter').addEventListener('change',()=>renderGameList(getFilteredGames()));

function populateTeamFilter(games){
  const sel=document.getElementById('teamFilter');
  const teams=[...new Set(games.flatMap(g=>[g.away_team_name,g.home_team_name]))].sort();
  sel.innerHTML='<option value="">All Teams</option>'+
    teams.map(t=>`<option value="${t}">${t}</option>`).join('');
}

function getFilteredGames(){
  const dateVal=document.getElementById('dt').value;
  const teamVal=document.getElementById('teamFilter').value;
  return allGames.filter(g=>{
    if(dateVal&&g.game_date!==dateVal)return false;
    if(teamVal&&g.away_team_name!==teamVal&&g.home_team_name!==teamVal)return false;
    return true;
  });
}

function renderGameList(games){
  const el=document.getElementById('gameList');
  if(!games.length){el.innerHTML='<p class="muted" style="font-size:11px">No games found.</p>';return;}
  el.innerHTML=games.map(g=>
    `<div class="game-row" data-pk="${g.gamePk}">
      <span>${g.away_team_name} @ ${g.home_team_name}</span>
      <span class="gstatus">${g.game_date} \u00b7 ${g.detailed_status}</span>
    </div>`
  ).join('');
  el.querySelectorAll('.game-row').forEach(row=>{
    row.addEventListener('click',()=>{
      el.querySelectorAll('.game-row').forEach(r=>r.classList.remove('active'));
      row.classList.add('active');
      loadGame(parseInt(row.dataset.pk));
    });
  });
}

async function loadGame(gamePk){
  document.getElementById('placeholder').style.display='none';
  document.getElementById('loadingMsg').style.display='block';
  document.getElementById('plot-area').style.display='none';
  document.getElementById('plot-title').style.display='none';
  document.getElementById('filter-panel').style.display='none';
  tip.style.display='none';
  currentData=null; activeFilter=null;
  try{
    const resp=await fetch(`/takes?gamePk=${gamePk}`);
    if(!resp.ok)throw new Error(resp.statusText);
    const DATA=await resp.json();
    currentData=DATA;
    document.getElementById('plot-title').textContent=DATA.title||`gamePk ${gamePk}`;
    document.getElementById('plot-title').style.display='block';
    document.getElementById('plot-area').style.display='flex';
    renderFilterPanel(buildParticipants(DATA.takes, DATA.away_team, DATA.home_team));
    renderPlot(DATA.takes);
  }catch(e){
    document.getElementById('plot-title').textContent='Error loading game data.';
    document.getElementById('plot-title').style.display='block';
  }finally{
    document.getElementById('loadingMsg').style.display='none';
  }
}

loadAllGames();

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------
function switchTab(name){
  document.getElementById('view-game').style.display=name==='game'?'flex':'none';
  document.getElementById('view-stats').style.display=name==='stats'?'flex':'none';
  document.getElementById('tab-game').classList.toggle('tab-active',name==='game');
  document.getElementById('tab-stats').classList.toggle('tab-active',name==='stats');
  location.hash=name;
  if(name==='stats'&&!statsCache[curEntity])fetchStatsData(curEntity);
}
document.getElementById('tab-game').addEventListener('click',()=>switchTab('game'));
document.getElementById('tab-stats').addEventListener('click',()=>switchTab('stats'));

// ---------------------------------------------------------------------------
// Statistics tab
// ---------------------------------------------------------------------------
const statsCache={};
const statsSort={};
let curEntity='batters';

// Column definitions: k=data key, h=header label, str=string col (sort as string), lft=left-align, pct=percentage
const ECOLS={
  batters:[
    {k:'batter_name',h:'Player',str:true,lft:true},
    {k:'team',h:'Team',str:true,lft:true},
    {k:'takes',h:'Takes'},
    {k:'missed_opps',h:'Missed Opp'},
    {k:'challenges_made',h:'Challenges'},
    {k:'successful',h:'Successful'},
    {k:'failed',h:'Failed'},
    {k:'success_rate',h:'Success%',pct:true},
    {k:'wrong_calls_against',h:'Wrong Calls'},
    {k:'wrong_call_rate',h:'Wrong%',pct:true},
  ],
  pitchers:[
    {k:'pitcher_name',h:'Player',str:true,lft:true},
    {k:'team',h:'Team',str:true,lft:true},
    {k:'takes_against',h:'Takes'},
    {k:'missed_opps',h:'Missed Opp'},
    {k:'challenges_faced',h:'Challenges'},
    {k:'challenges_won',h:'Won'},
    {k:'challenges_lost',h:'Lost'},
    {k:'wrong_calls_for',h:'Wrong For'},
    {k:'wrong_calls_against',h:'Wrong Against'},
  ],
  catchers:[
    {k:'catcher_name',h:'Player',str:true,lft:true},
    {k:'team',h:'Team',str:true,lft:true},
    {k:'takes_framed',h:'Takes'},
    {k:'challenges_made',h:'Challenges'},
    {k:'successful',h:'Successful'},
    {k:'failed',h:'Failed'},
    {k:'success_rate',h:'Success%',pct:true},
    {k:'missed_opps',h:'Missed Opp'},
    {k:'wrong_calls_for',h:'Wrong For'},
    {k:'wrong_calls_against',h:'Wrong Against'},
  ],
  umpires:[
    {k:'umpire_name',h:'Umpire',str:true,lft:true},
    {k:'games_called',h:'Games'},
    {k:'total_takes',h:'Takes'},
    {k:'correct_calls',h:'Correct'},
    {k:'incorrect_calls',h:'Incorrect'},
    {k:'accuracy_rate',h:'Accuracy%',pct:true},
    {k:'wrong_strikes',h:'Wrong Strikes'},
    {k:'wrong_balls',h:'Wrong Balls'},
    {k:'challenges_faced',h:'Challenges'},
    {k:'challenges_upheld',h:'Upheld'},
    {k:'challenges_overturned',h:'Overturned'},
    {k:'overturn_rate',h:'Overturn%',pct:true},
  ],
};
const DEFAULT_SORT_COL={batters:'takes',pitchers:'takes_against',catchers:'takes_framed',umpires:'total_takes'};

document.querySelectorAll('.stab-btn').forEach(btn=>{
  btn.addEventListener('click',()=>switchStatsTab(btn.dataset.entity));
});
document.getElementById('stats-search').addEventListener('input',()=>{
  if(statsCache[curEntity])renderStatsTable(curEntity);
});

function switchStatsTab(entity){
  curEntity=entity;
  document.querySelectorAll('.stab-btn').forEach(b=>b.classList.toggle('stab-active',b.dataset.entity===entity));
  document.getElementById('stats-search').value='';
  if(!statsSort[entity])statsSort[entity]={col:DEFAULT_SORT_COL[entity],dir:'desc'};
  if(statsCache[entity]){renderStatsTable(entity);}else{fetchStatsData(entity);}
}

async function fetchStatsData(entity){
  const msg=document.getElementById('stats-msg');
  msg.textContent='Loading\u2026';msg.style.color='#8b949e';msg.style.display='block';
  document.getElementById('stats-tbl-wrap').innerHTML='';
  try{
    const resp=await fetch('/api/stats/'+entity);
    if(!resp.ok)throw new Error(resp.statusText);
    statsCache[entity]=await resp.json();
    msg.style.display='none';
    renderStatsTable(entity);
  }catch(e){
    msg.textContent='Error loading stats: '+e.message;
    msg.style.color='#f44336';
  }
}

function renderStatsTable(entity){
  const data=statsCache[entity];
  const cols=ECOLS[entity];
  const nameKey=cols[0].k;
  const searchVal=document.getElementById('stats-search').value.toLowerCase();
  const sort=statsSort[entity]||{col:DEFAULT_SORT_COL[entity],dir:'desc'};

  let rows=searchVal?data.filter(r=>(r[nameKey]||'').toLowerCase().includes(searchVal)):[...data];

  const sortCol=cols.find(c=>c.k===sort.col);
  if(sortCol){
    rows.sort((a,b)=>{
      const av=a[sort.col],bv=b[sort.col];
      if(sortCol.str)return sort.dir==='asc'?(av||'').localeCompare(bv||''):(bv||'').localeCompare(av||'');
      return sort.dir==='asc'?(av??-Infinity)-(bv??-Infinity):(bv??-Infinity)-(av??-Infinity);
    });
  }

  let html='<table class="stats-tbl"><thead><tr>';
  for(const col of cols){
    const active=sort.col===col.k;
    const cls=active?(sort.dir==='asc'?'sort-asc':'sort-desc'):'';
    const align=col.lft?'text-align:left':'';
    html+=`<th class="${cls}" data-col="${col.k}" style="${align}">${col.h}</th>`;
  }
  html+='</tr></thead><tbody>';

  for(const r of rows){
    html+='<tr>';
    for(const col of cols){
      const v=r[col.k];
      let display;
      if(col.pct)display=v!=null?v.toFixed(1)+'%':'\u2014';
      else if(v==null)display='\u2014';
      else display=v;
      const tdStyle=col.lft?'text-align:left;color:#c9d1d9':'';
      html+=`<td style="${tdStyle}">${display}</td>`;
    }
    html+='</tr>';
  }
  html+='</tbody></table>';

  document.getElementById('stats-tbl-wrap').innerHTML=html;
  document.getElementById('stats-msg').style.display='none';

  document.querySelectorAll('.stats-tbl th[data-col]').forEach(th=>{
    th.addEventListener('click',()=>{
      const col=th.dataset.col;
      const cur=statsSort[entity]||{};
      statsSort[entity]={col,dir:cur.col===col&&cur.dir==='desc'?'asc':'desc'};
      renderStatsTable(entity);
    });
  });
}

// Restore tab from URL hash on load
if(location.hash==='#stats')switchTab('stats');
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return Response(_INDEX_HTML, mimetype="text/html")


@app.route("/games")
def games():
    game_date = request.args.get("date", "")
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")
    if game_date:
        start, end = game_date, game_date
    elif from_date:
        start, end = from_date, to_date or from_date
    else:
        return jsonify({"error": "date or from/to parameters required"}), 400
    try:
        result = fetch_games_for_date_range(start, end)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(result)


@app.route("/takes")
def takes():
    game_pk_str = request.args.get("gamePk", "")
    if not game_pk_str:
        return jsonify({"error": "gamePk parameter required"}), 400
    try:
        game_pk = int(game_pk_str)
    except ValueError:
        return jsonify({"error": "gamePk must be an integer"}), 400

    try:
        feed = fetch_game_feed(game_pk)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    pitches, missed_ops = parse_game(feed)
    hp_umpire = extract_hp_umpire(feed)
    catchers = extract_catchers(feed)

    missed_keys = {(mo.pitch.at_bat_index, mo.pitch.pitch_number) for mo in missed_ops}

    game_data = feed.get("gameData", {})
    teams = game_data.get("teams", {})
    away_name = teams.get("away", {}).get("name", "Away")
    home_name = teams.get("home", {}).get("name", "Home")
    game_date_str = game_data.get("datetime", {}).get("officialDate", "")
    title = f"{away_name} @ {home_name}  ({game_date_str})"
    away_abbrev = teams.get("away", {}).get("abbreviation", away_name)
    home_abbrev = teams.get("home", {}).get("abbreviation", home_name)

    result = []
    for p in pitches:
        catcher_side = "home" if p.half_inning == "top" else "away"
        catcher_name = catchers.get(catcher_side)

        if p.has_review:
            challenge_outcome = "successful" if p.is_overturned else "failed"
        elif (p.at_bat_index, p.pitch_number) in missed_keys:
            challenge_outcome = "missed"
        else:
            challenge_outcome = "none"

        if p.in_abs_zone is None:
            abs_result = "unknown"
        elif p.in_abs_zone:
            abs_result = "strike"
        else:
            abs_result = "ball"

        result.append({
            "inning": p.inning,
            "half_inning": p.half_inning,
            "at_bat_index": p.at_bat_index,
            "pitch_number": p.pitch_number,
            "batter_name": p.batter_name,
            "pitcher_name": p.pitcher_name,
            "catcher_name": catcher_name,
            "umpire_name": hp_umpire,
            "px": p.px,
            "pz": p.pz,
            "call_result": p.call_description,
            "abs_result": abs_result,
            "abs_zone_top": p.abs_zone_top,
            "abs_zone_bottom": p.abs_zone_bottom,
            "in_abs_zone": p.in_abs_zone,
            "challenge_outcome": challenge_outcome,
            "is_ball": p.is_ball,
            "is_strike": p.is_strike,
            "has_review": p.has_review,
            "challenger_name": p.challenger_name,
            "count_balls": p.count_balls,
            "count_strikes": p.count_strikes,
        })

    return jsonify({"game_pk": game_pk, "title": title,
                    "away_team": away_abbrev, "home_team": home_abbrev,
                    "takes": result})


# ---------------------------------------------------------------------------
# Statistics API — queries PostgreSQL takes table
# ---------------------------------------------------------------------------

def _no_db():
    return jsonify({"error": "Statistics database not configured."}), 503


@app.route("/api/stats/batters")
def stats_batters():
    if _db_engine is None:
        return _no_db()
    try:
        with _DBSession(_db_engine) as session:
            rows = session.execute(text("""
                SELECT
                    t.batter_name,
                    MAX(CASE WHEN t.inning_half='top' THEN g.away_team ELSE g.home_team END) AS team,
                    COUNT(*) AS takes,
                    COUNT(*) FILTER (WHERE t.missed_opportunity=TRUE AND t.umpire_call='called_strike') AS missed_opps,
                    COUNT(*) FILTER (WHERE t.challenge_outcome IN ('successful','failed') AND t.is_defense_challenge=FALSE) AS challenges_made,
                    COUNT(*) FILTER (WHERE t.challenge_outcome='successful' AND t.is_defense_challenge=FALSE) AS successful,
                    COUNT(*) FILTER (WHERE t.challenge_outcome='failed' AND t.is_defense_challenge=FALSE) AS failed,
                    COUNT(*) FILTER (WHERE t.umpire_call='called_strike' AND t.in_abs_zone=FALSE) AS wrong_calls_against
                FROM takes t
                JOIN games g ON t.game_pk=g.game_pk
                GROUP BY t.batter_id, t.batter_name
                ORDER BY takes DESC
            """)).mappings().all()
            result = []
            for r in rows:
                cm = r["challenges_made"]
                wca = r["wrong_calls_against"]
                takes = r["takes"]
                result.append({
                    "batter_name": r["batter_name"],
                    "team": r["team"],
                    "takes": takes,
                    "missed_opps": r["missed_opps"],
                    "challenges_made": cm,
                    "successful": r["successful"],
                    "failed": r["failed"],
                    "success_rate": round(r["successful"] / cm * 100, 1) if cm else None,
                    "wrong_calls_against": wca,
                    "wrong_call_rate": round(wca / takes * 100, 1) if takes else 0.0,
                })
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stats/pitchers")
def stats_pitchers():
    if _db_engine is None:
        return _no_db()
    try:
        with _DBSession(_db_engine) as session:
            rows = session.execute(text("""
                SELECT
                    t.pitcher_name,
                    MAX(CASE WHEN t.inning_half='top' THEN g.home_team ELSE g.away_team END) AS team,
                    COUNT(*) AS takes_against,
                    COUNT(*) FILTER (WHERE t.missed_opportunity=TRUE AND t.umpire_call='ball') AS missed_opps,
                    COUNT(*) FILTER (WHERE t.challenge_outcome IN ('successful','failed')) AS challenges_faced,
                    COUNT(*) FILTER (WHERE
                        (t.umpire_call='called_strike' AND t.challenge_outcome='failed') OR
                        (t.umpire_call='ball' AND t.challenge_outcome='successful')
                    ) AS challenges_won,
                    COUNT(*) FILTER (WHERE
                        (t.umpire_call='called_strike' AND t.challenge_outcome='successful') OR
                        (t.umpire_call='ball' AND t.challenge_outcome='failed')
                    ) AS challenges_lost,
                    COUNT(*) FILTER (WHERE t.missed_opportunity=TRUE AND t.umpire_call='called_strike') AS wrong_calls_for,
                    COUNT(*) FILTER (WHERE t.missed_opportunity=TRUE AND t.umpire_call='ball') AS wrong_calls_against
                FROM takes t
                JOIN games g ON t.game_pk=g.game_pk
                GROUP BY t.pitcher_id, t.pitcher_name
                ORDER BY takes_against DESC
            """)).mappings().all()
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stats/catchers")
def stats_catchers():
    if _db_engine is None:
        return _no_db()
    try:
        with _DBSession(_db_engine) as session:
            rows = session.execute(text("""
                SELECT
                    t.catcher_name,
                    MAX(CASE WHEN t.inning_half='top' THEN g.home_team ELSE g.away_team END) AS team,
                    COUNT(*) AS takes_framed,
                    COUNT(*) FILTER (WHERE t.challenge_outcome IN ('successful','failed') AND t.is_defense_challenge=TRUE) AS challenges_made,
                    COUNT(*) FILTER (WHERE t.challenge_outcome='successful' AND t.is_defense_challenge=TRUE AND t.umpire_call='ball') AS successful,
                    COUNT(*) FILTER (WHERE t.is_defense_challenge=TRUE AND NOT (t.challenge_outcome='successful' AND t.umpire_call='ball')) AS failed,
                    COUNT(*) FILTER (WHERE t.missed_opportunity=TRUE AND t.umpire_call='ball') AS missed_opps,
                    COUNT(*) FILTER (WHERE t.umpire_call='called_strike' AND t.in_abs_zone=FALSE) AS wrong_calls_for,
                    COUNT(*) FILTER (WHERE t.umpire_call='ball' AND t.in_abs_zone=TRUE) AS wrong_calls_against
                FROM takes t
                JOIN games g ON t.game_pk=g.game_pk
                WHERE t.catcher_name IS NOT NULL
                GROUP BY t.catcher_name
                ORDER BY takes_framed DESC
            """)).mappings().all()
            result = []
            for r in rows:
                cm = r["challenges_made"]
                result.append({
                    **dict(r),
                    "success_rate": round(r["successful"] / cm * 100, 1) if cm else None,
                })
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stats/umpires")
def stats_umpires():
    if _db_engine is None:
        return _no_db()
    try:
        with _DBSession(_db_engine) as session:
            rows = session.execute(text("""
                SELECT
                    t.umpire_name,
                    COUNT(DISTINCT t.game_pk) AS games_called,
                    COUNT(*) AS total_takes,
                    COUNT(*) FILTER (WHERE t.in_abs_zone IS NOT NULL AND (
                        (t.umpire_call='called_strike' AND t.in_abs_zone=TRUE) OR
                        (t.umpire_call='ball' AND t.in_abs_zone=FALSE)
                    )) AS correct_calls,
                    COUNT(*) FILTER (WHERE t.in_abs_zone IS NOT NULL AND (
                        (t.umpire_call='called_strike' AND t.in_abs_zone=FALSE) OR
                        (t.umpire_call='ball' AND t.in_abs_zone=TRUE)
                    )) AS incorrect_calls,
                    COUNT(*) FILTER (WHERE t.umpire_call='called_strike' AND t.in_abs_zone=FALSE) AS wrong_strikes,
                    COUNT(*) FILTER (WHERE t.umpire_call='ball' AND t.in_abs_zone=TRUE) AS wrong_balls,
                    COUNT(*) FILTER (WHERE t.challenge_outcome IN ('successful','failed')) AS challenges_faced,
                    COUNT(*) FILTER (WHERE t.challenge_outcome='failed') AS challenges_upheld,
                    COUNT(*) FILTER (WHERE t.challenge_outcome='successful') AS challenges_overturned
                FROM takes t
                WHERE t.umpire_name IS NOT NULL
                GROUP BY t.umpire_name
                ORDER BY total_takes DESC
            """)).mappings().all()
            result = []
            for r in rows:
                assessable = r["correct_calls"] + r["incorrect_calls"]
                cf = r["challenges_faced"]
                result.append({
                    **dict(r),
                    "accuracy_rate": round(r["correct_calls"] / assessable * 100, 1) if assessable else None,
                    "overturn_rate": round(r["challenges_overturned"] / cf * 100, 1) if cf else None,
                })
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def run(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
