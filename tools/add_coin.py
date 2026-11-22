"""Register a USDT market; validation is a separate, explicit research step."""
import argparse
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def register(root,symbol,name,glyph,peers):
    symbol=symbol.upper()
    if not re.fullmatch(r'[A-Z0-9]{2,24}USDT',symbol): raise ValueError('Use an uppercase Binance Spot USDT symbol, e.g. AVAXUSDT.')
    path=root/'assets.json';catalog=json.loads(path.read_text(encoding='utf-8'))
    if symbol in catalog['assets']: raise ValueError('Market already registered. Existing configurations are preserved.')
    if any(peer not in catalog['assets'] for peer in peers): raise ValueError('Register peer assets first.')
    ticker=symbol[:-4]
    catalog['assets'][symbol]={'ticker':ticker,'name':name,'glyph':glyph or ticker[0],'description':f'{name} · Binance Spot · {symbol}'}
    catalog.setdefault('similar_assets',{})[symbol]=peers
    settings_path=root/'research-settings.json';settings=json.loads(settings_path.read_text(encoding='utf-8'))
    settings['symbols']=list(dict.fromkeys([*settings['symbols'],symbol]))
    settings.setdefault('research_timeframes_by_symbol',{})[symbol]=['4h','1h','15m']
    for target,document in [(path,catalog),(settings_path,settings)]:
        temp=target.with_suffix('.json.tmp');temp.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(target)
    return symbol

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('symbol');p.add_argument('--name',required=True);p.add_argument('--glyph');p.add_argument('--peer',action='append',default=[]);a=p.parse_args()
    symbol=register(ROOT,a.symbol,a.name,a.glyph,a.peer)
    print(f'Registered {symbol}. Run python research_runner.py, verify its registry, then restart server.py. No BTC baseline retuning is performed.')
