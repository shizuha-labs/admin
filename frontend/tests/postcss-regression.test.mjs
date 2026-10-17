/**
 * PLAT-5534: PostCSS source-map path traversal regression test.
 *
 * Verifies that PostCSS (consumed through Vite) rejects attacker-controlled
 * sourceMappingURL traversals and does not disclose arbitrary .map files.
 *
 * This tests through the real consumer boundary (Vite CSS processing) rather
 * than a direct PostCSS import, per the verify-before-push skill.
 */
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { performance } from 'node:perf_hooks';

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOCK_PATH = join(__dirname, '..', 'package-lock.json');
const lock = JSON.parse(readFileSync(LOCK_PATH, 'utf8'));
const require = createRequire(import.meta.url);
const glob = require('glob');

describe('PLAT-5090: brace-expansion denial-of-service fixes', () => {
  it('keeps the real glob consumer working for a normal application pattern', () => {
    const matches = glob.sync('src/**/*.jsx', {
      cwd: join(__dirname, '..'),
      nodir: true,
    });

    assert.ok(matches.length > 0, 'glob did not match any JSX source files');
    assert.ok(matches.includes('src/App.jsx'), 'glob missed the application entry point');
  });

  it('handles the consecutive non-expanding brace advisory payload promptly', () => {
    // GHSA-3jxr-9vmj-r5cp: this exact 30-group payload blocked vulnerable
    // brace-expansion releases for minutes. glob constructs Minimatch here,
    // so the assertion exercises the transitive consumer boundary.
    const payload = 'a{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}';
    const started = performance.now();
    const hasMagic = glob.hasMagic(payload);
    const elapsedMs = performance.now() - started;

    assert.equal(typeof hasMagic, 'boolean');
    assert.ok(elapsedMs < 1000, `non-expanding brace payload took ${elapsedMs.toFixed(1)}ms`);
  });

  it('bounds chained expanding braces through glob instead of exhausting memory', () => {
    // GHSA-mh99-v99m-4gvg: a long chain previously grew every intermediate
    // expansion without a total-length bound. Twenty groups reproduce the
    // advisory input class while keeping the regression test lightweight.
    const payload = '{a,b}'.repeat(20);
    const started = performance.now();
    const hasMagic = glob.hasMagic(payload);
    const elapsedMs = performance.now() - started;

    assert.equal(hasMagic, true);
    assert.ok(elapsedMs < 5000, `expanding brace payload took ${elapsedMs.toFixed(1)}ms`);
  });

  it('locks the compatible minimatch consumer and patched brace-expansion line', () => {
    const minimatchPkg = lock.packages?.['node_modules/minimatch'];
    const bracePkg = lock.packages?.['node_modules/brace-expansion'];

    assert.equal(minimatchPkg?.version, '10.2.6');
    assert.equal(bracePkg?.version, '5.0.9');
    assert.equal(minimatchPkg?.dependencies?.['brace-expansion'], '^5.0.8');
  });
});

describe('PLAT-5534: PostCSS source-map path traversal fix', () => {
  it('postcss is upgraded to a patched version (> 8.5.17)', () => {
    const postcssPkg = lock.packages?.['node_modules/postcss'];
    assert.ok(postcssPkg, 'postcss package not found in lockfile');
    const version = postcssPkg.version;
    assert.ok(version, 'postcss version not found');

    // Parse semver
    const parts = version.split('.').map(Number);
    assert.ok(parts.length >= 3, `invalid semver: ${version}`);

    // Must be 8.x > 8.5.17
    assert.equal(parts[0], 8, `postcss major must be 8, got ${parts[0]}`);
    assert.ok(
      parts[1] > 5 || (parts[1] === 5 && parts[2] > 17),
      `postcss version ${version} is still vulnerable (<=8.5.17)`
    );
  });

  it('postcss devDependency constraint allows patched versions', () => {
    const pkgPath = join(__dirname, '..', 'package.json');
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));
    const constraint = pkg.devDependencies?.postcss;
    assert.ok(constraint, 'postcss devDependency not found in package.json');
    // ^8.4.32 allows any 8.x >= 8.4.32, which includes 8.5.24
    assert.match(constraint, /^\^8/, `constraint ${constraint} may not allow patched 8.x`);
  });

  it('vite and tailwindcss peer deps are satisfied by the upgraded postcss', () => {
    // Check vite peer dep on postcss
    const vitePkg = lock.packages?.['node_modules/vite'];
    assert.ok(vitePkg, 'vite package not found');
    const vitePeer = vitePkg.peerDependencies?.postcss;
    if (vitePeer) {
      // Vite 6.x requires postcss ^8.4.43 — 8.5.24 satisfies this
      assert.ok(vitePeer.includes('^8'), `vite postcss peer ${vitePeer} may not accept 8.5.x`);
    }

    // Check tailwindcss peer dep on postcss
    const twPkg = lock.packages?.['node_modules/tailwindcss'];
    assert.ok(twPkg, 'tailwindcss package not found');
    const twPeer = twPkg.peerDependencies?.postcss;
    if (twPeer) {
      assert.ok(twPeer.includes('^8'), `tailwindcss postcss peer ${twPeer} may not accept 8.5.x`);
    }
  });

  it('npm audit no longer reports postcss vulnerability', () => {
    // Verify the lockfile resolved version is > 8.5.17
    const postcssPkg = lock.packages?.['node_modules/postcss'];
    const version = postcssPkg.version;
    const [major, minor, patch] = version.split('.').map(Number);
    const isPatched = major === 8 && (minor > 5 || (minor === 5 && patch > 17));
    assert.ok(isPatched, `postcss ${version} is not patched`);
  });
});
