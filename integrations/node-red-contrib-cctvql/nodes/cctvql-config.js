module.exports = function (RED) {
    function CctvqlConfigNode(config) {
        RED.nodes.createNode(this, config);
        this.host = config.host || 'localhost';
        this.port = config.port || 8000;
        this.apiKey = config.apiKey || '';
        this.baseUrl = `http://${this.host}:${this.port}`;
    }
    RED.nodes.registerType('cctvql-config', CctvqlConfigNode, {
        credentials: {
            apiKey: { type: 'password' },
        },
    });
};
