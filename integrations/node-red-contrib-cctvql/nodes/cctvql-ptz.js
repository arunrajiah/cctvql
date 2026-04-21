const axios = require('axios');

const VALID_ACTIONS = ['left', 'right', 'up', 'down', 'zoom_in', 'zoom_out', 'home', 'preset'];

module.exports = function (RED) {
    function CctvqlPtzNode(config) {
        RED.nodes.createNode(this, config);
        const node = this;
        const server = RED.nodes.getNode(config.server);

        if (!server) {
            node.error('No cctvQL server configured');
            return;
        }

        node.on('input', async function (msg, send, done) {
            const cameraId = msg.cameraId || msg.payload?.cameraId || config.cameraId;
            const action = msg.action || msg.payload?.action || config.action;
            const speed = msg.speed || msg.payload?.speed || parseInt(config.speed, 10) || 50;
            const presetId = msg.presetId || msg.payload?.presetId || config.presetId || undefined;

            if (!cameraId) {
                done(new Error('No camera ID — set msg.cameraId or configure a default'));
                return;
            }
            if (!VALID_ACTIONS.includes(action)) {
                done(new Error(`Invalid PTZ action "${action}". Valid: ${VALID_ACTIONS.join(', ')}`));
                return;
            }

            node.status({ fill: 'blue', shape: 'dot', text: `${action} → ${cameraId}` });

            try {
                const headers = {};
                const apiKey = server.credentials?.apiKey || server.apiKey;
                if (apiKey) headers['X-API-Key'] = apiKey;

                const body = { action, speed };
                if (presetId !== undefined) body.preset_id = parseInt(presetId, 10);

                const { data } = await axios.post(
                    `${server.baseUrl}/cameras/${encodeURIComponent(cameraId)}/ptz`,
                    body,
                    { headers, timeout: 10000 }
                );

                msg.payload = data;
                node.status({ fill: 'green', shape: 'dot', text: 'ok' });
                send(msg);
                done();
            } catch (err) {
                node.status({ fill: 'red', shape: 'ring', text: err.message });
                done(err);
            }
        });

        node.on('close', (_removed, done) => done());
    }

    RED.nodes.registerType('cctvql-ptz', CctvqlPtzNode);
};
