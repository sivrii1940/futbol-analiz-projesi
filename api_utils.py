# api_utils.py

import requests
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, date
import streamlit as st

@st.cache_data(ttl=3600)
def make_api_request(api_key: str, base_url: str, endpoint: str, params: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    headers = {'x-rapidapi-key': api_key, 'x-rapidapi-host': "v3.football.api-sports.io"}
    url = f"{base_url}/{endpoint}"
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        api_data = response.json()
        if api_data.get('errors') and (isinstance(api_data['errors'], dict) and api_data['errors']) or (isinstance(api_data['errors'], list) and len(api_data['errors']) > 0):
            return None, f"API Hatası: {api_data['errors']}"
        return api_data.get('response', []), None
    except requests.exceptions.HTTPError as http_err:
        return None, f"HTTP Hatası: {http_err}. API Anahtarınızı veya aboneliğinizi kontrol edin."
    except requests.exceptions.RequestException as req_err:
        return None, f"Bağlantı Hatası: {req_err}"

@st.cache_data(ttl=86400) 
def get_fixture_injuries(api_key: str, base_url: str, fixture_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request(api_key, base_url, "injuries", {'fixture': fixture_id})

@st.cache_data(ttl=86400)
def get_squad_player_stats(api_key: str, base_url: str, team_id: int, season: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request(api_key, base_url, "players", {'team': team_id, 'season': season})

@st.cache_data(ttl=86400)
def get_league_standings(api_key: str, base_url: str, league_id: int, season: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    response, error = make_api_request(api_key, base_url, "standings", {'league': league_id, 'season': season})
    if error: return None, error
    if response and response[0]['league']['standings']:
        return response[0]['league']['standings'][0], None
    return None, None

@st.cache_data(ttl=86400)
def get_h2h_matches(api_key: str, base_url: str, team_a_id: int, team_b_id: int, limit: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request(api_key, base_url, "fixtures/headtohead", {'h2h': f"{team_a_id}-{team_b_id}", 'last': limit})

@st.cache_data(ttl=86400)
def get_fixture_statistics(api_key: str, base_url: str, fixture_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    return make_api_request(api_key, base_url, "fixtures/statistics", {'fixture': fixture_id})

@st.cache_data(ttl=86400)
def get_team_form_sequence(api_key: str, base_url: str, team_id: int, limit: int = 10) -> Optional[List[Dict[str, str]]]:
    matches, error = make_api_request(api_key, base_url, "fixtures", {'team': team_id, 'last': limit, 'status': 'FT'})
    if error or not matches:
        return None
    form_data = []
    for match in reversed(matches):
        try:
            score_home = match['score']['fulltime']['home']
            score_away = match['score']['fulltime']['away']
            if score_home is None or score_away is None: continue
            is_home_team = match['teams']['home']['id'] == team_id
            opponent_name = match['teams']['away']['name'] if is_home_team else match['teams']['home']['name']
            score_str = f"{score_home}-{score_away}" if is_home_team else f"{score_away}-{score_home}"
            result = 'B'
            if (is_home_team and score_home > score_away) or (not is_home_team and score_away > score_home):
                result = 'G'
            elif (is_home_team and score_home < score_away) or (not is_home_team and score_away < score_home):
                result = 'M'
            form_data.append({'result': result, 'opponent': opponent_name, 'score': score_str})
        except (KeyError, TypeError):
            continue
    return form_data

@st.cache_data(ttl=86400)
def get_team_league_info(api_key: str, base_url: str, team_id: int) -> Optional[Dict[str, Any]]:
    response, error = make_api_request(api_key, base_url, "leagues", {'team': team_id, 'current': 'true'})
    if error or not response: return None
    league, seasons = response[0]['league'], response[0]['seasons']
    season = next((s['year'] for s in seasons if s['current']), seasons[-1]['year'])
    return {'league_id': league['id'], 'season': season}

def find_upcoming_fixture(api_key: str, base_url: str, team_a_id: int, team_b_id: int, season: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    fixtures, error = make_api_request(api_key, base_url, "fixtures", {'team': team_a_id, 'season': season, 'status': 'NS'})
    if error: return None, error
    if fixtures:
        for f in fixtures:
            if f['teams']['home']['id'] == team_b_id or f['teams']['away']['id'] == team_b_id:
                return f, None
    return None, None

def get_fixtures_by_date(api_key: str, base_url: str, selected_league_ids: List[int], selected_date: date) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    all_fixtures, error_messages = [], []
    date_str = selected_date.strftime('%Y-%m-%d')
    season = selected_date.year
    status = 'FT' if selected_date < date.today() else 'NS'
    for league_id in selected_league_ids:
        params = {'date': date_str, 'status': status, 'league': league_id, 'season': season}
        response, error = make_api_request(api_key, base_url, "fixtures", params)
        if error:
            error_messages.append(f"Lig ID {league_id}: {error}")
            continue
        if response:
            for f in response:
                try:
                    fixture_data = {'match_id': f['fixture']['id'], 'time': datetime.fromtimestamp(f['fixture']['timestamp']).strftime('%H:%M'),
                                    'home_name': f['teams']['home']['name'], 'home_id': f['teams']['home']['id'],
                                    'away_name': f['teams']['away']['name'], 'away_id': f['teams']['away']['id'],
                                    'league_name': f['league']['name']}
                    if status == 'FT' and f.get('score', {}).get('fulltime'):
                        fixture_data['actual_score'] = f"{f['score']['fulltime']['home']} - {f['score']['fulltime']['away']}"
                        fixture_data['winner_home'] = f['teams']['home']['winner']
                    all_fixtures.append(fixture_data)
                except (KeyError, TypeError): continue
    final_error = "\n".join(error_messages) if error_messages else None
    return sorted(all_fixtures, key=lambda x: (x['league_name'], x['time'])), final_error

def get_team_id(api_key: str, base_url: str, team_input: str) -> Optional[Dict[str, Any]]:
    response, error = make_api_request(api_key, base_url, "teams", {'search': team_input} if not team_input.isdigit() else {'id': team_input})
    if error:
        st.sidebar.error(error); return None
    if response:
        team = response[0]['team']
        st.sidebar.success(f"✅ Bulunan: {team['name']} ({team['id']})")
        return {'id': team['id'], 'name': team['name']}
    st.sidebar.error(f"❌ Takım bulunamadı: '{team_input}'"); return None