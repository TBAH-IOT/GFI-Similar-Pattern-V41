"""Standalone audit of all source, assets and bootstrap/cache inputs in this bundle."""
import argparse
import ast
import csv
import gzip
import hashlib
from html.parser import HTMLParser
import importlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ('BTCUSDT', 'NEARUSDT', 'SOLUSDT')
FRAMES = ('15m', '1h', '4h', '1d')
ACTIVE_FRAMES = FRAMES[:3]
REQUIRED = (
    'server.py', 'demo_server.py', 'directional_prediction.py', 'forecast_selection.py',
    'horizon_forecast.py', 'occurrence_horizon.py', 'occurrence_horizon_v40.py',
    'arrow_forecast.py', 'mean_forecast.py', '.gitignore', '.gitattributes',
    'path_integrity.py', 'occurrence_identity.py', 'btc-baseline.json', 'assets.json',
    'research_runner.py', 'research-settings.json', 'research-results.json',
    'research-results.csv', 'pattern-catalog.json', 'catalog-coverage.json',
    'requirements.txt', 'requirements-tested.txt', 'requirements-lock.txt',
    'SHA256SUMS.json', 'VALIDATION.json', 'Dockerfile', 'compose.yaml', '.dockerignore',
    'README.md', 'START-HERE-VI.md', 'CHECK_PACKAGE.cmd', 'START_REALTIME.cmd',
    'START_SNAPSHOT_CHECK.cmd', 'THIRD_PARTY.md', 'demo-data/manifest.json',
    'runtime/research-registry.json', 'tools/verify_bundle.py', 'tools/preflight.py',
    'engine/canonical_catalog.py', 'engine/canonical_price_catalog.json',
    'tools/model_identity.py', 'CANONICAL-MIGRATION.json', 'CANONICAL-ENVIRONMENTS.json',
    'tests/test_canonical_model.py', 'tests/probe_canonical.py', 'CANONICAL-FIX-VI.md',
    'tools/add_coin.py', 'integration/api-contract.ts', 'integration/nginx-location.conf',
    'static/index.html', 'static/app.js', 'static/styles.css', 'static/reference.css',
    'static/forecast-native.js', 'static/forecast-arrows.js', 'static/spotlight.css',
    'static/pattern-presentation.js', 'static/live-feed.js',
    'static/integration/similar-pattern-adapter.js', 'static/vendor/lightweight-charts.js',
    'static/vendor/LICENSE-lightweight-charts.txt', 'static/vendor/NOTICE-lightweight-charts.txt',
    'docs/INTEGRATION-VI.md', 'docs/MODEL-LOGIC-VI.md', 'docs/SCALING-VI.md',
    'docs/ACCEPTANCE.md', 'docs/PACKAGE-AUDIT-VI.md', 'docs/V41-DISPLAY-VI.md',
    'tools/test_arrow_forecast.cjs', 'tools/test_occurrence_v40.py',
    'tests/test_v41_contract.py',
)

def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def required_paths():
    paths = list(REQUIRED)
    paths += ['engine/' + name + '.py' for name in (
        'similar_engine', 'pipeline', 'research_model', 'expanding_pipeline',
        'validated_pipeline', 'pattern_catalog', 'chart_library', 'curve_search',
        'specialized_patterns', 'strategy_catalog', 'eligibility', 'geometry')]
    for symbol in SYMBOLS:
        for frame in FRAMES:
            paths += [f'demo-data/{symbol}_{frame}.json.gz', f'runtime/history/{symbol}_{frame}.csv.gz']
        for frame in ACTIVE_FRAMES:
            paths.append(f'runtime/{symbol}_{frame}-forecast-paths.json.gz')
            if symbol != 'BTCUSDT':
                paths.append(f'runtime/setups/{symbol}_{frame}.json')
    for frame in ACTIVE_FRAMES:
        paths += [f'Data/data_btc_price_{frame}.csv', f'engine/Data/data_btc_price_{frame}.csv']
    return paths

def assert_required(root):
    missing = [name for name in required_paths() if not (root / name).is_file()]
    if missing:
        raise AssertionError('MISSING FILES: ' + ', '.join(missing))

class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.refs = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (key == 'src' or (key == 'href' and tag == 'link')):
                self.refs.append(value)

