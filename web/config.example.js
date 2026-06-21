// Deployment config for the web client.
//
// Copy this file to `config.js` (which is gitignored) on the deployment and fill in
// the real values. Keeping it out of the repo avoids leaking the secret signaling
// path and the network name. If `config.js` is absent the fields are simply left
// blank for the user to fill in by hand.
window.YAW_CONFIG = {
  // Pre-filled signaling endpoint (the secret WSS path). Leave '' to type by hand.
  signalURL: 'wss://your-anchor.example/<secret-path>/signal',

  // Pre-filled network name (the room). Leave '' for none.
  defaultNet: '',
};
