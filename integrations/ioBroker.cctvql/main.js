'use strict';

const utils = require('@iobroker/adapter-core');
const axios = require('axios');

class Cctvql extends utils.Adapter {
    constructor(options) {
        super({ ...options, name: 'cctvql' });
        this.pollTimer = null;
        this.on('ready', this.onReady.bind(this));
        this.on('stateChange', this.onStateChange.bind(this));
        this.on('unload', this.onUnload.bind(this));
    }

    get baseUrl() {
        const { protocol, host, port } = this.config;
        return `${protocol || 'http'}://${host || 'localhost'}:${port || 8000}`;
    }

    get headers() {
        const h = { 'Content-Type': 'application/json' };
        if (this.config.apiKey) h['X-API-Key'] = this.config.apiKey;
        return h;
    }

    async onReady() {
        await this.setObjectNotExistsAsync('info.connection', {
            type: 'state',
            common: { name: 'Connected', type: 'boolean', role: 'indicator.connected', read: true, write: false },
            native: {},
        });

        await this.subscribeStatesAsync('query.send');

        const ok = await this.checkConnection();
        await this.setState('info.connection', ok, true);

        if (ok) this.log.info(`cctvQL connected at ${this.baseUrl}`);
        else this.log.warn(`cctvQL not reachable at ${this.baseUrl}`);

        const interval = (this.config.pollingInterval || 30) * 1000;
        this.pollTimer = this.setInterval(() => this.pollEvents(), interval);
        await this.pollEvents();
    }

    async checkConnection() {
        try {
            await axios.get(`${this.baseUrl}/health`, { headers: this.headers, timeout: 5000 });
            return true;
        } catch {
            return false;
        }
    }

    async pollEvents() {
        try {
            const { data } = await axios.get(`${this.baseUrl}/events`, {
                headers: this.headers,
                params: { limit: 50 },
                timeout: 10000,
            });
            const events = Array.isArray(data) ? data : [];
            await this.setState('events.latest', JSON.stringify(events), true);
            await this.setState('events.count', events.length, true);

            if (!(await this.getStateAsync('info.connection'))?.val) {
                await this.setState('info.connection', true, true);
            }

            // Create per-camera states for the first event of each camera
            const seen = new Set();
            for (const ev of events) {
                const cam = ev.camera || ev.camera_id;
                if (!cam || seen.has(cam)) continue;
                seen.add(cam);
                const id = `cameras.${cam.replace(/[^a-zA-Z0-9_]/g, '_')}`;
                await this.setObjectNotExistsAsync(`${id}.lastEvent`, {
                    type: 'state',
                    common: { name: `${cam} last event`, type: 'string', role: 'json', read: true, write: false },
                    native: {},
                });
                await this.setState(`${id}.lastEvent`, JSON.stringify(ev), true);
            }
        } catch (err) {
            this.log.debug(`Event poll failed: ${err.message}`);
            await this.setState('info.connection', false, true);
        }
    }

    async onStateChange(id, state) {
        if (!state || state.ack) return;

        if (id.endsWith('query.send') && state.val) {
            await this.sendQuery(state.val);
        }

        // PTZ: write to cameras.<id>.ptz.action triggers a PTZ command
        const ptzMatch = id.match(/cameras\.([^.]+)\.ptz\.action$/);
        if (ptzMatch && state.val) {
            await this.sendPtz(ptzMatch[1], state.val);
        }
    }

    async sendQuery(query) {
        this.log.debug(`Query: ${query}`);
        try {
            const { data } = await axios.post(
                `${this.baseUrl}/query`,
                { query, session_id: 'iobroker' },
                { headers: this.headers, timeout: 30000 },
            );
            await this.setState('query.answer', data.answer || '', true);
            await this.setState('query.intent', data.intent || '', true);
            this.log.info(`cctvQL answer: ${data.answer}`);
        } catch (err) {
            this.log.error(`Query failed: ${err.message}`);
            await this.setState('query.answer', `Error: ${err.message}`, true);
        }
    }

    async sendPtz(cameraId, action) {
        this.log.debug(`PTZ ${cameraId} → ${action}`);
        try {
            const camId = cameraId.replace(/_/g, '-');
            await axios.post(
                `${this.baseUrl}/cameras/${encodeURIComponent(camId)}/ptz`,
                { action, speed: 50 },
                { headers: this.headers, timeout: 10000 },
            );
        } catch (err) {
            this.log.error(`PTZ failed: ${err.message}`);
        }
    }

    onUnload(callback) {
        try {
            if (this.pollTimer) this.clearInterval(this.pollTimer);
        } finally {
            callback();
        }
    }
}

if (require.main !== module) {
    module.exports = (options) => new Cctvql(options);
} else {
    new Cctvql();
}
