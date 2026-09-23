"""CLI adapter: the original three-table contract and a shared analytical pipeline."""
import argparse
import json
from pathlib import Path
from mg.dataset import Dataset
from mg.features import load
from mg.pipeline import run_pipeline
from mg.export import export_results
from mg.validation import validate_data

ROOT = Path(__file__).parent

def analyze(data_dir: Path, out: Path, cfg: dict):
    validate_data(Path(data_dir), cfg.get('min_tx_kzt', 0), cfg.get('max_depth', 4))
    edges, nodes, tx = load(Path(data_dir))
    dataset = Dataset.normalize(tx, edges, nodes, settings={**cfg, 'collection_threshold': cfg.get('min_tx_kzt')})
    result = run_pipeline(dataset, cfg, lambda stage, percent: print(f'{percent:3}% {stage}'))
    export_results(result, dataset, out, viewer=True, cli=True)
    print(json.dumps(result.summary['roles'], ensure_ascii=False))
    return result.summary

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(ROOT/'data'))
    parser.add_argument('--out', default=str(ROOT/'out'))
    parser.add_argument('--config', default=str(ROOT/'config.json'))
    args = parser.parse_args()
    analyze(Path(args.data), Path(args.out), json.loads(Path(args.config).read_text(encoding='utf-8')))

if __name__ == '__main__':
    main()
