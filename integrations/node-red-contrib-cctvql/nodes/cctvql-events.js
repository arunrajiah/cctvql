const axios = require('axios');

module.exports = function (RED) {
    function CctvqlEventsNode(config) {
        RED.nodes.createNode(this, config);
        const node = this;
        const server = RED.nodes.getNode(config.server);

        if (!server) {
            node.error('No cctvQL server configured');
            return;
        }

        let pollTimer = null;

        function buildHeaders() {
            const headers = {};
            const apiKey = server.credentials?.apiKey || server.apiKey;
            if (apiKey) headers['X-API-Key'] = apiKey;
            return headers;
        }

        async function poll() {
            const params = { limit: parseInt(config.limit, 10) || 20 };
            if (config.camera) params.camera = config.camera;
            if (config.label) params.label = config.label;

            try {
                const { data } = await axios.get(
                    `${server.baseUrl}/events`,
                    { headers: buildHeaders(), params, timeout: 10000 }
                );
                node.status({ fill: 'green', shape: 'dot', text: `${data.length} events` });
                const msg = { payload: data, topic: 'cctvql/events' };
                node.send(msg);
            } catch (err) {
                node.status({ fill: 'red', shape: 'ring', text: err.message });
                node.error(err);
            }
        }

        // Trigger on input message OR poll on interval if configured
        node.on('input', async function (_msg, _send, done) {
            await poll();
            done();
        });

        const interval = parseInt(config.pollInterval, 10);
        if (interval > 0) {
            pollTimer = setInterval(poll, interval * 1000);
            node.status({ fill: 'blue', shape: 'ring', text: `polling every ${interval}s` });
        } else {
            node.status({ fill: 'grey', shape: 'ring', text: 'trigger on input' });
        }

        node.on('close', (_removed, done) => {
            if (pollTimer) clearInterval(pollTimer);
            done();
        });
    }

    RED.nodes.registerType('cctvql-events', CctvqlEventsNode);
};
