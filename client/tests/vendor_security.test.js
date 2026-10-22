const braces = require('braces');
const { sprintf, vsprintf } = require('sprintf-js');
const bracesPkg = require('braces/package.json');
const sprintfPkg = require('sprintf-js/package.json');
const bracesConstants = require('braces/lib/constants');
const bracesUtils = require('braces/lib/utils');

describe('Vendor Security Patches Verification', () => {
    describe('braces@3.0.4 (CVE-2026-93687 / GHSA-vfj7-8cjw-p6xm)', () => {
        test('resolves patched version 3.0.4 with MAX_DEPTH = 64', () => {
            expect(bracesPkg.version).toBe('3.0.4');
            expect(bracesConstants.MAX_DEPTH).toBe(64);
        });

        test('expands and compiles normal brace patterns accurately', () => {
            expect(braces('{a,b,c}', { expand: true })).toEqual(['a', 'b', 'c']);
            expect(braces('a/{x,y}/b', { expand: true })).toEqual(['a/x/b', 'a/y/b']);
            expect(braces('{1..3}', { expand: true })).toEqual(['1', '2', '3']);
            expect(braces('{a,b}')).toEqual(['(a|b)']);
            expect(braces.stringify('a/{b,c}/d')).toBe('a/{b,c}/d');
        });

        test('throws RangeError when brace nesting exceeds MAX_DEPTH (64)', () => {
            const deepBraces = '{'.repeat(70) + 'a,b' + '}'.repeat(70);
            expect(() => braces(deepBraces)).toThrow(RangeError);
            expect(() => braces.expand(deepBraces)).toThrow(RangeError);
            expect(() => braces.parse(deepBraces)).toThrow(/Maximum nesting depth/);
        });

        test('throws RangeError when parenthesis nesting exceeds MAX_DEPTH (64)', () => {
            const deepParens = '('.repeat(70) + 'a' + ')'.repeat(70);
            expect(() => braces.parse(deepParens)).toThrow(RangeError);
        });

        test('honors custom options.maxDepth', () => {
            const nested5 = '{a,{b,{c,{d,{e,f}}}}}';
            expect(() => braces(nested5, { maxDepth: 3 })).toThrow(RangeError);
            expect(braces(nested5, { maxDepth: 10, expand: true })).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
        });

        test('enforces recursion depth limit in utils.flatten', () => {
            let deepArray = ['leaf'];
            for (let i = 0; i < 70; i++) {
                deepArray = [deepArray];
            }
            expect(() => bracesUtils.flatten(deepArray)).toThrow(RangeError);
        });
    });

    describe('sprintf-js@1.1.4 (CVE-2026-97058 / GHSA-hp3w-g68c-fv3c)', () => {
        test('resolves patched version 1.1.4', () => {
            expect(sprintfPkg.version).toBe('1.1.4');
        });

        test('formats standard specifiers and valid precisions accurately', () => {
            expect(sprintf('%.2f', 3.14159)).toBe('3.14');
            expect(sprintf('%.3e', 1234.5)).toBe('1.235e+3');
            expect(sprintf('%.4g', 123.456)).toBe('123.5');
            expect(sprintf('%.3s', 'abcdef')).toBe('abc');
            expect(vsprintf('%s-%d', ['test', 42])).toBe('test-42');
        });

        test('throws RangeError when float/exponential/general precision exceeds 100 or is 0 for %g', () => {
            expect(() => sprintf('%.101f', 1.23)).toThrow(RangeError);
            expect(() => sprintf('%.101e', 1.23)).toThrow(RangeError);
            expect(() => sprintf('%.101g', 1.23)).toThrow(RangeError);
            expect(() => sprintf('%.0g', 1.23)).toThrow(RangeError);
        });

        test('throws RangeError when placeholder width or precision exceeds 10000', () => {
            expect(() => sprintf('%10001s', 'a')).toThrow(RangeError);
            expect(() => sprintf('%.10001s', 'a')).toThrow(RangeError);
        });
    });
});
