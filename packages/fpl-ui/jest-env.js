/**
 * Custom jest environment for Node.js 25+ compatibility.
 *
 * Node.js 25 exposes `localStorage` as an own property of globalThis with a
 * getter that throws SecurityError unless --localstorage-file is passed.
 * jest-environment-node uses Object.getOwnPropertyNames() (not Object.keys())
 * to enumerate globals, so making localStorage non-enumerable does not help.
 *
 * Fix: delete the property before super() so jest-environment-node never
 * installs a lazy accessor for it. The property is configurable:true so the
 * delete succeeds without error. The getter is never called.
 *
 * This file is the fallback for direct `npx jest` runs.
 * npm test also passes NODE_OPTIONS=--no-experimental-webstorage via cross-env,
 * which disables Web Storage API entirely — belt and suspenders.
 */
const { TestEnvironment } = require('jest-environment-node');

class SafeNodeEnvironment extends TestEnvironment {
  constructor(config, context) {
    const desc = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    if (desc && desc.get && desc.configurable) {
      // Getter-based property that throws on access. Delete before super()
      // so jest-environment-node never installs its lazy accessor.
      delete globalThis.localStorage;
    }
    super(config, context);
  }
}

module.exports = SafeNodeEnvironment;
