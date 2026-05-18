import fs from 'node:fs';
import path from 'node:path';

const START_MARKER = '__SORTEROS_CFG_START__';
const END_MARKER = '__SORTEROS_CFG_END__';

function indexOfBuffer(haystack, needle, from = 0) {
    return haystack.indexOf(needle, from);
}

function main() {
    const input_path =
        process.argv[2] ||
        path.resolve(process.cwd(), 'tmp', 'sorteros-test-customized.img');

    const bytes = fs.readFileSync(input_path);
    const start_bytes = Buffer.from(START_MARKER, 'utf8');
    const end_bytes = Buffer.from(END_MARKER, 'utf8');
    const start = indexOfBuffer(bytes, start_bytes);

    if (start < 0) {
        throw new Error('start marker not found');
    }

    const end = indexOfBuffer(bytes, end_bytes, start + start_bytes.length);
    if (end < 0) {
        throw new Error('end marker not found');
    }

    const body = bytes
        .subarray(start + start_bytes.length, end)
        .toString('utf8')
        .replace(/\n+$/u, '');

    console.log(`file=${input_path}`);
    console.log(`start=${start}`);
    console.log(`end=${end}`);
    console.log('config:');
    console.log(body || '(empty)');
}

main();
