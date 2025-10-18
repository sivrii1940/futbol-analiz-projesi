# analysis_logic.py

import math
from typing import Dict, Any, List
import streamlit as st
import api_utils

@st.cache_data(ttl=86400)
def get_dynamic_league_average(api_key: str, base_url: str, league_info: Dict, default_avg: float) -> float:
    params = {'league': league_info['league_id'], 'season': league_info['season'], 'status': 'FT', 'last': 100}
    fixtures, _ = api_utils.make_api_request(api_key, base_url, "fixtures", params)
    if not fixtures: return default_avg
    goals, count = 0, 0
    for f in fixtures:
        score = f['score']['fulltime']
        if score['home'] is not None and score['away'] is not None:
            goals += score['home'] + score['away']; count += 1
    return (goals / count) if count > 0 else default_avg

@st.cache_data(ttl=86400)
def calculate_general_stats(api_key: str, base_url: str, team_id: int, limit: int) -> Dict:
    matches, _ = api_utils.make_api_request(api_key, base_url, "fixtures", {'team': team_id, 'last': limit, 'status': 'FT'})
    if not matches: return {'home': {}, 'away': {}}
    home, away = [dict.fromkeys(['count','goals','conceded','wins','draws','losses', 'corners', 'yc'], 0) for _ in range(2)]
    for m in matches:
        is_home = m['teams']['home']['id'] == team_id; stats = home if is_home else away
        s = m['score']['fulltime']
        if s['home'] is None: continue
        stats['count'] += 1
        if is_home:
            stats['goals'] += s['home']; stats['conceded'] += s['away']
            if s['home'] > s['away']: stats['wins'] += 1
            elif s['away'] > s['home']: stats['losses'] += 1
            else: stats['draws'] += 1
        else:
            stats['goals'] += s['away']; stats['conceded'] += s['home']
            if s['away'] > s['home']: stats['wins'] += 1
            elif s['home'] > s['away']: stats['losses'] += 1
            else: stats['draws'] += 1
        detail_stats, _ = api_utils.get_fixture_statistics(api_key, base_url, m['fixture']['id'])
        if detail_stats:
            team_stats = next((ts for ts in detail_stats if ts['team']['id'] == team_id), None)
            if team_stats:
                for stat in team_stats['statistics']:
                    value = stat['value']
                    if value:
                        if stat['type'] == 'Corner Kicks': stats['corners'] += int(value)
                        if stat['type'] == 'Yellow Cards': stats['yc'] += int(value)
    def get_avg(s):
        c = s.get('count', 0)
        if c == 0: return {}
        return {'Ort. Gol ATILAN': s['goals']/c, 'Ort. Gol YENEN': s['conceded']/c,
                'Ort. Korner': s['corners']/c, 'Ort. Sarı Kart': s['yc']/c,
                'Istikrar_Puani': round(((s['wins'] + 0.5*s['draws'])/c)*100, 1)}
    return {'home': get_avg(home), 'away': get_avg(away)}

def poisson_pmf(l, k):
    if l <= 0 or k < 0: return 0.0
    try: return (l**k) * math.exp(-l) / math.factorial(k)
    except (ValueError, OverflowError): return 0.0

def calculate_match_probabilities(s_a, s_b):
    p={'u25':0.0,'kgv':0.0,'w_a':0.0,'d':0.0}
    for i in range(7):
        for j in range(7):
            prob = poisson_pmf(s_a,i)*poisson_pmf(s_b,j)
            if i+j > 2.5: p['u25'] += prob
            if i>0 and j>0: p['kgv'] += prob
            if i>j: p['w_a'] += prob
            elif i==j: p['d'] += prob
    return {'ust_2.5':round(p['u25']*100,1),'alt_2.5':round((1-p['u25'])*100,1),
            'kg_var':round(p['kgv']*100,1),'kg_yok':round((1-p['kgv'])*100,1),
            'win_a':round(p['w_a']*100,1),'win_b':round((1-p['w_a']-p['d'])*100,1),'draw':round(p['d']*100,1)}

