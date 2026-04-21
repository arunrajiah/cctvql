const axios = require('axios');

module.exports = function (RED) {
    function CctvqlQueryNode(config) {
        RED.nodes.createNode(this, config);
        const node = this;
        const server = RED.nodes.getNode(config.server);

        if (!server) {
            node.error('No cctvQL server configured');
            return;
        }

        node.on('input', async function (msg, send, done) {
            const query = msg.query || msg.payload?.query || config.query;
            const sessionId = msg.sessionId || config.sessionId || 'node-red';

            if (!query) {
                done(new Error('No query provided — set msg.query or configure a default'));
                return;
            }

            node.status({ fill: 'blue', shape: 'dot', text: 'querying…' });

            try {
                const headers = {};
                const apiKey = server.credentials?.apiKey || server.apiKey;
                if (apiKey) headers['X-API-Key'] = apiKey;

                const { data } = await axios.post(
                    `${server.baseUrl}/query`,
                    { query, session_id: sessionId },
                    { headers, timeout: 30000 }
                );

                msg.payload = data;
                msg.answer = data.answer || '';
                msg.intent = data.intent || '';
                msg.sessionId = data.session_id || sessionId;

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

    RED.nodes.registerType('cctvql-query', CctvqlQueryNode);
};
