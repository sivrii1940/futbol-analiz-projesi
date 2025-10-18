import requests
import json
import math
from typing import Optional, Dict, Any, List, Union, Tuple
from datetime import datetime, date
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# --- KONFİGÜRASYON ---
try:
    API_KEY = st.secrets["API_KEY"]
except (FileNotFoundError, KeyError):
    st.error("⚠️ Lütfen `.streamlit/secrets.toml` dosyasını oluşturun ve API_KEY'inizi ekleyin.")
    st.stop()

BASE_HOST = "v3.football.api-sports.io"
BASE_URL = f"https://{BASE_HOST}"

INTERESTING_LEAGUES = {
    203: "🇹🇷 Süper Lig", 39: "🇬🇧 Premier League", 140: "🇪🇸 La Liga",
    135: "🇮🇹 Serie A", 78: "🇩🇪 Bundesliga", 61: "🇫🇷 Ligue 1",
    88: "🇳🇱 Eredivisie", 94: "🇵🇹 Primeira Liga",
    204: "🇹🇷 TFF 1. Lig", 40: "🇬🇧 Championship", 141: "🇪🇸 La Liga 2",
    136: "🇮🇹 Serie B", 79: "🇩🇪 2. Bundesliga", 62: "🇫🇷 Ligue 2",
    89: "🇳🇱 Eerste Divisie", 95: "🇵🇹 Liga Portugal 2"
}

# Varsayılan değerler, artık slider'lar için kullanılacak
FORM_MATCH_LIMIT = 15
H2H_MATCH_LIMIT = 10
LIG_ORTALAMA_GOL = 1.35
DEFAULT_MAX_GOAL_EXPECTANCY = 3.0
DEFAULT_HOME_ADVANTAGE_MULTIPLIER = 1.15
DEFAULT_KEY_PLAYER_IMPACT_MULTIPLIER = 0.80

# --- TEMEL API VE YARDIMCI FONKSİYONLAR ---

