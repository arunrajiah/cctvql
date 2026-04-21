import {
	IExecuteFunctions,
	IHttpRequestOptions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeOperationError,
} from 'n8n-workflow';

export class CctvqlPtz implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'cctvQL PTZ',
		name: 'cctvqlPtz',
		icon: 'file:cctvql.svg',
		group: ['output'],
		version: 1,
		subtitle: '={{$parameter["cameraId"] + " → " + $parameter["action"]}}',
		description: 'Send a pan/tilt/zoom command to a camera via cctvQL',
		defaults: { name: 'cctvQL PTZ' },
		inputs: ['main'],
		outputs: ['main'],
		credentials: [{ name: 'cctvqlApi', required: true }],
		properties: [
			{
				displayName: 'Camera ID',
				name: 'cameraId',
				type: 'string',
				default: '',
				placeholder: 'front_door',
				required: true,
				description: 'ID of the camera to control. Supports expressions (e.g. {{ $json.cameraId }}).',
			},
			{
				displayName: 'Action',
				name: 'action',
				type: 'options',
				options: [
					{ name: 'Left', value: 'left' },
					{ name: 'Right', value: 'right' },
					{ name: 'Up', value: 'up' },
					{ name: 'Down', value: 'down' },
					{ name: 'Zoom In', value: 'zoom_in' },
					{ name: 'Zoom Out', value: 'zoom_out' },
					{ name: 'Home', value: 'home' },
					{ name: 'Go to Preset', value: 'preset' },
				],
				default: 'home',
				required: true,
			},
			{
				displayName: 'Speed',
				name: 'speed',
				type: 'number',
				default: 50,
				typeOptions: { minValue: 1, maxValue: 100 },
				description: 'Movement speed from 1 (slowest) to 100 (fastest)',
			},
			{
				displayName: 'Preset ID',
				name: 'presetId',
				type: 'number',
				default: 1,
				displayOptions: { show: { action: ['preset'] } },
				description: 'Preset number to move to',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const credentials = await this.getCredentials('cctvqlApi');

		const baseUrl = `${credentials.protocol}://${credentials.host}:${credentials.port}`;
		const headers: Record<string, string> = { 'Content-Type': 'application/json' };
		if (credentials.apiKey) headers['X-API-Key'] = credentials.apiKey as string;

		for (let i = 0; i < items.length; i++) {
			const cameraId = this.getNodeParameter('cameraId', i) as string;
			const action = this.getNodeParameter('action', i) as string;
			const speed = this.getNodeParameter('speed', i) as number;

			if (!cameraId.trim()) {
				throw new NodeOperationError(this.getNode(), 'Camera ID cannot be empty', { itemIndex: i });
			}

			const body: Record<string, unknown> = { action, speed };
			if (action === 'preset') {
				body.preset_id = this.getNodeParameter('presetId', i) as number;
			}

			const options: IHttpRequestOptions = {
				method: 'POST',
				url: `${baseUrl}/cameras/${encodeURIComponent(cameraId)}/ptz`,
				headers,
				body,
				json: true,
			};

			const data = await this.helpers.httpRequest(options);

			returnData.push({
				json: { camera_id: cameraId, action, speed, ...data },
				pairedItem: { item: i },
			});
		}

		return [returnData];
	}
}
