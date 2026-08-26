#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import zipfile

EXPECTED = {
    '00':'ecc251174a150348a925e50d2f04980a1ad93a478708f655e4824a2eaba3f377',
    '01':'041b6711e2778ffc4adbe20c7bcc81a07d983ac87709f1b60496d3b3e46376b3',
    '02':'4f7abb0865a4ab4e909255b2eea1c1c6248542d984d4e1f4a866d1763ca78990',
    '03':'18290818f25e441d6acf4fe5d8d2b8a875b3be772fa9abccbe2954217bbfe4f4',
    '04':'93cbe43e53472b1b728b2a8c778c1ef4522f262c6542c1e5602c72ab92b9c140',
    '05':'52857c3bc29f3d7d872e4c0d29d331e2dc811135f1951b58abf752d48213e8c6',
    '06':'81cb1d0d642a6318ba435752e8a401b5cdab684d0e99418353e0309a643f3304',
}
SEED_SHA = '8dc2804e3aca7cd616b3c0ce6839b0c58c6bfcd18b5962fe0e454e33d1b8ed3f'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunks-dir', type=pathlib.Path, required=True)
    parser.add_argument('--out-zip', type=pathlib.Path, required=True)
    parser.add_argument('--extract-dir', type=pathlib.Path, required=True)
    parser.add_argument('--receipt', type=pathlib.Path, required=True)
    args = parser.parse_args()
    chunks = []
    rows = []
    for index, expected in EXPECTED.items():
        path = args.chunks_dir / f'payload.b64.{index}'
        text = ''.join(path.read_text(encoding='utf-8').split())
        before = hashlib.sha256(text.encode()).hexdigest()
        repair = 'none'
        if index == '02' and before != expected:
            if len(text) == 12001 and text[10400] == 'y' and text[11933:11937] == 'Vlyw':
                text = text[:10400] + 'Y' + text[10401:]
                text = text[:11933] + 'elw' + text[11937:]
                repair = 'verified_transport_repair_y_to_Y_and_Vlyw_to_elw'
        if len(text) > 12000 and index != '06' and hashlib.sha256(text[:12000].encode()).hexdigest() == expected:
            text = text[:12000]
            repair = 'trimmed_trailing_transport_byte'
        actual = hashlib.sha256(text.encode()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'chunk {index} mismatch {actual} != {expected}')
        chunks.append(text)
        rows.append({'chunk': index, 'chars': len(text), 'sha256_before': before, 'sha256_after': actual, 'repair': repair})
    data = base64.b64decode(''.join(chunks), validate=True)
    actual_seed = hashlib.sha256(data).hexdigest()
    if actual_seed != SEED_SHA:
        raise RuntimeError(f'seed mismatch {actual_seed} != {SEED_SHA}')
    args.out_zip.parent.mkdir(parents=True, exist_ok=True)
    args.out_zip.write_bytes(data)
    with zipfile.ZipFile(args.out_zip) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f'seed CRC error {bad}')
        args.extract_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(args.extract_dir)
    receipt = {'contract':'FQT_V26_SEED_RECONSTRUCTION_V1','seed_sha256':actual_seed,'chunks':rows,'members':sorted(path.name for path in args.extract_dir.iterdir())}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