def audit(root, runtime=False):
    assert_required(root)
    app = (root / 'static/app.js').read_text(encoding='utf-8')
    arrows = (root / 'static/forecast-arrows.js').read_text(encoding='utf-8')
    assert 'initialQuery.get("v") || "41"' in app, 'V41 is not the default UI'
    assert 'if (spotlightForecastMode) forecastCandleVisible = false' in app, 'V41 forecast candles not disabled'
    assert 'accuracyEmphasis(signal)' in arrows, 'V41 accuracy emphasis missing'
    checksums = json.loads((root / 'SHA256SUMS.json').read_text(encoding='utf-8'))
    for name, expected in checksums.items():
        path = (root / name).resolve()
        assert path.is_relative_to(root.resolve()), 'Unsafe manifest path: ' + name
        assert path.is_file() and digest(path) == expected, 'Missing/changed file: ' + name
    assert all(name in checksums for name in required_paths() if name != 'SHA256SUMS.json'), 'Required file is not checksum protected'

    python_files = [*root.glob('*.py'), *(root / 'engine').glob('*.py'),
                    *(root / 'tools').glob('*.py'), *(root / 'tests').glob('*.py')]
    locals_ = {p.stem for p in python_files}
    third_party = set()
    for path in python_files:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            imports = [x.name.split('.')[0] for x in node.names] if isinstance(node, ast.Import) else [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module else []
            third_party.update(name for name in imports if name not in sys.stdlib_module_names and name not in locals_)
    assert third_party == {'numpy', 'pandas', 'scipy'}, 'Undeclared imports: ' + repr(third_party)

    baseline = json.loads((root / 'btc-baseline.json').read_text(encoding='utf-8'))
    assert baseline['source_sha256'] == digest(root / 'engine/similar_engine.py')
    registry = json.loads((root / 'runtime/research-registry.json').read_text(encoding='utf-8'))
    assert registry['evaluation_hash'] == digest(root / 'research_runner.py')
    manifest = json.loads((root / 'demo-data/manifest.json').read_text(encoding='utf-8'))
    assert manifest['model_hash'] == registry['model_hash']
    assets = json.loads((root / 'assets.json').read_text(encoding='utf-8'))['assets']
    assert all(symbol in assets for symbol in SYMBOLS)

    patterns = path_rows = 0
    for symbol in SYMBOLS:
        for frame in FRAMES:
            with gzip.open(root / f'demo-data/{symbol}_{frame}.json.gz', 'rt', encoding='utf-8') as source:
                data = json.load(source)
            assert data['symbol'] == symbol and data['timeframe'] == frame
            assert data['candles'], (symbol, frame, 'Empty candle snapshot')
            patterns += len(data['signals'])
            for signal in data['signals']:
                for side in ('up', 'down'):
                    case = signal['prediction'][side + '_representative']
                    assert len(case['candles']) == 10, (symbol, frame, signal['id'], side)
            if frame == '1d':
                assert not data['signals']
            history = root / f'runtime/history/{symbol}_{frame}.csv.gz'
            with gzip.open(history, 'rt', encoding='utf-8') as source:
                columns = next(csv.reader(source))
                assert set(columns) == {'time', 'open', 'high', 'low', 'close', 'volume'}
                assert sum(1 for _ in source) > 0
            if frame in ACTIVE_FRAMES:
                with gzip.open(root / f'runtime/{symbol}_{frame}-forecast-paths.json.gz', 'rt', encoding='utf-8') as source:
                    cache = json.load(source)
                assert cache['model_hash'] == registry['model_hash']
                assert cache['source_sha256'] == digest(history)
                assert cache['path_contiguity_checked'] and cache['groups']
                path_rows += sum(len(group['rows']) for group in cache['groups'])
    assert patterns == 279, patterns
    for frame in ACTIVE_FRAMES:
        assert digest(root / f'Data/data_btc_price_{frame}.csv') == digest(root / f'engine/Data/data_btc_price_{frame}.csv')

    static_refs = 0
    for html in (root / 'static').glob('*.html'):
        parser = AssetLinks(); parser.feed(html.read_text(encoding='utf-8'))
        for ref in parser.refs:
            uri = urlsplit(ref)
            if uri.scheme or uri.netloc:
                continue
            path = root / 'static' / unquote(uri.path).lstrip('/') if uri.path.startswith('/') else html.parent / unquote(uri.path)
            assert path.is_file(), 'Missing frontend asset: ' + ref
            static_refs += 1

    summary = {'manifest_files': len(checksums), 'required_paths': len(required_paths()),
               'python_files_parsed': len(python_files), 'declared_dependencies': sorted(third_party),
               'static_assets_checked': static_refs, 'snapshots': 12, 'history_files': 12,
               'forecast_libraries': 9, 'forecast_library_rows': path_rows,
               'patterns_with_two_ten_candle_branches': patterns,
               'legacy_btc_csv_files': 6, 'missing_files': []}
    if runtime:
        sys.path.insert(0, str(root)); sys.path.insert(0, str(root / 'engine'))
        modules = ['server', 'demo_server', 'directional_prediction', 'forecast_selection',
                   'path_integrity', 'occurrence_identity', 'pipeline', 'research_model',
                   'expanding_pipeline', 'similar_engine', 'validated_pipeline', 'research_runner']
        for name in modules:
            module = importlib.import_module(name)
            assert Path(module.__file__).resolve().is_relative_to(root.resolve()), 'Imported outside the bundle: ' + name
        server = sys.modules['server']
        rows = {frame: len(server.frame(frame)) for frame in ACTIVE_FRAMES}
        assert all(rows.values())
        now_ms = int(time.time() * 1000)
        for symbol in SYMBOLS[1:]:
            for frame in ACTIVE_FRAMES:
                worker = server.PIPELINES[symbol, frame]
                assert worker._load(now_ms) and worker.models, (symbol, frame, 'Registry not loadable')
        server.PATH_EXECUTOR.shutdown(wait=False)
        summary.update(runtime_modules_loaded=len(modules), legacy_btc_rows=rows,
                       registry_markets_loaded=6)
    return summary

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', action='store_true', help='Also import modules/load registry and BTC CSV; requires installed requirements')
    args = parser.parse_args()
    print(json.dumps({'passed': True, **audit(ROOT, args.runtime)}, ensure_ascii=False, indent=2))
