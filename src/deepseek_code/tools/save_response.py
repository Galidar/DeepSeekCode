"""
save_response.py — Token-efficient response handler.

Reads DeepSeek JSON from stdin, writes code directly to disk,
and prints only lightweight metadata to stdout for Claude.

Usage (single file):
    python run.py --delegate "task" --json 2>/dev/null | \
        python -m deepseek_code.tools.save_response --output path/to/file.ext

Usage (multi-file auto-split):
    python run.py --delegate "task" --json 2>/dev/null | \
        python -m deepseek_code.tools.save_response --split --dir path/to/project/

Usage (just metadata, no save):
    python run.py --delegate "task" --json 2>/dev/null | \
        python -m deepseek_code.tools.save_response --meta-only

Claude sees ONLY the metadata (~200 tokens), not the full code.
Saves 90-97% of Claude output tokens on code generation tasks.
"""

import json
import sys
import os
import re
import argparse


def extract_files_from_response(response: str) -> dict[str, str]:
    """Split a multi-file response into {filename: content} pairs.

    Detects patterns like:
      // --- filename.ext ---
      /* filename.ext */
      # filename.ext
      <!-- filename.ext -->
      ```filename.ext
    """
    patterns = [
        r'(?:^|\n)\s*(?://|/\*|#|<!--)\s*-{2,}\s*(.+?\.\w+)\s*-{0,}(?:\*/|-->)?\s*\n',
        r'(?:^|\n)```(\S+\.\w+)\s*\n',
    ]

    splits = []
    for pat in patterns:
        for m in re.finditer(pat, response):
            splits.append((m.start(), m.end(), m.group(1).strip()))

    if not splits:
        return {}

    splits.sort(key=lambda x: x[0])

    files = {}
    for i, (start, end, name) in enumerate(splits):
        next_start = splits[i + 1][0] if i + 1 < len(splits) else len(response)
        content = response[end:next_start].strip()
        if content.endswith('```'):
            content = content[:-3].strip()
        files[name] = content

    return files


def build_metadata(data: dict) -> dict:
    """Extract lightweight metadata from the full JSON response."""
    meta = {}
    for key in ('success', 'mode', 'had_template', 'had_context',
                'duration_s', 'continuations', 'truncated',
                'missing_todos', 'token_usage'):
        if key in data:
            meta[key] = data[key]

    response = data.get('response', '')
    meta['response_lines'] = response.count('\n') + 1
    meta['response_chars'] = len(response)
    return meta


def main():
    parser = argparse.ArgumentParser(description='Token-efficient DeepSeek response handler')
    parser.add_argument('--output', '-o', help='Write response to this file')
    parser.add_argument('--split', action='store_true',
                        help='Auto-detect and split multi-file responses')
    parser.add_argument('--dir', '-d', default='.',
                        help='Base directory for --split output (default: .)')
    parser.add_argument('--meta-only', action='store_true',
                        help='Only print metadata, discard response')
    parser.add_argument('--preview', type=int, default=0,
                        help='Include first N lines of response in metadata')
    args = parser.parse_args()

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({'error': 'Invalid JSON from DeepSeek', 'raw_length': len(raw)}))
        sys.exit(1)

    if not data.get('success', False):
        print(json.dumps(data, ensure_ascii=False))
        sys.exit(1)

    response = data.get('response', '')
    meta = build_metadata(data)
    files_written = []

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        clean = response.encode('utf-8', errors='replace').decode('utf-8')
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(clean)
        files_written.append(args.output)
        meta['saved_to'] = args.output

    elif args.split:
        detected = extract_files_from_response(response)
        if detected:
            for filename, content in detected.items():
                filepath = os.path.join(args.dir, filename)
                os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
                clean = content.encode('utf-8', errors='replace').decode('utf-8')
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(clean)
                files_written.append(filepath)
            meta['files_saved'] = list(detected.keys())
        else:
            meta['warning'] = 'No file boundaries detected, response not saved'
            meta['hint'] = 'Use --output for single-file responses'

    if args.preview > 0:
        lines = response.split('\n')[:args.preview]
        meta['preview'] = '\n'.join(lines)

    meta['files_written'] = len(files_written)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
