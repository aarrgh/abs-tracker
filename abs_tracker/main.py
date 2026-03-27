"""
MLB ABS Challenge Tracker — CLI entry point.

Live (no DB) commands:
  python -m abs_tracker games 2026-03-26          # JSON game list for a date
  python -m abs_tracker takes 823812              # JSON takes for a game
  python -m abs_tracker plot  823812              # HTML strike zone plot for a game
  python -m abs_tracker smoke [game_pk]
  python -m abs_tracker game  823812 [--output csv|json|table]
  python -m abs_tracker date  2026-03-26
  python -m abs_tracker range 2026-03-26 2026-03-30

Database commands:
  python -m abs_tracker sync   [--db abs_tracker.db] [-v] [--from DATE] [--dry-run]
  python -m abs_tracker report [--db abs_tracker.db] [--output ...] date 2026-03-26
  python -m abs_tracker report [--db abs_tracker.db] [--output ...] range START END
  python -m abs_tracker status [--db abs_tracker.db]
"""

import argparse
import sys
from datetime import date, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Self-contained HTML template for the strike zone plot.
# __DATA__ is replaced at render time with an embedded JSON payload.
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ABS Zone Plot</title>
<style>
body{margin:0;padding:16px 20px;font-family:"Courier New",monospace;
     background:#0d1117;color:#c9d1d9}
h2{margin:0 0 12px;font-size:15px;color:#79c0ff;letter-spacing:.4px}
#wrap{display:flex;gap:28px;align-items:flex-start}
svg{display:block}
#legend{min-width:190px;font-size:12px;line-height:1.9}
#legend b{color:#79c0ff}
.leg{display:flex;align-items:center;gap:8px}
.dot{width:12px;height:12px;border-radius:50%;flex-shrink:0}
#tip{position:fixed;display:none;background:rgba(13,17,23,.96);
     border:1px solid #444;padding:9px 13px;font-size:12px;line-height:1.75;
     pointer-events:none;border-radius:5px;max-width:275px;
     box-shadow:0 4px 14px rgba(0,0,0,.6)}
#filter-panel{width:260px;font-size:11px;flex-shrink:0}
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
</style>
</head>
<body>
<h2 id="ttl"></h2>
<div id="wrap">
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
    <div id="counts" style="color:#8b949e;line-height:1.6"></div>
  </div>
  <div id="filter-panel"></div>
</div>
<div id="tip"></div>
<script>
const DATA = __DATA__;

const mg={t:24,r:20,b:32,l:40};
const PX0=-2,PX1=2,PZ0=0.5,PZ1=5.5;
const SCALE=85;  // px per foot — equal on both axes so balls render as circles
const W=(PX1-PX0)*SCALE,H=(PZ1-PZ0)*SCALE;
const SW=W+mg.l+mg.r,SH=H+mg.t+mg.b;

const sx=px=>mg.l+(px-PX0)/(PX1-PX0)*W;
const sy=pz=>mg.t+(1-(pz-PZ0)/(PZ1-PZ0))*H;

const COL={successful:'#4caf50',failed:'#f44336',missed:'#ffeb3b',none:'#9e9e9e',unknown:'#555'};
const NS='http://www.w3.org/2000/svg';
const tip=document.getElementById('tip');

const mk=(tag,a,p)=>{
  const e=document.createElementNS(NS,tag);
  for(const[k,v]of Object.entries(a))e.setAttribute(k,v);
  (p||document.getElementById('sv')).appendChild(e);return e;
};
const gtxt=(x,y,s,a={})=>{
  const e=mk('text',{x,y,'font-size':10,fill:'#555',...a});
  e.textContent=s;return e;
};

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
  if(activeFilter&&activeFilter.role==='batter'){
    const allTakes=(typeof DATA!=='undefined'&&DATA.takes)||[];
    const bt=allTakes.find(t=>t.batter_name===activeFilter.name&&t.abs_zone_top!=null);
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
let activeFilter=null;

function buildParticipants(takes, awayTeam, homeTeam){
  const s={
    batter:{away:new Set(),home:new Set()},
    pitcher:{away:new Set(),home:new Set()},
    catcher:{away:new Set(),home:new Set()},
    umpire:new Set()
  };
  for(const t of takes){
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
  renderPlot(getFilteredTakes(DATA.takes));
}

document.getElementById('ttl').textContent=DATA.title||`ABS Zone Plot \u2014 gamePk ${DATA.game_pk}`;
renderFilterPanel(buildParticipants(DATA.takes, DATA.away_team, DATA.home_team));
applyAndRender();
</script>
</body>
</html>"""

from .analyzer import (
    analyze_batters,
    analyze_challenges,
    analyze_defense,
    analyze_missed_opportunities,
    analyze_umpires,
)
from .db import db_summary, init_db, load_pitches
from .fetcher import fetch_game_feed, fetch_games_for_date, fetch_games_for_range, fetch_schedule
from .models import MissedOpportunity, Pitch
from .parser import derive_missed_ops, extract_catchers, extract_hp_umpire, parse_game
from .sync import OPENING_DAY_2026, sync_season


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg, file=sys.stderr)


def _print_df(df, fmt: str) -> None:
    import pandas as pd

    if df is None or df.empty:
        print("  (no data)")
        return
    if fmt == "json":
        print(df.to_json(orient="records", indent=2))
    elif fmt == "csv":
        print(df.to_csv(index=False))
    else:
        with pd.option_context("display.max_columns", None, "display.width", 220,
                               "display.max_rows", 200):
            print(df.to_string(index=False))


def _process_game(
    game_pk: int,
    game_date: str = "",
    verbose: bool = False,
) -> tuple[list[Pitch], list[MissedOpportunity]]:
    _log(f"  Fetching game {game_pk} ...", verbose)
    feed = fetch_game_feed(game_pk)
    pitches, missed = parse_game(feed)
    _log(
        f"  → {len(pitches)} takes | "
        f"{sum(1 for p in pitches if p.has_review)} challenges | "
        f"{len(missed)} missed opportunities",
        verbose,
    )
    return pitches, missed


def _process_date(
    target_date: str,
    verbose: bool = False,
) -> tuple[list[Pitch], list[MissedOpportunity]]:
    _log(f"Fetching schedule for {target_date} ...", verbose)
    games = fetch_schedule(target_date)
    final_games = [
        g for g in games
        if g.get("status", {}).get("abstractGameState") == "Final"
    ]
    _log(f"  {len(final_games)} completed game(s) found", verbose)

    all_pitches: list[Pitch] = []
    all_missed: list[MissedOpportunity] = []
    for g in final_games:
        p, m = _process_game(g["gamePk"], target_date, verbose=verbose)
        all_pitches.extend(p)
        all_missed.extend(m)
    return all_pitches, all_missed


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_smoke(game_pk: int) -> None:
    """
    Smoke test: fetch one game and print raw parsed pitch data.
    Designed for development/verification — shows challenges and a sample
    of missed opportunities with ABS zone details.
    """
    print(f"=== Smoke test: gamePk {game_pk} ===\n")
    feed = fetch_game_feed(game_pk)
    pitches, missed = parse_game(feed)

    challenges = [p for p in pitches if p.has_review]
    print(f"Total takes parsed       : {len(pitches)}")
    print(f"Challenged pitches       : {len(challenges)}")
    print(f"Missed opportunities     : {len(missed)}")
    print()

    if challenges:
        print("=== CHALLENGES ===")
        for p in challenges:
            outcome = "OVERTURNED" if p.is_overturned else "upheld"
            if p.in_abs_zone is not None:
                abs_label = "IN zone" if p.in_abs_zone else "OUT of zone"
            else:
                abs_label = "no coords"
            ht = f"{p.batter_height_ft:.2f}ft" if p.batter_height_ft else "ht=?"
            half = "T" if p.half_inning == "top" else "B"
            print(
                f"  [{p.inning}{half}] {p.batter_name} vs {p.pitcher_name} | "
                f"{p.call_description} ({p.call_code}) -> {outcome} | "
                f"pX={p.px:.3f} pZ={p.pz:.3f} | ABS: {abs_label} | "
                f"zone {p.abs_zone_bottom:.3f}-{p.abs_zone_top:.3f} ({ht})"
            )
        print()

    if missed:
        print(f"=== MISSED OPPORTUNITIES (showing up to 15 of {len(missed)}) ===")
        for mo in missed[:15]:
            p = mo.pitch
            half = "T" if p.half_inning == "top" else "B"
            zone_str = (
                f"{p.abs_zone_bottom:.3f}-{p.abs_zone_top:.3f}"
                if p.abs_zone_bottom and p.abs_zone_top else "?"
            )
            print(
                f"  [{p.inning}{half}] {p.batter_name} vs {p.pitcher_name} | "
                f"Ump: {mo.umpire_call} -> ABS: {mo.abs_verdict} | "
                f"pX={mo.px:.3f} pZ={mo.pz:.3f} | zone {zone_str} | "
                f"{mo.opportunity_type}"
            )
        print()

    print("=== SAMPLE TAKES (first 5) ===")
    for p in pitches[:5]:
        zone_str = (
            f"{p.abs_zone_bottom:.3f}-{p.abs_zone_top:.3f}"
            if p.abs_zone_bottom is not None and p.abs_zone_top is not None else "N/A"
        )
        ht = f"{p.batter_height_ft:.2f}ft" if p.batter_height_ft else "ht=?"
        print(
            f"  {p.batter_name} vs {p.pitcher_name} | "
            f"{p.call_description} | pX={p.px} pZ={p.pz} | "
            f"ABS zone: {zone_str} ({ht}) | in zone: {p.in_abs_zone}"
        )


def cmd_analyze(
    pitches: list[Pitch],
    missed: list[MissedOpportunity],
    fmt: str,
) -> None:
    if not pitches:
        print("No data found.", file=sys.stderr)
        return

    print("=== CHALLENGES ===")
    _print_df(analyze_challenges(pitches), fmt)

    print("\n=== BATTER STATS ===")
    _print_df(analyze_batters(pitches, missed), fmt)

    print("\n=== PITCHER / DEFENSE STATS ===")
    _print_df(analyze_defense(pitches, missed), fmt)

    print("\n=== UMPIRE ACCURACY (aggregate) ===")
    _print_df(analyze_umpires(pitches), fmt)

    print("\n=== MISSED OPPORTUNITIES ===")
    _print_df(analyze_missed_opportunities(missed), fmt)

    print(f"\nTotal takes: {len(pitches)} | "
          f"Challenges: {sum(1 for p in pitches if p.has_review)} | "
          f"Missed opps: {len(missed)}")


def cmd_games(game_date: str) -> None:
    """Print a JSON array of games for a given date."""
    import json
    games = fetch_games_for_date(game_date)
    print(json.dumps(games, indent=2))


def cmd_takes(game_pk: int) -> None:
    """
    Fetch a game and print every take as a JSON array.

    Each take includes: inning, half_inning, at_bat_index, pitch_number,
    batter_name, pitcher_name, catcher_name, umpire_name, px, pz,
    call_result, abs_result, in_abs_zone, challenge_outcome.

    challenge_outcome values:
      "successful" — challenged and overturned
      "failed"     — challenged and upheld
      "missed"     — not challenged but ABS says the call was wrong
      "none"       — not challenged and ABS agrees with the call (or no coords)
    """
    import json

    feed = fetch_game_feed(game_pk)
    pitches, missed_ops = parse_game(feed)
    hp_umpire = extract_hp_umpire(feed)
    catchers = extract_catchers(feed)

    # Build lookup: (at_bat_index, pitch_number) → True for missed opportunities
    missed_keys = {(mo.pitch.at_bat_index, mo.pitch.pitch_number) for mo in missed_ops}

    takes = []
    for p in pitches:
        # top half → home team defends (home catcher); bottom → away team defends
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

        takes.append({
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
            "in_abs_zone": p.in_abs_zone,
            "challenge_outcome": challenge_outcome,
        })

    print(json.dumps({"game_pk": game_pk, "takes": takes}, indent=2))


def cmd_plot(game_pk: int, output_path: str) -> None:
    """
    Generate a self-contained HTML strike zone plot for a game.
    Takes data is embedded as JSON — open the file directly in any browser.

    Dot colors:
      Green  = successful challenge (overturned)
      Red    = failed challenge (upheld)
      Yellow = missed opportunity (wrong call, no challenge)
      Gray   = correct call / no challenge
    Dot stroke: white outline = Called Strike, dark = Called Ball.
    """
    import json

    feed = fetch_game_feed(game_pk)
    pitches, missed_ops = parse_game(feed)
    hp_umpire = extract_hp_umpire(feed)
    catchers = extract_catchers(feed)

    missed_keys = {(mo.pitch.at_bat_index, mo.pitch.pitch_number) for mo in missed_ops}

    game_data = feed.get("gameData", {})
    teams = game_data.get("teams", {})
    away_name = teams.get("away", {}).get("name", "Away")
    home_name = teams.get("home", {}).get("name", "Home")
    game_date = game_data.get("datetime", {}).get("officialDate", "")
    title = f"ABS Zone Plot \u2014 {away_name} @ {home_name}  ({game_date})"
    away_abbrev = teams.get("away", {}).get("abbreviation", away_name)
    home_abbrev = teams.get("home", {}).get("abbreviation", home_name)

    takes = []
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

        takes.append({
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

    payload = json.dumps({"game_pk": game_pk, "title": title,
                          "away_team": away_abbrev, "home_team": home_abbrev,
                          "takes": takes})
    html = _HTML_TEMPLATE.replace("__DATA__", payload)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    non_trivial = sum(1 for t in takes if t["challenge_outcome"] != "none")
    print(f"Wrote {output_path}  ({len(takes)} takes, {non_trivial} challenged/missed)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="abs_tracker",
        description="MLB ABS (Automated Ball-Strike) Challenge Tracker",
    )
    sub = p.add_subparsers(dest="command")

    # games — structured game list for a date (JSON)
    games_cmd = sub.add_parser("games", help="List all games for a date as JSON")
    games_cmd.add_argument("date", help="YYYY-MM-DD")

    # takes — enriched take list for a game (JSON)
    takes_cmd = sub.add_parser("takes", help="List all take pitches for a game as JSON")
    takes_cmd.add_argument("game_pk", type=int)

    # plot — self-contained HTML strike zone visualization
    plot_cmd = sub.add_parser("plot", help="Generate HTML strike zone plot for a game")
    plot_cmd.add_argument("game_pk", type=int)
    plot_cmd.add_argument(
        "--output", default=None, metavar="FILE",
        help="Output HTML path (default: abs_plot_<game_pk>.html)",
    )

    # smoke
    smoke = sub.add_parser("smoke", help="Print raw parsed data for one game (dev/debug)")
    smoke.add_argument(
        "game_pk", type=int, nargs="?", default=823812,
        help="gamePk to inspect (default: 823812 — 2026 Opening Day)",
    )

    # game
    game = sub.add_parser("game", help="Analyze a single game by gamePk")
    game.add_argument("game_pk", type=int)
    game.add_argument("--output", choices=["table", "json", "csv"], default="table")
    game.add_argument("-v", "--verbose", action="store_true")

    # date
    date_cmd = sub.add_parser("date", help="Analyze all completed games on a date")
    date_cmd.add_argument("date", help="YYYY-MM-DD")
    date_cmd.add_argument("--output", choices=["table", "json", "csv"], default="table")
    date_cmd.add_argument("-v", "--verbose", action="store_true")

    # range
    rng = sub.add_parser("range", help="Analyze all completed games across a date range")
    rng.add_argument("start_date", help="YYYY-MM-DD")
    rng.add_argument("end_date", help="YYYY-MM-DD")
    rng.add_argument("--output", choices=["table", "json", "csv"], default="table")
    rng.add_argument("-v", "--verbose", action="store_true")

    # sync — fetch all missing 2026 games into the DB
    sync_cmd = sub.add_parser(
        "sync",
        help="Fetch all missing 2026 season games into the database (run daily)",
    )
    sync_cmd.add_argument(
        "--db", default="abs_tracker.db", metavar="PATH",
        help="SQLite database path (default: abs_tracker.db)",
    )
    sync_cmd.add_argument(
        "--from", dest="start_date", default=OPENING_DAY_2026, metavar="DATE",
        help=f"Start date (default: {OPENING_DAY_2026} — 2026 Opening Day)",
    )
    sync_cmd.add_argument(
        "--to", dest="end_date", default=None, metavar="DATE",
        help="End date inclusive (default: today)",
    )
    sync_cmd.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be fetched without writing anything",
    )
    sync_cmd.add_argument("-v", "--verbose", action="store_true")

    # report — analyze data already stored in the DB
    report_cmd = sub.add_parser(
        "report",
        help="Run analysis reports against the local database",
    )
    report_cmd.add_argument(
        "--db", default="abs_tracker.db", metavar="PATH",
        help="SQLite database path (default: abs_tracker.db)",
    )
    report_cmd.add_argument(
        "--output", choices=["table", "json", "csv"], default="table",
    )
    report_sub = report_cmd.add_subparsers(dest="report_scope")

    r_date = report_sub.add_parser("date", help="Report for a single date")
    r_date.add_argument("date", help="YYYY-MM-DD")

    r_range = report_sub.add_parser("range", help="Report for a date range")
    r_range.add_argument("start_date", help="YYYY-MM-DD")
    r_range.add_argument("end_date", help="YYYY-MM-DD")

    r_game = report_sub.add_parser("game", help="Report for a single game")
    r_game.add_argument("game_pk", type=int)

    r_season = report_sub.add_parser("season", help="Report for the full stored 2026 season")

    # serve — start the Flask web UI
    serve_cmd = sub.add_parser("serve", help="Start the web UI (Flask dev server)")
    serve_cmd.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_cmd.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")

    # status — show DB contents summary
    status_cmd = sub.add_parser("status", help="Show database summary counts")
    status_cmd.add_argument(
        "--db", default="abs_tracker.db", metavar="PATH",
        help="SQLite database path (default: abs_tracker.db)",
    )

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # --- games ---
    if args.command == "games":
        cmd_games(args.date)
        return

    # --- takes ---
    if args.command == "takes":
        cmd_takes(args.game_pk)
        return

    # --- plot ---
    if args.command == "plot":
        out = args.output or f"abs_plot_{args.game_pk}.html"
        cmd_plot(args.game_pk, out)
        return

    # --- serve ---
    if args.command == "serve":
        from .server import run as _run_server
        print(f"Starting ABS Tracker web UI at http://{args.host}:{args.port}/")
        _run_server(host=args.host, port=args.port)
        return

    # --- smoke (no DB) ---
    if args.command == "smoke" or args.command is None:
        cmd_smoke(getattr(args, "game_pk", 823812))
        return

    # --- sync ---
    if args.command == "sync":
        sync_season(
            db_path=args.db,
            start_date=args.start_date,
            end_date=args.end_date,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        return

    # --- status ---
    if args.command == "status":
        conn = init_db(args.db)
        info = db_summary(conn)
        conn.close()
        print(f"Database : {args.db}")
        print(f"Games    : {info['games']}")
        print(f"Pitches  : {info['pitches']}")
        print(f"Challenges: {info['challenges']}")
        print(f"Heights cached: {info['player_heights_cached']}")
        if info["earliest_date"]:
            print(f"Date range: {info['earliest_date']} -> {info['latest_date']}")
        return

    # --- report (from DB) ---
    if args.command == "report":
        conn = init_db(args.db)
        scope = getattr(args, "report_scope", None)

        if scope == "date":
            pitches = load_pitches(conn, game_date=args.date)
        elif scope == "range":
            pitches = load_pitches(conn, start_date=args.start_date, end_date=args.end_date)
        elif scope == "game":
            pitches = load_pitches(conn, game_pk=args.game_pk)
        elif scope == "season" or scope is None:
            pitches = load_pitches(conn)
        else:
            pitches = []

        conn.close()
        missed = derive_missed_ops(pitches)
        cmd_analyze(pitches, missed, args.output)
        return

    # --- live fetch commands (no DB) ---
    fmt = getattr(args, "output", "table")
    verbose = getattr(args, "verbose", False)
    all_pitches: list[Pitch] = []
    all_missed: list[MissedOpportunity] = []

    if args.command == "game":
        all_pitches, all_missed = _process_game(args.game_pk, verbose=verbose)

    elif args.command == "date":
        all_pitches, all_missed = _process_date(args.date, verbose=verbose)

    elif args.command == "range":
        current = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        while current <= end:
            p, m = _process_date(current.isoformat(), verbose=verbose)
            all_pitches.extend(p)
            all_missed.extend(m)
            current += timedelta(days=1)

    cmd_analyze(all_pitches, all_missed, fmt)


if __name__ == "__main__":
    main()