def get_key_players(player_stats: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    if not player_stats: return {'top_scorer_ids': [], 'most_minutes_ids': []}
    max_goals = 0; top_scorers = []
    for p in player_stats:
        goals = p['statistics'][0]['goals']['total'] or 0
        if goals > max_goals:
            max_goals = goals; top_scorers = [p['player']['id']]
        elif goals == max_goals and max_goals > 0:
            top_scorers.append(p['player']['id'])
    player_stats.sort(key=lambda p: p['statistics'][0]['games']['minutes'] or 0, reverse=True)
    most_minutes = [p['player']['id'] for p in player_stats[:4]]
    return {'top_scorer_ids': top_scorers, 'most_minutes_ids': most_minutes}

@st.cache_data(ttl=86400)
def run_core_analysis(api_key, base_url, id_a, id_b, fixture_id, league_info, model_params, form_limit, default_avg):
    avg_goals = get_dynamic_league_average(api_key, base_url, league_info, default_avg)
    stats_a = calculate_general_stats(api_key, base_url, id_a, form_limit)
    stats_b = calculate_general_stats(api_key, base_url, id_b, form_limit)
    injuries, _ = api_utils.get_fixture_injuries(api_key, base_url, fixture_id)
    injured_ids = {p['player']['id'] for p in injuries} if injuries else set()
    p_stats_a, _ = api_utils.get_squad_player_stats(api_key, base_url, id_a, league_info['season'])
    p_stats_b, _ = api_utils.get_squad_player_stats(api_key, base_url, id_b, league_info['season'])
    key_a = get_key_players(p_stats_a) if p_stats_a else {}
    key_b = get_key_players(p_stats_b) if p_stats_b else {}
    injury_impact, home_advantage, max_goals = model_params['injury_impact'], model_params['home_adv'], model_params['max_goals']
    att_mult_a = injury_impact if any(p in injured_ids for p in key_a.get('top_scorer_ids', [])) else 1.0
    def_mult_a = 1/injury_impact if any(p in injured_ids for p in key_a.get('most_minutes_ids', [])) else 1.0
    att_mult_b = injury_impact if any(p in injured_ids for p in key_b.get('top_scorer_ids', [])) else 1.0
    def_mult_b = 1/injury_impact if any(p in injured_ids for p in key_b.get('most_minutes_ids', [])) else 1.0
    home_att = max(stats_a.get('home',{}).get('Ort. Gol ATILAN',0.1), 0.1)
    away_def = max(stats_b.get('away',{}).get('Ort. Gol YENEN',0.1), 0.1)
    away_att = max(stats_b.get('away',{}).get('Ort. Gol ATILAN',0.1), 0.1)
    home_def = max(stats_a.get('home',{}).get('Ort. Gol YENEN',0.1), 0.1)
    lambda_a = ((home_att*att_mult_a)/avg_goals)*((away_def*def_mult_b)/avg_goals)*avg_goals*home_advantage
    lambda_b = ((away_att*att_mult_b)/avg_goals)*((home_def*def_mult_a)/avg_goals)*avg_goals
    score_a, score_b = min(lambda_a, max_goals), min(lambda_b, max_goals)
    probs = calculate_match_probabilities(score_a, score_b)
    prob_list = sorted([probs['win_a'], probs['win_b'], probs['draw']], reverse=True)
    diff = round(prob_list[0]-prob_list[1],1)
    stability_a = stats_a.get('home',{}).get('Istikrar_Puani',0); stability_b = stats_b.get('away',{}).get('Istikrar_Puani',0)
    avg_stab = (stability_a+stability_b)/2 if stability_a and stability_b else 0
    confidence = round((diff*avg_stab)/100, 1)
    return {'score_a':score_a, 'score_b':score_b, 'probs':probs, 'confidence':confidence, 'diff':diff,
            'params': {'avg_goals': avg_goals, 'home_att': home_att, 'away_def': away_def, 'away_att': away_att, 'home_def': home_def, 
                       'att_mult_a': att_mult_a, 'def_mult_a': def_mult_a, 'att_mult_b': att_mult_b, 'def_mult_b': def_mult_b},
            'stats': {'a': stats_a, 'b': stats_b}}