@st.cache_data(ttl=3600)
def make_api_request(endpoint: str, params: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': BASE_HOST}
    url = f"{BASE_URL}/{endpoint}"
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        api_data = response.json()
        if api_data.get('errors') and (isinstance(api_data['errors'], dict) and api_data['errors']) or (isinstance(api_data['errors'], list) and len(api_data['errors']) > 0):
            error_detail = str(api_data['errors'])
            return None, f"API Hatası: {error_detail}"
        return api_data.get('response', []), None
    except requests.exceptions.HTTPError as http_err:
        return None, f"HTTP Hatası: {http_err}. API Anahtarınızı veya aboneliğinizi kontrol edin."
    except requests.exceptions.RequestException as req_err:
        return None, f"Bağlantı Hatası: {req_err}"

@st.cache_data(ttl=86400) 
def get_fixture_injuries(fixture_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request("injuries", {'fixture': fixture_id})

@st.cache_data(ttl=86400)
def get_squad_player_stats(team_id: int, season: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request("players", {'team': team_id, 'season': season})

@st.cache_data(ttl=86400)
def get_league_standings(league_id: int, season: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    response, error = make_api_request("standings", {'league': league_id, 'season': season})
    if error: return None, error
    if response and response[0]['league']['standings']:
        return response[0]['league']['standings'][0], None
    return None, None

@st.cache_data(ttl=86400)
def get_h2h_matches(team_a_id: int, team_b_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request("fixtures/headtohead", {'h2h': f"{team_a_id}-{team_b_id}", 'last': H2H_MATCH_LIMIT})

@st.cache_data(ttl=86400)
def get_fixture_statistics(fixture_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request("fixtures/statistics", {'fixture': fixture_id})

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

def get_team_id(team_input: str) -> Optional[Dict[str, Any]]:
    response, error = make_api_request("teams", {'search': team_input} if not team_input.isdigit() else {'id': team_input})
    if error:
        st.sidebar.error(error); return None
    if response:
        team = response[0]['team']
        st.sidebar.success(f"✅ Bulunan: {team['name']} ({team['id']})")
        return {'id': team['id'], 'name': team['name']}
    st.sidebar.error(f"❌ Takım bulunamadı: '{team_input}'"); return None

@st.cache_data(ttl=86400)
def get_team_league_info(team_id: int) -> Optional[Dict[str, Union[int, str]]]:
    response, error = make_api_request("leagues", {'team': team_id, 'current': 'true'})
    if error or not response: return None
    league, seasons = response[0]['league'], response[0]['seasons']
    season = next((s['year'] for s in seasons if s['current']), seasons[-1]['year'])
    return {'league_id': league['id'], 'season': season}

def find_upcoming_fixture(team_a_id: int, team_b_id: int, season: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    fixtures, error = make_api_request("fixtures", {'team': team_a_id, 'season': season, 'status': 'NS'})
    if error: return None, error
    if fixtures:
        for f in fixtures:
            if f['teams']['home']['id'] == team_b_id or f['teams']['away']['id'] == team_b_id:
                return f, None
    return None, None

@st.cache_data(ttl=86400)
def get_dynamic_league_average(league_info: Dict[str, Union[int, str]]) -> float:
    params = {'league': league_info['league_id'], 'season': league_info['season'], 'status': 'FT', 'last': 100}
    fixtures, error = make_api_request("fixtures", params)
    if error or not fixtures: return LIG_ORTALAMA_GOL
    goals, count = 0, 0
    for f in fixtures:
        score = f['score']['fulltime']
        if score['home'] is not None and score['away'] is not None:
            goals += score['home'] + score['away']; count += 1
    return (goals / count) if count > 0 else LIG_ORTALAMA_GOL

@st.cache_data(ttl=86400)
def calculate_general_stats(team_id: int) -> Dict[str, Dict[str, float]]:
    matches, error = make_api_request("fixtures", {'team': team_id, 'last': FORM_MATCH_LIMIT, 'status': 'FT'})
    if error or not matches: return {'home': {}, 'away': {}}
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
        detail_stats, _ = get_fixture_statistics(m['fixture']['id'])
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

def get_todays_fixtures(selected_league_ids: List[int]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    all_fixtures, error_messages = [], []
    today_str = date.today().strftime('%Y-%m-%d')
    season = date.today().year
    for league_id in selected_league_ids:
        params = {'date': today_str, 'status': 'NS', 'league': league_id, 'season': season}
        response, error = make_api_request("fixtures", params)
        if error:
            error_messages.append(f"Lig ID {league_id}: {error}")
            continue
        if response:
            for f in response:
                try:
                    all_fixtures.append({'match_id': f['fixture']['id'], 'time': datetime.fromtimestamp(f['fixture']['timestamp']).strftime('%H:%M'),
                                         'home_name': f['teams']['home']['name'], 'home_id': f['teams']['home']['id'],
                                         'away_name': f['teams']['away']['name'], 'away_id': f['teams']['away']['id'],
                                         'league_name': f['league']['name']})
                except (KeyError, TypeError): continue
    final_error = "\n".join(error_messages) if error_messages else None
    return sorted(all_fixtures, key=lambda x: (x['league_name'], x['time'])), final_error

# --- ANA ANALİZ FONKSİYONLARI ---

@st.cache_data(ttl=86400)
def run_core_analysis(id_a, id_b, fixture_id, league_info, model_params: Dict):
    avg_goals = get_dynamic_league_average(league_info)
    stats_a, stats_b = calculate_general_stats(id_a), calculate_general_stats(id_b)
    injuries, _ = get_fixture_injuries(fixture_id)
    injured_ids = {p['player']['id'] for p in injuries} if injuries else set()
    p_stats_a, _ = get_squad_player_stats(id_a, league_info['season'])
    p_stats_b, _ = get_squad_player_stats(id_b, league_info['season'])
    key_a, key_b = get_key_players(p_stats_a), get_key_players(p_stats_b)

    injury_impact = model_params['injury_impact']
    home_advantage = model_params['home_adv']
    max_goals = model_params['max_goals']

    att_mult_a = injury_impact if any(p in injured_ids for p in key_a['top_scorer_ids']) else 1.0
    def_mult_a = 1/injury_impact if any(p in injured_ids for p in key_a['most_minutes_ids']) else 1.0
    att_mult_b = injury_impact if any(p in injured_ids for p in key_b['top_scorer_ids']) else 1.0
    def_mult_b = 1/injury_impact if any(p in injured_ids for p in key_b['most_minutes_ids']) else 1.0
    
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

def analyze_fixture_summary(fixture, model_params: Dict):
    try:
        id_a, name_a, id_b, name_b = fixture['home_id'],fixture['home_name'],fixture['away_id'],fixture['away_name']
        league_info = get_team_league_info(id_a)
        if not league_info: return None
        analysis = run_core_analysis(id_a, id_b, fixture['match_id'], league_info, model_params)
        if not analysis: return None
        probs, stats = analysis['probs'], analysis['stats']
        max_prob = max(probs, key=lambda k: probs[k] if 'win' in k or 'draw' in k else -1)
        decision = f"{name_a} K." if max_prob=='win_a' else f"{name_b} K." if max_prob=='win_b' else "Ber."
        total_corners = stats['a'].get('home', {}).get('Ort. Korner', 0) + stats['b'].get('away', {}).get('Ort. Korner', 0)
        total_cards = stats['a'].get('home', {}).get('Ort. Sarı Kart', 0) + stats['b'].get('away', {}).get('Ort. Sarı Kart', 0)

        return {"Saat":fixture['time'],"Lig":fixture['league_name'],"Ev Sahibi":name_a,"Deplasman":name_b,
                "Tahmin":decision,"AI Güven Puanı":analysis['confidence'],"2.5 ÜST (%)":probs['ust_2.5'],
                "KG VAR (%)":probs['kg_var'], "Ort. Korner": total_corners, "Ort. Sarı Kart": total_cards,
                "home_id":id_a,"away_id":id_b,"fixture_id":fixture['match_id']}
    except Exception: return None

def analyze_and_display(team_a_data, team_b_data, fixture_id, model_params: Dict):
    id_a,name_a,id_b,name_b = team_a_data['id'],team_a_data['name'],team_b_data['id'],team_b_data['name']
    st.header(f"⚽ {name_a} vs {name_b} Detaylı Analiz")
    league_info = get_team_league_info(id_a)
    if not league_info: st.error("Lig bilgisi alınamadı."); return
    analysis = run_core_analysis(id_a, id_b, fixture_id, league_info, model_params)
    if not analysis: st.error("Analiz verisi oluşturulamadı."); return
    params, stats = analysis['params'], analysis['stats']
    values_list = list(analysis.values())
    score_a, score_b, probs, confidence, diff = values_list[:5]
    max_prob = max(probs, key=lambda k: probs[k] if 'win' in k or 'draw' in k else -1)
    decision = f"{name_a} Kazanır" if max_prob=='win_a' else f"{name_b} Kazanır" if max_prob=='win_b' else "Beraberlik"
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🎯 Tahmin Özeti", "📈 Takım İstatistikleri", "🚑 Sakat ve Cezalılar", "⚙️ Analiz Parametreleri", "📊 Puan Durumu", "⚔️ Kafa Kafaya (H2H)"])
    with tab1:
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Ev S. Gol Beklentisi", f"{score_a:.2f}"); c2.metric("Dep. Gol Beklentisi", f"{score_b:.2f}")
        c3.metric("Olasılık Farkı", f"{diff:.1f}%"); c4.metric("AI Güven Puanı", f"**{confidence:.1f}**")
        st.info(f"**Ana Karar (1X2):** {decision}")
        st.markdown("---"); st.subheader("📊 Maç Sonucu Olasılıkları")
        col_1x2, col_gol = st.columns([0.6, 0.4])
        with col_1x2:
            st.markdown("##### 🏆 Maç Sonu (1X2)"); chart_data = pd.DataFrame({'Olasılık (%)': {f'{name_a} K.': probs['win_a'], 'Ber.': probs['draw'], f'{name_b} K.': probs['win_b']}})
            st.bar_chart(chart_data)
        with col_gol:
            st.markdown("##### ⚽ Gol Piyasaları"); gol_data = pd.DataFrame({'Kategori': ['2.5 ÜST', '2.5 ALT', 'KG VAR', 'KG YOK'], 'İhtimal (%)': [probs['ust_2.5'], probs['alt_2.5'], probs['kg_var'], probs['kg_yok']]}).set_index('Kategori')
            st.dataframe(gol_data.T, use_container_width=True)
    with tab2:
        st.subheader("📊 İstatistiksel Karşılaştırma Grafiği (Radar)")
        stats_a_home = stats['a'].get('home', {}); stats_b_away = stats['b'].get('away', {})
        categories = ['Atılan Gol', 'Yenen Gol', 'Korner', 'Sarı Kart', 'İstikrar']
        values_a = [stats_a_home.get('Ort. Gol ATILAN', 0), stats_a_home.get('Ort. Gol YENEN', 0), stats_a_home.get('Ort. Korner', 0), stats_a_home.get('Ort. Sarı Kart', 0), stats_a_home.get('Istikrar_Puani', 0)]
        values_b = [stats_b_away.get('Ort. Gol ATILAN', 0), stats_b_away.get('Ort. Gol YENEN', 0), stats_b_away.get('Ort. Korner', 0), stats_b_away.get('Ort. Sarı Kart', 0), stats_b_away.get('Istikrar_Puani', 0)]
        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(r=values_a, theta=categories, fill='toself', name=f'{name_a} (Ev)'))
        fig.add_trace(go.Scatterpolar(r=values_b, theta=categories, fill='toself', name=f'{name_b} (Dep)'))
        fig.update_layout(polar=dict(radialaxis=dict(visible=True)), showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        st.info("Not: 'Yenen Gol' ve 'Sarı Kart' metriklerinde daha düşük değerler daha iyidir.")
        st.markdown("---")
        st.subheader("📈 Genel Form İstatistikleri (Son 15 Maç)")
        def format_stats(stat_dict):
            return {k.replace('_', ' ').title(): f"{v:.2f}" for k, v in stat_dict.items()} if stat_dict else {"Veri Yok": "-"}
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**{name_a}**"); st.write("**Ev Sahibi Olarak:**"); st.dataframe(pd.Series(format_stats(stats['a'].get('home'))), use_container_width=True)
            st.write("**Deplasmanda Olarak:**"); st.dataframe(pd.Series(format_stats(stats['a'].get('away'))), use_container_width=True)
        with c2:
            st.markdown(f"**{name_b}**"); st.write("**Ev Sahibi Olarak:**"); st.dataframe(pd.Series(format_stats(stats['b'].get('home'))), use_container_width=True)
            st.write("**Deplasmanda Olarak:**"); st.dataframe(pd.Series(format_stats(stats['b'].get('away'))), use_container_width=True)
    with tab3:
        st.subheader("❗ Maç Öncesi Önemli Eksikler"); injuries, error = get_fixture_injuries(fixture_id)
        if error: st.warning(f"Sakatlık verisi çekilemedi: {error}")
        elif not injuries: st.success("✅ Takımlarda önemli bir eksik bildirilmedi.")
        else:
            team_a_inj=[p for p in injuries if p['team']['id']==id_a]; team_b_inj=[p for p in injuries if p['team']['id']==id_b]
            c1,c2=st.columns(2)
            with c1:
                st.markdown(f"**{name_a}**")
                if team_a_inj:
                    for p in team_a_inj: st.warning(f"**{p['player']['name']}** - {p['player']['reason']}")
                else: st.write("Eksik yok.")
            with c2:
                st.markdown(f"**{name_b}**")
                if team_b_inj:
                    for p in team_b_inj: st.warning(f"**{p['player']['name']}** - {p['player']['reason']}")
                else: st.write("Eksik yok.")
    with tab4:
        st.subheader("Modelin Kullandığı Parametreler"); c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**{name_a} (Ev Sahibi)**"); st.metric("Ham Hücum Gücü", f"{params['home_att']:.2f}"); st.metric("Ham Savunma Gücü", f"{params['home_def']:.2f}")
            st.metric("Hücum Etki Katsayısı", f"{params['att_mult_a']:.2f}"); st.metric("Savunma Etki Katsayısı", f"x{params['def_mult_a']:.2f}")
        with c2:
            st.markdown(f"**{name_b} (Deplasman)**"); st.metric("Ham Hücum Gücü", f"{params['away_att']:.2f}"); st.metric("Ham Savunma Gücü", f"{params['away_def']:.2f}")
            st.metric("Hücum Etki Katsayısı", f"{params['att_mult_b']:.2f}"); st.metric("Savunma Etki Katsayısı", f"x{params['def_mult_b']:.2f}")
        st.metric("Lig Ortalaması", f"{params['avg_goals']:.2f} Gol/Maç")
    with tab5:
        st.subheader("🏆 Lig Puan Durumu"); standings_data, error = get_league_standings(league_info['league_id'], league_info['season'])
        if error: st.warning(f"Puan durumu çekilemedi: {error}")
        elif standings_data:
            df = pd.DataFrame(standings_data)[['rank', 'team', 'points', 'goalsDiff', 'form']].rename(columns={'rank':'Sıra', 'team':'Takım', 'points':'Puan', 'goalsDiff':'Averaj', 'form':'Form'})
            df['Takım'] = df['Takım'].apply(lambda x: x['name'])
            def highlight(row):
                if row.Takım == name_a: return ['background-color: lightblue']*len(row)
                if row.Takım == name_b: return ['background-color: lightcoral']*len(row)
                return ['']*len(row)
            st.dataframe(df.style.apply(highlight, axis=1), hide_index=True, use_container_width=True)
        else: st.warning("Bu lig için puan durumu verisi bulunamadı.")
    with tab6:
        st.subheader(f"⚔️ {name_a} vs {name_b}: Geçmiş Karşılaşmalar"); h2h_matches, error = get_h2h_matches(id_a, id_b)
        if error: st.warning(f"H2H verisi çekilemedi: {error}")
        elif h2h_matches:
            w_a,w_b,d,g_a,g_b = 0,0,0,0,0
            for m in h2h_matches:
                s=m['score']['fulltime']
                if s['home'] is None: continue
                if m['teams']['home']['winner'] is True and m['teams']['home']['id'] == id_a: w_a += 1
                elif m['teams']['away']['winner'] is True and m['teams']['away']['id'] == id_a: w_a += 1
                elif m['teams']['home']['winner'] is True and m['teams']['home']['id'] == id_b: w_b += 1
                elif m['teams']['away']['winner'] is True and m['teams']['away']['id'] == id_b: w_b += 1
                else: d += 1
                g_a += s['home'] if m['teams']['home']['id']==id_a else s['away']
                g_b += s['away'] if m['teams']['home']['id']==id_a else s['home']
            t=len(h2h_matches); c1,c2,c3,c4=st.columns(4)
            c1.metric("Toplam Maç",t); c2.metric(f"{name_a} G.",w_a); c3.metric(f"{name_b} G.",w_b); c4.metric("Ber.",d)
            df = pd.DataFrame({'İstatistik':['Toplam Gol','Ort. Gol'], name_a:[g_a, f"{g_a/t:.2f}"], name_b:[g_b, f"{g_b/t:.2f}"]}).set_index('İstatistik')
            st.table(df)
        else: st.warning("İki takım arasında geçmişe dönük karşılaşma verisi bulunamadı.")

# --- GÖRÜNÜM OLUŞTURMA VE ANA AKIŞ ---
def build_dashboard_view(model_params: Dict):
    st.title(f"🗓️ {date.today().strftime('%d.%m.%Y')} Maç Panosu")
    leagues_map = {v: k for k, v in INTERESTING_LEAGUES.items()}
    selected_names = st.sidebar.multiselect("Analiz edilecek ligleri seçin:", options=list(INTERESTING_LEAGUES.values()), default=["🇹🇷 Süper Lig", "🇬🇧 Premier League"])
    if not selected_names:
        st.warning("Lütfen analiz için kenar çubuğundan en az bir lig seçin."); return
    selected_ids = [leagues_map[name] for name in selected_names]
    fixtures, error = get_todays_fixtures(selected_ids)
    if error: st.error(f"Maçlar çekilirken bir hata oluştu:\n\n{error}"); return
    if not fixtures: st.warning("Bugün için seçtiğiniz liglerde maç bulunamadı."); return
    progress_bar = st.progress(0, text="Maçlar analiz ediliyor...")
    analyzed = [summary for i, f in enumerate(fixtures) if (summary := analyze_fixture_summary(f, model_params)) and (progress_bar.progress((i+1)/len(fixtures), f"Analiz: {f['home_name']}"))]
    progress_bar.empty()
    if not analyzed: st.error("Hiçbir maç analiz edilemedi."); return
    df = pd.DataFrame(analyzed)
    st.subheader("🏆 AI Güven Puanına Göre Sıralama")
    st.dataframe(df.sort_values("AI Güven Puanı",ascending=False).drop(['home_id','away_id','fixture_id'],axis=1),use_container_width=True,hide_index=True)
    st.markdown("---"); st.subheader("🎯 Günün Gol Favorileri")
    c1,c2 = st.columns(2)
    with c1: st.markdown("##### Yüksek 2.5 Üst Olasılıkları"); st.dataframe(df.sort_values("2.5 ÜST (%)",ascending=False).head(5)[['Ev Sahibi','Deplasman','2.5 ÜST (%)']], use_container_width=True,hide_index=True)
    with c2: st.markdown("##### Yüksek KG Var Olasılıkları"); st.dataframe(df.sort_values("KG VAR (%)",ascending=False).head(5)[['Ev Sahibi','Deplasman','KG VAR (%)']], use_container_width=True,hide_index=True)
    st.markdown("---"); st.subheader("💥 Günün Korner ve Kart Favorileri")
    c3,c4 = st.columns(2)
    with c3:
        st.markdown("##### En Yüksek Ortalama Korner"); df_corners = df.sort_values("Ort. Korner", ascending=False).head(5)
        st.dataframe(df_corners[['Ev Sahibi', 'Deplasman', 'Ort. Korner']].style.format({"Ort. Korner": "{:.2f}"}), use_container_width=True, hide_index=True)
    with c4:
        st.markdown("##### En Yüksek Ortalama Sarı Kart"); df_cards = df.sort_values("Ort. Sarı Kart", ascending=False).head(5)
        st.dataframe(df_cards[['Ev Sahibi', 'Deplasman', 'Ort. Sarı Kart']].style.format({"Ort. Sarı Kart": "{:.2f}"}), use_container_width=True, hide_index=True)
    st.markdown("---"); st.subheader("🔍 Detaylı Maç Analizi")
    options = [f"{r['Saat']} | {r['Lig']} | {r['Ev Sahibi']} vs {r['Deplasman']}" for _,r in df.iterrows()]
    selected = st.selectbox("Detaylı analiz için maç seçin:", options, index=None, placeholder="Tablodan bir maç seçin...")
    if selected:
        row = df[df.apply(lambda r: f"{r['Saat']} | {r['Lig']} | {r['Ev Sahibi']} vs {r['Deplasman']}" == selected, axis=1)].iloc[0]
        team_a,team_b = {'id':row['home_id'],'name':row['Ev Sahibi']},{'id':row['away_id'],'name':row['Deplasman']}
        with st.spinner(f"**{team_a['name']} vs {team_b['name']}** analizi yapılıyor..."):
            analyze_and_display(team_a,team_b,row['fixture_id'], model_params)

def build_manual_view(model_params: Dict):
    st.title("🔩 Manuel Takım Analizi")
    c1,c2 = st.columns(2)
    t1_in,t2_in = c1.text_input("Ev Sahibi Takım (Ad/ID)"), c2.text_input("Deplasman Takımı (Ad/ID)")
    if st.button("Analizi Başlat", use_container_width=True):
        if not t1_in or not t2_in: st.warning("Lütfen iki takımı da girin."); return
        team_a,team_b = get_team_id(t1_in),get_team_id(t2_in)
        if team_a and team_b:
            with st.spinner('Maç aranıyor...'):
                info = get_team_league_info(team_a['id'])
                if not info: st.error(f"{team_a['name']} için sezon bilgisi yok."); return
                match, error = find_upcoming_fixture(team_a['id'], team_b['id'], info['season'])
            if error: st.error(f"Maç aranırken hata oluştu: {error}")
            elif match:
                st.success(f"✅ Maç bulundu! Tarih: {datetime.fromtimestamp(match['fixture']['timestamp']).strftime('%d.%m.%Y')}")
                with st.spinner('Detaylı analiz yapılıyor...'):
                    analyze_and_display(team_a, team_b, match['fixture']['id'], model_params)
            else: st.error("Bu iki takım arasında yakın zamanda maç bulunamadı.")
        else: st.error("Takımlar bulunamadı.")

if __name__ == "__main__":
    st.set_page_config(layout="wide", page_title="Futbol Analiz Motoru")
    if 'view' not in st.session_state:
        st.session_state.view = 'home'

    st.sidebar.title("⚽ Futbol Analiz Motoru"); st.sidebar.markdown("---")
    
    if st.sidebar.button("Maç Panosu", use_container_width=True):
        st.session_state.view = 'dashboard'
    
    if st.sidebar.button("Manuel Analiz", use_container_width=True):
        st.session_state.view = 'manual'
    
    with st.sidebar.expander("⚙️ Model Ayarlarını Değiştir"):
        home_adv = st.slider("Ev Sahibi Avantajı", 1.0, 1.5, DEFAULT_HOME_ADVANTAGE_MULTIPLIER, 0.01)
        injury_impact = st.slider("Kilit Oyuncu Etkisi", 0.5, 1.0, DEFAULT_KEY_PLAYER_IMPACT_MULTIPLIER, 0.05)
        max_goals = st.slider("Maksimum Gol Beklentisi", 2.0, 5.0, DEFAULT_MAX_GOAL_EXPECTANCY, 0.1)
    
    model_params = {"home_adv": home_adv, "injury_impact": injury_impact, "max_goals": max_goals}

    if st.session_state.view == 'home':
        st.title(" Futbol Analiz Motoruna Hoş Geldiniz!")
        st.info("Analize başlamak için lütfen kenar çubuğundan bir mod seçin.")
    
    elif st.session_state.view == 'dashboard':
        build_dashboard_view(model_params)

    elif st.session_state.view == 'manual':
        build_manual_view(model_params)