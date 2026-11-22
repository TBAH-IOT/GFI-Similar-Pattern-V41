"""Offline snapshot server for the pre-scanned V41 handoff demo."""
import argparse
import copy
from functools import lru_cache
import gzip
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser

from occurrence_horizon import OccurrenceHorizonService
from occurrence_horizon_v40 import OccurrenceHorizonV40

ROOT=Path(__file__).resolve().parent
V39_HORIZON = OccurrenceHorizonService(ROOT)
V40_HORIZON = OccurrenceHorizonV40(ROOT)

@lru_cache(maxsize=16)
def dataset(symbol,tf):
    path=ROOT/'demo-data'/f'{symbol}_{tf}.json.gz'
    if not path.is_file(): raise ValueError('Chưa có snapshot cho coin/khung này.')
    with gzip.open(path,'rt',encoding='utf-8') as source: return json.load(source)

def view_dataset(symbol, tf, view):
    """Return an isolated snapshot with the requested occurrence policy."""
    data = copy.deepcopy(dataset(symbol, tf))
    if tf in ('15m', '1h', '4h') and view in ('v39', 'v40'):
        service = V40_HORIZON if view == 'v40' else V39_HORIZON
        service.observe(symbol, tf, data.get('candles', []))
        data['signals'] = [service.extend(signal, symbol, tf) for signal in data.get('signals', [])]
    return data

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT/'static'),**kwargs)
    def do_GET(self):
        route=urlparse(self.path)
        if route.path=='/':
            query = route.query or 'v=41&build=github-v41'
            self.send_response(302);self.send_header('Location',f'/index.html?{query}#chart-panel');self.end_headers();return
        if not route.path.startswith('/api/'): return super().do_GET()
        try:
            catalog=json.loads((ROOT/'assets.json').read_text(encoding='utf-8'))
            if route.path=='/api/assets': result={**catalog,'pattern_timeframes':['15m','1h','4h'],'timeframes':['15m','1h','4h','1d']}
            elif route.path=='/api/health': result={'ok':True,'mode':'snapshot','manifest':json.loads((ROOT/'demo-data/manifest.json').read_text(encoding='utf-8'))}
            elif route.path=='/api/research': result={'progress':{'status':'complete'},'report':json.loads((ROOT/'research-results.json').read_text(encoding='utf-8'))}
            elif route.path=='/api/catalog': result=json.loads((ROOT/'pattern-catalog.json').read_text(encoding='utf-8'))
            else:
                params=parse_qs(route.query);symbol=params.get('symbol',['BTCUSDT'])[0].upper();tf=params.get('tf',['1h'])[0]
                if symbol not in catalog['assets'] or tf not in ['15m','1h','4h','1d']: raise ValueError('Coin/khung không hợp lệ.')
                view=params.get('view',['v39'])[0]
                data=view_dataset(symbol,tf,view)
                if route.path=='/api/market': result=data
                elif route.path=='/api/patterns': result={key:data[key] for key in ['symbol','timeframe','signals','server_time','source','pipeline','mode']}
                elif route.path=='/api/tick': result={**{key:data[key] for key in ['symbol','timeframe','last','change_24h','high_24h','low_24h','volume_24h','updated_at','source','mode']},'candles':data['candles'][-3:]}
                else: self.send_error(404);return
            self.json_response(result)
        except (ValueError,FileNotFoundError) as error: self.json_response({'error':str(error)},400)
    def json_response(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8767);parser.add_argument('--open',action='store_true');args=parser.parse_args()
    address=f'http://{args.host}:{args.port}'
    httpd=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'GFI pre-scanned snapshot demo: {address}',flush=True)
    print('Snapshot mode: no Internet/live feed/model rescan; Python requirements must be installed.',flush=True)
    if args.open: threading.Timer(.3,lambda:webbrowser.open(address)).start()
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass
    finally: httpd.server_close()
