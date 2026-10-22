# Vendor Security Patches (`client/vendor`)

## Module Responsibility
Houses hardened, locally-packaged `.tgz` tarballs for transitive npm dependencies whose upstream security fixes (`braces@3.0.4`, `sprintf-js@1.1.4`) are pinned via `file:./vendor/...` in `client/package.json` `dependencies` and `overrides`.

## Patched Packages
- **`braces-3.0.4.tgz` (`braces@3.0.4`)**:
  - **Remediation**: `CVE-2026-93687` / `GHSA-vfj7-8cjw-p6xm` (Uncontrolled Recursion / Stack Overflow via deeply nested brace and parenthesis expressions).
  - **Hardening**: Introduces `MAX_DEPTH: 64` (configurable via `options.maxDepth`) in `lib/constants.js` and enforces recursion/nesting depth limits across `lib/parse.js`, `lib/compile.js`, `lib/expand.js`, `lib/stringify.js`, and `lib/utils.js`.
- **`sprintf-js-1.1.4.tgz` (`sprintf-js@1.1.4`)**:
  - **Remediation**: `CVE-2026-97058` / `GHSA-hp3w-g68c-fv3c` (Improper Validation of Specified Quantity in Input via unbounded precision and width specifiers).
  - **Hardening**: Validates and bounds `ph.precision` (`0..100` for `%e`/`%f`, `1..100` for `%g`) and limits format placeholder width/precision (`<= 10000`) and JSON indentation (`<= 10`) in `src/sprintf.js` and `dist/sprintf.min.js`.

## Dependencies
- Referenced by `client/package.json` (`dependencies` and `overrides`) and locked in `client/package-lock.json`.
- Validated by `client/tests/vendor_security.test.js`.
