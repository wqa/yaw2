// Deployment config for the web client.
//
// Copy this file to `config.js` (which is gitignored) on the deployment and fill in
// the real values. Keeping it out of the repo avoids leaking the secret signaling
// path, the STUN/anchor host, and the network name. If `config.js` is absent the
// fields fall back to placeholders / manual entry.
window.YAW_CONFIG = {
  // Signaling endpoint (the secret WSS path). '' => type it by hand.
  signalURL: 'wss://your-anchor.example/<secret-path>/signal',

  // STUN server (host:port). Used for NAT traversal.
  stunURL: 'stun:your-anchor.example:3478',

  // Pre-filled network name (the room). '' => none.
  defaultNet: '',
};
