import {
	IDataObject,
	IExecuteFunctions,
	IHttpRequestOptions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
} from 'n8n-workflow';

export class CctvqlEvents implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'cctvQL Events',
		name: 'cctvqlEvents',
		icon: 'file:cctvql.svg',
		group: ['input'],
		version: 1,
		description: 'Fetch recent detection events from cctvQL, optionally filtered by camera or label',
		defaults: { name: 'cctvQL Events' },
		inputs: ['main'],
		outputs: ['main'],
		credentials: [{ name: 'cctvqlApi', required: true }],
		properties: [
			{
				displayName: 'Camera',
				name: 'camera',
				type: 'string',
				default: '',
				placeholder: 'front_door',
				description: 'Filter by camera name. Leave blank for all cameras.',
			},
			{
				displayName: 'Label',
				name: 'label',
				type: 'string',
				default: '',
				placeholder: 'person',
				description: 'Filter by object label (e.g. person, car). Leave blank for all labels.',
			},
			{
				displayName: 'Limit',
				name: 'limit',
				type: 'number',
				default: 20,
				description: 'Maximum number of events to return',
			},
			{
				displayName: 'Split Into Items',
				name: 'splitItems',
				type: 'boolean',
				default: true,
				description: 'Whether to output one item per event instead of an array',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const credentials = await this.getCredentials('cctvqlApi');

		const baseUrl = `${credentials.protocol}://${credentials.host}:${credentials.port}`;
		const headers: Record<string, string> = {};
		if (credentials.apiKey) headers['X-API-Key'] = credentials.apiKey as string;

		for (let i = 0; i < items.length; i++) {
			const camera = this.getNodeParameter('camera', i) as string;
			const label = this.getNodeParameter('label', i) as string;
			const limit = this.getNodeParameter('limit', i) as number;
			const splitItems = this.getNodeParameter('splitItems', i) as boolean;

			const qs: Record<string, string | number> = { limit };
			if (camera) qs.camera = camera;
			if (label) qs.label = label;

			const options: IHttpRequestOptions = {
				method: 'GET',
				url: `${baseUrl}/events`,
				headers,
				qs,
				json: true,
			};

			const data: unknown[] = await this.helpers.httpRequest(options);
			const events = Array.isArray(data) ? data : [];

			if (splitItems) {
				for (const event of events) {
					returnData.push({ json: event as IDataObject, pairedItem: { item: i } });
				}
			} else {
				returnData.push({ json: { events }, pairedItem: { item: i } });
			}
		}

		return [returnData];
	}
}
