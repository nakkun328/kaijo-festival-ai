"""Read-only information tools exposed to the LangChain agent."""
import re
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import truststore


class DailyTools:
    def needs_live_info(self, text, history):
        # Most casual turns need no network. Avoid an extra model call before speaking.
        live_hint = re.compile(
            r'天気|予報|気温|検索|調べ|調査|最新|ニュース|今の(?:株価|相場|為替|価格|首相|大統領|CEO)|'
            r'現在の(?:株価|相場|為替|価格|首相|大統領|CEO)|試合結果|運行情報|営業時間|発売日|'
            r'株価|為替|選挙結果|首相|大統領|CEO', re.IGNORECASE)
        recent_user = ' '.join(item.get('content', '') for item in history[-4:]
                               if item.get('role') == 'user')
        followup = re.search(r'^(?:それ|そっち|明日|あした|来週|昨日|きのう|じゃあ|では|大阪|東京)[はも、？?\s]*$', text.strip())
        return bool(live_hint.search(text) or (followup and live_hint.search(recent_user)))

    def run(self, plan):
        kind, query = plan['tool'], plan['query']
        if kind not in {'weather', 'search'}:
            raise ValueError('許可されていない情報ツールです。')
        result = {'tool':kind, 'sources':[], 'retrievedAt':datetime.now(timezone.utc).isoformat()}
        try:
            if kind == 'weather':
                if not query:
                    result['clarification'] = 'どの市区町村の天気か聞いてください。'
                else:
                    result.update(self.weather(query))
            elif kind == 'search':
                if not query:
                    result['clarification'] = '何を調べるか聞いてください。'
                else:
                    result.update(self.search(query))
        except Exception as exc:
            result['error'] = f'外部情報を取得できませんでした（{type(exc).__name__}）。未確認の天気や最新情報を推測して答えないでください。'
        return result

    def weather(self, place):
        aliases = {'東京':'Tokyo', '東京都':'Tokyo', '大阪':'Osaka', '大阪市':'Osaka',
                   '札幌':'Sapporo', '横浜':'Yokohama', '京都':'Kyoto', '福岡':'Fukuoka'}
        with httpx.Client(timeout=12, verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as client:
            response = client.get('https://geocoding-api.open-meteo.com/v1/search',
                                  params={'name':aliases.get(place, place), 'count':5, 'language':'ja', 'format':'json'})
            response.raise_for_status()
            locations = response.json().get('results', [])
            if not locations:
                return {'clarification':'地域を見つけられません。都道府県・市区町村名を確認してください。'}
            # Never silently use a distant namesake if several places match.
            if len(locations) > 1 and place not in aliases:
                return {'clarification':'地域候補を示して確認してください。',
                        'candidates':[', '.join(str(p.get(k,'')) for k in ('name','admin1','country')) for p in locations]}
            location = locations[0]
            response = client.get('https://api.open-meteo.com/v1/forecast', params={
                'latitude':location['latitude'], 'longitude':location['longitude'],
                'current':'temperature_2m,weather_code,wind_speed_10m',
                'daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
                'timezone':'auto', 'forecast_days':7})
            response.raise_for_status()
            forecast = response.json()
            return {'location':{k:location.get(k) for k in ('name','admin1','country')},
                    'forecast':forecast,
                    'note':'WMO weather_code: 0晴れ,1-3雲,45/48霧,51-57霧雨,61-67雨,71-77雪,80-82にわか雨,85/86雪,95-99雷雨。提供範囲外の日付は予測しない。',
                    'sources':[{'title':'Open-Meteo 天気予報', 'url':str(response.url)}]}

    def search(self, query):
        from ddgs import DDGS
        items = DDGS(timeout=10).text(query, region='jp-jp', safesearch='moderate', max_results=5)
        sources = []
        for item in items:
            url = item.get('href', '')
            if urlparse(url).scheme not in {'https','http'}:
                continue
            sources.append({'title':str(item.get('title',''))[:200], 'url':url,
                            'snippet':str(item.get('body',''))[:1200]})
        if not sources:
            return {'error':'検索結果がありません。確認できたと述べないでください。'}
        return {'sources':sources, 'note':'検索結果の抜粋です。本文全体は未取得。抜粋で確認できないことを断定せず、情報の古さに注意。'}
